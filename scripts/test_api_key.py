#!/usr/bin/env python3
"""
Upbit API 키 검증 스크립트
실제 주문 없이 API 연결만 테스트합니다.
"""

import asyncio
import os
from pathlib import Path
from dotenv import load_dotenv


async def test_api_key():
    """Test if Upbit API key is valid."""
    # Load .env
    env_file = Path('.env')
    if not env_file.exists():
        print("❌ .env file not found!")
        return False

    load_dotenv()

    api_key = os.getenv('UPBIT_API_KEY')
    api_secret = os.getenv('UPBIT_API_SECRET')

    if not api_key or not api_secret:
        print("❌ UPBIT_API_KEY or UPBIT_API_SECRET not set in .env")
        return False

    print(f"✅ API Key found: {api_key[:10]}...")
    print(f"✅ API Secret found: {api_secret[:10]}...")

    # Test connection
    try:
        from src.exchange.upbit import UpbitExchange

        print("\n🔌 Testing Upbit API connection...")
        exchange = UpbitExchange(api_key=api_key, api_secret=api_secret)

        # Test 1: Fetch balance (requires 자산조회 permission)
        print("   → Testing fetch_balance()...")
        balance = await exchange.fetch_balance()
        print(f"   ✅ Balance fetched successfully!")
        print(f"   💰 KRW balance: {balance.get('KRW', {}).get('free', 0):,.0f} KRW")

        # Test 2: Fetch ticker
        print("   → Testing fetch_ticker()...")
        ticker = await exchange.fetch_ticker("BTC/KRW")
        print(f"   ✅ Ticker fetched successfully!")
        print(f"   📊 BTC/KRW price: {ticker['last']:,.0f} KRW")

        await exchange.close()

        print("\n✅ API key is VALID! All tests passed.")
        return True

    except Exception as e:
        print(f"\n❌ API test FAILED: {e}")
        print("\n💡 Possible solutions:")
        print("   1. Go to https://upbit.com/mypage/open_api_management")
        print("   2. Delete old API key and create a new one")
        print("   3. Make sure '자산조회' permission is enabled")
        print("   4. Update .env file with new API key and secret")
        return False


if __name__ == "__main__":
    asyncio.run(test_api_key())
