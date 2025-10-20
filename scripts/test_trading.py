#!/usr/bin/env python3
"""
실시간 가격 모니터링 및 수동 주문 시스템 테스트 스크립트
"""

import sys
import os
import time
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.price_watcher import PriceWatcher
from src.trader import trader
from src.upbit_api import upbit_api
from src.logger import logger

def test_price_monitoring():
    """가격 모니터링 테스트"""
    print("=== 실시간 가격 모니터링 테스트 ===")
    
    # 테스트할 마켓들
    test_markets = ['KRW-BTC', 'KRW-ETH']
    
    # PriceWatcher 인스턴스 생성
    watcher = PriceWatcher(test_markets, update_interval=2.0)
    
    try:
        # 모니터링 시작
        watcher.start_monitoring()
        print(f"가격 모니터링 시작: {', '.join(test_markets)}")
        print("10초간 가격 업데이트를 확인합니다...")
        
        # 10초간 실행
        for i in range(10):
            time.sleep(1)
            print(f"\\r진행 중... {10-i}초 남음", end="", flush=True)
        
        print("\\n\\n현재 가격 요약:")
        watcher.display_current_prices()
        
        print("가격 히스토리 요약:")
        watcher.display_price_summary()
        
    except KeyboardInterrupt:
        print("\\n사용자에 의해 중단됨")
    finally:
        watcher.stop_monitoring()
        print("가격 모니터링 테스트 완료")

def test_balance_check():
    """잔고 조회 테스트"""
    print("\\n=== 잔고 조회 테스트 ===")
    
    try:
        accounts = upbit_api.get_accounts()
        if accounts:
            print("계좌 잔고:")
            for account in accounts:
                balance = float(account['balance'])
                locked = float(account['locked'])
                if balance > 0 or locked > 0:
                    print(f"  {account['currency']}: 잔고 {balance}, 사용중 {locked}")
        else:
            print("잔고 조회 실패 또는 API 키 미설정")
    except Exception as e:
        print(f"잔고 조회 중 오류: {e}")

def test_order_functions():
    """주문 기능 테스트 (실제 주문 X, 검증만)"""
    print("\\n=== 주문 기능 테스트 ===")
    
    # 현재 가격 조회 테스트
    current_price = trader.get_current_price('KRW-BTC')
    if current_price:
        print(f"BTC 현재가: {current_price:,} KRW")
    else:
        print("가격 조회 실패")
    
    # 잔고 조회 테스트
    krw_balance, krw_locked = trader.get_balance('KRW')
    print(f"KRW 잔고: {krw_balance:,}, 사용중: {krw_locked:,}")
    
    # 주문 계산 테스트
    if current_price and krw_balance > 10000:
        result = trader.calculate_buy_amount('KRW-BTC', 10000)
        if result:
            volume, price = result
            print(f"10,000 KRW로 구매 가능한 BTC: {volume:.8f} (가격: {price:,})")
    
    print("주문 기능 검증 완료 (실제 주문은 실행되지 않음)")

def test_order_status():
    """미체결 주문 조회 테스트"""
    print("\\n=== 미체결 주문 조회 테스트 ===")
    
    try:
        orders = upbit_api.get_orders()
        if orders:
            print(f"미체결 주문 {len(orders)}개:")
            for order in orders[:5]:  # 최대 5개만 표시
                print(f"  {order['market']} {order['side']} {order['ord_type']}")
                print(f"    UUID: {order['uuid']}")
        else:
            print("미체결 주문이 없습니다.")
    except Exception as e:
        print(f"주문 조회 중 오류: {e}")

def main():
    print("업비트 실시간 모니터링 + 수동 주문 시스템 테스트")
    print("=" * 50)
    
    # 각 기능 테스트
    test_balance_check()
    test_order_functions()
    test_order_status()
    test_price_monitoring()
    
    print("\\n" + "=" * 50)
    print("모든 테스트 완료!")
    print("\\n실제 거래를 원하면 다음 명령어를 실행하세요:")
    print("python scripts/manual_trade.py")

if __name__ == "__main__":
    main()