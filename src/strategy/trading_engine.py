"""
Trading Engine - MeanReversion Strategy + PositionTracker Integration

Entry/Exit 로직과 PositionTracker를 연결하는 통합 레이어.

주요 책임:
- MeanReversionStrategy의 시그널을 받아 실제 포지션 생성/관리
- PositionTracker와 동기화하여 진입/청산 실행
- 중복 진입 방지 (이미 포지션이 있으면 시그널 무시)
- 청산 조건 체크 후 자동 청산
- 리스크 파라미터(SL/TP) 연동
"""

from typing import Optional, Dict, List, Tuple
from datetime import datetime
import logging

from src.core.types import OHLCV, Signal, Position, OrderSide, MarketRegime
from src.strategy.mean_reversion import MeanReversionStrategy
from src.exec.position_tracker import PositionTracker
from src.risk.risk_manager import RiskManager
from src.core.time_utils import now_utc

logger = logging.getLogger(__name__)


class TradingEngine:
    """
    MeanReversion 전략 + PositionTracker 통합 엔진.

    워크플로우:
    1. 매 틱마다 update() 호출
    2. 포지션 없으면 → 진입 시그널 체크 → 진입
    3. 포지션 있으면 → 청산 시그널 체크 → 청산
    4. SL/TP는 RiskManager에서 계산, PositionTracker에 저장
    """

    def __init__(
        self,
        strategy: MeanReversionStrategy,
        position_tracker: PositionTracker,
        risk_manager: RiskManager,
    ):
        """
        Initialize trading engine.

        Args:
            strategy: MeanReversionStrategy instance
            position_tracker: PositionTracker instance
            risk_manager: RiskManager instance for SL/TP calculation
        """
        self.strategy = strategy
        self.tracker = position_tracker
        self.risk = risk_manager

        # 심볼별 마지막 시그널 저장 (중복 방지용)
        self.last_signals: Dict[str, Signal] = {}
        
        # CRITICAL: 실제 체결 시점의 봉 인덱스 추적 (time-stop용)
        # 시그널 시점이 아닌 포지션 오픈 시점 기준!
        self.entry_bar_indices: Dict[str, int] = {}

    # ===== Entry Logic =====

    def check_and_execute_entry(
        self,
        symbol: str,
        candles: List[OHLCV],
        regime: MarketRegime,
        account_balance: float,
        current_price: float,
        atr_value: float,
    ) -> Optional[Position]:
        """
        진입 조건 체크 및 포지션 생성.

        Args:
            symbol: 거래 심볼
            candles: OHLCV 캔들 리스트
            regime: 현재 시장 레짐
            account_balance: 계좌 잔고 (포지션 사이징용)
            current_price: 현재가
            atr_value: ATR 값 (SL/TP 계산용)

        Returns:
            Position 객체 or None (진입 안 함)
        """
        # 1. 이미 포지션이 있으면 진입 안 함
        if self.tracker.has_open_position(symbol):
            logger.debug(f"[{symbol}] Position already exists, skipping entry")
            return None

        # 2. 전략에서 진입 시그널 생성
        signal = self.strategy.generate_entry_signal(candles, regime, symbol)
        if signal is None:
            return None

        # 3. 장기 추세 필터 적용 (옵션)
        if not self.strategy.filter_signal_by_long_term_trend(candles, signal):
            logger.info(f"[{symbol}] Signal filtered by long-term trend")
            return None

        # 4. 포지션 사이징 (ATR 기반)
        try:
            position_size = self.risk.calculate_position_size_atr(
                account_balance=account_balance,
                entry_price=current_price,
                atr_value=atr_value,
                side=signal.side,  # FIX: side 파라미터 추가
                atr_multiplier=self.risk.limits.stop_atr_multiplier,
            )
        except Exception as e:
            logger.error(f"[{symbol}] Position sizing failed: {e}")
            return None

        if position_size <= 0:
            logger.warning(f"[{symbol}] Calculated position size is zero/negative")
            return None

        # 5. SL/TP 계산
        try:
            stop_loss, take_profit = self.risk.calculate_stop_loss_take_profit(
                entry_price=current_price,
                side=signal.side,
                atr_value=atr_value,
            )
        except Exception as e:
            logger.error(f"[{symbol}] SL/TP calculation failed: {e}")
            return None

        # 6. 실제 체결 시점의 봉 인덱스 기록 (time-stop용)
        # NOTE: PositionTracker 업데이트 전에 기록 (거래소 API 호출 실패 시 롤백 가능)
        self.entry_bar_indices[symbol] = len(candles) - 1

        # 7. PositionTracker에 포지션 등록
        # NOTE: 실전에서는 여기서 거래소 API 호출 후, 체결 확인되면 tracker 업데이트해야 함
        # TODO: 거래소 주문 실패 시 entry_bar_indices 롤백 로직 추가 필요
        position = self.tracker.open_position(
            symbol=symbol,
            side=signal.side,
            size=position_size,
            entry_price=current_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
        )

        # 8. 시그널 executed = True로 마킹
        signal.executed = True
        self.last_signals[symbol] = signal

        logger.info(
            f"[{symbol}] ENTRY EXECUTED: {signal.side.value} {position_size:.4f} @ {current_price:.2f} "
            f"(SL: {stop_loss:.2f}, TP: {take_profit:.2f})"
        )
        logger.info(f"[{symbol}] Entry reason: {signal.reason}")

        return position

    # ===== Exit Logic =====

    def check_and_execute_exit(
        self,
        symbol: str,
        candles: List[OHLCV],
        current_price: float,
        exit_fees: Optional[float] = None,
        slippage: Optional[float] = None,
    ) -> Optional[Tuple[bool, str]]:
        """
        청산 조건 체크 및 포지션 종료.

        Args:
            symbol: 거래 심볼
            candles: OHLCV 캔들 리스트
            current_price: 현재가
            exit_fees: 청산 시 수수료 (선택)
            slippage: 슬리피지 (선택)

        Returns:
            (청산 여부, 청산 사유) or None (포지션 없음)
        """
        # 1. 포지션 확인
        position = self.tracker.get_position(symbol)
        if position is None:
            return None

        # 2. 현재가 업데이트 (미실현손익 계산)
        self.tracker.update_position_price(symbol, current_price)

        # 3. RiskManager SL/TP 체크 (우선순위 높음)
        if self.risk.check_stop_loss(position):
            logger.warning(f"[{symbol}] STOP LOSS HIT @ {current_price:.2f}")
            trade = self.tracker.close_position(
                symbol=symbol,
                exit_price=current_price,
                fees=exit_fees,
                slippage=slippage,
            )
            if trade:
                logger.info(f"[{symbol}] Position closed by SL: PnL={trade.pnl:.2f} ({trade.pnl_pct:+.2f}%)")
            # CRITICAL: 청산 시 entry_bar_index 삭제
            self.entry_bar_indices.pop(symbol, None)
            return True, f"Stop Loss @ {position.stop_loss:.2f}"

        if self.risk.check_take_profit(position):
            logger.info(f"[{symbol}] TAKE PROFIT HIT @ {current_price:.2f}")
            trade = self.tracker.close_position(
                symbol=symbol,
                exit_price=current_price,
                fees=exit_fees,
                slippage=slippage,
            )
            if trade:
                logger.info(f"[{symbol}] Position closed by TP: PnL={trade.pnl:.2f} ({trade.pnl_pct:+.2f}%)")
            # CRITICAL: 청산 시 entry_bar_index 삭제
            self.entry_bar_indices.pop(symbol, None)
            return True, f"Take Profit @ {position.take_profit:.2f}"

        # 4. 전략 청산 조건 체크 (BB middle 회귀, RSI 정상화)
        # CRITICAL: entry_bar_index 전달 (실제 체결 시점 기준)
        entry_bar_idx = self.entry_bar_indices.get(symbol)
        should_exit, reason = self.strategy.should_exit(
            candles=candles,
            entry_side=position.side,
            entry_price=position.entry_price,
            entry_bar_index=entry_bar_idx,
        )

        if should_exit:
            logger.info(f"[{symbol}] STRATEGY EXIT: {reason}")
            trade = self.tracker.close_position(
                symbol=symbol,
                exit_price=current_price,
                fees=exit_fees,
                slippage=slippage,
            )
            if trade:
                logger.info(f"[{symbol}] Position closed by strategy: PnL={trade.pnl:.2f} ({trade.pnl_pct:+.2f}%)")
            # CRITICAL: 청산 시 entry_bar_index 삭제
            self.entry_bar_indices.pop(symbol, None)
            return True, reason

        # 5. 청산 안 함
        logger.debug(
            f"[{symbol}] Position held: unrealized PnL={position.unrealized_pnl:.2f} "
            f"({position.unrealized_pnl_pct:+.2f}%)"
        )
        return False, ""

    # ===== Main Update Loop =====

    def update(
        self,
        symbol: str,
        candles: List[OHLCV],
        regime: MarketRegime,
        account_balance: float,
        current_price: float,
        atr_value: float,
        exit_fees: Optional[float] = None,
        slippage: Optional[float] = None,
    ) -> Dict[str, any]:
        """
        메인 업데이트 루프 (매 틱마다 호출).

        Args:
            symbol: 거래 심볼
            candles: OHLCV 캔들 리스트
            regime: 현재 시장 레짐
            account_balance: 계좌 잔고
            current_price: 현재가
            atr_value: ATR 값
            exit_fees: 청산 수수료 (선택)
            slippage: 슬리피지 (선택)

        Returns:
            결과 딕셔너리:
            {
                'action': 'entry' | 'exit' | 'hold',
                'position': Position object or None,
                'reason': str (청산 사유 등),
                'signal': Signal object or None,
            }
        """
        result = {
            'action': 'hold',
            'position': None,
            'reason': '',
            'signal': None,
        }

        # 1. 포지션이 있으면 청산 체크
        if self.tracker.has_open_position(symbol):
            exit_result = self.check_and_execute_exit(
                symbol=symbol,
                candles=candles,
                current_price=current_price,
                exit_fees=exit_fees,
                slippage=slippage,
            )
            if exit_result and exit_result[0]:  # 청산됨
                result['action'] = 'exit'
                result['reason'] = exit_result[1]
                return result

            # 청산 안 됨 → hold
            result['position'] = self.tracker.get_position(symbol)
            return result

        # 2. 포지션이 없으면 진입 체크
        position = self.check_and_execute_entry(
            symbol=symbol,
            candles=candles,
            regime=regime,
            account_balance=account_balance,
            current_price=current_price,
            atr_value=atr_value,
        )

        if position:
            result['action'] = 'entry'
            result['position'] = position
            result['signal'] = self.last_signals.get(symbol)
            return result

        return result

    # ===== Status & Stats =====

    def get_position_status(self, symbol: str) -> Optional[Dict]:
        """
        포지션 상태 조회.

        Returns:
            포지션 상태 딕셔너리 or None
        """
        position = self.tracker.get_position(symbol)
        if position is None:
            return None

        return {
            'symbol': position.symbol,
            'side': position.side.value,
            'size': position.size,
            'entry_price': position.entry_price,
            'current_price': position.current_price,
            'unrealized_pnl': position.unrealized_pnl,
            'unrealized_pnl_pct': position.unrealized_pnl_pct,
            'stop_loss': position.stop_loss,
            'take_profit': position.take_profit,
            'entry_time': position.entry_time.isoformat(),
        }

    def get_all_positions_status(self) -> Dict[str, Dict]:
        """
        모든 포지션 상태 조회.

        Returns:
            {symbol: status_dict, ...}
        """
        positions = self.tracker.get_all_positions()
        return {
            pos.symbol: self.get_position_status(pos.symbol)
            for pos in positions
        }

    def get_performance_stats(self) -> Dict:
        """
        전체 성과 통계.

        Returns:
            통계 딕셔너리:
            - total_trades: 총 거래 횟수
            - win_rate: 승률 (%)
            - avg_pnl: 평균 손익
            - total_pnl: 총 손익
            - avg_win: 평균 수익
            - avg_loss: 평균 손실
            - profit_factor: 수익/손실 비율
            - unrealized_pnl: 미실현 손익
        """
        trade_stats = self.tracker.get_trade_stats()
        unrealized = self.tracker.get_total_unrealized_pnl()

        return {
            **trade_stats,
            'unrealized_pnl': unrealized,
        }

    def force_close_all(
        self,
        current_prices: Dict[str, float],
        reason: str = "Force close by system",
    ) -> List[str]:
        """
        모든 포지션 강제 청산.

        Args:
            current_prices: {symbol: current_price} 딕셔너리
            reason: 청산 사유

        Returns:
            청산된 심볼 리스트
        """
        closed_symbols = []
        positions = self.tracker.get_all_positions()

        for position in positions:
            symbol = position.symbol
            if symbol not in current_prices:
                logger.warning(f"[{symbol}] No current price provided, skipping force close")
                continue

            current_price = current_prices[symbol]
            trade = self.tracker.close_position(symbol, current_price)
            if trade:
                logger.warning(
                    f"[{symbol}] FORCE CLOSED: {reason} | "
                    f"PnL={trade.pnl:.2f} ({trade.pnl_pct:+.2f}%)"
                )
                closed_symbols.append(symbol)

        return closed_symbols
