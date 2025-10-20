import requests
import time
from typing import Dict, List, Optional, Any
from src.config import config
from src.utils.signature import generate_jwt_token
from src.logger import logger

class UpbitAPI:
    def __init__(self):
        self.server_url = config.server_url
        self.access_key = config.access_key
        self.secret_key = config.secret_key
        
    def _make_request(self, method: str, endpoint: str, params: Optional[Dict] = None, 
                     need_auth: bool = False) -> Optional[Dict]:
        url = f"{self.server_url}{endpoint}"
        headers = {'Content-Type': 'application/json'}
        
        if need_auth:
            if not config.has_api_keys:
                raise ValueError("API keys are required for authenticated requests")
            headers['Authorization'] = generate_jwt_token(self.access_key, self.secret_key, params)
        
        try:
            if method.upper() == 'GET':
                response = requests.get(url, params=params, headers=headers)
            elif method.upper() == 'POST':
                response = requests.post(url, json=params, headers=headers)
            elif method.upper() == 'DELETE':
                response = requests.delete(url, json=params, headers=headers)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")
            
            response.raise_for_status()
            return response.json()
            
        except requests.exceptions.RequestException as e:
            logger.error(f"API request failed: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Response content: {e.response.text}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            return None

    def get_accounts(self) -> Optional[List[Dict]]:
        return self._make_request('GET', '/v1/accounts', need_auth=True)

    def get_ticker(self, markets: List[str]) -> Optional[List[Dict]]:
        params = {'markets': ','.join(markets)}
        return self._make_request('GET', '/v1/ticker', params=params)

    def get_markets(self) -> Optional[List[Dict]]:
        return self._make_request('GET', '/v1/market/all', params={'isDetails': 'false'})

    def get_orderbook(self, markets: List[str]) -> Optional[List[Dict]]:
        params = {'markets': ','.join(markets)}
        return self._make_request('GET', '/v1/orderbook', params=params)

    def get_orders(self, market: Optional[str] = None, state: str = 'wait') -> Optional[List[Dict]]:
        params = {'state': state}
        if market:
            params['market'] = market
        return self._make_request('GET', '/v1/orders', params=params, need_auth=True)

    def place_order(self, market: str, side: str, volume: Optional[str] = None, 
                   price: Optional[str] = None, ord_type: str = 'limit') -> Optional[Dict]:
        params = {
            'market': market,
            'side': side,
            'ord_type': ord_type
        }
        
        if ord_type == 'limit':
            if not volume or not price:
                raise ValueError("Volume and price are required for limit orders")
            params['volume'] = volume
            params['price'] = price
        elif side == 'bid':  # 시장가 매수
            params['ord_type'] = 'price'  # 업비트 시장가 매수는 ord_type='price'
            if not price:
                raise ValueError("Price (KRW amount) is required for market buy orders")
            params['price'] = price
        elif side == 'ask':  # 시장가 매도
            params['ord_type'] = 'market'  # 업비트 시장가 매도는 ord_type='market'
            if not volume:
                raise ValueError("Volume is required for market sell orders")
            params['volume'] = volume
        
        return self._make_request('POST', '/v1/orders', params=params, need_auth=True)

    def cancel_order(self, uuid: str) -> Optional[Dict]:
        params = {'uuid': uuid}
        return self._make_request('DELETE', '/v1/order', params=params, need_auth=True)

    def get_order(self, uuid: str) -> Optional[Dict]:
        params = {'uuid': uuid}
        return self._make_request('GET', '/v1/order', params=params, need_auth=True)

    def get_candles_minutes(self, market: str, unit: int = 1, count: int = 1) -> Optional[List[Dict]]:
        params = {
            'market': market,
            'count': count
        }
        return self._make_request('GET', f'/v1/candles/minutes/{unit}', params=params)

upbit_api = UpbitAPI()