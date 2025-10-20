#!/usr/bin/env python3
"""
멀티 마켓 자동매매 실행기

여러 코인을 동시에 자동매매하는 스크립트입니다.
각 마켓별로 별도 프로세스로 실행하여 독립적인 상태 관리가 가능합니다.
"""

import subprocess
import sys
import os
import time
import signal
from typing import List, Dict
import threading

class MultiMarketRunner:
    def __init__(self, markets: List[str], krw_per_market: float, trading_mode: str = "DRYRUN"):
        self.markets = markets
        self.krw_per_market = krw_per_market
        self.trading_mode = trading_mode.upper()
        self.processes = {}
        self.running = True
        
        print(f"멀티 마켓 자동매매 설정:")
        print(f"  대상 마켓: {', '.join(markets)}")
        print(f"  마켓당 금액: {krw_per_market:,}원")
        print(f"  총 투자금액: {len(markets) * krw_per_market:,}원")
        print(f"  거래 모드: {trading_mode}")
        print()
    
    def start_market_process(self, market: str) -> subprocess.Popen:
        """개별 마켓 프로세스 시작"""
        cmd = [
            sys.executable, "src/runner.py",
            "--market", market,
            "--krw", str(self.krw_per_market),
            "--mode", self.trading_mode
        ]
        
        print(f"🚀 {market} 자동매매 시작 (PID: 대기중...)")
        
        # 프로세스 시작
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            bufsize=1
        )
        
        print(f"🚀 {market} 자동매매 시작 (PID: {process.pid})")
        
        # 출력 모니터링 스레드 시작
        output_thread = threading.Thread(
            target=self._monitor_process_output,
            args=(market, process),
            daemon=True
        )
        output_thread.start()
        
        return process
    
    def _monitor_process_output(self, market: str, process: subprocess.Popen):
        """프로세스 출력 모니터링"""
        try:
            for line in iter(process.stdout.readline, ''):
                if line.strip():
                    timestamp = time.strftime("%H:%M:%S")
                    print(f"[{timestamp}] {market}: {line.strip()}")
                
                if not self.running:
                    break
        except Exception as e:
            print(f"❌ {market} 출력 모니터링 오류: {e}")
    
    def start_all_markets(self):
        """모든 마켓 프로세스 시작"""
        print("=" * 60)
        print("멀티 마켓 자동매매 시작")
        print("=" * 60)
        
        for market in self.markets:
            try:
                process = self.start_market_process(market)
                self.processes[market] = process
                time.sleep(2)  # 프로세스 시작 간격
            except Exception as e:
                print(f"❌ {market} 시작 실패: {e}")
        
        print(f"\n✅ {len(self.processes)}개 마켓 자동매매 실행 중...")
        print("Ctrl+C로 모든 프로세스를 중지할 수 있습니다.\n")
    
    def stop_all_markets(self):
        """모든 마켓 프로세스 중지"""
        print("\n🛑 모든 자동매매 프로세스를 중지합니다...")
        self.running = False
        
        for market, process in self.processes.items():
            try:
                if process.poll() is None:  # 프로세스가 아직 실행 중
                    print(f"🛑 {market} 프로세스 중지 중...")
                    process.terminate()
                    
                    # 3초 대기 후 강제 종료
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        print(f"⚠️  {market} 강제 종료")
                        process.kill()
                        process.wait()
                    
                    print(f"✅ {market} 프로세스 중지 완료")
            except Exception as e:
                print(f"❌ {market} 중지 중 오류: {e}")
        
        print("모든 프로세스가 중지되었습니다.")
    
    def monitor_all_processes(self):
        """모든 프로세스 상태 모니터링"""
        try:
            while self.running:
                time.sleep(10)  # 10초마다 상태 확인
                
                # 종료된 프로세스 확인
                for market, process in list(self.processes.items()):
                    if process.poll() is not None:
                        return_code = process.returncode
                        if return_code == 0:
                            print(f"✅ {market} 정상 종료 (코드: {return_code})")
                        else:
                            print(f"❌ {market} 비정상 종료 (코드: {return_code})")
                        
                        # 자동 재시작 (선택적)
                        # if self.running:
                        #     print(f"🔄 {market} 재시작 중...")
                        #     new_process = self.start_market_process(market)
                        #     self.processes[market] = new_process
                
                # 모든 프로세스가 종료되었으면 중단
                if not any(p.poll() is None for p in self.processes.values()):
                    print("모든 프로세스가 종료되었습니다.")
                    break
        
        except KeyboardInterrupt:
            print("\nCtrl+C 감지됨. 프로세스를 중지합니다.")
        finally:
            self.stop_all_markets()
    
    def run(self):
        """메인 실행 함수"""
        # 시그널 핸들러 등록
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        try:
            self.start_all_markets()
            self.monitor_all_processes()
        except Exception as e:
            print(f"❌ 실행 중 오류: {e}")
        finally:
            self.stop_all_markets()
    
    def _signal_handler(self, signum, frame):
        """시그널 핸들러"""
        print(f"\n시그널 {signum} 수신. 종료 중...")
        self.running = False

def main():
    """메인 함수"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Multi-Market Automated Trading")
    parser.add_argument("--total-krw", type=float, default=100000, help="Total KRW amount (default: 100000)")
    parser.add_argument("--markets", type=str, default="KRW-BTC,KRW-ETH,KRW-XRP,KRW-SOL", help="Markets to trade (comma-separated)")
    parser.add_argument("--mode", type=str, default="DRYRUN", choices=["DRYRUN", "LIVE"], help="Trading mode")
    
    args = parser.parse_args()
    
    # 마켓 파싱
    markets = [m.strip().upper() for m in args.markets.split(',')]
    krw_per_market = args.total_krw / len(markets)
    
    print("=" * 60)
    print("🤖 업비트 멀티 마켓 자동매매 시스템")
    print("=" * 60)
    
    # 설정 확인
    if args.mode == "LIVE":
        print("⚠️  WARNING: LIVE 모드로 실거래를 시작합니다!")
        print(f"총 투자금액: {args.total_krw:,}원")
        print(f"대상 마켓: {', '.join(markets)}")
        print(f"마켓당 금액: {krw_per_market:,}원")
        print()
        
        confirm = input("계속하시겠습니까? (YES 입력): ").strip()
        if confirm != "YES":
            print("취소되었습니다.")
            return
    
    # 멀티 마켓 러너 실행
    runner = MultiMarketRunner(markets, krw_per_market, args.mode)
    runner.run()

if __name__ == "__main__":
    main()