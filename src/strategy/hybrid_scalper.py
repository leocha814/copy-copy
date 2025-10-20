"""
⚙️ 공격형 하이브리드 스캘퍼 자동매매 전략

3가지 통합 시그널:
1. 볼린저 재진입 + 거래량 돌파 (Volume Break Re-entry)
2. RSI 반등 가속형 (Momentum Rebound Scalper)  
3. Fakeout Hunter (밴드 이탈 후 꼬리 캔들 매수)

특징:
- 횡보장 중심 초단기 스캘핑
- 조건 충족 시 즉시 시장가 매수
- 짧은 익절/손절로 빠른 청산
- 3가지 시그널 중 하나라도 조건 만족 시 진입
"""

import time
import pandas as pd
import numpy as np
from typing import List, Dict, Optional, Any, Tuple
from dataclasses import dataclass
from src.strategy.indicators import calculate_rsi, calculate_bollinger_bands, calculate_sma, get_price_change_percent
from src.logger import logger
from src.performance_monitor import TradeResult, log_trade_result

@dataclass
class HybridScalperConfig:
    """공격형 하이브리드 스캘퍼 설정"""
    
    rsi_window: int = 14
    bb_window: int = 20
    bb_std: float = 2.0
    volume_window: int = 20
    
    
    take_profit: float = 0.007  
    stop_loss: float = -0.003   
    adaptive_profit: bool = True  
    min_hold_sec: int = 5       
    max_hold_sec: int = 180     
    cooldown_sec: int = 3       
    
    
    volume_boost_ratio: float = 1.5  
    volume_ma_ratio: float = 1.3     
    
    
    rsi_low_threshold: float = 35.0   
    rsi_rebound_delta: float = 5.0    
    rsi_exit_threshold: float = 60.0  
    
    
    fakeout_tail_ratio: float = 1.0   
    fakeout_max_hold: int = 180       
    
    
    rsi_overbought: float = 65.0      
    rsi_drop_threshold: float = 2.0   
    
    
    use_ranging_filter: bool = True
    ranging_rsi_min: float = 40.0
    ranging_rsi_max: float = 60.0
    
    
    profit_tune_window: int = 50     
    min_profit_rate: float = 0.0055  
    max_take_profit: float = 0.010   
    
    
    max_pyramid_entries: int = 2     
    pyramid_rsi_delta: float = 3.0   

class HybridScalper:
    """공격형 하이브리드 스캘퍼 전략"""
    
    def __init__(self, config: Optional[HybridScalperConfig] = None):
        self.config = config or HybridScalperConfig()
        self.last_signal_time = 0
        self.last_sell_time = 0
        
        
        self.entry_strategy = None  
        self.entry_rsi = None
        self.entry_time = None
        
        
        self.last_bar_ts = None  
        
        
        self.recent_trades = []  
        self.current_take_profit = self.config.take_profit  
        
        
        self.pyramid_entries = 0  
        self.pyramid_positions = []  
    
    def _update_adaptive_profit_target(self):
        """적응형 수익률 조정 - 최근 거래 성과 기반 익절 목표 조정"""
        if not self.config.adaptive_profit or len(self.recent_trades) < 10:
            return
        
        
        current_time = time.time()
        cutoff_time = current_time - (24 * 3600)  
        self.recent_trades = [(rate, ts) for rate, ts in self.recent_trades if ts > cutoff_time]
        
        
        recent_n = self.recent_trades[-self.config.profit_tune_window:]
        if len(recent_n) < self.config.profit_tune_window:
            return
        
        
        successful_trades = [rate for rate, _ in recent_n if rate > 0]
        if len(successful_trades) < self.config.profit_tune_window * 0.3:  
            return
        
        avg_profit_rate = sum(successful_trades) / len(successful_trades)
        
        
        if avg_profit_rate < self.config.min_profit_rate:
            adjustment = (self.config.min_profit_rate - avg_profit_rate) * 2
            new_target = min(
                self.current_take_profit + adjustment,
                self.config.max_take_profit
            )
            self.current_take_profit = new_target
            logger.info(f"📈 익절 목표 상향 조정: {self.current_take_profit:.1%} (평균 수익률 부족: {avg_profit_rate:.1%})")
        
        
        elif avg_profit_rate > self.config.min_profit_rate * 1.5:
            adjustment = 0.0005  
            new_target = max(
                self.current_take_profit - adjustment,
                self.config.take_profit
            )
            self.current_take_profit = new_target
            logger.info(f"📉 익절 목표 하향 조정: {self.current_take_profit:.1%} (평균 수익률 양호: {avg_profit_rate:.1%})")
    
    def _record_trade_result(self, profit_rate: float, position_state: Dict = None, current_price: float = 0, exit_reason: str = "unknown"):
        """거래 결과 기록 및 성능 모니터링"""
        current_time = time.time()
        
        # 기존 적응형 조정용 기록
        self.recent_trades.append((profit_rate, current_time))
        
        if len(self.recent_trades) > self.config.profit_tune_window * 2:
            self.recent_trades = self.recent_trades[-self.config.profit_tune_window:]
        
        # 📊 상세 거래 결과 로깅 (성능 모니터링용)
        if position_state and hasattr(self, 'current_market'):
            try:
                entry_price = position_state.get('entry_price', 0)
                entry_time = position_state.get('entry_time', current_time)
                hold_time = current_time - entry_time
                profit_krw = profit_rate * position_state.get('krw_amount', 20000)  # 추정 KRW 수익
                
                # 슬리피지 추정 (지정가 vs 실제 체결가)
                expected_price = position_state.get('limit_price', entry_price)
                slippage = abs(current_price - expected_price) / expected_price if expected_price > 0 else 0
                
                trade_result = TradeResult(
                    timestamp=current_time,
                    market=getattr(self, 'current_market', 'UNKNOWN'),
                    entry_strategy=self.entry_strategy or 'unknown',
                    entry_price=entry_price,
                    exit_price=current_price,
                    entry_time=entry_time,
                    exit_time=current_time,
                    profit_rate=profit_rate,
                    profit_krw=profit_krw,
                    hold_time=hold_time,
                    exit_reason=exit_reason,
                    entry_rsi=self.entry_rsi or 0,
                    exit_rsi=getattr(self, 'current_rsi', 0),
                    volume_ratio=getattr(self, 'last_volume_ratio', None),
                    slippage=slippage
                )
                
                # 성능 모니터링 시스템에 로깅
                log_trade_result(trade_result)
                
            except Exception as e:
                logger.error(f"거래 결과 상세 로깅 실패: {e}")
        
        # 적응형 수익률 조정 실행
        self._update_adaptive_profit_target()
    
    def _should_pyramid_entry(self, current_rsi: float, prev_rsi: float, strategy: str) -> bool:
        """피라미딩 진입 조건 확인"""
        if self.pyramid_entries >= self.config.max_pyramid_entries:
            return False
        
        
        if strategy == "rsi_rebound":
            rsi_acceleration = current_rsi - prev_rsi
            return rsi_acceleration >= self.config.pyramid_rsi_delta
        
        return False
    
    def _calculate_limit_entry_price(self, current_price: float, strategy: str) -> float:
        """
        지정가 진입 가격 계산 (슬리피지 최소화)
        
        전략별로 다른 접근:
        - volume_break: 돌파 직후이므로 현재가보다 약간 높게 설정
        - rsi_rebound: 반등 중이므로 현재가 근처에서 진입
        - fakeout_hunter: 급락 후 회복이므로 현재가보다 약간 낮게 설정
        """
        if strategy == "volume_break":
            
            return current_price * 1.0002
        elif strategy == "rsi_rebound":
            
            return current_price * 1.0001
        elif strategy == "fakeout_hunter":
            
            return current_price * 0.9999
        elif strategy == "pyramid":
            
            return current_price * 0.9998
        else:
            
            return current_price
    
    def generate_signal(self, candles: List[Dict[str, Any]], position_state: Optional[Dict] = None) -> Dict[str, Any]:
        """
        하이브리드 스캘핑 시그널 생성
        """
        try:
            current_time = time.time()
            
            if current_time - self.last_signal_time < self.config.cooldown_sec:
                return {"action": "HOLD", "meta": {"reason": "signal_cooldown"}}
            
            if current_time - self.last_sell_time < self.config.cooldown_sec:
                return {"action": "HOLD", "meta": {"reason": "sell_cooldown"}}
            
            required_length = max(self.config.rsi_window, self.config.bb_window, self.config.volume_window) + 5
            if len(candles) < required_length:
                return {"action": "HOLD", "meta": {"reason": "insufficient_data", "required": required_length, "available": len(candles)}}
            
            prices = [float(c['trade_price']) for c in candles]
            closes = prices  # ✅ closes 정의 추가
            volumes = [float(c['candle_acc_trade_volume']) for c in candles]
            opens = [float(c['opening_price']) for c in candles]
            highs = [float(c['high_price']) for c in candles]
            lows = [float(c['low_price']) for c in candles]
            
            current_price = prices[-1]
            current_volume = volumes[-1]
            current_open = opens[-1]
            current_high = highs[-1]
            current_low = lows[-1]
            
            rsi_values = calculate_rsi(prices, self.config.rsi_window)
            bb_upper, bb_middle, bb_lower = calculate_bollinger_bands(prices, self.config.bb_window, self.config.bb_std)
            
            if not rsi_values or len(rsi_values) < 4 or not bb_lower:
                return {"action": "HOLD", "meta": {"reason": "invalid_indicators"}}
            
            current_rsi = rsi_values[-1]
            prev_rsi = rsi_values[-2]
            current_bb_lower = bb_lower[-1]
            current_bb_upper = bb_upper[-1]
            
            # 이미 포지션이 있으면 청산 조건 체크
            if position_state and position_state.get('has_position'):
                return self._check_exit_conditions(
                    current_price, current_rsi, prev_rsi, current_bb_upper, 
                    position_state, current_time
                )
            
            # 횡보장 필터
            if self.config.use_ranging_filter:
                if not self._is_ranging_market(rsi_values):
                    return {"action": "HOLD", "meta": {"reason": "not_ranging_market"}}
            
            # 진입 조건 체크
            entry_signal = self._check_hybrid_entry_conditions(
                candles,
                current_price,
                opens[-2],   # prev_open
                closes[-2],  # prev_close
                highs[-2],   # prev_high
                lows[-2],    # prev_low
                volumes[-2], # prev_volume
                volumes,
                prices,
                current_rsi,
                rsi_values,
                current_bb_lower,
                current_bb_upper,
                current_time
            )


            
            # ✅ 매수 시 entry 정보 기록
            if entry_signal["action"] == "BUY":
                if position_state is not None:
                    position_state["entry_price"] = current_price
                    position_state["entry_time"] = time.time()
                    # ⚠️ krw_amount는 runner에서 지정되므로 없을 수 있음 → 안전 처리
                    position_state["volume"] = position_state.get("volume") or 0.0
            
            return entry_signal
        
        except Exception as e:
            logger.error(f"Hybrid scalper signal generation error: {e}")
            return {"action": "HOLD", "meta": {"reason": "error", "error": str(e)}}

    
    def _check_exit_conditions(self, current_price: float, current_rsi: float, prev_rsi: float,
                              current_bb_upper: float, position_state: Dict, current_time: float) -> Dict[str, Any]:
        """하이브리드 청산 조건 확인"""
        entry_price = position_state.get('entry_price', 0)
        entry_time = position_state.get('entry_time', 0)
        
        if entry_price is None or entry_price <= 0:
            market = position_state.get('market', 'UNKNOWN')
            logger.error(f"[Safety Stop] Invalid entry_price={entry_price} for {market}. Skipping profit calculation.")
            return {"action": "HOLD", "meta": {"reason": "invalid_entry_price"}}

        
        
        profit_rate = get_price_change_percent(current_price, entry_price)
        hold_time = current_time - entry_time
        
        
        
        
        if current_rsi >= self.config.rsi_overbought:  
            self._reset_strategy_state()
            self.last_signal_time = current_time
            self.last_sell_time = current_time
            return {
                "action": "SELL",
                "meta": {
                    "reason": "rsi_overbought_exit",
                    "profit_rate": profit_rate,
                    "hold_time": hold_time,
                    "current_rsi": current_rsi,
                    "entry_strategy": self.entry_strategy
                }
            }
        
        
        if current_price >= current_bb_upper:
            self._reset_strategy_state()
            self.last_signal_time = current_time
            self.last_sell_time = current_time
            return {
                "action": "SELL",
                "meta": {
                    "reason": "bb_upper_breakout_exit",
                    "profit_rate": profit_rate,
                    "hold_time": hold_time,
                    "current_price": current_price,
                    "entry_strategy": self.entry_strategy
                }
            }
        
        
        rsi_drop = prev_rsi - current_rsi
        if rsi_drop >= self.config.rsi_drop_threshold:  
            self._reset_strategy_state()
            self.last_signal_time = current_time
            self.last_sell_time = current_time
            return {
                "action": "SELL",
                "meta": {
                    "reason": "rsi_drop_exit",
                    "profit_rate": profit_rate,
                    "hold_time": hold_time,
                    "rsi_drop": rsi_drop,
                    "entry_strategy": self.entry_strategy
                }
            }
        
        
        if profit_rate >= self.current_take_profit:
            self._record_trade_result(profit_rate, position_state, current_price, "adaptive_take_profit")
            self._reset_strategy_state()
            self.last_signal_time = current_time
            self.last_sell_time = current_time
            return {
                "action": "SELL",
                "meta": {
                    "reason": "adaptive_take_profit",
                    "profit_rate": profit_rate,
                    "target_profit": self.current_take_profit,
                    "hold_time": hold_time,
                    "current_rsi": current_rsi,
                    "entry_strategy": self.entry_strategy
                }
            }
        
        
        rsi_drop = prev_rsi - current_rsi
        if profit_rate <= self.config.stop_loss or rsi_drop >= self.config.rsi_drop_threshold:  
            self._record_trade_result(profit_rate, position_state, current_price, "immediate_stop_loss")
            self._reset_strategy_state()
            self.last_signal_time = current_time
            self.last_sell_time = current_time
            return {
                "action": "SELL",
                "meta": {
                    "reason": "immediate_stop_loss",
                    "profit_rate": profit_rate,
                    "hold_time": hold_time,
                    "rsi_drop": rsi_drop,
                    "entry_strategy": self.entry_strategy
                }
            }
        
        
        if hold_time >= self.config.min_hold_sec:
            
            
            if self.entry_strategy == "rsi_rebound" and current_rsi >= self.config.rsi_exit_threshold:  
                self._reset_strategy_state()
                self.last_signal_time = current_time
                self.last_sell_time = current_time
                return {
                    "action": "SELL",
                    "meta": {
                        "reason": "rsi_rebound_exit",
                        "profit_rate": profit_rate,
                        "hold_time": hold_time,
                        "current_rsi": current_rsi,
                        "entry_strategy": self.entry_strategy
                    }
                }
            
            
            if self.entry_strategy == "fakeout_hunter" and hold_time >= self.config.fakeout_max_hold:
                self._reset_strategy_state()
                self.last_signal_time = current_time
                self.last_sell_time = current_time
                return {
                    "action": "SELL",
                    "meta": {
                        "reason": "fakeout_time_exit",
                        "profit_rate": profit_rate,
                        "hold_time": hold_time,
                        "entry_strategy": self.entry_strategy
                    }
                }
        
        
        if hold_time >= self.config.max_hold_sec:  
            self._reset_strategy_state()
            self.last_signal_time = current_time
            self.last_sell_time = current_time
            return {
                "action": "SELL",
                "meta": {
                    "reason": "max_hold_time",
                    "profit_rate": profit_rate,
                    "hold_time": hold_time,
                    "entry_strategy": self.entry_strategy
                }
            }
        
        
        return {
            "action": "HOLD",
            "meta": {
                "reason": "holding_position",
                "profit_rate": profit_rate,
                "hold_time": hold_time,
                "current_rsi": current_rsi,
                "entry_strategy": self.entry_strategy
            }
        }
    
    def _check_hybrid_entry_conditions(self, candles: List[Dict], current_price: float,
                                   prev_close: float, prev_open: float, prev_high: float,
                                   prev_low: float, prev_volume: float,
                                   volumes: List[float], prices: List[float], current_rsi: float,
                                   rsi_values: List[float], current_bb_lower: float, current_bb_upper: float,
                                   current_time: float) -> Dict[str, Any]:

        """3가지 하이브리드 진입 조건 확인"""
        
        
        
        
        
        volume_signal = self._check_volume_break_reentry(
            current_price, prev_volume, volumes, prev_high, current_rsi, rsi_values
        )
        
        
        rsi_signal = self._check_rsi_momentum_rebound(
            current_price, prev_close, current_rsi, rsi_values
        )
        
        
        fakeout_signal = self._check_fakeout_hunter(
            prev_close, prev_open, prev_high, prev_low, current_bb_lower
        )
        
        
        entry_signals = [volume_signal, rsi_signal, fakeout_signal]
        valid_signals = [signal for signal in entry_signals if signal['valid']]
        
        if valid_signals:
            
            if volume_signal['valid']:
                chosen_signal = volume_signal
                self.entry_strategy = "volume_break"
            elif rsi_signal['valid']:
                chosen_signal = rsi_signal
                self.entry_strategy = "rsi_rebound"
            else:
                chosen_signal = fakeout_signal
                self.entry_strategy = "fakeout_hunter"
            
            
            self.entry_rsi = current_rsi
            self.entry_time = current_time
            self.last_signal_time = current_time
            
            
            limit_price = self._calculate_limit_entry_price(current_price, self.entry_strategy)
            
            return {
                "action": "BUY",
                "meta": {
                    "reason": f"hybrid_entry_{self.entry_strategy}",
                    "entry_strategy": self.entry_strategy,
                    "current_price": current_price,
                    "limit_price": limit_price,  
                    "order_type": "limit",       
                    "current_rsi": current_rsi,
                    "signal_details": chosen_signal['details'],
                    "all_signals": {
                        "volume_break": volume_signal,
                        "rsi_rebound": rsi_signal,
                        "fakeout_hunter": fakeout_signal
                    }
                }
            }
        
        return {
            "action": "HOLD",
            "meta": {
                "reason": "no_hybrid_signal",
                "current_rsi": current_rsi,
                "all_signals": {
                    "volume_break": volume_signal,
                    "rsi_rebound": rsi_signal,
                    "fakeout_hunter": fakeout_signal
                }
            }
        }
    
    def _check_volume_break_reentry(self, current_price: float, prev_volume: float,
                                   volumes: List[float], prev_high: float, current_rsi: float,
                                   rsi_values: List[float]) -> Dict[str, Any]:
        """Volume Break Re-entry 시그널 확인 (강화된 거래량 필터)"""
        try:
            
            if len(volumes) < self.config.volume_window + 1:
                return {"valid": False, "reason": "insufficient_volume_data"}
            
            avg_volume = sum(volumes[-self.config.volume_window-1:-1]) / self.config.volume_window
            volume_ratio = prev_volume / avg_volume if avg_volume > 0 else 0
            
            
            
            volume_boost = volume_ratio >= self.config.volume_boost_ratio  
            
            
            volume_ma_check = volume_ratio >= self.config.volume_ma_ratio  
            
            
            recent_volumes = volumes[-6:-1] if len(volumes) >= 6 else volumes[:-1]
            volume_consistency = len([v for v in recent_volumes if v >= avg_volume * 0.8]) >= 2
            
            
            price_breakout = current_price > prev_high
            hard_break = current_price >= prev_high * 1.0005  
            rsi_rising = len(rsi_values) > 1 and current_rsi > rsi_values[-2]
            
            
            valid = (price_breakout and volume_boost and volume_ma_check and 
                    volume_consistency and rsi_rising)
            
            return {
                "valid": valid,
                "details": {
                    "volume_ratio": volume_ratio,
                    "volume_boost": volume_boost,
                    "volume_ma_check": volume_ma_check,
                    "volume_consistency": volume_consistency,
                    "price_breakout": price_breakout,
                    "hard_break": hard_break,
                    "rsi_rising": rsi_rising,
                    "prev_high": prev_high,
                    "avg_volume": avg_volume
                },
                "reason": "enhanced_volume_break_conditions" if valid else "enhanced_volume_break_not_met"
            }
        
        except Exception as e:
            logger.error(f"Error checking volume break re-entry: {e}")
            return {"valid": False, "reason": "volume_break_error"}
    
    def _check_rsi_momentum_rebound(self, current_price: float, prev_close: float,
                                   current_rsi: float, rsi_values: List[float]) -> Dict[str, Any]:
        """RSI Momentum Rebound 시그널 확인"""
        try:
            if len(rsi_values) < 4:
                return {"valid": False, "reason": "insufficient_rsi_data"}
            
            rsi_3_ago = rsi_values[-4]  
            rsi_delta = current_rsi - rsi_3_ago
            
            
            rsi_was_low = rsi_3_ago < self.config.rsi_low_threshold  
            rsi_rebound_strong = rsi_delta > self.config.rsi_rebound_delta  
            price_rising = current_price >= prev_close * 0.9995  
            
            valid = rsi_was_low and rsi_rebound_strong and price_rising
            
            return {
                "valid": valid,
                "details": {
                    "rsi_3_ago": rsi_3_ago,
                    "current_rsi": current_rsi,
                    "rsi_delta": rsi_delta,
                    "rsi_was_low": rsi_was_low,
                    "rsi_rebound_strong": rsi_rebound_strong,
                    "price_rising": price_rising
                },
                "reason": "rsi_rebound_conditions" if valid else "rsi_rebound_not_met"
            }
        
        except Exception as e:
            logger.error(f"Error checking RSI momentum rebound: {e}")
            return {"valid": False, "reason": "rsi_rebound_error"}
    
    def _check_fakeout_hunter(self, prev_close: float, prev_open: float,
                             prev_high: float, prev_low: float, current_bb_lower: float) -> Dict[str, Any]:
        """Fakeout Hunter 시그널 확인 (완성봉 기준, 향상된 꼬리 판정)"""
        try:
            
            bullish_candle = prev_close > prev_open  
            lower_wick_touch = prev_low < current_bb_lower  
            close_above_band = prev_close > current_bb_lower  
            
            
            body = abs(prev_close - prev_open)
            lower_wick = prev_open - prev_low if bullish_candle else prev_close - prev_low
            upper_wick = prev_high - prev_close if bullish_candle else prev_high - prev_open
            
            
            long_lower_tail = (
                (lower_wick > body * 1.0) or  
                (lower_wick > upper_wick * self.config.fakeout_tail_ratio)  
            )
            
            valid = bullish_candle and lower_wick_touch and close_above_band and long_lower_tail
            
            return {
                "valid": valid,
                "details": {
                    "bullish_candle": bullish_candle,
                    "lower_wick_touch": lower_wick_touch,
                    "close_above_band": close_above_band,
                    "long_lower_tail": long_lower_tail,
                    "lower_wick": lower_wick,
                    "upper_wick": upper_wick,
                    "bb_lower": current_bb_lower
                },
                "reason": "fakeout_conditions" if valid else "fakeout_not_met"
            }
        
        except Exception as e:
            logger.error(f"Error checking fakeout hunter: {e}")
            return {"valid": False, "reason": "fakeout_error"}
    
    def _is_ranging_market(self, rsi_values: List[float]) -> bool:
        """횡보 시장 판단 (RSI 기반)"""
        try:
            recent_rsi = [r for r in rsi_values[-10:] if r is not None and not pd.isna(r)]
            if len(recent_rsi) >= 5:
                avg_rsi = sum(recent_rsi) / len(recent_rsi)
                return self.config.ranging_rsi_min <= avg_rsi <= self.config.ranging_rsi_max
            return False
        
        except Exception as e:
            logger.error(f"Error checking ranging market: {e}")
            return False
    
    def _reset_strategy_state(self):
        """전략 상태 초기화"""
        self.entry_strategy = None
        self.entry_rsi = None
        self.entry_time = None
        
        self.pyramid_entries = 0
        self.pyramid_positions.clear()
        


_hybrid_strategy_instances = {}

def get_hybrid_strategy_instance(market: str = "default") -> HybridScalper:
    """코인별 독립적인 하이브리드 전략 인스턴스 반환"""
    if market not in _hybrid_strategy_instances:
        instance = HybridScalper()
        instance.current_market = market  # 성능 모니터링을 위한 마켓 정보 설정
        _hybrid_strategy_instances[market] = instance
        logger.info(f"Created new HybridScalper instance for {market}")
    return _hybrid_strategy_instances[market]

def generate_signal(candles: List[Dict[str, Any]], position_state: Optional[Dict] = None, market: str = "default") -> Dict[str, Any]:
    """코인별 독립적인 하이브리드 시그널 생성"""
    strategy = get_hybrid_strategy_instance(market)
    return strategy.generate_signal(candles, position_state)


default_hybrid_scalper = get_hybrid_strategy_instance("default")