"""
PullbackReversionStrategy 사용 예시

UPTREND 레짐에서 EMA 빠른선 근처 눌림목 매수 전략.
"""

from datetime import datetime, timezone
from typing import List

from src.strategy.pullback_reversion import PullbackReversionStrategy
from src.strategy.regime_detector import RegimeDetector
from src.core.types import OHLCV, MarketRegime


def test_pullback_strategy():
    """눌림목 전략 테스트."""

    print("=" * 60)
    print("Pullback Reversion Strategy - Test")
    print("=" * 60)

    # 1. 전략 초기화
    strategy = PullbackReversionStrategy(
        ema_fast=20,
        ema_slow=50,
        rsi_period=14,
        rsi_entry_threshold=45.0,  # RSI < 40에서 진입
        rsi_exit_threshold=55.0,   # RSI > 55에서 청산
        pullback_min_pct=0.3,      # 최소 1% 눌림
        pullback_max_pct=5.0,      # 최대 5% 눌림
        cooldown_seconds=300,
        time_stop_bars=20,
    )

    regime_detector = RegimeDetector()

    print("\n✅ Strategy initialized:")
    print(f"   EMA Fast: {strategy.ema_fast}")
    print(f"   EMA Slow: {strategy.ema_slow}")
    print(f"   RSI Entry: < {strategy.rsi_entry_threshold}")
    print(f"   RSI Exit: > {strategy.rsi_exit_threshold}")
    print(f"   Pullback Range: {strategy.pullback_min_pct}% ~ {strategy.pullback_max_pct}%")

    # 2. 가상 데이터 생성 (상승 추세 + 눌림 시뮬레이션)
    candles: List[OHLCV] = []
    base_price = 100000.0

    # 상승 추세 구간 (100개 캔들)
    for i in range(100):
        ts = datetime.now(timezone.utc)
        price = base_price + (i * 500)  # 지속적 상승

        # 약간의 변동성 추가
        noise = ((-1) ** i) * 200
        o = price + noise
        h = o + 300
        l = o - 300
        c = price + noise
        v = 100.0

        candles.append(OHLCV(
            timestamp=ts,
            open=o,
            high=h,
            low=l,
            close=c,
            volume=v,
        ))

    # 눌림 구간 (10개 캔들)
    pullback_start = candles[-1].close
    for i in range(10):
        ts = datetime.now(timezone.utc)
        # 2-3% 눌림 시뮬레이션
        price = pullback_start - (i * 500)

        o = price
        h = o + 200
        l = o - 200
        c = price
        v = 150.0  # 눌림 시 거래량 증가

        candles.append(OHLCV(
            timestamp=ts,
            open=o,
            high=h,
            low=l,
            close=c,
            volume=v,
        ))

    print(f"\n📊 Generated {len(candles)} candles")
    print(f"   Price range: {candles[0].close:.0f} → {candles[-1].close:.0f}")
    print(f"   Simulated pullback from {pullback_start:.0f} to {candles[-1].close:.0f}")

    # 3. 레짐 감지
    regime, regime_info = regime_detector.detect_regime(candles)
    print(f"\n🌐 Market Regime: {regime.value}")
    if regime_info:
        print(f"   ADX: {regime_info.get('adx', 0):.1f}")
        print(f"   ATR: {regime_info.get('atr', 0):.1f}")

    # 4. 진입 시그널 생성
    signal = strategy.generate_entry_signal(candles, regime, "TEST/KRW")

    if signal:
        print(f"\n✅ ENTRY SIGNAL GENERATED:")
        print(f"   Symbol: {signal.symbol}")
        print(f"   Side: {signal.side.value}")
        print(f"   Reason: {signal.reason}")
        print(f"\n   Indicators:")
        for key, value in signal.indicators.items():
            if isinstance(value, float):
                print(f"     {key}: {value:.2f}")
            else:
                print(f"     {key}: {value}")
    else:
        print(f"\n⚪ No entry signal")
        print(f"   Regime may not be UPTREND or conditions not met")

    # 5. 청산 조건 테스트 (가정: 진입 후 추세 회복)
    if signal:
        # 추세 회복 시뮬레이션 (5개 캔들)
        recovery_candles = candles.copy()
        last_price = recovery_candles[-1].close

        for i in range(5):
            ts = datetime.now(timezone.utc)
            price = last_price + (i * 600)  # 빠른 회복

            recovery_candles.append(OHLCV(
                timestamp=ts,
                open=price,
                high=price + 300,
                low=price - 100,
                close=price,
                volume=120.0,
            ))

        entry_bar_index = len(candles) - 1
        should_exit, exit_reason = strategy.should_exit(
            recovery_candles,
            signal.side,
            candles[-1].close,
            entry_bar_index=entry_bar_index,
        )

        if should_exit:
            print(f"\n❌ EXIT SIGNAL:")
            print(f"   Reason: {exit_reason}")
            print(f"   Entry price: {candles[-1].close:.0f}")
            print(f"   Exit price: {recovery_candles[-1].close:.0f}")
            pnl_pct = ((recovery_candles[-1].close - candles[-1].close) / candles[-1].close) * 100
            print(f"   PnL: {pnl_pct:+.2f}%")
        else:
            print(f"\n⏳ Position still held (no exit signal)")

    print("\n" + "=" * 60)


def show_strategy_comparison():
    """전략 비교표 출력."""
    print("\n" + "=" * 80)
    print("Strategy Comparison")
    print("=" * 80)
    print()
    print("| Strategy              | Regime    | Entry Condition                    | Exit Condition              |")
    print("|-----------------------|-----------|------------------------------------|-----------------------------|")
    print("| MeanReversion         | RANGING   | BB band breakout + RSI extreme     | BB middle reversion         |")
    print("| PullbackReversion     | UPTREND   | EMA pullback + RSI oversold        | EMA recovery + RSI recovery |")
    print("| TrendFollower         | UPTREND   | High breakout + strong momentum    | Trailing stop + trend break |")
    print()
    print("=" * 80)
    print()
    print("Pullback Strategy Parameters:")
    print("  - ema_fast: 20 (빠른 EMA, 진입/청산 기준)")
    print("  - ema_slow: 50 (느린 EMA, 추세 확인)")
    print("  - rsi_entry_threshold: 40 (RSI < 40에서 진입)")
    print("  - rsi_exit_threshold: 55 (RSI > 55에서 청산)")
    print("  - pullback_min_pct: 1.0% (최소 눌림 폭)")
    print("  - pullback_max_pct: 5.0% (최대 눌림 폭)")
    print()
    print("Recommended Use:")
    print("  ✅ Strong uptrends with healthy pullbacks")
    print("  ✅ Lower risk than trend following (buy dips)")
    print("  ✅ Quick exits on EMA recovery")
    print("  ❌ Not for ranging markets")
    print("  ❌ Not for weak/choppy uptrends")
    print()
    print("=" * 80)


if __name__ == "__main__":
    test_pullback_strategy()
    show_strategy_comparison()
