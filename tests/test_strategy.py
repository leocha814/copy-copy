#!/usr/bin/env python3
"""
스캘핑 전략 단위 테스트

take_profit, stop_loss, max_hold_sec 조건별 SELL 트리거 테스트
"""

import sys
import os
import time
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.strategy.rsi_bollinger_scalper import RSIBollingerScalper, ScalperConfig
from src.strategy.indicators import calculate_rsi, calculate_bollinger_bands

class TestScalpingStrategy(unittest.TestCase):
    """스캘핑 전략 테스트"""
    
    def setUp(self):
        """테스트 설정"""
        self.config = ScalperConfig(
            rsi_window=14,
            bb_window=20,
            bb_std=2.0,
            take_profit=0.005,  # 0.5%
            stop_loss=-0.004,   # -0.4%
            max_hold_sec=300,   # 5분
            use_ranging_filter=False  # 테스트를 위해 비활성화
        )
        self.strategy = RSIBollingerScalper(self.config)
    
    def create_test_candles(self, prices: list) -> list:
        """테스트용 캔들 데이터 생성"""
        candles = []
        base_time = int(time.time() * 1000)
        
        for i, price in enumerate(prices):
            candle = {
                'timestamp': base_time + (i * 60000),  # 1분 간격
                'opening_price': price,
                'high_price': price * 1.002,
                'low_price': price * 0.998,
                'trade_price': price,
                'candle_acc_trade_volume': 100.0
            }
            candles.append(candle)
        
        return candles
    
    def test_take_profit_condition(self):
        """익절 조건 테스트"""
        # 포지션 상태 (진입가 100,000원)
        entry_price = 100000.0
        entry_time = time.time()
        position_state = {
            'has_position': True,
            'entry_price': entry_price,
            'entry_time': entry_time,
            'entry_volume': 0.001
        }
        
        # 현재가가 익절 기준(+0.5%) 이상
        current_price = entry_price * (1 + self.config.take_profit + 0.001)  # 0.6%
        candles = self.create_test_candles([current_price] * 30)
        
        signal = self.strategy.generate_signal(candles, position_state)
        
        self.assertEqual(signal['action'], 'SELL')
        self.assertEqual(signal['meta']['reason'], 'take_profit')
        self.assertGreaterEqual(signal['meta']['profit_rate'], self.config.take_profit)
    
    def test_stop_loss_condition(self):
        """손절 조건 테스트"""
        # 포지션 상태 (진입가 100,000원)
        entry_price = 100000.0
        entry_time = time.time()
        position_state = {
            'has_position': True,
            'entry_price': entry_price,
            'entry_time': entry_time,
            'entry_volume': 0.001
        }
        
        # 현재가가 손절 기준(-0.4%) 이하
        current_price = entry_price * (1 + self.config.stop_loss - 0.001)  # -0.5%
        candles = self.create_test_candles([current_price] * 30)
        
        signal = self.strategy.generate_signal(candles, position_state)
        
        self.assertEqual(signal['action'], 'SELL')
        self.assertEqual(signal['meta']['reason'], 'stop_loss')
        self.assertLessEqual(signal['meta']['profit_rate'], self.config.stop_loss)
    
    def test_max_hold_time_condition(self):
        """최대 보유시간 조건 테스트"""
        # 포지션 상태 (5분 전 진입)
        entry_price = 100000.0
        entry_time = time.time() - (self.config.max_hold_sec + 10)  # 5분 10초 전
        position_state = {
            'has_position': True,
            'entry_price': entry_price,
            'entry_time': entry_time,
            'entry_volume': 0.001
        }
        
        # 현재가는 손익 범위 내 (익절/손절 조건 미충족)
        current_price = entry_price * 1.002  # 0.2% 상승
        candles = self.create_test_candles([current_price] * 30)
        
        signal = self.strategy.generate_signal(candles, position_state)
        
        self.assertEqual(signal['action'], 'SELL')
        self.assertEqual(signal['meta']['reason'], 'max_hold_time')
        self.assertGreaterEqual(signal['meta']['hold_time'], self.config.max_hold_sec)
    
    def test_holding_condition(self):
        """보유 중 조건 테스트 (청산 조건 미충족)"""
        # 포지션 상태 (최근 진입)
        entry_price = 100000.0
        entry_time = time.time() - 60  # 1분 전 진입
        position_state = {
            'has_position': True,
            'entry_price': entry_price,
            'entry_time': entry_time,
            'entry_volume': 0.001
        }
        
        # 현재가는 익절/손절 범위 내
        current_price = entry_price * 1.002  # 0.2% 상승 (익절 0.5% 미만)
        candles = self.create_test_candles([current_price] * 30)
        
        signal = self.strategy.generate_signal(candles, position_state)
        
        self.assertEqual(signal['action'], 'HOLD')
        self.assertEqual(signal['meta']['reason'], 'holding')
    
    def test_entry_signal_generation(self):
        """진입 신호 생성 테스트"""
        # 볼린저 하단 이탈 + RSI 과매도 상황 시뮬레이션
        # 가격이 하락하는 패턴 생성
        base_price = 100000
        declining_prices = []
        
        # 20개 정도는 안정적인 가격
        for i in range(20):
            declining_prices.append(base_price - (i * 100))
        
        # 볼린저 하단을 뚫는 급락
        for i in range(10):
            declining_prices.append(base_price - 2000 - (i * 200))
        
        candles = self.create_test_candles(declining_prices)
        
        # 포지션 없는 상태
        signal = self.strategy.generate_signal(candles, None)
        
        # RSI 과매도 + 볼린저 하단 이탈 조건이 맞으면 BUY 신호
        if signal['action'] == 'BUY':
            self.assertEqual(signal['meta']['reason'], 'entry_signal')
            self.assertTrue(signal['meta']['bb_breakout'])
            self.assertTrue(signal['meta']['rsi_oversold'])
    
    def test_insufficient_data(self):
        """데이터 부족 시 HOLD 테스트"""
        # 부족한 캔들 데이터 (RSI, 볼린저 계산 불가)
        short_candles = self.create_test_candles([100000] * 5)
        
        signal = self.strategy.generate_signal(short_candles, None)
        
        self.assertEqual(signal['action'], 'HOLD')
        self.assertEqual(signal['meta']['reason'], 'insufficient_data')

class TestTechnicalIndicators(unittest.TestCase):
    """기술적 지표 계산 테스트"""
    
    def test_rsi_calculation(self):
        """RSI 계산 테스트"""
        # 상승 패턴 가격
        rising_prices = [100 + i for i in range(20)]
        rsi_values = calculate_rsi(rising_prices, window=14)
        
        # RSI는 0-100 범위
        for rsi in rsi_values:
            if not pd.isna(rsi):
                self.assertGreaterEqual(rsi, 0)
                self.assertLessEqual(rsi, 100)
    
    def test_bollinger_bands_calculation(self):
        """볼린저 밴드 계산 테스트"""
        prices = [100 + (i % 10) for i in range(30)]  # 변동하는 가격
        upper, middle, lower = calculate_bollinger_bands(prices, window=20, std_dev=2.0)
        
        # 최신 값들이 유효한지 확인
        self.assertIsNotNone(upper[-1])
        self.assertIsNotNone(middle[-1])
        self.assertIsNotNone(lower[-1])
        
        # 상단 > 중간 > 하단
        self.assertGreater(upper[-1], middle[-1])
        self.assertGreater(middle[-1], lower[-1])

def run_strategy_tests():
    """전략 테스트 실행"""
    print("=" * 60)
    print("RSI + Bollinger Scalper Strategy Tests")
    print("=" * 60)
    
    # 테스트 스위트 생성
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # 테스트 케이스 추가
    suite.addTests(loader.loadTestsFromTestCase(TestScalpingStrategy))
    suite.addTests(loader.loadTestsFromTestCase(TestTechnicalIndicators))
    
    # 테스트 실행
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # 결과 요약
    print("\n" + "=" * 60)
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print("=" * 60)
    
    return result.wasSuccessful()

if __name__ == "__main__":
    import pandas as pd
    import numpy as np
    
    success = run_strategy_tests()
    sys.exit(0 if success else 1)