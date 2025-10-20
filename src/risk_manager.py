"""
리스크 관리 모듈

초단타 스캘핑에서 필수적인 리스크 관리 레이어를 제공합니다.
- 주문 전 사전 검증
- API 레이트 리밋 핸들링
- 시장 상태 분석
- 응급 정지 메커니즘
"""

import time
import os
import random
from typing import Dict, List, Tuple, Optional, Any, Union
from datetime import datetime, timedelta
from dataclasses import dataclass
import requests
import pandas as pd
import numpy as np
from src.logger import logger
from src.strategy.indicators import calculate_bollinger_bands, calculate_rsi, calculate_sma

@dataclass
class RiskLimits:
    """리스크 제한 설정"""
    max_order_krw: float = 10000.0          # 1회 주문 최대 금액
    daily_max_dd_pct: float = 0.05          # 일일 최대 손실률 (5%)
    daily_max_loss_krw: float = 50000.0     # 일일 최대 손실 금액
    max_positions: int = 1                   # 최대 동시 포지션 수
    consecutive_loss_limit: int = 3          # 연속 손실 제한
    min_balance_krw: float = 5000.0         # 최소 잔고 유지
    
    # 거래 시간 제한
    trading_start_hour: int = 9             # 거래 시작 시간
    trading_end_hour: int = 23              # 거래 종료 시간
    allow_weekend: bool = True              # 주말 거래 허용
    
    # 레이트 리밋 설정
    max_requests_per_second: int = 8        # 초당 최대 요청 수
    rate_limit_backoff_base: float = 1.0    # 백오프 기본 시간
    rate_limit_max_retries: int = 5         # 최대 재시도 횟수

class RiskManager:
    """리스크 관리자"""
    
    def __init__(self, limits: Optional[RiskLimits] = None):
        self.limits = limits or self._load_limits_from_env()
        
        # 상태 추적
        self.daily_stats = self._load_daily_stats()
        self.last_request_times = []
        self.consecutive_losses = 0
        self.emergency_stop = False
        self.last_emergency_check = time.time()
        
        logger.info(f"Risk Manager initialized with limits: {self.limits}")
    
    def _load_limits_from_env(self) -> RiskLimits:
        """환경변수에서 리스크 제한 로드"""
        return RiskLimits(
            max_order_krw=float(os.getenv('MAX_ORDER_KRW', '10000')),
            daily_max_dd_pct=float(os.getenv('DAILY_MAX_DD_PCT', '0.05')),
            daily_max_loss_krw=float(os.getenv('DAILY_MAX_LOSS_KRW', '50000')),
            max_positions=int(os.getenv('MAX_POSITIONS', '1')),
            consecutive_loss_limit=int(os.getenv('CONSECUTIVE_LOSS_LIMIT', '3')),
            min_balance_krw=float(os.getenv('MIN_BALANCE_KRW', '5000')),
            trading_start_hour=int(os.getenv('TRADING_START_HOUR', '9')),
            trading_end_hour=int(os.getenv('TRADING_END_HOUR', '23')),
            allow_weekend=os.getenv('ALLOW_WEEKEND', 'true').lower() == 'true',
            max_requests_per_second=int(os.getenv('MAX_REQUESTS_PER_SECOND', '8')),
            rate_limit_backoff_base=float(os.getenv('RATE_LIMIT_BACKOFF_BASE', '1.0')),
            rate_limit_max_retries=int(os.getenv('RATE_LIMIT_MAX_RETRIES', '5'))
        )
    
    def _load_daily_stats(self) -> Dict[str, Any]:
        """일일 통계 로드"""
        today = datetime.now().strftime('%Y-%m-%d')
        return {
            'date': today,
            'total_loss': 0.0,
            'total_profit': 0.0,
            'trade_count': 0,
            'loss_count': 0,
            'last_reset': time.time()
        }
    
    def _reset_daily_stats_if_needed(self):
        """필요시 일일 통계 리셋"""
        today = datetime.now().strftime('%Y-%m-%d')
        if self.daily_stats['date'] != today:
            logger.info(f"Resetting daily stats for new day: {today}")
            self.daily_stats = self._load_daily_stats()
            self.consecutive_losses = 0
    
    def check_pre_trade(self, market: str, krw_amount: Optional[float] = None, 
                       volume: Optional[float] = None, current_positions: int = 0,
                       current_balance: float = 0.0) -> Tuple[bool, str]:
        """
        거래 전 사전 검증
        
        Args:
            market: 거래 마켓
            krw_amount: KRW 주문 금액 (매수시)
            volume: 코인 수량 (매도시)
            current_positions: 현재 포지션 수
            current_balance: 현재 KRW 잔고
        
        Returns:
            (허용 여부, 사유)
        """
        try:
            self._reset_daily_stats_if_needed()
            
            # 응급 정지 확인
            if self.emergency_stop:
                return False, "emergency_stop_activated"
            
            # 거래 시간 확인
            if not self._is_trading_hours():
                return False, "outside_trading_hours"
            
            # 주문 금액 제한 확인
            if krw_amount and krw_amount > self.limits.max_order_krw:
                return False, f"order_amount_exceeds_limit_{krw_amount}>{self.limits.max_order_krw}"
            
            # 최소 잔고 확인
            if current_balance < self.limits.min_balance_krw:
                return False, f"insufficient_balance_{current_balance}<{self.limits.min_balance_krw}"
            
            # 포지션 수 제한 확인
            if current_positions >= self.limits.max_positions:
                return False, f"max_positions_exceeded_{current_positions}>={self.limits.max_positions}"
            
            # 일일 손실 제한 확인
            if self.daily_stats['total_loss'] >= self.limits.daily_max_loss_krw:
                return False, f"daily_loss_limit_exceeded_{self.daily_stats['total_loss']}>={self.limits.daily_max_loss_krw}"
            
            # 일일 손실률 확인 (시작 자본 대비)
            if self.daily_stats['total_profit'] < 0:
                loss_rate = abs(self.daily_stats['total_profit']) / (current_balance + abs(self.daily_stats['total_profit']))
                if loss_rate >= self.limits.daily_max_dd_pct:
                    return False, f"daily_drawdown_exceeded_{loss_rate:.2%}>={self.limits.daily_max_dd_pct:.2%}"
            
            # 연속 손실 확인
            if self.consecutive_losses >= self.limits.consecutive_loss_limit:
                return False, f"consecutive_losses_exceeded_{self.consecutive_losses}>={self.limits.consecutive_loss_limit}"
            
            return True, "approved"
        
        except Exception as e:
            logger.error(f"Error in pre-trade check: {e}")
            return False, f"check_error_{str(e)}"
    
    def _is_trading_hours(self) -> bool:
        """거래 가능 시간 확인"""
        now = datetime.now()
        
        # 주말 확인
        if not self.limits.allow_weekend and now.weekday() >= 5:  # 5=토요일, 6=일요일
            return False
        
        # 시간대 확인
        current_hour = now.hour
        if self.limits.trading_start_hour <= self.limits.trading_end_hour:
            # 일반적인 경우 (9시-23시)
            return self.limits.trading_start_hour <= current_hour < self.limits.trading_end_hour
        else:
            # 자정을 넘는 경우 (23시-9시)
            return current_hour >= self.limits.trading_start_hour or current_hour < self.limits.trading_end_hour
    
    def handle_rate_limit(self, response: Optional[requests.Response] = None, 
                         exception: Optional[Exception] = None) -> Tuple[bool, float]:
        """
        API 레이트 리밋 핸들링
        
        Args:
            response: HTTP 응답 객체
            exception: 발생한 예외
        
        Returns:
            (재시도 여부, 대기 시간)
        """
        try:
            # 429 상태 코드 확인
            if response and response.status_code == 429:
                retry_after = self._get_retry_after(response)
                logger.warning(f"Rate limit hit, waiting {retry_after:.1f}s")
                return True, retry_after
            
            # 네트워크 관련 예외 확인
            if exception:
                if isinstance(exception, (requests.exceptions.ConnectionError, 
                                        requests.exceptions.Timeout,
                                        requests.exceptions.RequestException)):
                    backoff_time = self._calculate_backoff()
                    logger.warning(f"Network error, backing off {backoff_time:.1f}s: {exception}")
                    return True, backoff_time
            
            return False, 0.0
        
        except Exception as e:
            logger.error(f"Error in rate limit handling: {e}")
            return True, 5.0  # 기본 5초 대기
    
    def _get_retry_after(self, response: requests.Response) -> float:
        """Retry-After 헤더에서 대기 시간 추출"""
        retry_after = response.headers.get('Retry-After')
        if retry_after:
            try:
                return float(retry_after)
            except ValueError:
                pass
        
        # 기본 백오프 계산
        return self._calculate_backoff()
    
    def _calculate_backoff(self) -> float:
        """지수 백오프 계산"""
        base_time = self.limits.rate_limit_backoff_base
        jitter = random.uniform(0.5, 1.5)  # 지터 추가
        backoff = base_time * (2 ** min(len(self.last_request_times), 5)) * jitter
        return min(backoff, 30.0)  # 최대 30초
    
    def is_ranging_market(self, candles: List[Dict[str, Any]], 
                         rsi_window: int = 14, bb_window: int = 20) -> Tuple[bool, Dict[str, Any]]:
        """
        횡보 시장 판단
        
        Args:
            candles: 캔들 데이터
            rsi_window: RSI 계산 기간
            bb_window: 볼린저 밴드 계산 기간
        
        Returns:
            (횡보 여부, 메타 정보)
        """
        try:
            if len(candles) < max(rsi_window, bb_window) + 5:
                return False, {"reason": "insufficient_data"}
            
            prices = [float(candle['trade_price']) for candle in candles]
            
            # 1. RSI 기반 횡보 판단 (40-60 범위)
            rsi_values = calculate_rsi(prices, rsi_window)
            recent_rsi = [r for r in rsi_values[-10:] if r is not None and not pd.isna(r)]
            
            if len(recent_rsi) < 5:
                return False, {"reason": "insufficient_rsi_data"}
            
            avg_rsi = sum(recent_rsi) / len(recent_rsi)
            rsi_ranging = 40 <= avg_rsi <= 60
            
            # 2. 볼린저 밴드 폭 기반 판단
            bb_upper, bb_middle, bb_lower = calculate_bollinger_bands(prices, bb_window, 2.0)
            
            if len(bb_upper) < 10 or bb_middle[-1] is None:
                return False, {"reason": "insufficient_bb_data"}
            
            # 볼린저 밴드 폭 (상단-하단) / 중간선
            bb_width_pct = (bb_upper[-1] - bb_lower[-1]) / bb_middle[-1] * 100
            bb_width_avg = sum([(bb_upper[i] - bb_lower[i]) / bb_middle[i] * 100 
                               for i in range(-10, 0) if bb_middle[i] is not None]) / 10
            
            # 볼린저 밴드 폭이 평균보다 작으면 횡보
            bb_ranging = bb_width_pct < bb_width_avg * 1.2
            
            # 3. 가격 변동성 확인
            price_volatility = (max(prices[-20:]) - min(prices[-20:])) / prices[-1] * 100
            volatility_ranging = price_volatility < 3.0  # 3% 미만 변동
            
            # 종합 판단 (2개 이상 조건 만족)
            conditions = [rsi_ranging, bb_ranging, volatility_ranging]
            is_ranging = sum(conditions) >= 2
            
            meta = {
                "avg_rsi": avg_rsi,
                "rsi_ranging": rsi_ranging,
                "bb_width_pct": bb_width_pct,
                "bb_width_avg": bb_width_avg,
                "bb_ranging": bb_ranging,
                "price_volatility": price_volatility,
                "volatility_ranging": volatility_ranging,
                "conditions_met": sum(conditions)
            }
            
            return is_ranging, meta
        
        except Exception as e:
            logger.error(f"Error in ranging market detection: {e}")
            return False, {"reason": "error", "error": str(e)}
    
    def update_trade_result(self, profit_krw: float, is_loss: bool):
        """거래 결과 업데이트"""
        try:
            self._reset_daily_stats_if_needed()
            
            self.daily_stats['trade_count'] += 1
            self.daily_stats['total_profit'] += profit_krw
            
            if is_loss:
                self.daily_stats['loss_count'] += 1
                self.daily_stats['total_loss'] += abs(profit_krw)
                self.consecutive_losses += 1
                
                logger.warning(f"Loss recorded: {profit_krw:.0f} KRW, consecutive losses: {self.consecutive_losses}")
                
                # 응급 정지 확인
                if self.consecutive_losses >= self.limits.consecutive_loss_limit:
                    self._trigger_emergency_stop("consecutive_losses")
            else:
                self.consecutive_losses = 0  # 수익시 연속 손실 리셋
                logger.info(f"Profit recorded: {profit_krw:.0f} KRW")
            
            # 일일 손실 한도 확인
            if self.daily_stats['total_loss'] >= self.limits.daily_max_loss_krw:
                self._trigger_emergency_stop("daily_loss_limit")
        
        except Exception as e:
            logger.error(f"Error updating trade result: {e}")
    
    def _trigger_emergency_stop(self, reason: str):
        """응급 정지 발동"""
        self.emergency_stop = True
        self.last_emergency_check = time.time()
        
        logger.critical(f"🚨 EMERGENCY STOP TRIGGERED: {reason}")
        logger.critical(f"Daily stats: {self.daily_stats}")
        logger.critical(f"Consecutive losses: {self.consecutive_losses}")
        
        # 여기에 알림 훅 호출 추가 가능 (4단계)
        # self._send_emergency_notification(reason)
    
    def reset_emergency_stop(self, manual_override: bool = False) -> bool:
        """응급 정지 해제"""
        if not self.emergency_stop:
            return True
        
        if manual_override:
            self.emergency_stop = False
            self.consecutive_losses = 0
            logger.warning("Emergency stop manually overridden")
            return True
        
        # 자동 해제 조건 (일정 시간 경과 후)
        if time.time() - self.last_emergency_check > 3600:  # 1시간 후
            self.emergency_stop = False
            logger.info("Emergency stop automatically reset after cooldown")
            return True
        
        return False
    
    def get_risk_status(self) -> Dict[str, Any]:
        """현재 리스크 상태 반환"""
        self._reset_daily_stats_if_needed()
        
        return {
            "emergency_stop": self.emergency_stop,
            "consecutive_losses": self.consecutive_losses,
            "daily_stats": self.daily_stats.copy(),
            "trading_hours": self._is_trading_hours(),
            "limits": {
                "max_order_krw": self.limits.max_order_krw,
                "daily_max_loss_krw": self.limits.daily_max_loss_krw,
                "consecutive_loss_limit": self.limits.consecutive_loss_limit
            }
        }
    
    def wait_for_rate_limit(self):
        """레이트 리밋 준수를 위한 대기"""
        current_time = time.time()
        
        # 최근 요청 시간 정리 (1초 이전 제거)
        self.last_request_times = [t for t in self.last_request_times if current_time - t < 1.0]
        
        # 요청 수 제한 확인
        if len(self.last_request_times) >= self.limits.max_requests_per_second:
            wait_time = 1.0 - (current_time - self.last_request_times[0])
            if wait_time > 0:
                time.sleep(wait_time)
        
        # 현재 요청 시간 기록
        self.last_request_times.append(current_time)

# 기본 인스턴스
default_risk_manager = RiskManager()