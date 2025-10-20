#!/usr/bin/env python3
"""
RSI + 볼린저 밴드 스캘핑 자동매매 메인 실행기

실시간으로 캔들 데이터를 수집하고 전략을 실행하여 자동매매를 수행합니다.
DRYRUN 모드에서는 실제 주문 없이 시뮬레이션만 수행합니다.

사용법:
    python src/runner.py --market KRW-BTC --krw 10000 --mode DRYRUN
    python src/runner.py --market KRW-ETH --krw 5000 --mode LIVE
"""

import argparse
import time
import os
import signal
import sys
from typing import List, Dict, Optional, Any
from datetime import datetime

# 프로젝트 루트 디렉토리를 Python 경로에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.upbit_api import upbit_api
from src.trader import trader
from src.strategy.hybrid_scalper import get_hybrid_strategy_instance, HybridScalperConfig
from src.state_manager import StateManager
from src.risk_manager import RiskManager
from src.logger import logger

class TradingRunner:
    """자동매매 실행기"""
    
    def __init__(self, market: str, krw_amount: float, trading_mode: str = "DRYRUN"):
        self.market = market
        self.krw_amount = krw_amount
        self.trading_mode = trading_mode.upper()
        
        # 컴포넌트 초기화 (하이브리드 스캘퍼, 코인별 독립적인 인스턴스)
        self.strategy = get_hybrid_strategy_instance(self.market)
        self.state_manager = StateManager(f".state/trade_state_{market.replace('-', '_').lower()}.json")
        self.risk_manager = RiskManager()
        
        # 상태 로드
        self.state = self.state_manager.load_state()
        
        # 설정
        self.loop_interval = 1.0  # 1초 주기 (API 레이트 리밋 고려)
        self.candle_count = 80    # 캔들 데이터 개수 (SMA60 고려하여 증가)
        self.order_cooldown = 5   # 주문 후 쿨다운 (5초로 단축)
        self.last_order_time = 0
        
        # 실행 상태
        self.running = False
        self.error_count = 0
        self.max_errors = 10
        
        # 안전장치
        if self.trading_mode not in ["DRYRUN", "LIVE"]:
            raise ValueError("Trading mode must be 'DRYRUN' or 'LIVE'")
        
        logger.info(f"Trading Runner initialized: {market}, {krw_amount} KRW, Mode: {trading_mode}")
    
    def get_candles(self) -> Optional[List[Dict[str, Any]]]:
        """분봉 데이터 조회"""
        try:
            # 1분봉 캔들 데이터 조회
            candles = upbit_api.get_candles_minutes(self.market, unit=1, count=self.candle_count)
            
            if not candles:
                logger.error("Failed to fetch candle data")
                return None
            
            # 업비트 API는 최신 데이터가 첫 번째에 오므로 역순으로 정렬 (과거 -> 현재)
            candles.reverse()
            
            logger.debug(f"Fetched {len(candles)} candles for {self.market}")
            return candles
        
        except Exception as e:
            logger.error(f"Error fetching candles: {e}")
            return None
    
    def execute_buy_order(self, signal_meta: Dict) -> bool:
        """매수 주문 실행"""
        try:
            # 리스크 사전 검증
            krw_balance, _ = trader.get_balance('KRW')
            current_positions = 1 if self.state.get('has_position') else 0
            
            allowed, reason = self.risk_manager.check_pre_trade(
                market=self.market,
                krw_amount=self.krw_amount,
                current_positions=current_positions,
                current_balance=krw_balance
            )
            
            if not allowed:
                logger.warning(f"Buy order rejected by risk manager: {reason}")
                return False
            
            # 레이트 리밋 대기
            self.risk_manager.wait_for_rate_limit()
            
            if self.trading_mode == "DRYRUN":
                # 드라이런 모드: 시뮬레이션
                current_price = signal_meta.get('current_price', 0)
                simulated_volume = self.krw_amount / current_price if current_price > 0 else 0
                
                # 하이브리드 전략 상태 업데이트 (다중 진입 기능 제거됨)
                # if hasattr(self.strategy, 'update_multi_entry'):
                #     self.strategy.update_multi_entry(current_price, simulated_volume)
                
                # 상태 업데이트
                self.state = self.state_manager.enter_position(
                    self.state, self.market, current_price, simulated_volume, "DRYRUN_BUY"
                )
                
                entry_strategy = getattr(self.strategy, 'entry_strategy', 'unknown')
                logger.info(f"[DRYRUN] BUY {self.market}: {self.krw_amount:,} KRW at {current_price:,} KRW (Vol: {simulated_volume:.6f}) (Strategy: {entry_strategy})")
                return True
            
            else:
                # 실제 거래 모드
                result = trader.market_buy(self.market, self.krw_amount, confirm=False)

                if result:
                    # 🔍 체결 정보 확인 단계 추가
                    order_uuid = result.get('uuid')
                    executed_volume = 0
                    executed_price = 0

                    if order_uuid:
                        # 체결 확인 요청 (API에서 체결 완료 정보 받아오기)
                        time.sleep(0.5)  # 서버 반영 대기
                        order_info = trader.get_order(order_uuid)
                        if order_info and 'trades' in order_info:
                            filled_trades = order_info['trades']
                            if filled_trades:
                                executed_volume = sum(float(t['volume']) for t in filled_trades)
                                total_price = sum(float(t['price']) * float(t['volume']) for t in filled_trades)
                                executed_price = total_price / executed_volume if executed_volume > 0 else 0

                    # ⚠️ 체결 정보 없을 경우 대비
                    if executed_volume <= 0 or executed_price <= 0:
                        logger.warning(f"[Safety Fix] No filled volume info for {self.market}. Using fallback price={signal_meta.get('current_price', 0)}")
                        executed_volume = self.krw_amount / max(signal_meta.get('current_price', 1), 1)
                        executed_price = signal_meta.get('current_price', 0)

                    # 상태 저장
                    self.state = self.state_manager.enter_position(
                        self.state, self.market, executed_price, executed_volume, result.get('uuid')
                    )

                    entry_strategy = getattr(self.strategy, 'entry_strategy', 'unknown')
                    logger.info(f"[LIVE] BUY executed: {result['uuid']} (Vol={executed_volume:.6f}, Price={executed_price}) (Strategy: {entry_strategy})")
                    self.last_order_time = time.time()
                    return True

                else:
                    logger.error("Buy order failed")
                    return False
        
        except Exception as e:
            logger.error(f"Error executing buy order: {e}")
            return False
    
    def execute_sell_order(self, signal_meta: Dict) -> bool:
        """매도 주문 실행"""
        try:
            position_info = self.state_manager.get_position_info(self.state)
            if not position_info:
                logger.warning("No position to sell")
                return False
            
            volume = position_info['entry_volume']
            if volume is None or volume <= 0:
                market = self.market
                logger.error(f"[Safety Stop] Invalid sell volume={volume} for {market}. Skipping sell order.")
                return False

            # 레이트 리밋 대기
            self.risk_manager.wait_for_rate_limit()
            
            if self.trading_mode == "DRYRUN":
                # 드라이런 모드: 시뮬레이션
                current_price = signal_meta.get('current_price', 0)
                exit_reason = signal_meta.get('reason', 'unknown')
                entry_price = position_info.get('entry_price', 0)
                
                # 수익 계산 및 리스크 매니저 업데이트
                if entry_price > 0:
                    profit_krw = (current_price - entry_price) * volume
                    is_loss = profit_krw < 0
                    self.risk_manager.update_trade_result(profit_krw, is_loss)
                
                self.state = self.state_manager.exit_position(
                    self.state, current_price, exit_reason, "DRYRUN_SELL"
                )
                
                # 하이브리드 전략 상태 초기화
                if hasattr(self.strategy, '_reset_strategy_state'):
                    self.strategy._reset_strategy_state()
                
                logger.info(f"[DRYRUN] SELL {self.market}: {volume:.6f} at {current_price:,} KRW (Reason: {exit_reason})")
                return True
            
            else:
                # 실제 거래 모드
                result = trader.market_sell(self.market, volume, confirm=False)
                
                if result:
                    # 주문 성공
                    executed_price = float(result.get('price', 0)) if result.get('price') else signal_meta.get('current_price', 0)
                    exit_reason = signal_meta.get('reason', 'manual')
                    entry_price = position_info.get('entry_price', 0)
                    
                    # 수익 계산 및 리스크 매니저 업데이트
                    if entry_price > 0:
                        profit_krw = (executed_price - entry_price) * volume
                        is_loss = profit_krw < 0
                        self.risk_manager.update_trade_result(profit_krw, is_loss)
                    
                    self.state = self.state_manager.exit_position(
                        self.state, executed_price, exit_reason, result.get('uuid')
                    )
                    
                    # 하이브리드 전략 상태 초기화
                    if hasattr(self.strategy, '_reset_strategy_state'):
                        self.strategy._reset_strategy_state()
                    
                    logger.info(f"[LIVE] SELL executed: {result['uuid']}")
                    self.last_order_time = time.time()
                    return True
                else:
                    logger.error("Sell order failed")
                    return False
        
        except Exception as e:
            logger.error(f"Error executing sell order: {e}")
            return False
    
    def process_signal(self, signal: Dict[str, Any]) -> bool:
        """시그널 처리"""
        action = signal.get('action', 'HOLD')
        meta = signal.get('meta', {})
        
        # 쿨다운 체크
        if time.time() - self.last_order_time < self.order_cooldown:
            if action in ['BUY', 'SELL']:
                logger.debug(f"Order cooldown active, skipping {action}")
                return False
        
        if action == 'BUY':
            if self.state.get('has_position'):
                logger.warning("Already have position, ignoring BUY signal")
                return False
            
            return self.execute_buy_order(meta)
        
        elif action == 'SELL':
            if not self.state.get('has_position'):
                logger.warning("No position to sell, ignoring SELL signal")
                return False
            
            return self.execute_sell_order(meta)
        
        else:  # HOLD
            # 현재 포지션 상태 로깅 (상세한 경우에만)
            if self.state.get('has_position'):
                reason = meta.get('reason', 'unknown')
                if reason == 'holding_position':
                    profit_rate = meta.get('profit_rate', 0)
                    hold_time = meta.get('hold_time', 0)
                    entry_strategy = meta.get('entry_strategy', 'unknown')
                    logger.debug(f"Holding position: {profit_rate*100:.2f}%, {hold_time:.0f}s, Strategy: {entry_strategy}")
            
            return True
    
    def run_loop(self):
        """메인 실행 루프"""
        logger.info(f"Starting trading loop for {self.market} (Mode: {self.trading_mode})")
        
        try:
            while self.running:
                loop_start = time.time()
                
                try:
                    # 0. 응급 정지 확인
                    if self.risk_manager.emergency_stop:
                        logger.critical("Emergency stop activated, halting trading")
                        break
                    
                    # 1. 캔들 데이터 조회
                    candles = self.get_candles()
                    if not candles:
                        logger.warning("No candle data, skipping iteration")
                        time.sleep(self.loop_interval)
                        continue
                    
                    # 2. 횡보 시장 필터 (진입 시에만)
                    if not self.state.get('has_position'):
                        is_ranging, ranging_meta = self.risk_manager.is_ranging_market(candles)
                        if not is_ranging:
                            logger.debug(f"Not ranging market, skipping: {ranging_meta.get('reason', 'unknown')}")
                            time.sleep(self.loop_interval)
                            continue
                    
                    # 3. 현재 포지션 상태 확인
                    position_state = self.state if self.state.get('has_position') else None
                    
                    # 4. 전략 시그널 생성
                    signal = self.strategy.generate_signal(candles, position_state)
                    
                    # 5. 시그널 처리
                    success = self.process_signal(signal)
                    
                    # 6. 상태 저장
                    if success and signal.get('action') in ['BUY', 'SELL']:
                        self.state_manager.save_state(self.state)
                    
                    # 7. 에러 카운트 리셋
                    self.error_count = 0
                    
                    # 8. 통계 출력 (주기적)
                    if int(time.time()) % 60 == 0:  # 1분마다
                        self.print_status()
                
                except Exception as e:
                    self.error_count += 1
                    logger.error(f"Error in main loop ({self.error_count}/{self.max_errors}): {e}")
                    
                    # 레이트 리밋 처리
                    should_retry, wait_time = self.risk_manager.handle_rate_limit(exception=e)
                    if should_retry:
                        logger.info(f"Rate limit/network error, waiting {wait_time:.1f}s")
                        time.sleep(wait_time)
                        continue
                    
                    if self.error_count >= self.max_errors:
                        logger.error("Too many errors, stopping")
                        break
                    
                    # 기본 백오프 지연
                    backoff_time = min(0.5 + (self.error_count * 0.1), 2.0)
                    time.sleep(backoff_time)
                
                # 7. 루프 간격 조절
                elapsed = time.time() - loop_start
                sleep_time = max(0, self.loop_interval - elapsed)
                if sleep_time > 0:
                    time.sleep(sleep_time)
        
        except KeyboardInterrupt:
            logger.info("Interrupted by user")
        except Exception as e:
            logger.error(f"Fatal error in main loop: {e}")
        finally:
            self.cleanup()
    
    def print_status(self):
        """현재 상태 출력"""
        stats = self.state_manager.get_trading_stats(self.state)
        position = self.state_manager.get_position_info(self.state)
        risk_status = self.risk_manager.get_risk_status()
        
        logger.info("=" * 50)
        logger.info(f"Market: {self.market} | Mode: {self.trading_mode}")
        logger.info(f"Total Trades: {stats['total_trades']} | Win Rate: {stats['win_rate']:.1f}%")
        logger.info(f"Total Profit: {stats['total_profit']:,.0f} KRW")
        
        # 리스크 상태 정보
        logger.info(f"Risk Status: Emergency Stop: {risk_status['emergency_stop']}, Consecutive Losses: {risk_status['consecutive_losses']}")
        logger.info(f"Daily Loss: {risk_status['daily_stats']['total_loss']:,.0f} KRW")
        
        if position:
            profit_rate = ((time.time() - position['entry_time']) / position['entry_price'] - 1) * 100 if position['entry_price'] > 0 else 0
            logger.info(f"Position: {position['entry_volume']:.6f} at {position['entry_price']:,.0f} KRW")
            logger.info(f"Hold Time: {position['hold_time']:.0f}s")
        else:
            logger.info("Position: None")
        
        logger.info("=" * 50)
    
    def start(self):
        """실행 시작"""
        self.running = True
        
        # 시그널 핸들러 등록
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        # 초기 상태 백업
        self.state_manager.backup_state()
        
        # 메인 루프 실행
        self.run_loop()
    
    def stop(self):
        """실행 중지"""
        logger.info("Stopping trading runner...")
        self.running = False
    
    def cleanup(self):
        """정리 작업"""
        logger.info("Cleaning up...")
        
        # 최종 상태 저장
        self.state_manager.save_state(self.state)
        
        # 최종 통계 출력
        self.print_status()
        
        logger.info("Trading runner stopped")
    
    def _signal_handler(self, signum, frame):
        """시그널 핸들러"""
        logger.info(f"Received signal {signum}")
        self.stop()

def main():
    """메인 함수"""
    parser = argparse.ArgumentParser(description="RSI + Bollinger Band Scalping Trading Bot")
    parser.add_argument("--market", type=str, required=True, help="Trading market (e.g., KRW-BTC)")
    parser.add_argument("--krw", type=float, required=True, help="KRW amount per trade")
    parser.add_argument("--mode", type=str, default="DRYRUN", choices=["DRYRUN", "LIVE"], help="Trading mode")
    
    args = parser.parse_args()
    
    # 환경변수에서 모드 재정의 가능
    trading_mode = os.getenv("TRADING_MODE", args.mode).upper()
    
    # 안전 확인
    if trading_mode == "LIVE":
        auto_confirm = os.getenv("AUTO_CONFIRM_LIVE", "false").lower() == "true"
        
        print("⚠️  WARNING: You are about to start LIVE trading!")
        print(f"Market: {args.market}")
        print(f"Amount: {args.krw:,} KRW per trade")
        print("\nThis will use real money. Are you sure?")
        
        if auto_confirm:
            print("AUTO_CONFIRM_LIVE=true, proceeding automatically...")
            confirm = "YES"
        else:
            confirm = input("Type 'YES' to continue: ").strip()
        
        if confirm != "YES":
            print("Aborted.")
            return
    
    try:
        # 트레이딩 러너 초기화 및 실행
        runner = TradingRunner(args.market, args.krw, trading_mode)
        runner.start()
    
    except Exception as e:
        logger.error(f"Failed to start trading runner: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()