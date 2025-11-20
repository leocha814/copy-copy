"""
TradingEngine 사용 예시

MeanReversionStrategy + PositionTracker + RiskManager를 통합한
TradingEngine의 실전 사용법 데모.
"""

import asyncio
from datetime import datetime, timezone
from typing import List

from src.strategy.mean_reversion import MeanReversionStrategy
from src.strategy.regime_detector import RegimeDetector
from src.strategy.trading_engine import TradingEngine
from src.exec.position_tracker import PositionTracker
from src.risk.risk_manager import RiskManager
from src.core.types import OHLCV, RiskLimits, MarketRegime
from src.exchange.upbit import UpbitExchange
from src.indicators.indicators import calculate_atr


# ===== 1. 초기화 =====

def setup_trading_system():
    """트레이딩 시스템 컴포넌트 초기화."""

    # 1) MeanReversion 전략
    strategy = MeanReversionStrategy(
        rsi_period=14,
        rsi_oversold=30.0,
        rsi_overbought=70.0,
        bb_period=20,
        bb_std_dev=2.0,
        rsi_exit_threshold=50.0,
        cooldown_seconds=300,  # 5분 쿨다운
        bb_width_min=1.0,      # BB 폭 최소 1%
        bb_width_max=10.0,     # BB 폭 최대 10%
        time_stop_bars=20,     # 20봉 이상 보유 시 강제 청산
    )

    # 2) PositionTracker
    tracker = PositionTracker()

    # 3) RiskManager
    risk_limits = RiskLimits(
        per_trade_risk_pct=2.0,       # 거래당 2% 리스크
        max_daily_loss_pct=5.0,       # 일일 최대 손실 5%
        max_consecutive_losses=5,     # 연속 손실 5회 제한
        max_drawdown_pct=15.0,        # 최대 드로우다운 15%
        max_position_size_pct=50.0,   # 최대 포지션 크기 50%
        stop_atr_multiplier=2.0,      # 손절: ATR × 2
        target_atr_multiplier=3.0,    # 익절: ATR × 3
    )
    risk_manager = RiskManager(risk_limits)

    # 4) RegimeDetector
    regime_detector = RegimeDetector(
        adx_threshold_low=20.0,
        adx_threshold_high=25.0,
    )

    # 5) TradingEngine (통합)
    engine = TradingEngine(
        strategy=strategy,
        position_tracker=tracker,
        risk_manager=risk_manager,
    )

    return engine, regime_detector


# ===== 2. 메인 트레이딩 루프 =====

async def trading_loop_example():
    """실제 트레이딩 루프 예시."""

    # 시스템 초기화
    engine, regime_detector = setup_trading_system()

    # 거래소 연결 (Upbit 예시)
    exchange = UpbitExchange(
        api_key="YOUR_API_KEY",
        api_secret="YOUR_API_SECRET",
    )

    # 거래 심볼 & 타임프레임
    symbol = "BTC/KRW"
    timeframe = "5m"

    # 초기 계좌 잔고
    balance_info = await exchange.fetch_balance()
    account_balance = balance_info['KRW']['free']

    print(f"🤖 Trading Engine Started")
    print(f"💰 Initial Balance: {account_balance:,.0f} KRW")
    print(f"📊 Symbol: {symbol} | Timeframe: {timeframe}\n")

    # 메인 루프
    iteration = 0
    while True:
        try:
            iteration += 1
            print(f"{'='*60}")
            print(f"📅 Iteration #{iteration} | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"{'='*60}")

            # 1) OHLCV 데이터 가져오기
            candles = await exchange.fetch_ohlcv(
                symbol=symbol,
                timeframe=timeframe,
                limit=200,  # 충분한 과거 데이터
            )

            if len(candles) < 50:
                print("⚠️ Insufficient candles, waiting...")
                await asyncio.sleep(60)
                continue

            # 2) 현재가 & ATR 계산
            current_price = candles[-1].close
            high_prices = [c.high for c in candles]
            low_prices = [c.low for c in candles]
            close_prices = [c.close for c in candles]
            atr_values = calculate_atr(high_prices, low_prices, close_prices, period=14)
            current_atr = atr_values[-1]

            print(f"💵 Current Price: {current_price:,.0f} KRW")
            print(f"📊 ATR: {current_atr:,.2f}")

            # 3) 시장 레짐 감지
            regime, regime_info = regime_detector.detect_regime(candles)
            print(f"🌐 Market Regime: {regime.value.upper()}")
            if regime_info:
                print(f"   └─ ADX: {regime_info.get('adx', 0):.1f} | ATR: {regime_info.get('atr', 0):.1f}")

            # 4) TradingEngine 업데이트
            result = engine.update(
                symbol=symbol,
                candles=candles,
                regime=regime,
                account_balance=account_balance,
                current_price=current_price,
                atr_value=current_atr,
                exit_fees=None,  # 수수료는 실제 체결 시 계산
                slippage=0.0005, # 0.05% 슬리피지
            )

            # 5) 결과 처리
            action = result['action']

            if action == 'entry':
                position = result['position']
                signal = result['signal']
                print(f"\n✅ ENTRY EXECUTED")
                print(f"   Side: {position.side.value.upper()}")
                print(f"   Size: {position.size:.4f}")
                print(f"   Entry: {position.entry_price:,.0f} KRW")
                print(f"   SL: {position.stop_loss:,.0f} KRW")
                print(f"   TP: {position.take_profit:,.0f} KRW")
                print(f"   Reason: {signal.reason}")

                # 실제로는 여기서 거래소 API로 주문 실행
                # order = await exchange.create_order(...)

            elif action == 'exit':
                reason = result['reason']
                print(f"\n❌ EXIT EXECUTED")
                print(f"   Reason: {reason}")

                # 성과 통계 출력
                stats = engine.get_performance_stats()
                print(f"\n📊 Performance Stats:")
                print(f"   Total Trades: {stats['total_trades']}")
                print(f"   Win Rate: {stats['win_rate']:.1f}%")
                print(f"   Total PnL: {stats['total_pnl']:+,.0f} KRW")
                print(f"   Avg PnL: {stats['avg_pnl']:+,.0f} KRW")

            elif action == 'hold':
                position = result['position']
                if position:
                    print(f"\n⏳ POSITION HELD")
                    print(f"   Side: {position.side.value.upper()}")
                    print(f"   Entry: {position.entry_price:,.0f} KRW")
                    print(f"   Current: {position.current_price:,.0f} KRW")
                    print(f"   Unrealized PnL: {position.unrealized_pnl:+,.0f} KRW ({position.unrealized_pnl_pct:+.2f}%)")
                else:
                    print(f"\n⚪ NO POSITION | Waiting for signal...")

            # 6) 대기 (1분마다 체크)
            print(f"\n⏱️ Next check in 60 seconds...\n")
            await asyncio.sleep(60)

        except KeyboardInterrupt:
            print("\n🛑 Shutting down...")
            break
        except Exception as e:
            print(f"\n❌ Error: {e}")
            import traceback
            traceback.print_exc()
            await asyncio.sleep(60)

    # 종료 시 모든 포지션 강제 청산
    if engine.tracker.get_all_positions():
        print("\n🚨 Force closing all positions...")
        current_prices = {symbol: current_price}
        closed = engine.force_close_all(current_prices, reason="System shutdown")
        print(f"   Closed: {', '.join(closed)}")

    await exchange.close()
    print("✅ Trading Engine Stopped")


# ===== 3. 간단한 백테스트 예시 =====

def backtest_example():
    """과거 데이터로 전략 테스트 (간단한 예시)."""

    print("📈 Backtest Example")
    print("=" * 60)

    # 시스템 초기화
    engine, regime_detector = setup_trading_system()

    # 가상 캔들 데이터 (실제로는 CSV/DB에서 로드)
    # 여기서는 더미 데이터 생성
    candles: List[OHLCV] = []
    base_price = 50000000  # 5천만원

    for i in range(200):
        ts = datetime.now(timezone.utc)
        o = base_price + (i * 10000)
        h = o + 50000
        l = o - 50000
        c = o + ((-1) ** i * 30000)  # 지그재그 패턴
        v = 100.0

        candles.append(OHLCV(
            timestamp=ts,
            open=o,
            high=h,
            low=l,
            close=c,
            volume=v,
        ))

    # 초기 잔고
    account_balance = 10_000_000  # 1천만원

    # 백테스트 실행
    for i in range(50, len(candles)):
        window = candles[:i+1]
        current_price = window[-1].close

        # ATR 계산
        high_prices = [c.high for c in window]
        low_prices = [c.low for c in window]
        close_prices = [c.close for c in window]
        atr_values = calculate_atr(high_prices, low_prices, close_prices, period=14)
        current_atr = atr_values[-1]

        # 레짐 감지
        regime, _ = regime_detector.detect_regime(window)

        # 엔진 업데이트
        result = engine.update(
            symbol="TEST/KRW",
            candles=window,
            regime=regime,
            account_balance=account_balance,
            current_price=current_price,
            atr_value=current_atr,
        )

        if result['action'] == 'entry':
            print(f"[Bar {i}] ENTRY: {result['signal'].reason}")
        elif result['action'] == 'exit':
            print(f"[Bar {i}] EXIT: {result['reason']}")

    # 최종 통계
    stats = engine.get_performance_stats()
    print("\n" + "=" * 60)
    print("📊 Final Statistics:")
    print(f"   Total Trades: {stats['total_trades']}")
    print(f"   Win Rate: {stats['win_rate']:.1f}%")
    print(f"   Total PnL: {stats['total_pnl']:+,.0f}")
    print(f"   Avg PnL: {stats['avg_pnl']:+,.0f}")
    print(f"   Profit Factor: {stats['profit_factor']:.2f}")
    print("=" * 60)


# ===== 실행 =====

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "backtest":
        # 백테스트 모드
        backtest_example()
    else:
        # 실시간 트레이딩 모드
        asyncio.run(trading_loop_example())
