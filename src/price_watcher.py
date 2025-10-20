import time
import threading
from datetime import datetime
from typing import Dict, List, Optional
from src.upbit_api import upbit_api
from src.logger import logger

class PriceWatcher:
    def __init__(self, markets: List[str], update_interval: float = 1.0):
        self.markets = markets
        self.update_interval = update_interval
        self.running = False
        self.prices = {}
        self.price_history = {}
        self.monitor_thread = None
        
    def start_monitoring(self):
        if self.running:
            logger.warning("가격 모니터링이 이미 실행 중입니다.")
            return
        
        self.running = True
        self.monitor_thread = threading.Thread(target=self._monitor_prices, daemon=True)
        self.monitor_thread.start()
        logger.info(f"가격 모니터링 시작: {self.markets}")
    
    def stop_monitoring(self):
        self.running = False
        if self.monitor_thread:
            self.monitor_thread.join()
        logger.info("가격 모니터링 중지")
    
    def _monitor_prices(self):
        while self.running:
            try:
                tickers = upbit_api.get_ticker(self.markets)
                if tickers:
                    for ticker in tickers:
                        market = ticker['market']
                        current_price = float(ticker['trade_price'])
                        change_rate = float(ticker['change_rate'])
                        change_price = float(ticker['change_price'])
                        
                        # 이전 가격과 비교
                        prev_price = self.prices.get(market)
                        self.prices[market] = current_price
                        
                        # 가격 히스토리 저장 (최근 100개)
                        if market not in self.price_history:
                            self.price_history[market] = []
                        
                        self.price_history[market].append({
                            'timestamp': datetime.now(),
                            'price': current_price,
                            'change_rate': change_rate,
                            'change_price': change_price
                        })
                        
                        if len(self.price_history[market]) > 100:
                            self.price_history[market].pop(0)
                        
                        # 가격 변동 출력
                        if prev_price:
                            direction = "↑" if current_price > prev_price else "↓" if current_price < prev_price else "→"
                            change_percent = f"{change_rate * 100:+.2f}%"
                        else:
                            direction = "→"
                            change_percent = f"{change_rate * 100:+.2f}%"
                        
                        print(f"\r{market}: {current_price:,} KRW {direction} ({change_percent})", end=" " * 20, flush=True)
                
                time.sleep(self.update_interval)
                
            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error(f"가격 모니터링 중 오류: {e}")
                time.sleep(self.update_interval)
    
    def get_current_price(self, market: str) -> Optional[float]:
        return self.prices.get(market)
    
    def get_price_history(self, market: str, limit: int = 10) -> List[Dict]:
        history = self.price_history.get(market, [])
        return history[-limit:] if history else []
    
    def display_current_prices(self):
        if not self.prices:
            print("아직 가격 정보가 없습니다.")
            return
        
        print("\n=== 현재 가격 정보 ===")
        for market, price in self.prices.items():
            print(f"{market}: {price:,} KRW")
        print()
    
    def display_price_summary(self):
        if not self.price_history:
            print("가격 히스토리가 없습니다.")
            return
        
        print("\n=== 가격 요약 ===")
        for market in self.markets:
            history = self.price_history.get(market, [])
            if history:
                current = history[-1]
                if len(history) > 1:
                    start = history[0]
                    change = current['price'] - start['price']
                    change_percent = (change / start['price']) * 100
                    print(f"{market}: {current['price']:,} KRW (세션 변동: {change:+,.0f} KRW, {change_percent:+.2f}%)")
                else:
                    print(f"{market}: {current['price']:,} KRW")
        print()

class MultiMarketWatcher:
    def __init__(self):
        self.watchers = {}
        
    def add_market(self, market: str, update_interval: float = 1.0):
        if market not in self.watchers:
            self.watchers[market] = PriceWatcher([market], update_interval)
            
    def start_all(self):
        for watcher in self.watchers.values():
            watcher.start_monitoring()
            
    def stop_all(self):
        for watcher in self.watchers.values():
            watcher.stop_monitoring()
            
    def get_price(self, market: str) -> Optional[float]:
        watcher = self.watchers.get(market)
        return watcher.get_current_price(market) if watcher else None