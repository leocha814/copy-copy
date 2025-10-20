"""
🎯 개선형 하이브리드 스캘퍼 - 명확한 신호만 거래

핵심 개선사항:
1. 💸 손익 0.2% 이하 거래 무시 (미세한 움직임 스킵)
2. 📊 RSI + 볼린저 + SMA 추세 필터 3중 확인
3. 📈 명확한 눌림매수/반등매도만 포착
4. 🚫 155→154원 같은 노이즈 거래 완전 차단

전략 철학:
- "적게 거래하되, 확실할 때만 거래"
- "수수료를 이기는 명확한 신호만 포착"
- "노이즈를 피하고 트렌드를 따라가는 구조"
"""

import time
import pandas as pd
import numpy as np
from typing import List, Dict, Optional, Any
from dataclasses import dataclass
from src.strategy.indicators import calculate_rsi, calculate_bollinger_bands, calculate_sma, get_price_change_percent
from src.logger import logger
from src.performance_monitor import TradeResult, log_trade_result

@dataclass
class EnhancedHybridConfig:
    """개선형 하이브리드 스캘퍼 설정"""
    
    # 기본 지표 설정
    rsi_window: int = 14
    bb_window: int = 20
    bb_std: float = 2.0
    sma_short: int = 10      # 단기 SMA (추세 필터용)
    sma_long: int = 20       # 장기 SMA (추세 필터용)
    volume_window: int = 20
    
    # 💸 손익 필터 (핵심 개선)
    min_profit_threshold: float = 0.002  # 0.2% 이하 거래 무시
    take_profit: float = 0.008           # 0.8% 익절 (수수료 충분히 커버)
    stop_loss: float = -0.003            # -0.3% 손절 (빠른 손절)
    
    # 🎯 엄격한 진입 조건
    rsi_oversold: float = 30.0           # RSI 과매도 (더 엄격)
    rsi_overbought: float = 70.0         # RSI 과매수 (더 엄격)
    rsi_momentum_min: float = 5.0        # RSI 모멘텀 최소 기준
    
    # 📊 볼린저 밴드 + 추세 필터
    bb_penetration_min: float = 0.005    # 밴드 침투 최소 0.5%
    trend_confirmation_bars: int = 3     # 추세 확인 캔들 수
    
    # 🚫 노이즈 필터
    min_price_move: float = 0.002        # 최소 가격 변동 0.2%
    volume_surge_ratio: float = 1.8      # 거래량 급증 비율 (더 엄격)
    
    # ⏰ 시간 제한
    max_hold_sec: int = 300              # 최대 보유 5분
    cooldown_sec: int = 60               # 거래 후 1분 쿨다운

class EnhancedHybridScalper:
    """개선형 하이브리드 스캘퍼 - 명확한 신호만 거래"""
    
    def __init__(self, config: Optional[EnhancedHybridConfig] = None):
        self.config = config or EnhancedHybridConfig()
        self.last_signal_time = 0
        self.last_trade_time = 0
        self.current_market = "UNKNOWN"
        
        # 전략 상태 추적
        self.entry_strategy = None
        self.entry_price = None
        self.entry_time = None
        self.entry_rsi = None
        
        # 노이즈 필터링을 위한 가격 추적
        self.price_history = []
        self.last_significant_move = 0
        
    def generate_signal(self, candles: List[Dict[str, Any]], position_state: Optional[Dict] = None) -> Dict[str, Any]:
        """
        개선형 하이브리드 시그널 생성 - 명확한 신호만
        
        핵심 로직:
        1. 노이즈 필터링 (0.2% 이하 움직임 무시)
        2. RSI + 볼린저 + SMA 3중 확인
        3. 명확한 눌림매수/반등매도만 포착
        """
        try:
            current_time = time.time()
            
            # 🕐 쿨다운 체크
            if current_time - self.last_trade_time < self.config.cooldown_sec:
                return {"action": "HOLD", "meta": {"reason": "cooldown_active"}}
            
            # 📊 데이터 충분성 검사
            required_length = max(self.config.rsi_window, self.config.bb_window, 
                                self.config.sma_long, self.config.volume_window) + 5
            if len(candles) < required_length:
                return {"action": "HOLD", "meta": {"reason": "insufficient_data"}}
            
            # 🔢 데이터 추출
            prices = [float(candle['trade_price']) for candle in candles]
            volumes = [float(candle['candle_acc_trade_volume']) for candle in candles]
            highs = [float(candle['high_price']) for candle in candles]
            lows = [float(candle['low_price']) for candle in candles]
            
            current_price = prices[-1]
            
            # 💸 노이즈 필터: 의미 있는 가격 변동만 처리
            if not self._is_significant_price_move(prices):
                return {"action": "HOLD", "meta": {"reason": "insufficient_price_movement"}}
            
            # 📈 기술적 지표 계산
            rsi_values = calculate_rsi(prices, self.config.rsi_window)
            bb_upper, bb_middle, bb_lower = calculate_bollinger_bands(prices, self.config.bb_window, self.config.bb_std)
            sma_short = calculate_sma(prices, self.config.sma_short)
            sma_long = calculate_sma(prices, self.config.sma_long)
            
            if not all([rsi_values, bb_lower, sma_short, sma_long]):
                return {"action": "HOLD", "meta": {"reason": "invalid_indicators"}}
            
            current_rsi = rsi_values[-1]
            
            # 📊 현재 상태 저장 (성능 모니터링용)
            self.current_rsi = current_rsi
            
            # 💼 포지션 있는 경우: 청산 조건 확인
            if position_state and position_state.get('has_position'):
                return self._check_enhanced_exit_conditions(
                    current_price, current_rsi, bb_upper, bb_lower, position_state, current_time
                )
            
            # 🎯 진입 조건 확인: 3중 필터 (RSI + 볼린저 + SMA)
            return self._check_enhanced_entry_conditions(
                candles, current_price, prices, volumes, rsi_values, 
                bb_upper, bb_middle, bb_lower, sma_short, sma_long, current_time
            )
            
        except Exception as e:
            logger.error(f"Enhanced hybrid signal generation error: {e}")
            return {"action": "HOLD", "meta": {"reason": "error", "error": str(e)}}
    
    def _is_significant_price_move(self, prices: List[float]) -> bool:
        """💸 의미 있는 가격 변동 확인 (노이즈 필터링)"""
        if len(prices) < 5:
            return False
        
        # 최근 5분봉 동안의 가격 변동 확인
        recent_prices = prices[-5:]
        max_price = max(recent_prices)
        min_price = min(recent_prices)
        
        price_move_pct = (max_price - min_price) / min_price
        
        # 0.2% 이하 변동은 무의미한 노이즈로 간주
        return price_move_pct >= self.config.min_profit_threshold
    
    def _check_enhanced_exit_conditions(self, current_price: float, current_rsi: float, 
                                      bb_upper: List[float], bb_lower: List[float],
                                      position_state: Dict, current_time: float) -> Dict[str, Any]:
        """🎯 개선된 청산 조건 (명확한 신호만)"""
        entry_price = position_state.get('entry_price', 0)
        entry_time = position_state.get('entry_time', 0)
        
        if entry_price <= 0:
            return {"action": "HOLD", "meta": {"reason": "invalid_entry_price"}}
        
        profit_rate = get_price_change_percent(current_price, entry_price)
        hold_time = current_time - entry_time
        
        # 🎯 명확한 익절: 0.8% 이상
        if profit_rate >= self.config.take_profit:
            self._record_trade_result(profit_rate, position_state, current_price, "clear_profit_target")
            self._reset_strategy_state()
            return {
                "action": "SELL",
                "meta": {
                    "reason": "clear_profit_target",
                    "profit_rate": profit_rate,
                    "hold_time": hold_time
                }
            }
        
        # 🚫 빠른 손절: -0.3%
        if profit_rate <= self.config.stop_loss:
            self._record_trade_result(profit_rate, position_state, current_price, "quick_stop_loss")
            self._reset_strategy_state()
            return {
                "action": "SELL",
                "meta": {
                    "reason": "quick_stop_loss",
                    "profit_rate": profit_rate,
                    "hold_time": hold_time
                }
            }
        
        # 📊 RSI 과매수 즉시 청산 (명확한 신호)
        if current_rsi >= self.config.rsi_overbought:
            self._record_trade_result(profit_rate, position_state, current_price, "rsi_overbought_exit")
            self._reset_strategy_state()
            return {
                "action": "SELL",
                "meta": {
                    "reason": "rsi_overbought_exit",
                    "profit_rate": profit_rate,
                    "current_rsi": current_rsi
                }
            }
        
        # 📈 볼린저 상단 돌파 시 즉시 청산
        if current_price >= bb_upper[-1]:
            self._record_trade_result(profit_rate, position_state, current_price, "bb_upper_breakout")
            self._reset_strategy_state()
            return {
                "action": "SELL",
                "meta": {
                    "reason": "bb_upper_breakout",
                    "profit_rate": profit_rate,
                    "bb_upper": bb_upper[-1]
                }
            }
        
        # ⏰ 시간 기반 청산
        if hold_time >= self.config.max_hold_sec:
            self._record_trade_result(profit_rate, position_state, current_price, "time_exit")
            self._reset_strategy_state()
            return {
                "action": "SELL",
                "meta": {
                    "reason": "time_exit",
                    "profit_rate": profit_rate,
                    "hold_time": hold_time
                }
            }
        
        return {
            "action": "HOLD",
            "meta": {
                "reason": "holding_position",
                "profit_rate": profit_rate,
                "hold_time": hold_time,
                "current_rsi": current_rsi
            }
        }
    
    def _check_enhanced_entry_conditions(self, candles: List[Dict], current_price: float, 
                                        prices: List[float], volumes: List[float],
                                        rsi_values: List[float], bb_upper: List[float], 
                                        bb_middle: List[float], bb_lower: List[float],
                                        sma_short: List[float], sma_long: List[float],
                                        current_time: float) -> Dict[str, Any]:
        """🎯 개선된 진입 조건 (3중 필터: RSI + 볼린저 + SMA)"""
        
        current_rsi = rsi_values[-1]
        
        # 🔍 1단계: RSI 필터 (명확한 과매도 + 반등)
        rsi_signal = self._check_rsi_pullback_signal(rsi_values)
        
        # 🔍 2단계: 볼린저 밴드 필터 (명확한 하단 터치 + 복귀)
        bb_signal = self._check_bollinger_pullback_signal(prices, bb_lower, bb_middle)
        
        # 🔍 3단계: SMA 추세 필터 (상승 추세 확인)
        trend_signal = self._check_sma_trend_signal(sma_short, sma_long)
        
        # 🔍 4단계: 거래량 필터 (명확한 급증)
        volume_signal = self._check_volume_surge_signal(volumes)
        
        # 🎯 3중 확인: RSI + 볼린저 + 추세 모두 만족해야 진입
        if rsi_signal['valid'] and bb_signal['valid'] and trend_signal['valid'] and volume_signal['valid']:
            
            # 진입 상태 기록
            self.entry_strategy = "enhanced_pullback"
            self.entry_price = current_price
            self.entry_time = current_time
            self.entry_rsi = current_rsi
            self.last_signal_time = current_time
            self.last_trade_time = current_time
            
            return {
                "action": "BUY",
                "meta": {
                    "reason": "enhanced_pullback_entry",
                    "entry_strategy": self.entry_strategy,
                    "current_price": current_price,
                    "current_rsi": current_rsi,
                    "rsi_signal": rsi_signal,
                    "bb_signal": bb_signal,
                    "trend_signal": trend_signal,
                    "volume_signal": volume_signal
                }
            }
        
        return {
            "action": "HOLD",
            "meta": {
                "reason": "waiting_for_clear_signal",
                "current_rsi": current_rsi,
                "rsi_valid": rsi_signal['valid'],
                "bb_valid": bb_signal['valid'],
                "trend_valid": trend_signal['valid'],
                "volume_valid": volume_signal['valid']
            }
        }
    
    def _check_rsi_pullback_signal(self, rsi_values: List[float]) -> Dict[str, Any]:
        """📊 RSI 눌림매수 신호 확인 (명확한 과매도에서 반등)"""
        if len(rsi_values) < 5:
            return {"valid": False, "reason": "insufficient_rsi_data"}
        
        current_rsi = rsi_values[-1]
        prev_rsi = rsi_values[-2]
        min_rsi_3bars = min(rsi_values[-4:-1])  # 최근 3봉 중 최저 RSI
        
        # 조건 1: 최근에 명확한 과매도 구간 터치 (30 이하)
        touched_oversold = min_rsi_3bars <= self.config.rsi_oversold
        
        # 조건 2: 현재 RSI가 반등 중 (최소 5포인트 이상 상승)
        rsi_rebound = current_rsi > prev_rsi and (current_rsi - min_rsi_3bars) >= self.config.rsi_momentum_min
        
        # 조건 3: 아직 과매수 구간은 아님
        not_overbought = current_rsi < self.config.rsi_overbought - 10  # 60 이하
        
        valid = touched_oversold and rsi_rebound and not_overbought
        
        return {
            "valid": valid,
            "current_rsi": current_rsi,
            "min_rsi_3bars": min_rsi_3bars,
            "rsi_momentum": current_rsi - min_rsi_3bars,
            "touched_oversold": touched_oversold,
            "rsi_rebound": rsi_rebound,
            "not_overbought": not_overbought
        }
    
    def _check_bollinger_pullback_signal(self, prices: List[float], bb_lower: List[float], 
                                       bb_middle: List[float]) -> Dict[str, Any]:
        """📈 볼린저 밴드 눌림매수 신호 확인"""
        if len(prices) < 5 or len(bb_lower) < 5:
            return {"valid": False, "reason": "insufficient_bb_data"}
        
        current_price = prices[-1]
        prev_price = prices[-2]
        min_price_3bars = min(prices[-4:-1])
        
        current_bb_lower = bb_lower[-1]
        current_bb_middle = bb_middle[-1]
        
        # 조건 1: 최근에 볼린저 하단 명확히 터치 (0.5% 이상 침투)
        bb_penetration = (current_bb_lower - min_price_3bars) / current_bb_lower
        touched_lower_band = bb_penetration >= self.config.bb_penetration_min
        
        # 조건 2: 현재 가격이 볼린저 하단 위로 복귀
        above_lower_band = current_price > current_bb_lower
        
        # 조건 3: 볼린저 중앙선 아래에서 진입 (상단까지는 여유 있음)
        below_middle_band = current_price < current_bb_middle
        
        valid = touched_lower_band and above_lower_band and below_middle_band
        
        return {
            "valid": valid,
            "current_price": current_price,
            "bb_lower": current_bb_lower,
            "bb_middle": current_bb_middle,
            "bb_penetration": bb_penetration,
            "touched_lower_band": touched_lower_band,
            "above_lower_band": above_lower_band,
            "below_middle_band": below_middle_band
        }
    
    def _check_sma_trend_signal(self, sma_short: List[float], sma_long: List[float]) -> Dict[str, Any]:
        """📊 SMA 추세 필터 (상승 추세에서만 매수)"""
        if len(sma_short) < 3 or len(sma_long) < 3:
            return {"valid": False, "reason": "insufficient_sma_data"}
        
        current_sma_short = sma_short[-1]
        current_sma_long = sma_long[-1]
        prev_sma_short = sma_short[-2]
        
        # 조건 1: 단기 SMA가 장기 SMA 위에 있음 (상승 추세)
        sma_bullish = current_sma_short > current_sma_long
        
        # 조건 2: 단기 SMA가 상승 중
        sma_rising = current_sma_short > prev_sma_short
        
        # 조건 3: SMA 간격이 충분히 벌어져 있음 (최소 0.1% 차이)
        sma_spread = (current_sma_short - current_sma_long) / current_sma_long
        sufficient_spread = sma_spread >= 0.001  # 0.1%
        
        valid = sma_bullish and sma_rising and sufficient_spread
        
        return {
            "valid": valid,
            "sma_short": current_sma_short,
            "sma_long": current_sma_long,
            "sma_spread": sma_spread,
            "sma_bullish": sma_bullish,
            "sma_rising": sma_rising,
            "sufficient_spread": sufficient_spread
        }
    
    def _check_volume_surge_signal(self, volumes: List[float]) -> Dict[str, Any]:
        """📊 거래량 급증 신호 확인 (더 엄격한 기준)"""
        if len(volumes) < self.config.volume_window + 1:
            return {"valid": False, "reason": "insufficient_volume_data"}
        
        current_volume = volumes[-1]
        avg_volume = sum(volumes[-self.config.volume_window-1:-1]) / self.config.volume_window
        
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 0
        
        # 더 엄격한 거래량 기준: 1.8배 이상 급증
        volume_surge = volume_ratio >= self.config.volume_surge_ratio
        
        return {
            "valid": volume_surge,
            "current_volume": current_volume,
            "avg_volume": avg_volume,
            "volume_ratio": volume_ratio,
            "volume_surge": volume_surge
        }
    
    def _record_trade_result(self, profit_rate: float, position_state: Dict = None, 
                           current_price: float = 0, exit_reason: str = "unknown"):
        """거래 결과 기록"""
        if position_state and hasattr(self, 'current_market'):
            try:
                entry_price = position_state.get('entry_price', 0)
                entry_time = position_state.get('entry_time', time.time())
                hold_time = time.time() - entry_time
                profit_krw = profit_rate * position_state.get('krw_amount', 20000)
                
                trade_result = TradeResult(
                    timestamp=time.time(),
                    market=getattr(self, 'current_market', 'UNKNOWN'),
                    entry_strategy=self.entry_strategy or 'enhanced_pullback',
                    entry_price=entry_price,
                    exit_price=current_price,
                    entry_time=entry_time,
                    exit_time=time.time(),
                    profit_rate=profit_rate,
                    profit_krw=profit_krw,
                    hold_time=hold_time,
                    exit_reason=exit_reason,
                    entry_rsi=self.entry_rsi or 0,
                    exit_rsi=getattr(self, 'current_rsi', 0)
                )
                
                log_trade_result(trade_result)
                
            except Exception as e:
                logger.error(f"Enhanced trade result logging failed: {e}")
    
    def _reset_strategy_state(self):
        """전략 상태 초기화"""
        self.entry_strategy = None
        self.entry_price = None
        self.entry_time = None
        self.entry_rsi = None

# 코인별 독립적인 인스턴스 관리
_enhanced_strategy_instances = {}

def get_enhanced_strategy_instance(market: str = "default") -> EnhancedHybridScalper:
    """코인별 독립적인 개선형 전략 인스턴스 반환"""
    if market not in _enhanced_strategy_instances:
        instance = EnhancedHybridScalper()
        instance.current_market = market
        _enhanced_strategy_instances[market] = instance
        logger.info(f"Created new EnhancedHybridScalper instance for {market}")
    return _enhanced_strategy_instances[market]

def generate_signal(candles: List[Dict[str, Any]], position_state: Optional[Dict] = None, 
                   market: str = "default") -> Dict[str, Any]:
    """코인별 독립적인 개선형 하이브리드 시그널 생성"""
    strategy = get_enhanced_strategy_instance(market)
    return strategy.generate_signal(candles, position_state)

# 기본 인스턴스
default_enhanced_scalper = get_enhanced_strategy_instance("default")