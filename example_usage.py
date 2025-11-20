"""
Example: __init__.py를 사용한 깔끔한 import
"""

# ❌ __init__.py 없이 (복잡함)
from src.core.types import MarketRegime, Signal, Position
from src.core.utils import calculate_slippage
from src.strategy.regime_detector import RegimeDetector
from src.strategy.mean_reversion import MeanReversionStrategy

# ✅ __init__.py로 export하면 (간결함)
from src.core import MarketRegime, Signal, Position, calculate_slippage
from src.strategy import RegimeDetector, MeanReversionStrategy

# 또는 전체 모듈 import
import src.core as core
import src.strategy as strategy

# 사용 예시
regime = core.MarketRegime.RANGING
detector = strategy.RegimeDetector()
