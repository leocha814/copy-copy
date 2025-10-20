#!/usr/bin/env python3
"""
리스크 관리 통합 테스트 스크립트

실제 runner.py와 연동하여 리스크 관리 기능이 정상 작동하는지 테스트합니다.
"""

import sys
import os
import time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.risk_manager import RiskManager, RiskLimits
from src.upbit_api import upbit_api
from src.trader import trader
from src.logger import logger

def test_order_amount_limit():
    """주문 금액 제한 테스트"""
    print("=== 주문 금액 제한 테스트 ===")
    
    # 작은 한도로 설정
    limits = RiskLimits(max_order_krw=5000.0)
    risk_manager = RiskManager(limits)
    
    # 정상 주문 (한도 내)
    allowed, reason = risk_manager.check_pre_trade(
        market="KRW-BTC",
        krw_amount=3000.0,
        current_positions=0,
        current_balance=50000.0
    )
    print(f"3,000원 주문: {'허용' if allowed else '차단'} - {reason}")
    
    # 한도 초과 주문
    allowed, reason = risk_manager.check_pre_trade(
        market="KRW-BTC",
        krw_amount=7000.0,  # 5,000원 초과
        current_positions=0,
        current_balance=50000.0
    )
    print(f"7,000원 주문: {'허용' if allowed else '차단'} - {reason}")

def test_position_limit():
    """포지션 수 제한 테스트"""
    print("\n=== 포지션 수 제한 테스트 ===")
    
    limits = RiskLimits(max_positions=1)
    risk_manager = RiskManager(limits)
    
    # 포지션 없을 때
    allowed, reason = risk_manager.check_pre_trade(
        market="KRW-BTC",
        krw_amount=5000.0,
        current_positions=0,
        current_balance=50000.0
    )
    print(f"포지션 0개 상태에서 매수: {'허용' if allowed else '차단'} - {reason}")
    
    # 포지션 1개 있을 때
    allowed, reason = risk_manager.check_pre_trade(
        market="KRW-ETH",
        krw_amount=5000.0,
        current_positions=1,  # 이미 1개 포지션
        current_balance=50000.0
    )
    print(f"포지션 1개 상태에서 추가 매수: {'허용' if allowed else '차단'} - {reason}")

def test_consecutive_losses():
    """연속 손실 제한 테스트"""
    print("\n=== 연속 손실 제한 테스트 ===")
    
    limits = RiskLimits(consecutive_loss_limit=3)
    risk_manager = RiskManager(limits)
    
    print("연속 손실 시뮬레이션:")
    for i in range(4):
        if i < 3:
            risk_manager.update_trade_result(-1000.0, is_loss=True)
            print(f"손실 {i+1}회: 연속 손실 = {risk_manager.consecutive_losses}")
        
        allowed, reason = risk_manager.check_pre_trade(
            market="KRW-BTC",
            krw_amount=5000.0,
            current_positions=0,
            current_balance=50000.0
        )
        print(f"  거래 허용: {'예' if allowed else '아니오'} - {reason}")
        
        if risk_manager.emergency_stop:
            print("  🚨 응급 정지 발동!")
            break

def test_trading_hours():
    """거래 시간 제한 테스트"""
    print("\n=== 거래 시간 제한 테스트 ===")
    
    risk_manager = RiskManager()
    current_hour = time.localtime().tm_hour
    
    print(f"현재 시간: {current_hour}시")
    print(f"거래 시간: {risk_manager.limits.trading_start_hour}시 ~ {risk_manager.limits.trading_end_hour}시")
    
    allowed, reason = risk_manager.check_pre_trade(
        market="KRW-BTC",
        krw_amount=5000.0,
        current_positions=0,
        current_balance=50000.0
    )
    
    if "trading_hours" in reason:
        print(f"거래 시간 제한: 차단됨 - {reason}")
    else:
        print("거래 시간: 정상")

def test_ranging_market_detection():
    """횡보 시장 판단 테스트"""
    print("\n=== 횡보 시장 판단 테스트 ===")
    
    risk_manager = RiskManager()
    
    # 실제 BTC 1분봉 데이터 조회
    try:
        candles = upbit_api.get_candles_minutes("KRW-BTC", unit=1, count=50)
        if candles:
            # 업비트 API는 최신이 첫 번째이므로 역순 정렬
            candles.reverse()
            
            is_ranging, meta = risk_manager.is_ranging_market(candles)
            
            print(f"BTC 시장 상태: {'횡보' if is_ranging else '트렌딩'}")
            print(f"  평균 RSI: {meta.get('avg_rsi', 'N/A'):.1f}")
            print(f"  볼린저 밴드 폭: {meta.get('bb_width_pct', 'N/A'):.2f}%")
            print(f"  가격 변동성: {meta.get('price_volatility', 'N/A'):.2f}%")
            print(f"  조건 충족: {meta.get('conditions_met', 0)}/3")
        else:
            print("캔들 데이터 조회 실패")
    except Exception as e:
        print(f"시장 데이터 조회 오류: {e}")

def test_rate_limit_simulation():
    """레이트 리밋 시뮬레이션"""
    print("\n=== 레이트 리밋 테스트 ===")
    
    risk_manager = RiskManager()
    
    # 연속 요청으로 레이트 리밋 테스트
    print("연속 요청 시뮬레이션:")
    for i in range(10):
        start_time = time.time()
        risk_manager.wait_for_rate_limit()
        elapsed = time.time() - start_time
        
        if elapsed > 0.01:  # 10ms 이상 대기했다면
            print(f"요청 {i+1}: {elapsed*1000:.1f}ms 대기")
        else:
            print(f"요청 {i+1}: 즉시 처리")

def test_emergency_stop_recovery():
    """응급 정지 및 복구 테스트"""
    print("\n=== 응급 정지 및 복구 테스트 ===")
    
    limits = RiskLimits(consecutive_loss_limit=2)
    risk_manager = RiskManager(limits)
    
    # 응급 정지 발동
    for i in range(2):
        risk_manager.update_trade_result(-1000.0, is_loss=True)
    
    print(f"응급 정지 상태: {risk_manager.emergency_stop}")
    
    # 수동 복구
    success = risk_manager.reset_emergency_stop(manual_override=True)
    print(f"수동 복구 성공: {success}")
    print(f"복구 후 상태: {risk_manager.emergency_stop}")

def test_daily_stats_tracking():
    """일일 통계 추적 테스트"""
    print("\n=== 일일 통계 추적 테스트 ===")
    
    risk_manager = RiskManager()
    
    # 가상 거래 결과 추가
    trades = [
        (1500.0, False),   # 수익
        (-800.0, True),    # 손실
        (2200.0, False),   # 수익
        (-1200.0, True),   # 손실
    ]
    
    for profit, is_loss in trades:
        risk_manager.update_trade_result(profit, is_loss)
        print(f"거래 결과: {profit:+.0f}원 ({'손실' if is_loss else '수익'})")
    
    status = risk_manager.get_risk_status()
    daily_stats = status['daily_stats']
    
    print(f"\n일일 통계:")
    print(f"  총 거래: {daily_stats['trade_count']}회")
    print(f"  총 수익: {daily_stats['total_profit']:+,.0f}원")
    print(f"  총 손실: {daily_stats['total_loss']:,.0f}원")
    print(f"  손실 횟수: {daily_stats['loss_count']}회")
    print(f"  연속 손실: {status['consecutive_losses']}회")

def main():
    """메인 테스트 함수"""
    print("리스크 관리 통합 테스트")
    print("=" * 60)
    
    try:
        test_order_amount_limit()
        test_position_limit()
        test_consecutive_losses()
        test_trading_hours()
        test_ranging_market_detection()
        test_rate_limit_simulation()
        test_emergency_stop_recovery()
        test_daily_stats_tracking()
        
        print("\n" + "=" * 60)
        print("모든 테스트 완료!")
        print("\n실제 자동매매 실행:")
        print("python src/runner.py --market KRW-BTC --krw 5000 --mode DRYRUN")
        
    except Exception as e:
        logger.error(f"테스트 중 오류 발생: {e}")
        return False
    
    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)