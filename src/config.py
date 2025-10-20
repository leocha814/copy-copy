import os
from dotenv import load_dotenv
from typing import Optional

load_dotenv()

class Config:
    def __init__(self):
        # API 설정
        self.access_key: Optional[str] = os.getenv('UPBIT_ACCESS_KEY')
        self.secret_key: Optional[str] = os.getenv('UPBIT_SECRET_KEY')
        self.server_url: str = os.getenv('UPBIT_SERVER_URL', 'https://api.upbit.com')
        
        # 거래 모드
        self.trading_mode: str = os.getenv('TRADING_MODE', 'DRYRUN').upper()
        
        # 리스크 관리 설정
        self.max_order_krw: float = float(os.getenv('MAX_ORDER_KRW', '10000'))
        self.daily_max_dd_pct: float = float(os.getenv('DAILY_MAX_DD_PCT', '0.05'))
        self.daily_max_loss_krw: float = float(os.getenv('DAILY_MAX_LOSS_KRW', '50000'))
        self.max_positions: int = int(os.getenv('MAX_POSITIONS', '1'))
        self.consecutive_loss_limit: int = int(os.getenv('CONSECUTIVE_LOSS_LIMIT', '3'))
        self.min_balance_krw: float = float(os.getenv('MIN_BALANCE_KRW', '5000'))
        
        # 거래 시간 제한
        self.trading_start_hour: int = int(os.getenv('TRADING_START_HOUR', '9'))
        self.trading_end_hour: int = int(os.getenv('TRADING_END_HOUR', '23'))
        self.allow_weekend: bool = os.getenv('ALLOW_WEEKEND', 'true').lower() == 'true'
        
        # API 레이트 리밋 설정
        self.max_requests_per_second: int = int(os.getenv('MAX_REQUESTS_PER_SECOND', '8'))
        self.rate_limit_backoff_base: float = float(os.getenv('RATE_LIMIT_BACKOFF_BASE', '1.0'))
        self.rate_limit_max_retries: int = int(os.getenv('RATE_LIMIT_MAX_RETRIES', '5'))
        
        self._validate_config()
    
    def _validate_config(self):
        # API 키 검증 (DRYRUN 모드에서는 선택적)
        if self.trading_mode == 'LIVE':
            if not self.access_key:
                raise ValueError("UPBIT_ACCESS_KEY is required for LIVE mode")
            if not self.secret_key:
                raise ValueError("UPBIT_SECRET_KEY is required for LIVE mode")
        
        # 거래 모드 검증
        if self.trading_mode not in ['DRYRUN', 'LIVE']:
            raise ValueError("TRADING_MODE must be 'DRYRUN' or 'LIVE'")
        
        # 리스크 설정 검증
        if self.max_order_krw <= 0:
            raise ValueError("MAX_ORDER_KRW must be positive")
        if not 0 < self.daily_max_dd_pct <= 1:
            raise ValueError("DAILY_MAX_DD_PCT must be between 0 and 1")
        if self.max_positions < 1:
            raise ValueError("MAX_POSITIONS must be at least 1")
    
    @property
    def has_api_keys(self) -> bool:
        return bool(self.access_key and self.secret_key)
    
    def get_risk_limits_dict(self) -> dict:
        """리스크 제한을 딕셔너리로 반환"""
        return {
            'max_order_krw': self.max_order_krw,
            'daily_max_dd_pct': self.daily_max_dd_pct,
            'daily_max_loss_krw': self.daily_max_loss_krw,
            'max_positions': self.max_positions,
            'consecutive_loss_limit': self.consecutive_loss_limit,
            'min_balance_krw': self.min_balance_krw,
            'trading_start_hour': self.trading_start_hour,
            'trading_end_hour': self.trading_end_hour,
            'allow_weekend': self.allow_weekend,
            'max_requests_per_second': self.max_requests_per_second,
            'rate_limit_backoff_base': self.rate_limit_backoff_base,
            'rate_limit_max_retries': self.rate_limit_max_retries
        }

config = Config()