#!/usr/bin/env python3

import sys
import os
import threading
import time
from typing import List, Optional

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.upbit_api import upbit_api
from src.trader import trader
from src.price_watcher import PriceWatcher
from src.logger import logger

class ManualTrader:
    def __init__(self):
        self.price_watcher = None
        self.monitored_markets = ['KRW-BTC', 'KRW-ETH', 'KRW-ADA', 'KRW-DOT', 'KRW-SOL','KRW-ZBT']
        self.running = False
        
    def start_price_monitoring(self):
        """실시간 가격 모니터링 시작"""
        if self.price_watcher:
            self.price_watcher.stop_monitoring()
        
        self.price_watcher = PriceWatcher(self.monitored_markets, update_interval=1.0)
        self.price_watcher.start_monitoring()
        print(f"실시간 가격 모니터링 시작: {', '.join(self.monitored_markets)}")
        print("가격 업데이트가 화면에 표시됩니다...")
        print()
    
    def stop_price_monitoring(self):
        """가격 모니터링 중지"""
        if self.price_watcher:
            self.price_watcher.stop_monitoring()
            self.price_watcher = None
        print("\\n가격 모니터링이 중지되었습니다.")
    
    def display_help(self):
        """도움말 출력"""
        print("\\n=== 수동 거래 명령어 ===")
        print("기본 형식: [명령어] [종목] [수량/금액] [옵션]")
        print()
        print("매수 명령어:")
        print("  buy BTC 50000 market        # BTC를 50,000원 시장가 매수")
        print("  buy ETH 0.1 100000          # ETH 0.1개를 100,000원 지정가 매수")
        print()
        print("매도 명령어:")
        print("  sell BTC 0.001 market       # BTC 0.001개 시장가 매도")
        print("  sell ETH 0.1 150000         # ETH 0.1개를 150,000원 지정가 매도")
        print()
        print("기타 명령어:")
        print("  cancel [UUID]               # 주문 취소")
        print("  balance                     # 잔고 조회")
        print("  orders                      # 미체결 주문 조회")
        print("  price                       # 현재 가격 표시")
        print("  markets                     # 모니터링 종목 변경")
        print("  help                        # 도움말")
        print("  quit                        # 프로그램 종료")
        print()
    
    def show_balance(self):
        """계좌 잔고 조회"""
        try:
            accounts = upbit_api.get_accounts()
            if not accounts:
                print("잔고 조회에 실패했습니다.")
                return
            
            print("\\n=== 계좌 잔고 ===")
            for account in accounts:
                balance = float(account['balance'])
                locked = float(account['locked'])
                if balance > 0 or locked > 0:
                    print(f"{account['currency']:>6}: 잔고 {balance:>12.8f}, 사용중 {locked:>12.8f}")
            print()
        
        except Exception as e:
            print(f"잔고 조회 중 오류: {e}")
    
    def show_orders(self):
        """미체결 주문 조회"""
        try:
            orders = upbit_api.get_orders()
            if not orders:
                print("미체결 주문이 없습니다.")
                return
            
            print("\\n=== 미체결 주문 ===")
            for order in orders:
                market = order['market']
                side = "매수" if order['side'] == 'bid' else "매도"
                ord_type = "시장가" if order['ord_type'] == 'market' else "지정가"
                volume = float(order['volume'])
                price = float(order['price']) if order['price'] else 0
                remaining_volume = float(order['remaining_volume'])
                
                print(f"UUID: {order['uuid']}")
                print(f"  {market} {side} {ord_type}")
                print(f"  수량: {volume}, 잔여: {remaining_volume}")
                if price > 0:
                    print(f"  가격: {price:,} KRW")
                print()
        
        except Exception as e:
            print(f"주문 조회 중 오류: {e}")
    
    def show_current_prices(self):
        """현재 가격 표시"""
        if self.price_watcher:
            self.price_watcher.display_current_prices()
        else:
            print("가격 모니터링이 실행되지 않았습니다.")
    
    def change_monitored_markets(self):
        """모니터링 종목 변경"""
        try:
            markets = upbit_api.get_markets()
            if not markets:
                print("마켓 정보를 가져올 수 없습니다.")
                return
            
            krw_markets = [m['market'] for m in markets if m['market'].startswith('KRW-')][:20]
            
            print("\\n사용 가능한 KRW 마켓 (상위 20개):")
            for i, market in enumerate(krw_markets):
                marker = " *" if market in self.monitored_markets else ""
                print(f"{i+1:2d}. {market}{marker}")
            
            print(f"\\n현재 모니터링 중: {', '.join(self.monitored_markets)}")
            print("새로운 종목들을 입력하세요 (쉼표로 구분, 예: KRW-BTC,KRW-ETH):")
            
            user_input = input("> ").strip()
            if user_input:
                new_markets = [m.strip().upper() for m in user_input.split(',')]
                valid_markets = [m for m in new_markets if m in krw_markets]
                
                if valid_markets:
                    self.monitored_markets = valid_markets
                    print(f"모니터링 종목이 변경되었습니다: {', '.join(self.monitored_markets)}")
                    
                    # 가격 모니터링 재시작
                    if self.price_watcher:
                        self.stop_price_monitoring()
                        time.sleep(1)
                        self.start_price_monitoring()
                else:
                    print("유효한 종목이 없습니다.")
        
        except Exception as e:
            print(f"종목 변경 중 오류: {e}")
    
    def parse_command(self, command: str) -> bool:
        """명령어 파싱 및 실행"""
        try:
            parts = command.strip().split()
            if not parts:
                return True
            
            cmd = parts[0].lower()
            
            if cmd == 'quit' or cmd == 'exit':
                return False
            
            elif cmd == 'help':
                self.display_help()
            
            elif cmd == 'balance':
                self.show_balance()
            
            elif cmd == 'orders':
                self.show_orders()
            
            elif cmd == 'price':
                self.show_current_prices()
            
            elif cmd == 'markets':
                self.change_monitored_markets()
            
            elif cmd == 'buy':
                if len(parts) < 4:
                    print("사용법: buy [종목] [수량/금액] [market/가격]")
                    return True
                
                symbol = parts[1].upper()
                market = f"KRW-{symbol}" if not symbol.startswith('KRW-') else symbol
                amount = float(parts[2])
                order_type = parts[3].lower()
                
                if order_type == 'market':
                    result = trader.market_buy(market, amount)
                    if result:
                        print(f"시장가 매수 주문 완료: {result['uuid']}")
                else:
                    price = float(order_type)
                    result = trader.limit_buy(market, amount, price)
                    if result:
                        print(f"지정가 매수 주문 완료: {result['uuid']}")
            
            elif cmd == 'sell':
                if len(parts) < 4:
                    print("사용법: sell [종목] [수량] [market/가격]")
                    return True
                
                symbol = parts[1].upper()
                market = f"KRW-{symbol}" if not symbol.startswith('KRW-') else symbol
                volume = float(parts[2])
                order_type = parts[3].lower()
                
                if order_type == 'market':
                    result = trader.market_sell(market, volume)
                    if result:
                        print(f"시장가 매도 주문 완료: {result['uuid']}")
                else:
                    price = float(order_type)
                    result = trader.limit_sell(market, volume, price)
                    if result:
                        print(f"지정가 매도 주문 완료: {result['uuid']}")
            
            elif cmd == 'cancel':
                if len(parts) < 2:
                    print("사용법: cancel [UUID]")
                    return True
                
                uuid = parts[1]
                success = trader.cancel_order(uuid)
                if success:
                    print(f"주문 취소 완료: {uuid}")
                else:
                    print(f"주문 취소 실패: {uuid}")
            
            else:
                print(f"알 수 없는 명령어: {cmd}")
                print("'help' 명령어로 사용법을 확인하세요.")
        
        except ValueError as e:
            print(f"잘못된 입력 형식: {e}")
        except Exception as e:
            print(f"명령어 실행 중 오류: {e}")
        
        return True
    
    def run(self):
        """메인 실행 루프"""
        print("=== 업비트 수동 거래 시스템 ===")
        print("실시간 가격 모니터링과 수동 주문을 지원합니다.")
        print("'help' 명령어로 사용법을 확인하세요.")
        print()
        
        # 가격 모니터링 시작
        self.start_price_monitoring()
        self.running = True
        
        try:
            while self.running:
                try:
                    print("\\n명령어를 입력하세요 (help: 도움말, quit: 종료):")
                    command = input("> ").strip()
                    
                    if not self.parse_command(command):
                        break
                        
                except KeyboardInterrupt:
                    print("\\n\\n프로그램을 종료합니다...")
                    break
                except EOFError:
                    print("\\n\\n프로그램을 종료합니다...")
                    break
        
        finally:
            self.stop_price_monitoring()
            print("수동 거래 시스템이 종료되었습니다.")

def main():
    manual_trader = ManualTrader()
    manual_trader.run()

if __name__ == "__main__":
    main()