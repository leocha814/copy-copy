#!/usr/bin/env python3

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.upbit_api import upbit_api
from src.config import config
from src.logger import logger

def check_market_data():
    logger.info("=== 시장 데이터 조회 테스트 ===")
    
    try:
        markets = upbit_api.get_markets()
        if markets:
            krw_markets = [m for m in markets if m['market'].startswith('KRW-')][:5]
            logger.info(f"사용 가능한 KRW 마켓 (상위 5개): {[m['market'] for m in krw_markets]}")
            
            market_codes = [m['market'] for m in krw_markets]
            tickers = upbit_api.get_ticker(market_codes)
            
            if tickers:
                logger.info("현재 시세 정보:")
                for ticker in tickers:
                    logger.info(f"  {ticker['market']}: {ticker['trade_price']:,} KRW")
            else:
                logger.error("시세 정보 조회 실패")
        else:
            logger.error("마켓 정보 조회 실패")
    
    except Exception as e:
        logger.error(f"시장 데이터 조회 중 오류: {e}")

def check_account_info():
    logger.info("=== 계좌 정보 조회 테스트 ===")
    
    if not config.has_api_keys:
        logger.warning("API 키가 설정되지 않아 계좌 정보를 조회할 수 없습니다.")
        logger.info("계좌 정보 조회를 위해 .env 파일에 다음 정보를 추가하세요:")
        logger.info("UPBIT_ACCESS_KEY=your_access_key")
        logger.info("UPBIT_SECRET_KEY=your_secret_key")
        return
    
    try:
        accounts = upbit_api.get_accounts()
        if accounts:
            logger.info("계좌 잔고 정보:")
            for account in accounts:
                balance = float(account['balance'])
                locked = float(account['locked'])
                if balance > 0 or locked > 0:
                    logger.info(f"  {account['currency']}: 잔고 {balance:,.8f}, 사용중 {locked:,.8f}")
        else:
            logger.error("계좌 정보 조회 실패")
    
    except Exception as e:
        logger.error(f"계좌 정보 조회 중 오류: {e}")

def check_orderbook():
    logger.info("=== 호가 정보 조회 테스트 ===")
    
    try:
        orderbook = upbit_api.get_orderbook(['KRW-BTC'])
        if orderbook and len(orderbook) > 0:
            ob = orderbook[0]
            logger.info(f"{ob['market']} 호가 정보:")
            
            for i, (ask, bid) in enumerate(zip(ob['orderbook_units'][:3], ob['orderbook_units'][:3])):
                logger.info(f"  매도 {i+1}: {ask['ask_price']:,} KRW (수량: {ask['ask_size']})")
                logger.info(f"  매수 {i+1}: {bid['bid_price']:,} KRW (수량: {bid['bid_size']})")
        else:
            logger.error("호가 정보 조회 실패")
    
    except Exception as e:
        logger.error(f"호가 정보 조회 중 오류: {e}")

def main():
    logger.info("업비트 API 연결 테스트를 시작합니다.")
    logger.info(f"서버 URL: {config.server_url}")
    
    check_market_data()
    print()
    
    check_account_info()
    print()
    
    check_orderbook()
    print()
    
    logger.info("테스트 완료!")

if __name__ == "__main__":
    main()