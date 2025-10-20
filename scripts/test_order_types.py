#!/usr/bin/env python3
"""
업비트 주문 타입별 테스트 스크립트
실제 주문은 하지 않고 API 파라미터 검증만 수행
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.upbit_api import upbit_api
from src.trader import trader
from src.logger import logger

def test_order_parameters():
    """주문 파라미터 테스트 (실제 주문 X)"""
    print("=== 업비트 주문 타입별 파라미터 테스트 ===")
    
    # 테스트할 주문 정보
    test_market = "KRW-SOL"
    test_krw_amount = 5000.0
    test_volume = 0.01
    test_price = 150000.0
    
    print(f"테스트 마켓: {test_market}")
    print(f"테스트 금액: {test_krw_amount:,} KRW")
    print(f"테스트 수량: {test_volume}")
    print(f"테스트 가격: {test_price:,} KRW")
    print()
    
    # 1. 시장가 매수 파라미터 검증
    print("1. 시장가 매수 파라미터:")
    try:
        # place_order 함수의 파라미터 생성 로직만 테스트
        params = {
            'market': test_market,
            'side': 'bid',
            'ord_type': 'price'  # 수정된 부분
        }
        params['price'] = str(test_krw_amount)
        print(f"   ✓ {params}")
    except Exception as e:
        print(f"   ✗ 오류: {e}")
    
    # 2. 시장가 매도 파라미터 검증
    print("2. 시장가 매도 파라미터:")
    try:
        params = {
            'market': test_market,
            'side': 'ask',
            'ord_type': 'market'
        }
        params['volume'] = str(test_volume)
        print(f"   ✓ {params}")
    except Exception as e:
        print(f"   ✗ 오류: {e}")
    
    # 3. 지정가 매수 파라미터 검증
    print("3. 지정가 매수 파라미터:")
    try:
        params = {
            'market': test_market,
            'side': 'bid',
            'ord_type': 'limit'
        }
        params['volume'] = str(test_volume)
        params['price'] = str(test_price)
        print(f"   ✓ {params}")
    except Exception as e:
        print(f"   ✗ 오류: {e}")
    
    # 4. 지정가 매도 파라미터 검증
    print("4. 지정가 매도 파라미터:")
    try:
        params = {
            'market': test_market,
            'side': 'ask',
            'ord_type': 'limit'
        }
        params['volume'] = str(test_volume)
        params['price'] = str(test_price)
        print(f"   ✓ {params}")
    except Exception as e:
        print(f"   ✗ 오류: {e}")

def test_current_price():
    """현재 가격 조회 테스트"""
    print("\n=== 현재 가격 조회 테스트 ===")
    
    test_markets = ['KRW-BTC', 'KRW-ETH', 'KRW-SOL']
    
    for market in test_markets:
        try:
            price = trader.get_current_price(market)
            if price:
                print(f"{market}: {price:,} KRW")
            else:
                print(f"{market}: 가격 조회 실패")
        except Exception as e:
            print(f"{market}: 오류 - {e}")

def test_balance_check():
    """잔고 조회 테스트"""
    print("\n=== 잔고 조회 테스트 ===")
    
    try:
        krw_balance, krw_locked = trader.get_balance('KRW')
        print(f"KRW 잔고: {krw_balance:,}, 사용중: {krw_locked:,}")
        
        if krw_balance >= 5000:
            print("✓ 시장가 매수 테스트 가능한 잔고")
        else:
            print("✗ 시장가 매수 테스트 불가 (최소 5,000원 필요)")
            
    except Exception as e:
        print(f"잔고 조회 오류: {e}")

def show_order_type_reference():
    """업비트 주문 타입 참조표"""
    print("\n=== 업비트 주문 타입 참조표 ===")
    print("매수 주문:")
    print("  - 시장가 매수: ord_type='price', side='bid', price='금액(KRW)'")
    print("  - 지정가 매수: ord_type='limit', side='bid', volume='수량', price='가격'")
    print()
    print("매도 주문:")
    print("  - 시장가 매도: ord_type='market', side='ask', volume='수량'")
    print("  - 지정가 매도: ord_type='limit', side='ask', volume='수량', price='가격'")
    print()
    print("주의사항:")
    print("  - 시장가 매수는 ord_type='market'이 아니라 'price'를 사용!")
    print("  - 시장가 매수는 volume이 아니라 price(KRW 금액)를 전달!")

def main():
    print("업비트 주문 타입 수정 후 테스트")
    print("=" * 50)
    
    show_order_type_reference()
    test_order_parameters()
    test_current_price()
    test_balance_check()
    
    print("\n" + "=" * 50)
    print("파라미터 테스트 완료!")
    print("\n이제 실제 거래를 테스트하려면:")
    print("python scripts/manual_trade.py")
    print("명령어: buy SOL 5000 market")

if __name__ == "__main__":
    main()