import time
import logging
from typing import Optional, Dict, Tuple
from decimal import Decimal, ROUND_DOWN
from datetime import datetime
from src.upbit_api import upbit_api
from src.logger import logger

# Order 전용 로거 설정
order_logger = logging.getLogger('order_logger')
order_handler = logging.FileHandler('logs/orders.log', encoding='utf-8')
order_formatter = logging.Formatter('%(asctime)s - ORDER - %(message)s')
order_handler.setFormatter(order_formatter)
order_logger.addHandler(order_handler)
order_logger.setLevel(logging.INFO)

class UpbitTrader:
    def __init__(self):
        self.api = upbit_api
        self.min_order_amounts = {
            'KRW-BTC': 5000,
            'KRW-ETH': 5000,
            'default': 5000
        }
    
    def get_balance(self, currency: str) -> Tuple[float, float]:
        try:
            accounts = self.api.get_accounts()
            if not accounts:
                return 0.0, 0.0
            
            for account in accounts:
                if account['currency'] == currency:
                    balance = float(account['balance'])
                    locked = float(account['locked'])
                    return balance, locked
            
            return 0.0, 0.0
        
        except Exception as e:
            logger.error(f"Failed to get balance for {currency}: {e}")
            return 0.0, 0.0
    
    def get_current_price(self, market: str) -> Optional[float]:
        try:
            ticker = self.api.get_ticker([market])
            if ticker and len(ticker) > 0:
                return float(ticker[0]['trade_price'])
            return None
        
        except Exception as e:
            logger.error(f"Failed to get current price for {market}: {e}")
            return None
    
    def calculate_buy_amount(self, market: str, krw_amount: float) -> Optional[Tuple[float, float]]:
        try:
            current_price = self.get_current_price(market)
            if not current_price:
                logger.error(f"Could not get current price for {market}")
                return None
            
            min_amount = self.min_order_amounts.get(market, self.min_order_amounts['default'])
            if krw_amount < min_amount:
                logger.error(f"Order amount {krw_amount} is less than minimum {min_amount}")
                return None
            
            volume = krw_amount / current_price
            volume = float(Decimal(str(volume)).quantize(Decimal('0.00000001'), rounding=ROUND_DOWN))
            
            return volume, current_price
        
        except Exception as e:
            logger.error(f"Failed to calculate buy amount for {market}: {e}")
            return None
    
    def market_buy(self, market: str, krw_amount: float, confirm: bool = True) -> Optional[Dict]:
        try:
            krw_balance, _ = self.get_balance('KRW')
            if krw_balance < krw_amount:
                logger.error(f"Insufficient KRW balance. Available: {krw_balance}, Required: {krw_amount}")
                return None
            
            min_amount = self.min_order_amounts.get(market, self.min_order_amounts['default'])
            if krw_amount < min_amount:
                logger.error(f"Order amount {krw_amount} is less than minimum {min_amount}")
                return None
            
            # 확인 메시지
            if confirm:
                print(f"\n=== 주문 확인 ===")
                print(f"종목: {market}")
                print(f"주문 타입: 시장가 매수")
                print(f"주문 금액: {krw_amount:,} KRW")
                print(f"사용 가능 잔고: {krw_balance:,} KRW")
                response = input("주문을 실행하시겠습니까? (yes/y): ").lower().strip()
                if response not in ['yes', 'y']:
                    print("주문이 취소되었습니다.")
                    return None
            
            logger.info(f"Placing buy market order for {market} with {krw_amount} KRW")
            order_logger.info(f"MARKET_BUY - {market} - {krw_amount} KRW")
            
            result = self.api.place_order(
                market=market,
                side='bid',
                price=str(krw_amount),
                ord_type='price'  # 업비트 시장가 매수는 ord_type='price'
            )
            
            if result:
                logger.info(f"Buy order placed successfully: {result['uuid']}")
                order_logger.info(f"ORDER_SUCCESS - UUID: {result['uuid']} - {market} - MARKET_BUY - {krw_amount} KRW")
            else:
                order_logger.error(f"ORDER_FAILED - {market} - MARKET_BUY - {krw_amount} KRW")
            
            return result
        
        except Exception as e:
            logger.error(f"Failed to place buy order for {market}: {e}")
            return None
    
    def market_sell(self, market: str, volume: float, confirm: bool = True) -> Optional[Dict]:
        try:
            currency = market.split('-')[1]
            available_balance, _ = self.get_balance(currency)
            
            if available_balance < volume:
                logger.error(f"Insufficient {currency} balance. Available: {available_balance}, Required: {volume}")
                return None
            
            volume = float(Decimal(str(volume)).quantize(Decimal('0.00000001'), rounding=ROUND_DOWN))
            current_price = self.get_current_price(market)
            estimated_value = volume * current_price if current_price else 0
            
            # 확인 메시지
            if confirm:
                print(f"\n=== 주문 확인 ===")
                print(f"종목: {market}")
                print(f"주문 타입: 시장가 매도")
                print(f"수량: {volume} {currency}")
                print(f"현재가: {current_price:,} KRW" if current_price else "현재가: 조회 실패")
                print(f"예상 수령 금액: {estimated_value:,} KRW" if current_price else "예상 금액: 계산 불가")
                print(f"사용 가능 잔고: {available_balance} {currency}")
                response = input("주문을 실행하시겠습니까? (yes/y): ").lower().strip()
                if response not in ['yes', 'y']:
                    print("주문이 취소되었습니다.")
                    return None
            
            logger.info(f"Placing sell market order for {market} with {volume} {currency}")
            order_logger.info(f"MARKET_SELL - {market} - {volume} {currency}")
            
            result = self.api.place_order(
                market=market,
                side='ask',
                volume=str(volume),
                ord_type='market'  # 업비트 시장가 매도는 ord_type='market'
            )
            
            if result:
                logger.info(f"Sell order placed successfully: {result['uuid']}")
                order_logger.info(f"ORDER_SUCCESS - UUID: {result['uuid']} - {market} - MARKET_SELL - {volume} {currency}")
            else:
                order_logger.error(f"ORDER_FAILED - {market} - MARKET_SELL - {volume} {currency}")
            
            return result
        
        except Exception as e:
            logger.error(f"Failed to place sell order for {market}: {e}")
            return None
    
    def limit_buy(self, market: str, volume: float, price: float, confirm: bool = True) -> Optional[Dict]:
        try:
            total_cost = volume * price
            krw_balance, _ = self.get_balance('KRW')
            
            if krw_balance < total_cost:
                logger.error(f"Insufficient KRW balance. Available: {krw_balance}, Required: {total_cost}")
                return None
            
            min_amount = self.min_order_amounts.get(market, self.min_order_amounts['default'])
            if total_cost < min_amount:
                logger.error(f"Order amount {total_cost} is less than minimum {min_amount}")
                return None
            
            volume = float(Decimal(str(volume)).quantize(Decimal('0.00000001'), rounding=ROUND_DOWN))
            price = float(Decimal(str(price)).quantize(Decimal('0.01'), rounding=ROUND_DOWN))
            
            # 확인 메시지
            if confirm:
                print(f"\n=== 주문 확인 ===")
                print(f"종목: {market}")
                print(f"주문 타입: 지정가 매수")
                print(f"수량: {volume} {market.split('-')[1]}")
                print(f"가격: {price:,} KRW")
                print(f"총 금액: {total_cost:,} KRW")
                print(f"사용 가능 잔고: {krw_balance:,} KRW")
                response = input("주문을 실행하시겠습니까? (yes/y): ").lower().strip()
                if response not in ['yes', 'y']:
                    print("주문이 취소되었습니다.")
                    return None
            
            logger.info(f"Placing buy limit order for {market}: {volume} at {price}")
            order_logger.info(f"LIMIT_BUY - {market} - {volume} @ {price} KRW")
            
            result = self.api.place_order(
                market=market,
                side='bid',
                volume=str(volume),
                price=str(price),
                ord_type='limit'
            )
            
            if result:
                logger.info(f"Buy limit order placed successfully: {result['uuid']}")
                order_logger.info(f"ORDER_SUCCESS - UUID: {result['uuid']} - {market} - LIMIT_BUY - {volume} @ {price} KRW")
            else:
                order_logger.error(f"ORDER_FAILED - {market} - LIMIT_BUY - {volume} @ {price} KRW")
            
            return result
        
        except Exception as e:
            logger.error(f"Failed to place buy limit order for {market}: {e}")
            return None
    
    def limit_sell(self, market: str, volume: float, price: float, confirm: bool = True) -> Optional[Dict]:
        try:
            currency = market.split('-')[1]
            available_balance, _ = self.get_balance(currency)
            
            if available_balance < volume:
                logger.error(f"Insufficient {currency} balance. Available: {available_balance}, Required: {volume}")
                return None
            
            volume = float(Decimal(str(volume)).quantize(Decimal('0.00000001'), rounding=ROUND_DOWN))
            price = float(Decimal(str(price)).quantize(Decimal('0.01'), rounding=ROUND_DOWN))
            total_value = volume * price
            
            # 확인 메시지
            if confirm:
                print(f"\n=== 주문 확인 ===")
                print(f"종목: {market}")
                print(f"주문 타입: 지정가 매도")
                print(f"수량: {volume} {currency}")
                print(f"가격: {price:,} KRW")
                print(f"예상 수령 금액: {total_value:,} KRW")
                print(f"사용 가능 잔고: {available_balance} {currency}")
                response = input("주문을 실행하시겠습니까? (yes/y): ").lower().strip()
                if response not in ['yes', 'y']:
                    print("주문이 취소되었습니다.")
                    return None
            
            logger.info(f"Placing sell limit order for {market}: {volume} at {price}")
            order_logger.info(f"LIMIT_SELL - {market} - {volume} @ {price} KRW")
            
            result = self.api.place_order(
                market=market,
                side='ask',
                volume=str(volume),
                price=str(price),
                ord_type='limit'
            )
            
            if result:
                logger.info(f"Sell limit order placed successfully: {result['uuid']}")
                order_logger.info(f"ORDER_SUCCESS - UUID: {result['uuid']} - {market} - LIMIT_SELL - {volume} @ {price} KRW")
            else:
                order_logger.error(f"ORDER_FAILED - {market} - LIMIT_SELL - {volume} @ {price} KRW")
            
            return result
        
        except Exception as e:
            logger.error(f"Failed to place sell limit order for {market}: {e}")
            return None
    
    def cancel_order(self, uuid: str, confirm: bool = True) -> bool:
        try:
            order_info = self.get_order_status(uuid)
            if not order_info:
                logger.error(f"주문 정보를 찾을 수 없습니다: {uuid}")
                return False
            
            if confirm:
                print(f"\n=== 주문 취소 확인 ===")
                print(f"주문 UUID: {uuid}")
                print(f"종목: {order_info.get('market', 'N/A')}")
                print(f"주문 타입: {order_info.get('side', 'N/A')} {order_info.get('ord_type', 'N/A')}")
                print(f"상태: {order_info.get('state', 'N/A')}")
                response = input("주문을 취소하시겠습니까? (yes/y): ").lower().strip()
                if response not in ['yes', 'y']:
                    print("취소가 중단되었습니다.")
                    return False
            
            result = self.api.cancel_order(uuid)
            if result:
                logger.info(f"Order {uuid} cancelled successfully")
                order_logger.info(f"ORDER_CANCELLED - UUID: {uuid} - {order_info.get('market', 'N/A')}")
                return True
            return False
        
        except Exception as e:
            logger.error(f"Failed to cancel order {uuid}: {e}")
            order_logger.error(f"CANCEL_FAILED - UUID: {uuid} - Error: {e}")
            return False
    
    def get_order_status(self, uuid: str) -> Optional[Dict]:
        try:
            return self.api.get_order(uuid)
        except Exception as e:
            logger.error(f"Failed to get order status for {uuid}: {e}")
            return None

    # 레거시 메서드 호환성 유지
    def buy_market_order(self, market: str, krw_amount: float) -> Optional[Dict]:
        return self.market_buy(market, krw_amount, confirm=False)
    
    def sell_market_order(self, market: str, volume: float) -> Optional[Dict]:
        """매도 주문 안전 버전 (수량 검증 + 잔고 자동확인)"""
        try:
            currency = market.split('-')[1]
            balance, _ = self.get_balance(currency)

            # ⚠️ 안전검사 1: volume이 None이거나 0 이하인 경우
            if not volume or volume <= 0:
                logger.warning(f"[Safety Check] 매도 수량이 0 또는 None입니다. 실시간 잔고 재확인 중... ({market})")
                time.sleep(1.5)
                balance, _ = self.get_balance(currency)
                if balance <= 0:
                    logger.error(f"[Safety Stop] 매도 가능한 {currency} 잔고가 없습니다. 주문 중단.")
                    return None
                volume = balance  # 실시간 잔고로 대체

            # ⚠️ 안전검사 2: 너무 작은 단위의 매도 방지 (거래 최소단위 미만)
            if volume < 0.00000001:
                logger.error(f"[Safety Stop] 매도 수량({volume})이 최소 단위 미만입니다. ({market})")
                return None

            # 매도 실행
            logger.info(f"Placing safe sell market order for {market} with {volume} {currency}")
            order_logger.info(f"SAFE_MARKET_SELL - {market} - {volume} {currency}")

            result = self.api.place_order(
                market=market,
                side='ask',
                volume=str(volume),
                ord_type='market'
            )

            if result:
                logger.info(f"✅ Safe sell order placed successfully: {result['uuid']}")
                order_logger.info(f"SAFE_ORDER_SUCCESS - UUID: {result['uuid']} - {market} - MARKET_SELL - {volume} {currency}")
            else:
                logger.error(f"❌ Safe sell order failed for {market}")
                order_logger.error(f"SAFE_ORDER_FAILED - {market} - MARKET_SELL - {volume} {currency}")

            return result

        except Exception as e:
            logger.error(f"[Safety Exception] 매도 주문 중 예외 발생: {e}")
            return None

    
    def buy_limit_order(self, market: str, volume: float, price: float) -> Optional[Dict]:
        return self.limit_buy(market, volume, price, confirm=False)
    
    def sell_limit_order(self, market: str, volume: float, price: float) -> Optional[Dict]:
        return self.limit_sell(market, volume, price, confirm=False)

trader = UpbitTrader()
