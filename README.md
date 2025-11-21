# 스캘핑 봇 (XRP/KRW, 1분봉)

## 핵심 동작
- 잔액 조회 → 진입 신호 판단 → 가용 KRW 95% 시장가 매수 → 청산 판단 → 전체 매도 → 반복
- 레짐 감지: EMA 9/21 기반 상승·하락·횡보 판별
- 진입 전략: RSI+볼린저 중심의 평균회귀 롱 (하락장 바운스 포함)
- 청산: 고정 손절 0.2%, 고정 익절 0.35%, 시간 제한(기본 5분), 전략 신호
- 리스크: 기본 한도는 완화되어 진입 차단 없이 흐름 유지 (필요 시 .env 조정)

## 실행 준비
1) 의존성 설치
```bash
pip3 install -r requirements.txt
```

2) 환경 변수 설정
```bash
cp .env.example .env
# 필수: UPBIT_API_KEY, UPBIT_API_SECRET
# 모드: DRY_RUN=true(종이거래), false(실거래)
# 심볼/주기: TRADING_SYMBOLS=XRP/KRW, TIMEFRAME=1m
# 체크 주기: CHECK_INTERVAL_SECONDS=10
# 리스크/스탑: FIXED_STOP_LOSS_PCT=0.20, FIXED_TAKE_PROFIT_PCT=0.35 등
```

## 실행
- 드라이런: `python3 -m src.app.scalping_bot` (DRY_RUN=true)
- 실거래: `.env`에서 DRY_RUN=false 설정 후 실행

## 주요 설정 요약 (.env)
- 거래소/계정: `UPBIT_API_KEY`, `UPBIT_API_SECRET`
- 모드/잔액: `DRY_RUN`, `INITIAL_BALANCE`(드라이런 전용)
- 전략: `RSI_OVERSOLD=35`, `RSI_OVERBOUGHT=65`, `BB_PERIOD=20`, `BB_STD_DEV=2.0`, `ENTRY_COOLDOWN_SECONDS=20`, `TIME_STOP_MINUTES=5`
- 리스크: `PER_TRADE_RISK=100.0`, `MAX_DAILY_LOSS=1000.0`, `MAX_DRAWDOWN=1000.0`, `MAX_CONSECUTIVE_LOSSES=999`, `MAX_POSITION_SIZE=100.0` (진입 차단 없도록 설정, 실거래 시 조정 권장)
- 스탑/익절: `FIXED_STOP_LOSS_PCT=0.20`, `FIXED_TAKE_PROFIT_PCT=0.35`
- 주문: `DEFAULT_ORDER_TYPE=market`, `MAX_SLIPPAGE_PCT=1.0`, `LIMIT_ORDER_TIMEOUT_SECONDS=3`

## 주문/체결 로직
- 매수: 최신 가용 KRW(free) 기준, 95% 비용으로 코인 수량 계산 후 시장가 매수
- 매도: 보유 코인 전량 시장가 매도
- 지정가 폴백: 설정에 따라 지정가 시도 후 타임아웃 시 시장가 전환

## 로그 확인
- 콘솔 및 `logs/trading_YYYYMMDD.csv`에 진입/청산/잔고 요약 기록
- 요약 예) `잔고=1,017,030 KRW | 자산=1,017,030 KRW | 미실현손익=+0 KRW | 일간손익=+16,032 KRW | 구매가=30,120 | 손절=30,050 | 익절=30,220`
- 포지션이 없으면 구매가/손절/익절은 `-`로 표시
