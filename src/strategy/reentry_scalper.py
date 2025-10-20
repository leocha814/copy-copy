"""
⚡ 현실적이지만 적극적인 Re-entry Scalper 자동매매 전략

전략 개요:
- 볼린저 밴드 하단 돌파 후 되돌림 순간을 적극적으로 포착
- 다중 진입 허용으로 평균매입가 관리
- RSI 반등 속도와 거래량 필터로 신호 품질 향상
- 횡보 시장에서만 작동하여 리스크 제한

강화 조건:
- 다중 진입: 최대 3분할 진입 허용
- RSI 반등 속도: 최근 3개 RSI 상승폭 합 > +5
- 거래량 필터: 직전 거래량이 20봉 평균의 1.5배 이상
- 횡보 시장 한정: SMA20과 SMA60 차이 < 1%
- 즉시 반전 청산: RSI > 60 또는 가격 > upper_band
"""

import time
import pandas as pd
import numpy as np
from typing import List, Dict, Optional, Any, Tuple
from dataclasses import dataclass
from src.strategy.indicators import calculate_rsi, calculate_bollinger_bands, calculate_sma, get_price_change_percent
from src.logger import logger

@dataclass
class ReentryScalperConfig:
    """적극적 Re-entry Scalper 설정"""
    
    rsi_window: int = 14
    bb_window: int = 20
    bb_std: float = 2.0
    sma_short: int = 20
    sma_long: int = 60
    
    
    rsi_reentry_threshold: float = 35.0
    rsi_overbought: float = 60.0
    take_profit: float = 0.007  
    stop_loss: float = -0.004   
    max_hold_sec: int = 600     
    cooldown_sec: int = 5       
    
    
    max_entries: int = 3        
    rsi_rebound_threshold: float = 5.0  
    volume_boost: float = 1.2   # 1.5에서 1.2로 완화
    ranging_threshold: float = 0.01  
    
    
    use_ranging_filter: bool = True
    ranging_rsi_min: float = 40.0
    ranging_rsi_max: float = 60.0

class ReentryScalper:
    """적극적 Re-entry Scalper 전략"""
    
    def __init__(self, config: Optional[ReentryScalperConfig] = None):
        self.config = config or ReentryScalperConfig()
        self.last_signal_time = 0
        self.last_sell_time = 0
        
        
        self.entry_count = 0
        self.total_volume = 0.0
        self.total_cost = 0.0
        self.entry_times = []
    
    def generate_signal(self, candles: List[Dict[str, Any]], position_state: Optional[Dict] = None) -> Dict[str, Any]:
        """
        적극적 Re-entry 스캘핑 시그널 생성
        
        Args:
            candles: 캔들 데이터 리스트 (최신이 마지막)
            position_state: 현재 포지션 상태
        
        Returns:
            {"action": "BUY"/"SELL"/"HOLD", "meta": {...}}
        """
        try:
            current_time = time.time()
            
            
            if current_time - self.last_signal_time < self.config.cooldown_sec:
                return {"action": "HOLD", "meta": {"reason": "signal_cooldown"}}
            
            
            if current_time - self.last_sell_time < self.config.cooldown_sec:
                return {"action": "HOLD", "meta": {"reason": "sell_cooldown"}}
            
            
            required_length = max(self.config.rsi_window, self.config.bb_window, self.config.sma_long) + 5
            if len(candles) < required_length:
                return {"action": "HOLD", "meta": {"reason": "insufficient_data", "required": required_length, "available": len(candles)}}
            
            
            prices = [float(candle['trade_price']) for candle in candles]
            volumes = [float(candle['candle_acc_trade_volume']) for candle in candles]
            
            current_price = prices[-1]
            prev_price = prices[-2]
            current_volume = volumes[-1]
            
            
            rsi_values = calculate_rsi(prices, self.config.rsi_window)
            bb_upper, bb_middle, bb_lower = calculate_bollinger_bands(prices, self.config.bb_window, self.config.bb_std)
            sma20 = calculate_sma(prices, self.config.sma_short)
            sma60 = calculate_sma(prices, self.config.sma_long)
            
            
            if (not rsi_values or len(rsi_values) < 3 or not bb_lower or not sma20 or not sma60):
                return {"action": "HOLD", "meta": {"reason": "invalid_indicators"}}
            
            current_rsi = rsi_values[-1]
            prev_rsi = rsi_values[-2]
            current_bb_lower = bb_lower[-1]
            current_bb_upper = bb_upper[-1]
            prev_bb_lower = bb_lower[-2]
            
            
            if position_state and position_state.get('has_position'):
                return self._check_exit_conditions(current_price, current_rsi, current_bb_upper, position_state)
            
            
            return self._check_entry_conditions(
                candles, current_price, prev_price, current_volume, volumes,
                current_rsi, prev_rsi, rsi_values, current_bb_lower, prev_bb_lower,
                sma20, sma60, current_time
            )
        
        except Exception as e:
            logger.error(f"Reentry scalper signal generation error: {e}")
            return {"action": "HOLD", "meta": {"reason": "error", "error": str(e)}}
    
    def _check_exit_conditions(self, current_price: float, current_rsi: float, 
                              current_bb_upper: float, position_state: Dict) -> Dict[str, Any]:
        """청산 조건 확인 (강화된 조건)"""
        entry_price = position_state.get('entry_price', 0)
        entry_time = position_state.get('entry_time', 0)
        current_time = time.time()
        
        # 다중 진입인 경우 평균매입가 사용, 단일 진입인 경우 일반 진입가 사용
        if self.entry_count > 1 and self.total_volume > 0:
            effective_entry_price = self.get_average_entry_price()
            logger.debug(f"Using average entry price: {effective_entry_price:,.0f} (entries: {self.entry_count})")
        else:
            effective_entry_price = entry_price
        
        if effective_entry_price == 0:
            return {"action": "SELL", "meta": {"reason": "invalid_entry_price"}}
        
        
        profit_rate = get_price_change_percent(current_price, effective_entry_price)
        hold_time = current_time - entry_time
        
        
        immediate_exit = False
        immediate_reason = ""
        
        
        if current_rsi >= self.config.rsi_overbought:  
            immediate_exit = True
            immediate_reason = "rsi_overbought_exit"
        
        
        elif current_price >= current_bb_upper:
            immediate_exit = True
            immediate_reason = "bb_upper_breakout_exit"
        
        if immediate_exit:
            self.last_signal_time = current_time
            self.last_sell_time = current_time
            self._reset_multi_entry()
            return {
                "action": "SELL",
                "meta": {
                    "reason": immediate_reason,
                    "profit_rate": profit_rate,
                    "hold_time": hold_time,
                    "current_rsi": current_rsi,
                    "current_price": current_price,
                    "entry_price": effective_entry_price,
                    "original_entry_price": entry_price,
                    "entry_count": self.entry_count
                }
            }
        
        
        # RSI 기반 공격적 익절 (수익 구간에서 RSI 하락 시)
        if profit_rate > 0.003 and current_rsi < 45:  # 0.3% 이상 수익 + RSI 45 미만
            self.last_signal_time = current_time
            self.last_sell_time = current_time
            self._reset_multi_entry()
            return {
                "action": "SELL",
                "meta": {
                    "reason": "rsi_profit_taking",
                    "profit_rate": profit_rate,
                    "hold_time": hold_time,
                    "current_rsi": current_rsi,
                    "current_price": current_price,
                    "entry_price": effective_entry_price,
                    "original_entry_price": entry_price,
                    "entry_count": self.entry_count
                }
            }
        
        # 일반 익절 조건
        if profit_rate >= self.config.take_profit:
            self.last_signal_time = current_time
            self.last_sell_time = current_time
            self._reset_multi_entry()
            return {
                "action": "SELL",
                "meta": {
                    "reason": "take_profit",
                    "profit_rate": profit_rate,
                    "hold_time": hold_time,
                    "current_price": current_price,
                    "entry_price": effective_entry_price,
                    "original_entry_price": entry_price,
                    "entry_count": self.entry_count
                }
            }
        
        
        if profit_rate <= self.config.stop_loss:
            self.last_signal_time = current_time
            self.last_sell_time = current_time
            self._reset_multi_entry()
            return {
                "action": "SELL",
                "meta": {
                    "reason": "stop_loss",
                    "profit_rate": profit_rate,
                    "hold_time": hold_time,
                    "current_price": current_price,
                    "entry_price": effective_entry_price,
                    "original_entry_price": entry_price,
                    "entry_count": self.entry_count
                }
            }
        
        
        if hold_time >= self.config.max_hold_sec:
            self.last_signal_time = current_time
            self.last_sell_time = current_time
            self._reset_multi_entry()
            return {
                "action": "SELL",
                "meta": {
                    "reason": "max_hold_time",
                    "profit_rate": profit_rate,
                    "hold_time": hold_time,
                    "current_price": current_price,
                    "entry_price": effective_entry_price,
                    "original_entry_price": entry_price,
                    "entry_count": self.entry_count
                }
            }
        
        return {
            "action": "HOLD",
            "meta": {
                "reason": "holding_position",
                "profit_rate": profit_rate,
                "hold_time": hold_time,
                "current_rsi": current_rsi,
                "entry_count": self.entry_count
            }
        }
    
    def _check_entry_conditions(self, candles: List[Dict], current_price: float, prev_price: float,
                               current_volume: float, volumes: List[float], current_rsi: float, prev_rsi: float,
                               rsi_values: List[float], current_bb_lower: float, prev_bb_lower: float,
                               sma20: List[float], sma60: List[float], current_time: float) -> Dict[str, Any]:
        """강화된 진입 조건 확인"""
        
        
        if self.config.use_ranging_filter:
            if not self._is_ranging_market(sma20, sma60, rsi_values):
                return {"action": "HOLD", "meta": {"reason": "not_ranging_market"}}
        
        
        prev_below_bb = prev_price < prev_bb_lower
        current_above_bb = current_price > current_bb_lower
        bb_reentry = prev_below_bb and current_above_bb
        
        
        rsi_was_low = prev_rsi < self.config.rsi_reentry_threshold
        rsi_rising = current_rsi > prev_rsi
        basic_rsi_upturn = rsi_was_low and rsi_rising
        
        
        
        
        rsi_momentum = self._check_rsi_momentum(rsi_values)
        
        
        volume_boost = self._check_volume_boost(current_volume, volumes)
        
        
        can_multi_entry = (
            self.entry_count < self.config.max_entries and
            current_rsi < 40 and  
            bb_reentry and
            rsi_momentum and
            volume_boost
        )
        
        
        # 신규 진입 조건 (민감도 향상: rsi_momentum OR volume_boost)
        new_entry_signal = (
            bb_reentry and
            basic_rsi_upturn and
            (rsi_momentum or volume_boost)  # 둘 중 하나만 만족해도 진입
        )
        
        
        if new_entry_signal or can_multi_entry:
            self.last_signal_time = current_time
            
            
            if self.entry_count == 0:
                self._reset_multi_entry()
            
            self.entry_count += 1
            self.entry_times.append(current_time)
            
            signal_type = "multi_entry" if self.entry_count > 1 else "new_entry"
            
            return {
                "action": "BUY",
                "meta": {
                    "reason": f"reentry_signal_{signal_type}",
                    "entry_count": self.entry_count,
                    "current_price": current_price,
                    "current_rsi": current_rsi,
                    "prev_rsi": prev_rsi,
                    "bb_reentry": bb_reentry,
                    "rsi_momentum": rsi_momentum,
                    "volume_boost": volume_boost,
                    "basic_rsi_upturn": basic_rsi_upturn,
                    "can_multi_entry": can_multi_entry
                }
            }
        
        return {
            "action": "HOLD",
            "meta": {
                "reason": "no_reentry_signal",
                "current_rsi": current_rsi,
                "prev_rsi": prev_rsi,
                "bb_reentry": bb_reentry,
                "rsi_momentum": rsi_momentum,
                "volume_boost": volume_boost,
                "basic_rsi_upturn": basic_rsi_upturn
            }
        }
    
    def _is_ranging_market(self, sma20: List[float], sma60: List[float], rsi_values: List[float]) -> bool:
        """횡보 시장 판단"""
        try:
            
            if len(sma20) > 0 and len(sma60) > 0:
                sma_diff_pct = abs(sma20[-1] - sma60[-1]) / sma20[-1]
                sma_ranging = sma_diff_pct < self.config.ranging_threshold  
            else:
                sma_ranging = False
            
            
            recent_rsi = [r for r in rsi_values[-10:] if r is not None and not pd.isna(r)]
            if len(recent_rsi) >= 5:
                avg_rsi = sum(recent_rsi) / len(recent_rsi)
                rsi_ranging = self.config.ranging_rsi_min <= avg_rsi <= self.config.ranging_rsi_max
            else:
                rsi_ranging = False
            
            return sma_ranging and rsi_ranging
        
        except Exception as e:
            logger.error(f"Error checking ranging market: {e}")
            return False
    
    def _check_rsi_momentum(self, rsi_values: List[float]) -> bool:
        """RSI 반등 속도 확인"""
        try:
            if len(rsi_values) < 4:
                return False
            
            
            rsi_changes = []
            for i in range(-3, 0):
                if i == -3:
                    prev_val = rsi_values[i-1] if len(rsi_values) > abs(i) else rsi_values[i]
                else:
                    prev_val = rsi_values[i-1]
                
                change = rsi_values[i] - prev_val
                rsi_changes.append(max(0, change))  
            
            total_rebound = sum(rsi_changes)
            return total_rebound > self.config.rsi_rebound_threshold  
        
        except Exception as e:
            logger.error(f"Error checking RSI momentum: {e}")
            return False
    
    def _check_volume_boost(self, current_volume: float, volumes: List[float]) -> bool:
        """거래량 급증 확인 (유연한 기준)"""
        try:
            if len(volumes) < 21:  
                return True  # 데이터 부족시 통과
            
            # 최근 20봉 평균 거래량
            avg_volume = sum(volumes[-21:-1]) / 20
            
            if avg_volume <= 0:
                return True
            
            # 거래량 비율 계산
            volume_ratio = current_volume / avg_volume
            
            # 기본 조건: 평균의 1.2배 이상
            basic_condition = volume_ratio >= self.config.volume_boost
            
            # 완화 조건: 거래량이 작아도 최근 5봉 중 상위 20%면 통과
            recent_volumes = volumes[-6:-1]  # 최근 5봉
            if len(recent_volumes) >= 5:
                sorted_recent = sorted(recent_volumes, reverse=True)
                top_20_percent = sorted_recent[0]  # 상위 1개 (20%)
                relaxed_condition = current_volume >= top_20_percent * 0.8
            else:
                relaxed_condition = False
            
            return basic_condition or relaxed_condition
        
        except Exception as e:
            logger.error(f"Error checking volume boost: {e}")
            return True  # 에러시 통과  
    
    def _reset_multi_entry(self):
        """다중 진입 상태 초기화"""
        self.entry_count = 0
        self.total_volume = 0.0
        self.total_cost = 0.0
        self.entry_times = []
    
    def update_multi_entry(self, executed_price: float, executed_volume: float):
        """다중 진입 정보 업데이트"""
        self.total_cost += executed_price * executed_volume
        self.total_volume += executed_volume
    
    def get_average_entry_price(self) -> float:
        """평균 매입가 계산"""
        if self.total_volume <= 0:
            return 0.0
        return self.total_cost / self.total_volume


# 코인별 독립적인 인스턴스 관리
_strategy_instances = {}

def get_strategy_instance(market: str = "default") -> ReentryScalper:
    """코인별 독립적인 전략 인스턴스 반환"""
    if market not in _strategy_instances:
        _strategy_instances[market] = ReentryScalper()
        logger.info(f"Created new ReentryScalper instance for {market}")
    return _strategy_instances[market]

def generate_signal(candles: List[Dict[str, Any]], position_state: Optional[Dict] = None, market: str = "default") -> Dict[str, Any]:
    """코인별 독립적인 시그널 생성"""
    strategy = get_strategy_instance(market)
    return strategy.generate_signal(candles, position_state)

# 기본 인스턴스 (하위 호환성)
default_reentry_scalper = get_strategy_instance("default")