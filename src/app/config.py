"""
Configuration loader from environment variables.
Loads settings from .env file for secure credential management.
"""
import os
from typing import List
from pathlib import Path
from dataclasses import dataclass
import logging


logger = logging.getLogger(__name__)


@dataclass
class ExchangeConfig:
    """Exchange API configuration."""
    api_key: str
    api_secret: str
    testnet: bool = False


@dataclass
class StrategyConfig:
    """Strategy parameters."""
    # RSI parameters
    rsi_period: int = 14
    rsi_oversold: float = 30.0
    rsi_overbought: float = 70.0
    rsi_exit_neutral: float = 50.0
    rsi_entry_low: float = 35.0
    rsi_entry_high: float = 65.0

    # Bollinger Bands parameters
    bb_period: int = 20
    bb_std_dev: float = 2.0

    # Regime detection parameters
    adx_threshold_low: float = 20.0
    adx_threshold_high: float = 25.0
    adx_period: int = 14
    atr_period: int = 14

    # Scalping parameters
    entry_cooldown_seconds: int = 15
    bb_width_min: float = 0.5
    bb_width_max: float = 8.0
    time_stop_minutes: int = 5
    bb_pos_entry_max: float = 25.0
    volume_lookback: int = 20
    volume_confirm_multiplier: float = 1.5
    ema_slope_threshold: float = 0.15
    max_entries_per_hour: int = 6
    trend_rsi_min: float = 60.0
    trend_bb_pos_min: float = 60.0
    trend_price_above_ema_pct: float = 0.3
    trend_volume_multiplier: float = 2.0
    use_atr_position_sizing: bool = False
    atr_position_risk_pct: float = 1.0  # 계좌 대비 퍼센트 리스크
    use_score_based_sizing: bool = False
    use_atr_sl_tp: bool = False
    atr_stop_multiplier: float = 0.5
    atr_target_multiplier: float = 1.0
    min_expected_rr: float = 0.5
    fee_rate_pct: float = 0.10
    slippage_buffer_pct: float = 0.25

    # Trading symbols
    symbols: List[str] = None
    timeframe: str = '1m'


@dataclass
class RiskConfig:
    """Risk management parameters."""
    per_trade_risk_pct: float = 0.5
    max_daily_loss_pct: float = 10.0
    max_consecutive_losses: int = 3
    max_drawdown_pct: float = 5.0
    max_position_size_pct: float = 30.0

    # Fixed stops for scalping
    use_fixed_stops: bool = True
    fixed_stop_loss_pct: float = 0.18
    fixed_take_profit_pct: float = 0.30

    # Downtrend bounce (counter-trend) stops
    downtrend_stop_loss_pct: float = 0.15
    downtrend_take_profit_pct: float = 0.20

    # ATR-based stops (fallback)
    stop_atr_multiplier: float = 2.0
    target_atr_multiplier: float = 3.0


@dataclass
class ExecutionConfig:
    """Execution and order routing parameters."""
    default_order_type: str = 'market'  # 'market' or 'limit'
    limit_order_timeout_seconds: float = 30.0
    max_slippage_pct: float = 0.5
    amount_precision: int = 8
    price_precision: int = 2
    prefer_maker: bool = False
    maker_retry_seconds: float = 3.0
    maker_max_retries: int = 1


@dataclass
class TelegramConfig:
    """Telegram alert configuration."""
    bot_token: str = None
    chat_id: str = None


@dataclass
class TradingConfig:
    """Main trading configuration."""
    exchange: ExchangeConfig
    strategy: StrategyConfig
    risk: RiskConfig
    execution: ExecutionConfig
    telegram: TelegramConfig

    # System settings
    log_dir: str = 'logs'
    check_interval_seconds: float = 60.0
    dry_run: bool = False  # Simulation mode
    initial_balance: float = 1000000.0  # Virtual starting balance for dry-run


def load_config() -> TradingConfig:
    """
    Load configuration from environment variables.
    Expects .env file in project root with required keys.

    Returns:
        TradingConfig object

    Raises:
        ValueError: If required environment variables are missing
    """
    # Load .env file if exists
    env_file = Path('.env')
    if env_file.exists():
        from dotenv import load_dotenv
        load_dotenv()
        logger.info("Loaded configuration from .env file")
    else:
        logger.warning("No .env file found, using environment variables")

    # Exchange config
    api_key = os.getenv('UPBIT_API_KEY')
    api_secret = os.getenv('UPBIT_API_SECRET')

    if not api_key or not api_secret:
        raise ValueError(
            "Missing UPBIT_API_KEY or UPBIT_API_SECRET in environment. "
            "Create .env file with these keys."
        )

    exchange_config = ExchangeConfig(
        api_key=api_key,
        api_secret=api_secret,
        testnet=os.getenv('TESTNET', 'false').lower() == 'true'
    )

    # Strategy config
    symbols_str = os.getenv('TRADING_SYMBOLS', 'BTC/KRW')
    symbols = [s.strip() for s in symbols_str.split(',')]

    strategy_config = StrategyConfig(
        rsi_period=int(os.getenv('RSI_PERIOD', '14')),
        rsi_oversold=float(os.getenv('RSI_OVERSOLD', '35')),
        rsi_overbought=float(os.getenv('RSI_OVERBOUGHT', '65')),
        rsi_exit_neutral=float(os.getenv('RSI_EXIT_NEUTRAL', '50')),
        rsi_entry_low=float(os.getenv('RSI_ENTRY_LOW', '35')),
        rsi_entry_high=float(os.getenv('RSI_ENTRY_HIGH', '65')),
        bb_period=int(os.getenv('BB_PERIOD', '20')),
        bb_std_dev=float(os.getenv('BB_STD_DEV', '2.0')),
        adx_threshold_low=float(os.getenv('ADX_THRESHOLD_LOW', '20')),
        adx_threshold_high=float(os.getenv('ADX_THRESHOLD_HIGH', '25')),
        adx_period=int(os.getenv('ADX_PERIOD', '14')),
        atr_period=int(os.getenv('ATR_PERIOD', '14')),
        entry_cooldown_seconds=int(os.getenv('ENTRY_COOLDOWN_SECONDS', '15')),
        bb_width_min=float(os.getenv('BB_WIDTH_MIN', '0.5')),
        bb_width_max=float(os.getenv('BB_WIDTH_MAX', '8.0')),
        time_stop_minutes=int(os.getenv('TIME_STOP_MINUTES', '5')),
        bb_pos_entry_max=float(os.getenv('BB_POS_ENTRY_MAX', '25.0')),
        volume_lookback=int(os.getenv('VOLUME_LOOKBACK', '20')),
        volume_confirm_multiplier=float(os.getenv('VOLUME_CONFIRM_MULTIPLIER', '1.5')),
        ema_slope_threshold=float(os.getenv('EMA_SLOPE_THRESHOLD', '0.15')),
        max_entries_per_hour=int(os.getenv('MAX_ENTRIES_PER_HOUR', '6')),
        trend_rsi_min=float(os.getenv('TREND_RSI_MIN', '60.0')),
        trend_bb_pos_min=float(os.getenv('TREND_BB_POS_MIN', '60.0')),
        trend_price_above_ema_pct=float(os.getenv('TREND_PRICE_ABOVE_EMA_PCT', '0.3')),
        trend_volume_multiplier=float(os.getenv('TREND_VOLUME_MULTIPLIER', '2.0')),
        use_atr_position_sizing=os.getenv('USE_ATR_POSITION_SIZING', 'false').lower() == 'true',
        atr_position_risk_pct=float(os.getenv('ATR_POSITION_RISK_PCT', '1.0')),
        use_score_based_sizing=os.getenv('USE_SCORE_BASED_SIZING', 'false').lower() == 'true',
        use_atr_sl_tp=os.getenv('USE_ATR_SLTP', 'false').lower() == 'true',
        atr_stop_multiplier=float(os.getenv('ATR_STOP_MULTIPLIER', '0.5')),
        atr_target_multiplier=float(os.getenv('ATR_TARGET_MULTIPLIER', '1.0')),
        min_expected_rr=float(os.getenv('MIN_EXPECTED_RR', '0.5')),
        fee_rate_pct=float(os.getenv('FEE_RATE_PCT', '0.10')),
        slippage_buffer_pct=float(os.getenv('SLIPPAGE_BUFFER_PCT', '0.25')),
        symbols=symbols,
        timeframe=os.getenv('TIMEFRAME', '1m')
    )

    # Risk config
    risk_config = RiskConfig(
        per_trade_risk_pct=float(os.getenv('PER_TRADE_RISK', '2.0')),
        max_daily_loss_pct=float(os.getenv('MAX_DAILY_LOSS', '10.0')),
        max_consecutive_losses=int(os.getenv('MAX_CONSECUTIVE_LOSSES', '3')),
        max_drawdown_pct=float(os.getenv('MAX_DRAWDOWN', '5.0')),
        max_position_size_pct=float(os.getenv('MAX_POSITION_SIZE', '30.0')),
        use_fixed_stops=os.getenv('USE_FIXED_STOPS', 'true').lower() == 'true',
        fixed_stop_loss_pct=float(os.getenv('FIXED_STOP_LOSS_PCT', '0.18')),
        fixed_take_profit_pct=float(os.getenv('FIXED_TAKE_PROFIT_PCT', '0.30')),
        downtrend_stop_loss_pct=float(os.getenv('DOWNTREND_STOP_LOSS_PCT', '0.15')),
        downtrend_take_profit_pct=float(os.getenv('DOWNTREND_TAKE_PROFIT_PCT', '0.20')),
        stop_atr_multiplier=float(os.getenv('FALLBACK_STOP_ATR_MULTIPLIER', '2.0')),
        target_atr_multiplier=float(os.getenv('FALLBACK_TARGET_ATR_MULTIPLIER', '3.0'))
    )

    # Execution config
    execution_config = ExecutionConfig(
        default_order_type=os.getenv('DEFAULT_ORDER_TYPE', 'market'),
        limit_order_timeout_seconds=float(os.getenv('LIMIT_ORDER_TIMEOUT_SECONDS', '30.0')),
        max_slippage_pct=float(os.getenv('MAX_SLIPPAGE_PCT', '0.5')),
        amount_precision=int(os.getenv('AMOUNT_PRECISION', '8')),
        price_precision=int(os.getenv('PRICE_PRECISION', '2')),
        prefer_maker=os.getenv('PREFER_MAKER', 'false').lower() == 'true',
        maker_retry_seconds=float(os.getenv('MAKER_RETRY_SECONDS', '3.0')),
        maker_max_retries=int(os.getenv('MAKER_MAX_RETRIES', '1')),
    )

    # Telegram config
    telegram_config = TelegramConfig(
        bot_token=os.getenv('TELEGRAM_BOT_TOKEN'),
        chat_id=os.getenv('TELEGRAM_CHAT_ID')
    )

    # System settings
    log_dir = os.getenv('LOG_DIR', 'logs')
    check_interval = float(os.getenv('CHECK_INTERVAL_SECONDS', '60'))
    dry_run = os.getenv('DRY_RUN', 'false').lower() == 'true'
    initial_balance = float(os.getenv('INITIAL_BALANCE', '1000000'))

    config = TradingConfig(
        exchange=exchange_config,
        strategy=strategy_config,
        risk=risk_config,
        execution=execution_config,
        telegram=telegram_config,
        log_dir=log_dir,
        check_interval_seconds=check_interval,
        dry_run=dry_run,
        initial_balance=initial_balance
    )

    # Validate configuration
    validate_config(config)

    # Simplified config log
    mode = "DRY RUN" if dry_run else "LIVE"
    logger.info(f"⚙️ Config loaded | {mode} | {', '.join(symbols)} | {strategy_config.timeframe}")

    return config



def validate_strategy_config(config: StrategyConfig) -> None:
    """
    Validate strategy configuration parameters.
    
    Args:
        config: StrategyConfig to validate
        
    Raises:
        ValueError: If any parameter is out of valid range
    """
    errors = []
    
    # RSI validation
    if not (1 <= config.rsi_period <= 100):
        errors.append(f"RSI_PERIOD must be between 1-100, got {config.rsi_period}")
    if not (0 <= config.rsi_oversold <= 100):
        errors.append(f"RSI_OVERSOLD must be between 0-100, got {config.rsi_oversold}")
    if not (0 <= config.rsi_overbought <= 100):
        errors.append(f"RSI_OVERBOUGHT must be between 0-100, got {config.rsi_overbought}")
    if config.rsi_oversold >= config.rsi_overbought:
        errors.append(f"RSI_OVERSOLD ({config.rsi_oversold}) must be < RSI_OVERBOUGHT ({config.rsi_overbought})")
    if config.rsi_entry_low > config.rsi_entry_high:
        errors.append(f"RSI_ENTRY_LOW ({config.rsi_entry_low}) must be <= RSI_ENTRY_HIGH ({config.rsi_entry_high})")
    
    # Bollinger Bands validation
    if not (2 <= config.bb_period <= 200):
        errors.append(f"BB_PERIOD must be between 2-200, got {config.bb_period}")
    if not (0.1 <= config.bb_std_dev <= 5.0):
        errors.append(f"BB_STD_DEV must be between 0.1-5.0, got {config.bb_std_dev}")
    if not (-100.0 <= config.bb_pos_entry_max <= 100.0):
        errors.append(f"BB_POS_ENTRY_MAX must be between -100~100, got {config.bb_pos_entry_max}")
    if config.volume_lookback < 1:
        errors.append(f"VOLUME_LOOKBACK must be >=1, got {config.volume_lookback}")
    if config.volume_confirm_multiplier < 0:
        errors.append(f"VOLUME_CONFIRM_MULTIPLIER must be >=0, got {config.volume_confirm_multiplier}")
    if config.trend_bb_pos_min < -100 or config.trend_bb_pos_min > 100:
        errors.append(f"TREND_BB_POS_MIN must be between -100~100, got {config.trend_bb_pos_min}")
    if config.trend_rsi_min < 0 or config.trend_rsi_min > 100:
        errors.append(f"TREND_RSI_MIN must be between 0~100, got {config.trend_rsi_min}")
    if config.trend_volume_multiplier < 0:
        errors.append(f"TREND_VOLUME_MULTIPLIER must be >=0, got {config.trend_volume_multiplier}")
    if config.trend_price_above_ema_pct < 0:
        errors.append(f"TREND_PRICE_ABOVE_EMA_PCT must be >=0, got {config.trend_price_above_ema_pct}")
    if config.atr_position_risk_pct < 0 or config.atr_position_risk_pct > 100:
        errors.append(f"ATR_POSITION_RISK_PCT must be between 0-100, got {config.atr_position_risk_pct}")
    if config.atr_stop_multiplier <= 0 or config.atr_target_multiplier <= 0:
        errors.append(f"ATR multipliers must be >0, got stop={config.atr_stop_multiplier}, target={config.atr_target_multiplier}")
    if config.min_expected_rr < 0:
        errors.append(f"MIN_EXPECTED_RR must be >=0, got {config.min_expected_rr}")
    
    # ADX/ATR validation
    if not (1 <= config.adx_period <= 100):
        errors.append(f"ADX_PERIOD must be between 1-100, got {config.adx_period}")
    if not (1 <= config.atr_period <= 100):
        errors.append(f"ATR_PERIOD must be between 1-100, got {config.atr_period}")
    if not (0 <= config.adx_threshold_low <= 100):
        errors.append(f"ADX_THRESHOLD_LOW must be between 0-100, got {config.adx_threshold_low}")
    if not (0 <= config.adx_threshold_high <= 100):
        errors.append(f"ADX_THRESHOLD_HIGH must be between 0-100, got {config.adx_threshold_high}")
    if config.adx_threshold_low >= config.adx_threshold_high:
        errors.append(f"ADX_THRESHOLD_LOW ({config.adx_threshold_low}) must be < ADX_THRESHOLD_HIGH ({config.adx_threshold_high})")
    
    # Symbol format validation
    if not config.symbols:
        errors.append("TRADING_SYMBOLS cannot be empty")
    else:
        valid_formats = ['/', '-']
        for symbol in config.symbols:
            if not any(fmt in symbol for fmt in valid_formats):
                errors.append(f"Invalid symbol format: '{symbol}'. Expected format: BTC/KRW or BTC-KRW")
            # Check for common Upbit format
            parts = symbol.replace('-', '/').split('/')
            if len(parts) != 2:
                errors.append(f"Invalid symbol format: '{symbol}'. Must have exactly 2 parts (e.g., BTC/KRW)")
    
    # Timeframe validation
    valid_timeframes = ['1m', '3m', '5m', '15m', '30m', '1h', '2h', '4h', '6h', '12h', '1d', '1w']
    if config.timeframe not in valid_timeframes:
        errors.append(f"Invalid TIMEFRAME: '{config.timeframe}'. Valid: {', '.join(valid_timeframes)}")
    
    if errors:
        raise ValueError("Strategy configuration validation failed:\n" + "\n".join(f"  - {e}" for e in errors))


def validate_risk_config(config: RiskConfig) -> None:
    """
    Validate risk configuration parameters.
    
    Args:
        config: RiskConfig to validate
        
    Raises:
        ValueError: If any parameter is out of valid range
    """
    errors = []
    
    # Percentage validations
    if not (0.1 <= config.per_trade_risk_pct <= 100.0):
        errors.append(f"PER_TRADE_RISK must be between 0.1-100.0%, got {config.per_trade_risk_pct}%")
    # 상한을 넓혀 전체 잔액 매매 플로우가 리스크 검증에서 막히지 않도록 허용
    if config.max_daily_loss_pct < 0.0:
        errors.append(f"MAX_DAILY_LOSS must be >= 0.0%, got {config.max_daily_loss_pct}%")
    if config.max_drawdown_pct < 0.0:
        errors.append(f"MAX_DRAWDOWN must be >= 0.0%, got {config.max_drawdown_pct}%")
    if not (10.0 <= config.max_position_size_pct <= 100.0):
        errors.append(f"MAX_POSITION_SIZE must be between 10.0-100.0%, got {config.max_position_size_pct}%")
    
    # Consecutive losses validation
    if config.max_consecutive_losses < 0:
        errors.append(f"MAX_CONSECUTIVE_LOSSES must be >= 0, got {config.max_consecutive_losses}")
    
    # ATR multiplier validation
    if not (0.5 <= config.stop_atr_multiplier <= 10.0):
        errors.append(f"STOP_ATR_MULTIPLIER must be between 0.5-10.0, got {config.stop_atr_multiplier}")
    if not (0.5 <= config.target_atr_multiplier <= 20.0):
        errors.append(f"TARGET_ATR_MULTIPLIER must be between 0.5-20.0, got {config.target_atr_multiplier}")
    if config.target_atr_multiplier <= config.stop_atr_multiplier:
        errors.append(f"TARGET_ATR_MULTIPLIER ({config.target_atr_multiplier}) must be > STOP_ATR_MULTIPLIER ({config.stop_atr_multiplier})")
    
    # Logical validations (skip for full-in mode: PER_TRADE_RISK=100%)
    if config.per_trade_risk_pct <= 100.0 and config.max_daily_loss_pct > 0 and config.per_trade_risk_pct > config.max_daily_loss_pct:
        errors.append(f"PER_TRADE_RISK ({config.per_trade_risk_pct}%) should be <= MAX_DAILY_LOSS ({config.max_daily_loss_pct}%)")
    
    if errors:
        raise ValueError("Risk configuration validation failed:\n" + "\n".join(f"  - {e}" for e in errors))


def validate_config(config: TradingConfig) -> None:
    """
    Validate entire trading configuration.
    
    Args:
        config: TradingConfig to validate
        
    Raises:
        ValueError: If any parameter is invalid
    """
    logger.info("Validating configuration...")
    
    # Validate strategy parameters
    validate_strategy_config(config.strategy)
    logger.info("✓ Strategy configuration validated")
    
    # Validate risk parameters
    validate_risk_config(config.risk)
    logger.info("✓ Risk configuration validated")
    
    # System settings validation
    if config.check_interval_seconds < 1.0:
        raise ValueError(f"CHECK_INTERVAL_SECONDS must be >= 1.0, got {config.check_interval_seconds}")
    
    if config.dry_run and config.initial_balance <= 0:
        raise ValueError(f"INITIAL_BALANCE must be > 0 for dry run mode, got {config.initial_balance}")
    
    logger.info("✓ All configuration validation passed")


def create_example_env_file():
    """Create example .env file with all required keys."""
    example_content = """# Upbit API Credentials
UPBIT_API_KEY=your_api_key_here
UPBIT_API_SECRET=your_api_secret_here
TESTNET=false

# Trading Parameters
TRADING_SYMBOLS=BTC/KRW,ETH/KRW,XRP/KRW
TIMEFRAME=5m

# Strategy Parameters
RSI_PERIOD=14
RSI_OVERSOLD=30
RSI_OVERBOUGHT=70
BB_PERIOD=20
BB_STD_DEV=2.0
ADX_THRESHOLD_LOW=20
ADX_THRESHOLD_HIGH=25
ADX_PERIOD=14
ATR_PERIOD=14

# Risk Management
PER_TRADE_RISK=2.0
MAX_DAILY_LOSS=5.0
MAX_CONSECUTIVE_LOSSES=5
MAX_DRAWDOWN=15.0
MAX_POSITION_SIZE=50.0
STOP_ATR_MULTIPLIER=2.0
TARGET_ATR_MULTIPLIER=3.0

# Telegram Alerts (optional)
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

# System
LOG_DIR=logs
CHECK_INTERVAL_SECONDS=60
"""

    env_example = Path('.env.example')
    with open(env_example, 'w') as f:
        f.write(example_content)

    logger.info(f"Created {env_example}. Copy to .env and fill in your credentials.")
