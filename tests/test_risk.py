"""
Test risk management functions.
Run: python tests/test_risk.py
"""
from datetime import datetime
from src.core import RiskLimits, AccountState, Position, OrderSide
from src.risk import RiskManager


def test_position_sizing():
    """Test ATR-based position sizing."""
    print("\n💰 Testing Position Sizing:")

    limits = RiskLimits(
        per_trade_risk_pct=2.0,
        max_position_size_pct=50.0
    )
    risk_mgr = RiskManager(limits)

    account_balance = 10_000_000  # 1천만원
    entry_price = 50_000
    atr_value = 500

    size = risk_mgr.calculate_position_size_atr(
        account_balance,
        entry_price,
        atr_value,
        atr_multiplier=2.0
    )

    print(f"  Account: {account_balance:,}원")
    print(f"  Entry Price: {entry_price:,}원")
    print(f"  ATR: {atr_value:,}원")
    print(f"  Position Size: {size:.4f} units")
    print(f"  Position Value: {size * entry_price:,.0f}원")

    # Check it doesn't exceed max position size
    max_value = account_balance * 0.5
    assert size * entry_price <= max_value


def test_stop_loss_take_profit():
    """Test SL/TP calculation."""
    print("\n🎯 Testing Stop Loss / Take Profit:")

    limits = RiskLimits()
    risk_mgr = RiskManager(limits)

    entry_price = 50_000
    atr_value = 500

    stop_loss, take_profit = risk_mgr.calculate_stop_loss_take_profit(
        entry_price,
        OrderSide.BUY,
        atr_value,
        stop_atr_multiplier=2.0,
        target_atr_multiplier=3.0
    )

    print(f"  Entry: {entry_price:,}원")
    print(f"  Stop Loss: {stop_loss:,}원 ({((stop_loss/entry_price - 1) * 100):.2f}%)")
    print(f"  Take Profit: {take_profit:,}원 ({((take_profit/entry_price - 1) * 100):.2f}%)")
    print(f"  Risk:Reward = 1:{(take_profit - entry_price) / (entry_price - stop_loss):.2f}")

    # SL should be below entry for LONG
    assert stop_loss < entry_price
    assert take_profit > entry_price


def test_risk_limits():
    """Test account protection limits."""
    print("\n🛡️ Testing Risk Limits:")

    limits = RiskLimits(
        max_daily_loss_pct=5.0,
        max_consecutive_losses=5,
        max_drawdown_pct=15.0
    )
    risk_mgr = RiskManager(limits)

    # Test daily loss limit
    print("\n  Testing Daily Loss Limit:")
    account = AccountState(
        timestamp=datetime.now(),
        total_balance=10_000_000,
        available_balance=8_000_000,
        equity=9_400_000,  # -600k loss
        daily_pnl=-600_000,  # -6% loss
        total_pnl=-600_000,
        open_positions=0,
        consecutive_losses=0,
        max_equity=10_000_000
    )

    breach = risk_mgr.check_daily_loss_limit(account)
    print(f"    Daily Loss: {abs(account.daily_pnl):,}원 ({abs(account.daily_pnl / account.total_balance) * 100:.1f}%)")
    print(f"    Limit Breached: {breach}")
    assert breach  # Should breach 5% limit

    # Test consecutive losses
    print("\n  Testing Consecutive Losses:")
    account.consecutive_losses = 6
    breach = risk_mgr.check_consecutive_losses(account)
    print(f"    Consecutive Losses: {account.consecutive_losses}")
    print(f"    Limit Breached: {breach}")
    assert breach

    # Test drawdown
    print("\n  Testing Max Drawdown:")
    account.max_equity = 12_000_000
    account.equity = 10_000_000  # -16.7% DD
    breach = risk_mgr.check_max_drawdown(account)
    dd = account.current_drawdown_pct
    print(f"    Peak Equity: {account.max_equity:,}원")
    print(f"    Current Equity: {account.equity:,}원")
    print(f"    Drawdown: {dd:.1f}%")
    print(f"    Limit Breached: {breach}")
    assert breach


def test_stop_loss_check():
    """Test stop loss hit detection."""
    print("\n🔴 Testing Stop Loss Detection:")

    limits = RiskLimits()
    risk_mgr = RiskManager(limits)

    position = Position(
        symbol='BTC/KRW',
        side=OrderSide.BUY,
        size=0.01,
        entry_price=50_000,
        entry_time=datetime.now(),
        stop_loss=49_000,
        take_profit=51_500,
        current_price=48_800  # Below stop loss
    )

    hit = risk_mgr.check_stop_loss(position)
    print(f"  Entry: {position.entry_price:,}원")
    print(f"  Stop Loss: {position.stop_loss:,}원")
    print(f"  Current: {position.current_price:,}원")
    print(f"  Stop Loss Hit: {hit}")
    assert hit


if __name__ == '__main__':
    print("="*60)
    print("🧪 Risk Management Testing Suite")
    print("="*60)

    test_position_sizing()
    test_stop_loss_take_profit()
    test_risk_limits()
    test_stop_loss_check()

    print("\n" + "="*60)
    print("✅ All risk management tests completed!")
    print("="*60)
