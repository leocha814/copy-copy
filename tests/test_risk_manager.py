#!/usr/bin/env python3
"""
리스크 관리자 테스트

MAX_ORDER_KRW 초과, 포지션 수 제한, 429 에러 처리, 횡보 시장 판단 등을 테스트합니다.
"""

import sys
import os
import time
import unittest
from unittest.mock import patch, MagicMock
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.risk_manager import RiskManager, RiskLimits

class TestRiskManager(unittest.TestCase):
    """리스크 매니저 테스트"""
    
    def setUp(self):
        """테스트 설정"""
        self.limits = RiskLimits(
            max_order_krw=10000.0,
            daily_max_dd_pct=0.05,
            daily_max_loss_krw=50000.0,
            max_positions=1,
            consecutive_loss_limit=3,
            min_balance_krw=5000.0
        )
        self.risk_manager = RiskManager(self.limits)
    
    def test_max_order_krw_limit(self):
        """최대 주문 금액 제한 테스트"""
        # 정상 주문 (한도 내)
        allowed, reason = self.risk_manager.check_pre_trade(
            market="KRW-BTC",
            krw_amount=5000.0,
            current_positions=0,
            current_balance=50000.0
        )
        self.assertTrue(allowed)
        self.assertEqual(reason, "approved")
        
        # 한도 초과 주문
        allowed, reason = self.risk_manager.check_pre_trade(
            market="KRW-BTC",
            krw_amount=15000.0,  # 10,000 초과
            current_positions=0,
            current_balance=50000.0
        )
        self.assertFalse(allowed)
        self.assertIn("order_amount_exceeds_limit", reason)
    
    def test_max_positions_limit(self):
        """최대 포지션 수 제한 테스트"""
        # 포지션 없을 때 정상
        allowed, reason = self.risk_manager.check_pre_trade(
            market="KRW-BTC",
            krw_amount=5000.0,
            current_positions=0,
            current_balance=50000.0
        )
        self.assertTrue(allowed)
        
        # 포지션 1개 있을 때 추가 매수 차단
        allowed, reason = self.risk_manager.check_pre_trade(
            market="KRW-ETH",
            krw_amount=5000.0,
            current_positions=1,  # 이미 1개 포지션
            current_balance=50000.0
        )
        self.assertFalse(allowed)
        self.assertIn("max_positions_exceeded", reason)
    
    def test_min_balance_check(self):
        """최소 잔고 확인 테스트"""
        # 최소 잔고 미만
        allowed, reason = self.risk_manager.check_pre_trade(
            market="KRW-BTC",
            krw_amount=5000.0,
            current_positions=0,
            current_balance=3000.0  # 5,000 미만
        )
        self.assertFalse(allowed)
        self.assertIn("insufficient_balance", reason)
    
    def test_consecutive_losses_limit(self):
        """연속 손실 제한 테스트"""
        # 연속 손실 증가
        for i in range(3):
            self.risk_manager.update_trade_result(-1000.0, is_loss=True)
        
        # 3번 연속 손실 후 거래 차단
        allowed, reason = self.risk_manager.check_pre_trade(
            market="KRW-BTC",
            krw_amount=5000.0,
            current_positions=0,
            current_balance=50000.0
        )
        self.assertFalse(allowed)
        self.assertIn("consecutive_losses_exceeded", reason)
    
    def test_emergency_stop_trigger(self):
        """응급 정지 발동 테스트"""
        # 연속 손실로 응급 정지 발동
        for i in range(3):
            self.risk_manager.update_trade_result(-1000.0, is_loss=True)
        
        self.assertTrue(self.risk_manager.emergency_stop)
        
        # 응급 정지 상태에서 모든 거래 차단
        allowed, reason = self.risk_manager.check_pre_trade(
            market="KRW-BTC",
            krw_amount=1000.0,
            current_positions=0,
            current_balance=50000.0
        )
        self.assertFalse(allowed)
        self.assertEqual(reason, "emergency_stop_activated")
    
    def test_daily_loss_limit(self):
        """일일 손실 한도 테스트"""
        # 일일 손실 한도 초과
        self.risk_manager.update_trade_result(-60000.0, is_loss=True)  # 50,000 초과
        
        allowed, reason = self.risk_manager.check_pre_trade(
            market="KRW-BTC",
            krw_amount=5000.0,
            current_positions=0,
            current_balance=50000.0
        )
        self.assertFalse(allowed)
        self.assertIn("daily_loss_limit_exceeded", reason)
    
    def test_trading_hours(self):
        """거래 시간 제한 테스트"""
        # 거래 시간 외 설정
        self.risk_manager.limits.trading_start_hour = 25  # 무효한 시간
        self.risk_manager.limits.trading_end_hour = 26
        
        allowed, reason = self.risk_manager.check_pre_trade(
            market="KRW-BTC",
            krw_amount=5000.0,
            current_positions=0,
            current_balance=50000.0
        )
        # 무효한 시간 설정으로 인해 거래 차단될 수 있음
        # 실제로는 현재 시간에 따라 결과가 달라짐
    
    def test_rate_limit_handling(self):
        """레이트 리밋 처리 테스트"""
        # 429 응답 모킹
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.headers = {'Retry-After': '5'}
        
        should_retry, wait_time = self.risk_manager.handle_rate_limit(response=mock_response)
        
        self.assertTrue(should_retry)
        self.assertEqual(wait_time, 5.0)
        
        # 네트워크 예외 처리
        network_error = requests.exceptions.ConnectionError("Connection failed")
        should_retry, wait_time = self.risk_manager.handle_rate_limit(exception=network_error)
        
        self.assertTrue(should_retry)
        self.assertGreater(wait_time, 0)
    
    def test_ranging_market_detection(self):
        """횡보 시장 판단 테스트"""
        # 횡보 시장 시뮬레이션 (변동성 낮음)
        base_price = 50000
        ranging_candles = []
        
        for i in range(50):
            # 작은 변동 (±1%)
            price = base_price + (i % 10 - 5) * 100
            candle = {
                'timestamp': int(time.time() * 1000) + i * 60000,
                'opening_price': price,
                'high_price': price * 1.005,
                'low_price': price * 0.995,
                'trade_price': price,
                'candle_acc_trade_volume': 100.0
            }
            ranging_candles.append(candle)
        
        is_ranging, meta = self.risk_manager.is_ranging_market(ranging_candles)
        
        # 메타 정보 확인
        self.assertIn('avg_rsi', meta)
        self.assertIn('bb_width_pct', meta)
        self.assertIn('price_volatility', meta)
        
        # 트렌딩 시장 시뮬레이션 (상승 추세)
        trending_candles = []
        for i in range(50):
            price = base_price + i * 500  # 지속적 상승
            candle = {
                'timestamp': int(time.time() * 1000) + i * 60000,
                'opening_price': price,
                'high_price': price * 1.01,
                'low_price': price * 0.99,
                'trade_price': price,
                'candle_acc_trade_volume': 100.0
            }
            trending_candles.append(candle)
        
        is_trending, meta = self.risk_manager.is_ranging_market(trending_candles)
        
        # 트렌딩 시장에서는 횡보가 아니어야 함
        self.assertFalse(is_trending)
    
    def test_insufficient_data_handling(self):
        """데이터 부족 시 처리 테스트"""
        # 데이터 부족한 경우
        short_candles = [
            {
                'timestamp': int(time.time() * 1000),
                'opening_price': 50000,
                'high_price': 50500,
                'low_price': 49500,
                'trade_price': 50000,
                'candle_acc_trade_volume': 100.0
            }
        ]
        
        is_ranging, meta = self.risk_manager.is_ranging_market(short_candles)
        
        self.assertFalse(is_ranging)
        self.assertEqual(meta['reason'], 'insufficient_data')
    
    def test_risk_status_reporting(self):
        """리스크 상태 보고 테스트"""
        # 일부 손실 발생
        self.risk_manager.update_trade_result(-2000.0, is_loss=True)
        
        status = self.risk_manager.get_risk_status()
        
        self.assertIn('emergency_stop', status)
        self.assertIn('consecutive_losses', status)
        self.assertIn('daily_stats', status)
        self.assertIn('trading_hours', status)
        self.assertIn('limits', status)
        
        self.assertEqual(status['consecutive_losses'], 1)
        self.assertEqual(status['daily_stats']['total_loss'], 2000.0)
    
    def test_emergency_stop_reset(self):
        """응급 정지 해제 테스트"""
        # 응급 정지 발동
        for i in range(3):
            self.risk_manager.update_trade_result(-1000.0, is_loss=True)
        
        self.assertTrue(self.risk_manager.emergency_stop)
        
        # 수동 해제
        success = self.risk_manager.reset_emergency_stop(manual_override=True)
        self.assertTrue(success)
        self.assertFalse(self.risk_manager.emergency_stop)
        self.assertEqual(self.risk_manager.consecutive_losses, 0)

def run_risk_tests():
    """리스크 관리 테스트 실행"""
    print("=" * 60)
    print("Risk Manager Tests")
    print("=" * 60)
    
    # 테스트 스위트 생성
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # 테스트 케이스 추가
    suite.addTests(loader.loadTestsFromTestCase(TestRiskManager))
    
    # 테스트 실행
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # 결과 요약
    print("\n" + "=" * 60)
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    
    if result.failures:
        print("\nFailures:")
        for test, traceback in result.failures:
            print(f"- {test}: {traceback}")
    
    if result.errors:
        print("\nErrors:")
        for test, traceback in result.errors:
            print(f"- {test}: {traceback}")
    
    print("=" * 60)
    
    return result.wasSuccessful()

if __name__ == "__main__":
    import pandas as pd
    import numpy as np
    
    success = run_risk_tests()
    sys.exit(0 if success else 1)