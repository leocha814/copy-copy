"""
📊 실시간 성능 모니터링 및 적응형 파라미터 조정 시스템

기능:
1. 거래 결과 CSV 로깅
2. 실시간 성능 지표 계산 (승률, 평균 수익률, 슬리피지 등)
3. 적응형 수익률 조정을 위한 피드백 루프
4. 자동 백테스트 및 파라미터 최적화
"""

import os
import csv
import time
import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from src.logger import logger

@dataclass
class TradeResult:
    """거래 결과 데이터 클래스"""
    timestamp: float
    market: str
    entry_strategy: str
    entry_price: float
    exit_price: float
    entry_time: float
    exit_time: float
    profit_rate: float
    profit_krw: float
    hold_time: float
    exit_reason: str
    entry_rsi: float
    exit_rsi: float
    volume_ratio: Optional[float] = None
    slippage: Optional[float] = None  # 실제 체결가 vs 예상 체결가 차이

@dataclass
class PerformanceMetrics:
    """성능 지표 데이터 클래스"""
    total_trades: int
    win_trades: int
    loss_trades: int
    win_rate: float
    average_profit_rate: float
    average_loss_rate: float
    profit_factor: float  # 총 수익 / 총 손실
    max_drawdown: float
    daily_trades: float
    avg_hold_time: float
    best_strategy: str
    slippage_estimate: float
    sharpe_ratio: Optional[float] = None

class PerformanceMonitor:
    """실시간 성능 모니터링 및 적응형 조정"""
    
    def __init__(self, log_dir: str = "logs"):
        self.log_dir = log_dir
        self.csv_file = os.path.join(log_dir, "performance_log.csv")
        self.metrics_file = os.path.join(log_dir, "daily_metrics.csv")
        
        # CSV 헤더 초기화
        self._initialize_csv_files()
        
        # 성능 데이터 캐시
        self.trade_cache = []
        self.last_metrics_update = 0
        self.metrics_update_interval = 300  # 5분마다 메트릭 업데이트
        
        # 적응형 조정 설정
        self.min_trades_for_adjustment = 20  # 최소 20회 거래 후 조정
        self.adjustment_check_interval = 3600  # 1시간마다 조정 검토
        self.last_adjustment_check = 0
    
    def _initialize_csv_files(self):
        """CSV 파일 헤더 초기화"""
        os.makedirs(self.log_dir, exist_ok=True)
        
        # 거래 결과 CSV 헤더
        if not os.path.exists(self.csv_file):
            trade_headers = list(TradeResult.__annotations__.keys())
            with open(self.csv_file, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(trade_headers)
        
        # 일일 메트릭 CSV 헤더
        if not os.path.exists(self.metrics_file):
            metrics_headers = ['date'] + list(PerformanceMetrics.__annotations__.keys())
            with open(self.metrics_file, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(metrics_headers)
    
    def log_trade(self, trade_result: TradeResult):
        """거래 결과를 CSV에 로깅"""
        try:
            # 🚨 1️⃣ 이상치 필터링
            if trade_result.entry_price <= 0 or not np.isfinite(trade_result.profit_rate):
                logger.warning(f"[Anomaly] Invalid entry_price or profit_rate skipped: "
                            f"entry_price={trade_result.entry_price}, profit_rate={trade_result.profit_rate}")
                return
            
            # 🚨 2️⃣ 극단적인 수익률 필터링 (±1000% 이상은 기록 제외)
            if abs(trade_result.profit_rate) > 10:  # ±1000% 초과
                logger.warning(f"[Anomaly] Unrealistic profit_rate={trade_result.profit_rate:.2%}, skipping record.")
                return

            # CSV 파일에 추가
            with open(self.csv_file, 'a', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(list(asdict(trade_result).values()))
            
            # 캐시에도 추가
            self.trade_cache.append(trade_result)
            if len(self.trade_cache) > 1000:
                self.trade_cache = self.trade_cache[-1000:]
            
            logger.info(f"📊 거래 기록: {trade_result.market} {trade_result.entry_strategy} "
                    f"{trade_result.profit_rate:.2%} ({trade_result.exit_reason})")
            
            # 메트릭 주기적 업데이트
            current_time = time.time()
            if current_time - self.last_metrics_update >= self.metrics_update_interval:
                self._update_metrics()
                self.last_metrics_update = current_time
        
        except Exception as e:
            logger.error(f"거래 로깅 실패: {e}")

    
    def calculate_metrics(self, days: int = 1) -> PerformanceMetrics:
        """지정 기간 동안의 성능 지표 계산"""
        try:
            # 최근 N일 데이터 로드
            cutoff_time = time.time() - (days * 24 * 3600)
            
            if os.path.exists(self.csv_file):
                df = pd.read_csv(self.csv_file)
                if not df.empty:
                    df = df[df['timestamp'] >= cutoff_time]
                else:
                    df = pd.DataFrame()
            else:
                df = pd.DataFrame()
            
            # 캐시 데이터도 포함
            cache_data = [asdict(trade) for trade in self.trade_cache 
                         if trade.timestamp >= cutoff_time]
            if cache_data:
                cache_df = pd.DataFrame(cache_data)
                df = pd.concat([df, cache_df]).drop_duplicates(subset=['timestamp', 'market'])
            
            if df.empty:
                return self._create_empty_metrics()
            
            # 메트릭 계산
            total_trades = len(df)
            win_trades = len(df[df['profit_rate'] > 0])
            loss_trades = len(df[df['profit_rate'] <= 0])
            
            win_rate = win_trades / total_trades if total_trades > 0 else 0
            average_profit_rate = df['profit_rate'].mean()
            
            # 승리/패배 평균 분리
            win_df = df[df['profit_rate'] > 0]
            loss_df = df[df['profit_rate'] <= 0]
            average_win_rate = win_df['profit_rate'].mean() if not win_df.empty else 0
            average_loss_rate = loss_df['profit_rate'].mean() if not loss_df.empty else 0
            
            # Profit Factor (총 수익 / 총 손실)
            total_profit = win_df['profit_rate'].sum() if not win_df.empty else 0
            total_loss = abs(loss_df['profit_rate'].sum()) if not loss_df.empty else 0.001
            profit_factor = total_profit / total_loss
            
            # 최대 낙폭 계산
            cumulative_returns = (1 + df['profit_rate']).cumprod()
            running_max = cumulative_returns.expanding().max()
            drawdown = (cumulative_returns - running_max) / running_max
            max_drawdown = drawdown.min()
            
            # 일일 거래 횟수
            daily_trades = total_trades / days
            
            # 평균 보유 시간
            avg_hold_time = df['hold_time'].mean()
            
            # 최고 성과 전략
            strategy_performance = df.groupby('entry_strategy')['profit_rate'].mean()
            best_strategy = strategy_performance.idxmax() if not strategy_performance.empty else "unknown"
            
            # 슬리피지 추정
            slippage_estimate = df['slippage'].mean() if 'slippage' in df.columns else 0
            
            # Sharpe Ratio (연환산)
            if len(df) > 1:
                daily_returns = df['profit_rate']
                sharpe_ratio = (daily_returns.mean() / daily_returns.std()) * np.sqrt(365) if daily_returns.std() > 0 else 0
            else:
                sharpe_ratio = 0
            
            return PerformanceMetrics(
                total_trades=total_trades,
                win_trades=win_trades,
                loss_trades=loss_trades,
                win_rate=win_rate,
                average_profit_rate=average_profit_rate,
                average_loss_rate=average_loss_rate,
                profit_factor=profit_factor,
                max_drawdown=max_drawdown,
                daily_trades=daily_trades,
                avg_hold_time=avg_hold_time,
                best_strategy=best_strategy,
                slippage_estimate=slippage_estimate,
                sharpe_ratio=sharpe_ratio
            )
            
        except Exception as e:
            logger.error(f"메트릭 계산 실패: {e}")
            return self._create_empty_metrics()
    
    def _create_empty_metrics(self) -> PerformanceMetrics:
        """빈 메트릭 객체 생성"""
        return PerformanceMetrics(
            total_trades=0, win_trades=0, loss_trades=0, win_rate=0,
            average_profit_rate=0, average_loss_rate=0, profit_factor=0,
            max_drawdown=0, daily_trades=0, avg_hold_time=0,
            best_strategy="none", slippage_estimate=0, sharpe_ratio=0
        )
    
    def _update_metrics(self):
        """일일 메트릭 업데이트 및 저장"""
        try:
            metrics = self.calculate_metrics(days=1)
            
            # 일일 메트릭 CSV에 저장
            today = datetime.now().strftime('%Y-%m-%d')
            with open(self.metrics_file, 'a', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                row = [today] + list(asdict(metrics).values())
                writer.writerow(row)
            
            logger.info(f"📈 일일 성과: 거래 {metrics.total_trades}회, "
                       f"승률 {metrics.win_rate:.1%}, 평균수익률 {metrics.average_profit_rate:.2%}")
            
        except Exception as e:
            logger.error(f"메트릭 업데이트 실패: {e}")
    
    def get_adaptive_adjustments(self) -> Dict[str, float]:
        """적응형 파라미터 조정 제안 계산"""
        try:
            current_time = time.time()
            
            # 조정 검토 간격 체크
            if current_time - self.last_adjustment_check < self.adjustment_check_interval:
                return {}
            
            self.last_adjustment_check = current_time
            
            # 최근 성과 분석
            metrics = self.calculate_metrics(days=1)
            
            if metrics.total_trades < self.min_trades_for_adjustment:
                return {}
            
            adjustments = {}
            
            # 1. 승률 기반 익절/손절 조정
            if metrics.win_rate < 0.45:  # 승률 45% 미만
                # 익절 상향, 손절 완화
                adjustments['take_profit_increase'] = 0.001  # +0.1%
                adjustments['stop_loss_relax'] = 0.0005     # 손절 완화 +0.05%
                logger.info(f"📊 승률 부족({metrics.win_rate:.1%}) → 익절 상향 조정 제안")
            
            elif metrics.win_rate > 0.65:  # 승률 65% 초과
                # 익절 하향, 손절 강화 (더 자주 매매)
                adjustments['take_profit_decrease'] = 0.0005  # -0.05%
                adjustments['stop_loss_tighten'] = 0.0002    # 손절 강화 -0.02%
                logger.info(f"📊 승률 과도({metrics.win_rate:.1%}) → 익절 하향 조정 제안")
            
            # 2. Profit Factor 기반 조정
            if metrics.profit_factor < 1.2:  # 수익 대비 손실 과도
                adjustments['volume_filter_strengthen'] = 0.1  # 거래량 필터 강화
                logger.info(f"📊 Profit Factor 부족({metrics.profit_factor:.2f}) → 필터 강화 제안")
            
            # 3. 일일 거래 횟수 기반 조정
            if metrics.daily_trades < 5:  # 거래 빈도 부족
                adjustments['signal_sensitivity_increase'] = 0.05  # 시그널 민감도 증가
                logger.info(f"📊 거래 빈도 부족({metrics.daily_trades:.1f}회/일) → 민감도 증가 제안")
            
            elif metrics.daily_trades > 20:  # 과도한 거래
                adjustments['signal_sensitivity_decrease'] = 0.05  # 시그널 민감도 감소
                logger.info(f"📊 거래 과도({metrics.daily_trades:.1f}회/일) → 민감도 감소 제안")
            
            return adjustments
            
        except Exception as e:
            logger.error(f"적응형 조정 계산 실패: {e}")
            return {}
    
    def generate_performance_report(self, days: int = 7) -> str:
        """성과 리포트 생성"""
        try:
            metrics = self.calculate_metrics(days)
            
            report = f"""
📊 성과 리포트 (최근 {days}일)
═══════════════════════════════════
📈 전체 성과:
  • 총 거래: {metrics.total_trades}회
  • 승률: {metrics.win_rate:.1%} ({metrics.win_trades}승 {metrics.loss_trades}패)
  • 평균 수익률: {metrics.average_profit_rate:.2%}
  • Profit Factor: {metrics.profit_factor:.2f}
  • 최대 낙폭: {metrics.max_drawdown:.2%}

📊 거래 특성:
  • 일일 평균 거래: {metrics.daily_trades:.1f}회
  • 평균 보유시간: {metrics.avg_hold_time/60:.1f}분
  • 최고 성과 전략: {metrics.best_strategy}
  • 추정 슬리피지: {metrics.slippage_estimate:.3%}
  • Sharpe Ratio: {metrics.sharpe_ratio:.2f}

💡 수익성 분석:
  • 평균 승리: +{metrics.average_profit_rate if metrics.average_profit_rate > 0 else 0:.2%}
  • 평균 손실: {metrics.average_loss_rate:.2%}
  • 리스크 대비 수익: {abs(metrics.average_profit_rate/metrics.average_loss_rate) if metrics.average_loss_rate != 0 else 0:.2f}:1
            """
            
            return report.strip()
            
        except Exception as e:
            logger.error(f"리포트 생성 실패: {e}")
            return f"리포트 생성 실패: {e}"

# 글로벌 인스턴스
performance_monitor = PerformanceMonitor()

def log_trade_result(trade_result: TradeResult):
    """거래 결과 로깅 (편의 함수)"""
    performance_monitor.log_trade(trade_result)

def get_performance_metrics(days: int = 1) -> PerformanceMetrics:
    """성능 메트릭 조회 (편의 함수)"""
    return performance_monitor.calculate_metrics(days)

def get_adaptive_adjustments() -> Dict[str, float]:
    """적응형 조정 제안 조회 (편의 함수)"""
    return performance_monitor.get_adaptive_adjustments()

def generate_performance_report(days: int = 7) -> str:
    """성과 리포트 생성 (편의 함수)"""
    return performance_monitor.generate_performance_report(days)