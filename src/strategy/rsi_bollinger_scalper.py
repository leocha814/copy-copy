"""
⚔️ 볼린저 밴드 반등형 Re-entry Scalper

전략 개요:
- 하단 밴드 이탈 후 되돌림 순간에 진입하는 적극적 스캘핑 전략
- "낙하산 펼쳤다" 신호만 보고 진입하여 빠른 반등 포착
- 거래 횟수 2~3배 증가, 짧은 파동을 매우 자주 매매

진입 조건:
- 이전 캔들: close < lower_band (밴드 이탈)
- 현재 캔들: close > lower_band (되돌림 신호)
- RSI 상승 전환: 직전 RSI < 35, 현재 RSI > 직전 RSI

청산 조건:
- +0.6~0.7% 익절 OR -0.4% 손절 OR 보유 5분 경과
- 낙폭이 깊은 코인(XRP, DOGE 등)에 특히 효과적
"""

import time
import pandas as pd
import numpy as np
from typing import List, Dict, Optional, Any
from dataclasses import dataclass
from src.strategy.indicators import calculate_rsi, calculate_bollinger_bands, get_price_change_percent
from src.logger import logger

@dataclass
class ScalperConfig:
    """볼린저 밴드 반등형 스캘퍼 설정"""
    rsi_window: int = 14
    bb_window: int = 20
    bb_std: float = 2.0
    rsi_reentry_threshold: float = 35.0  # RSI 상승 전환 기준
    rsi_overbought: float = 70.0
    take_profit: float = 0.0065  # 0.65% (0.6~0.7% 중간값)
    stop_loss: float = -0.004    # -0.4%
    max_hold_sec: int = 300      # 5분
    use_ranging_filter: bool = True
    ranging_rsi_min: float = 40.0
    ranging_rsi_max: float = 60.0

class RSIBollingerScalper:
    """볼린저 밴드 반등형 Re-entry Scalper"""
    
    def __init__(self, config: Optional[ScalperConfig] = None):
        self.config = config or ScalperConfig()
        self.last_signal_time = 0
        self.min_signal_interval = 1.0  # 최소 시그널 간격 (초)
    
    def generate_signal(self, candles: List[Dict[str, Any]], position_state: Optional[Dict] = None) -> Dict[str, Any]:
        """
        캔들 데이터를 기반으로 매매 시그널 생성
        
        Args:
            candles: 캔들 데이터 리스트 (최신이 마지막, index -1)
                    [{'timestamp': ms, 'opening_price': float, 'high_price': float, 
                      'low_price': float, 'trade_price': float, 'candle_acc_trade_volume': float}, ...]
            position_state: 현재 포지션 상태 (None이면 포지션 없음)
        
        Returns:
            {"action": "BUY"/"SELL"/"HOLD", "meta": {...}}
        """
        try:
            # 시그널 간격 제한
            current_time = time.time()
            if current_time - self.last_signal_time < self.min_signal_interval:
                return {"action": "HOLD", "meta": {"reason": "signal_cooldown"}}
            
            if len(candles) < max(self.config.rsi_window, self.config.bb_window) + 1:
                return {"action": "HOLD", "meta": {"reason": "insufficient_data", "required": max(self.config.rsi_window, self.config.bb_window) + 1, "available": len(candles)}}
            
            # 가격 데이터 추출 (종가 기준)
            prices = [float(candle['trade_price']) for candle in candles]
            current_price = prices[-1]
            prev_price = prices[-2] if len(prices) > 1 else current_price
            
            # 기술적 지표 계산
            rsi_values = calculate_rsi(prices, self.config.rsi_window)
            bb_upper, bb_middle, bb_lower = calculate_bollinger_bands(prices, self.config.bb_window, self.config.bb_std)
            
            current_rsi = rsi_values[-1] if len(rsi_values) > 0 else None
            current_bb_lower = bb_lower[-1] if len(bb_lower) > 0 else None
            prev_bb_lower = bb_lower[-2] if len(bb_lower) > 1 else None
            
            # 지표 유효성 검사
            if current_rsi is None or current_bb_lower is None or prev_bb_lower is None:
                return {"action": "HOLD", "meta": {"reason": "invalid_indicators"}}
            
            # 이전 RSI 값도 필요
            prev_rsi = rsi_values[-2] if len(rsi_values) > 1 else None
            if prev_rsi is None:
                return {"action": "HOLD", "meta": {"reason": "insufficient_rsi_data"}}
            
            # 포지션이 있는 경우 청산 조건 확인
            if position_state and position_state.get('has_position'):
                return self._check_exit_conditions(current_price, position_state)
            
            # 포지션이 없는 경우 진입 조건 확인
            return self._check_entry_conditions(current_price, prev_price, current_rsi, prev_rsi, current_bb_lower, prev_bb_lower, rsi_values)
        
        except Exception as e:
            logger.error(f"Signal generation error: {e}")
            return {"action": "HOLD", "meta": {"reason": "error", "error": str(e)}}
    
    def _check_exit_conditions(self, current_price: float, position_state: Dict) -> Dict[str, Any]:
        """청산 조건 확인"""
        entry_price = position_state.get('entry_price', 0)
        entry_time = position_state.get('entry_time', 0)
        current_time = time.time()
        
        if entry_price == 0:
            return {"action": "SELL", "meta": {"reason": "invalid_entry_price"}}
        
        # 수익률 계산
        profit_rate = get_price_change_percent(current_price, entry_price)
        hold_time = current_time - entry_time
        
        # 익절 조건
        if profit_rate >= self.config.take_profit:
            self.last_signal_time = current_time
            return {
                "action": "SELL", 
                "meta": {
                    "reason": "take_profit",
                    "profit_rate": profit_rate,
                    "hold_time": hold_time,
                    "entry_price": entry_price,
                    "current_price": current_price
                }
            }
        
        # 손절 조건
        if profit_rate <= self.config.stop_loss:
            self.last_signal_time = current_time
            return {
                "action": "SELL", 
                "meta": {
                    "reason": "stop_loss",
                    "profit_rate": profit_rate,
                    "hold_time": hold_time,
                    "entry_price": entry_price,
                    "current_price": current_price
                }
            }
        
        # 시간 기반 청산
        if hold_time >= self.config.max_hold_sec:
            self.last_signal_time = current_time
            return {
                "action": "SELL", 
                "meta": {
                    "reason": "max_hold_time",
                    "profit_rate": profit_rate,
                    "hold_time": hold_time,
                    "entry_price": entry_price,
                    "current_price": current_price
                }
            }
        
        return {
            "action": "HOLD", 
            "meta": {
                "reason": "holding",
                "profit_rate": profit_rate,
                "hold_time": hold_time,
                "entry_price": entry_price,
                "current_price": current_price
            }
        }
    
    def _check_entry_conditions(self, current_price: float, prev_price: float, current_rsi: float, prev_rsi: float,
                               current_bb_lower: float, prev_bb_lower: float, rsi_values: List[float]) -> Dict[str, Any]:
        """진입 조건 확인"""
        
        # 횡보 필터 (선택적)
        if self.config.use_ranging_filter:
            # 최근 RSI 평균으로 횡보 구간 판단
            recent_rsi = [r for r in rsi_values[-10:] if r is not None and not pd.isna(r)]
            if len(recent_rsi) > 5:
                avg_rsi = sum(recent_rsi) / len(recent_rsi)
                if not (self.config.ranging_rsi_min <= avg_rsi <= self.config.ranging_rsi_max):
                    return {
                        "action": "HOLD", 
                        "meta": {
                            "reason": "not_ranging_market",
                            "avg_rsi": avg_rsi,
                            "current_rsi": current_rsi
                        }
                    }
        
        # ⚔️ 볼린저 밴드 반등형 Re-entry 조건
        
        # 조건 1: 이전 캔들이 볼린저 하단 이탈 (close < lower_band)
        prev_below_bb = prev_price < prev_bb_lower
        
        # 조건 2: 현재 캔들이 볼린저 하단 복귀 (close > lower_band) - 되돌림 신호
        current_above_bb = current_price > current_bb_lower
        bb_reentry = prev_below_bb and current_above_bb
        
        # 조건 3: RSI 상승 전환 (직전 RSI < 35, 현재 RSI > 직전 RSI)
        rsi_was_low = prev_rsi < self.config.rsi_reentry_threshold  # 35
        rsi_rising = current_rsi > prev_rsi
        rsi_upturn = rsi_was_low and rsi_rising
        
        # 🚀 "낙하산 펼쳤다" 매수 시그널
        if bb_reentry and rsi_upturn:
            self.last_signal_time = time.time()
            return {
                "action": "BUY",
                "meta": {
                    "reason": "reentry_signal",
                    "current_price": current_price,
                    "current_rsi": current_rsi,
                    "prev_rsi": prev_rsi,
                    "bb_lower": current_bb_lower,
                    "prev_below_bb": prev_below_bb,
                    "current_above_bb": current_above_bb,
                    "bb_reentry": bb_reentry,
                    "rsi_was_low": rsi_was_low,
                    "rsi_rising": rsi_rising,
                    "rsi_upturn": rsi_upturn
                }
            }
        
        return {
            "action": "HOLD",
            "meta": {
                "reason": "no_reentry_signal",
                "current_price": current_price,
                "current_rsi": current_rsi,
                "prev_rsi": prev_rsi,
                "bb_lower": current_bb_lower,
                "bb_reentry": bb_reentry,
                "rsi_upturn": rsi_upturn,
                "prev_below_bb": prev_below_bb,
                "current_above_bb": current_above_bb,
                "rsi_was_low": rsi_was_low,
                "rsi_rising": rsi_rising
            }
        }

# 기본 인스턴스 생성
default_scalper = RSIBollingerScalper()

def generate_signal(candles: List[Dict[str, Any]], position_state: Optional[Dict] = None) -> Dict[str, Any]:
    """
    편의를 위한 래퍼 함수
    """
    return default_scalper.generate_signal(candles, position_state)