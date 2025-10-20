"""
기술적 지표 계산 모듈
RSI, 볼린저 밴드 등의 기술적 지표를 계산합니다.
"""

import pandas as pd
import numpy as np
from typing import List, Dict, Tuple, Optional

def calculate_rsi(prices: List[float], window: int = 14) -> List[float]:
    """
    RSI(Relative Strength Index) 계산
    
    Args:
        prices: 가격 리스트 (최신이 마지막)
        window: RSI 계산 기간
    
    Returns:
        RSI 값 리스트 (초기 window-1개는 NaN)
    """
    if len(prices) < window + 1:
        return [np.nan] * len(prices)
    
    df = pd.DataFrame({'price': prices})
    delta = df['price'].diff()
    
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    
    avg_gain = gain.rolling(window=window).mean()
    avg_loss = loss.rolling(window=window).mean()
    
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    
    return rsi.fillna(np.nan).tolist()

def calculate_bollinger_bands(prices: List[float], window: int = 20, std_dev: float = 2.0) -> Tuple[List[float], List[float], List[float]]:
    """
    볼린저 밴드 계산
    
    Args:
        prices: 가격 리스트 (최신이 마지막)
        window: 이동평균 기간
        std_dev: 표준편차 배수
    
    Returns:
        Tuple[상단밴드, 중간선(SMA), 하단밴드]
    """
    if len(prices) < window:
        nan_list = [np.nan] * len(prices)
        return nan_list, nan_list, nan_list
    
    df = pd.DataFrame({'price': prices})
    
    # 단순이동평균
    sma = df['price'].rolling(window=window).mean()
    
    # 표준편차
    std = df['price'].rolling(window=window).std()
    
    # 볼린저 밴드
    upper_band = sma + (std * std_dev)
    lower_band = sma - (std * std_dev)
    
    return (
        upper_band.fillna(np.nan).tolist(),
        sma.fillna(np.nan).tolist(),
        lower_band.fillna(np.nan).tolist()
    )

def calculate_sma(prices: List[float], window: int) -> List[float]:
    """
    단순이동평균(Simple Moving Average) 계산
    
    Args:
        prices: 가격 리스트
        window: 이동평균 기간
    
    Returns:
        SMA 값 리스트
    """
    if len(prices) < window:
        return [np.nan] * len(prices)
    
    df = pd.DataFrame({'price': prices})
    sma = df['price'].rolling(window=window).mean()
    
    return sma.fillna(np.nan).tolist()

def get_price_change_percent(current_price: float, entry_price: float) -> float:
    """
    가격 변화율 계산
    
    Args:
        current_price: 현재 가격
        entry_price: 진입 가격
    
    Returns:
        변화율 (0.01 = 1%)
    """
    if entry_price == 0:
        return 0.0
    
    return (current_price - entry_price) / entry_price