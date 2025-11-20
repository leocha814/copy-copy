# XRP/KRW 1분봉 스캘핑 봇

## 개요

- **거래소**: Upbit
- **심볼**: XRP/KRW
- **타임프레임**: 1분봉
- **거래 모드**: 초단타 스캘핑 (1~5분 내 진입·청산)
- **전략**: EMA 레짐 감지 + 다중 진입/청산 신호
- **리스크 관리**: 고정 스탑/테이크프로핏 또는 ATR 기반 스탑
- **주문**: 시장가 주문 (지정가 폴백 지원)

---

## 설치 & 실행

### 1. 의존성 설치

```bash
pip3 install -r requirements.txt
```

### 2. 환경 설정

```bash
# .env 파일이 이미 있으면 그대로 사용
# 없으면 .env.example을 복사하여 수정
cp .env.example .env

# .env에서 다음 항목 확인:
# - UPBIT_API_KEY
# - UPBIT_API_SECRET
# - DRY_RUN (테스트: true, 실거래: false)
# - INITIAL_BALANCE (드라이런 초기자금)
# - TRADING_SYMBOLS (XRP/KRW 권장)
```

### 3. 실행

**드라이런 (시뮬레이션)**

```bash
DRY_RUN=true python3 -m src.app.scalping_bot
```

**실거래**

```bash
# 주의: 실제 자금이 사용됩니다
DRY_RUN=false python3 -m src.app.scalping_bot
```

**백그라운드 실행 (MacBook)**

```bash
# 절전 모드 방지 + 백그라운드 실행
caffeinate -d python3 -m src.app.scalping_bot &
```

---

## 주요 설정 (.env)

### 거래 파라미터

| 항목                     | 기본값    | 설명          |
| ------------------------ | --------- | ------------- |
| `TRADING_SYMBOLS`        | `XRP/KRW` | 거래 심볼     |
| `TIMEFRAME`              | `1m`      | 캔들 주기     |
| `CHECK_INTERVAL_SECONDS` | `10`      | 체크 주기(초) |

### 전략 파라미터

| 항목                     | 기본값 | 설명                  |
| ------------------------ | ------ | --------------------- |
| `RSI_PERIOD`             | `14`   | RSI 기간              |
| `RSI_OVERSOLD`           | `35`   | RSI 과매도선          |
| `RSI_OVERBOUGHT`         | `65`   | RSI 과매수선          |
| `BB_PERIOD`              | `20`   | 볼린저밴드 기간       |
| `BB_STD_DEV`             | `2.0`  | 볼린저밴드 표준편차   |
| `BB_WIDTH_MIN`           | `0.2`  | BB 폭 최소(%)         |
| `BB_WIDTH_MAX`           | `15.0` | BB 폭 최대(%)         |
| `ENTRY_COOLDOWN_SECONDS` | `15`   | 진입 쿨다운(초)       |
| `TIME_STOP_MINUTES`      | `5`    | 포지션 보유 시간 제한 |

### 리스크 관리

| 항목                     | 기본값  | 설명                 |
| ------------------------ | ------- | -------------------- |
| `PER_TRADE_RISK`         | `8.0`   | 1회 거래 리스크(%)   |
| `MAX_DAILY_LOSS`         | `20.0`  | 하루 최대 손실(%)    |
| `MAX_CONSECUTIVE_LOSSES` | `10`    | 연속 손실 제한(횟수) |
| `MAX_DRAWDOWN`           | `100.0` | 최대 낙폭(%)         |
| `MAX_POSITION_SIZE`      | `50.0`  | 최대 포지션 크기(%)  |

### 스탑/테이크프로핏

| 항목                        | 기본값 | 설명           |
| --------------------------- | ------ | -------------- |
| `USE_FIXED_STOPS`           | `true` | 고정 스탑 사용 |
| `FIXED_STOP_LOSS_PCT`       | `0.18` | 고정 손절(%\*) |
| `FIXED_TAKE_PROFIT_PCT`     | `0.30` | 고정 익절(%)   |
| `DOWNTREND_STOP_LOSS_PCT`   | `0.15` | 하락장 손절(%) |
| `DOWNTREND_TAKE_PROFIT_PCT` | `0.20` | 하락장 익절(%) |

### 주문/실행

| 항목                          | 기본값   | 설명                    |
| ----------------------------- | -------- | ----------------------- |
| `DEFAULT_ORDER_TYPE`          | `market` | 주문 유형(market/limit) |
| `LIMIT_ORDER_TIMEOUT_SECONDS` | `30`     | 지정가 타임아웃(초)     |
| `MAX_SLIPPAGE_PCT`            | `0.5`    | 최대 슬리피지(%)        |

---

## 거래 전략

### 레짐 감지 (EMA 기반)

- **상승장**: EMA 9 > EMA 21 (정배열)
- **하락장**: EMA 9 < EMA 21 (역배열)
- **횡보장**: EMA 괴리도 < 0.3%

### 진입 조건

#### 상승장 롱

- EMA 정배열 상태
- BB 폭 필터 충족 (0.2% ~ 15%)
- 가격이 EMA 9 ±0.5% 범위 내
- RSI 35~55 (과매도/과매수 아님)
- 쿨다운 충족 (15초)

#### 하락장 바운스 롱

- EMA 역배열 상태
- RSI ≤ 35 (과매도)
- BB 위치 < -40 (하단 근처)
- 저가 바운스 신호 감지

#### 횡보장 롱 (평균회귀)

- EMA 괴리도 < 0.3%
- BB 위치 < -20 (하단 반부)
- RSI < 50

### 청산 조건

| 조건          | 설명                    |
| ------------- | ----------------------- |
| **고정 손절** | 입가 - 0.18%            |
| **고정 익절** | 입가 + 0.30%            |
| **시간 종료** | 5분 보유 후 시장가 청산 |
| **RSI 청산**  | RSI ≥ 70 (과매수)       |
| **BB 청산**   | BB 상단 + RSI > 60      |
| **횡보 회귀** | BB 중단선 회귀 신호     |

---

## 위험 관리

### 포지션 사이징

```
위험금액 = 계좌잔고 × (PER_TRADE_RISK / 100)
손절거리 = |진입가 - 손절가|
포지션수량 = 위험금액 / 손절거리
최대노션 = 계좌잔고 × (MAX_POSITION_SIZE / 100)
최종수량 = MIN(위험금액 기반 수량, 최대노션)
```

### 리스크 한도

- 1거래 최대 손실: PER_TRADE_RISK (%)
- 일간 최대 손실: MAX_DAILY_LOSS (%)
- 연속 손실 제한: MAX_CONSECUTIVE_LOSSES (회)
- 최대 낙폭: MAX_DRAWDOWN (%)

한도 초과 시 **자동 진입 중단** (기존 포지션은 청산)

### 주문 검증

- 시장가 주문으로 진입/청산
- 지정가 전환 옵션 지원 (미체결 시)
- 슬리피지 제한: MAX_SLIPPAGE_PCT (%)
- 슬리피지 초과 시 경고 로그

---

## 로그 & 모니터링

### 로그 위치

- **콘솔**: 실시간 거래 로그 (진입/청산/손익)
- **파일**: `logs/trading_YYYYMMDD.csv` (거래 기록)

### 주요 로그 항목

```
[요약] 잔고: 129,745 KRW | 일손익: +1,234 KRW (+0.95%) | 가격: XRP/KRW:3,152 | 레짐: XRP/KRW:상승장

[XRP/KRW] ✅ 포지션 오픈: BUY 20.50941077 @ 3152.00
[XRP/KRW] ✅ 포지션 청산 | 손익: +23.45 KRW | 일간 손익: +23.45 KRW | 이유: Take profit hit
```

### Telegram 알림 (선택)

- 진입/청산 신호
- 리스크 한도 초과
- 주문 오류 및 경고

설정: `.env`에서 `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`

---

## 실거래 안전 수칙

### 필수 사전 점검

1. **API 키 보안**

   - 새 API 키 생성 (기존 키 교체)
   - 허용 IP에 서버 공인 IPv4 등록
   - 출금 권한 제거 (입금/거래만 허가)

2. **소액 테스트**

   - DRY_RUN으로 3~5일 백테스트
   - 실거래 전 최소 금액으로 1~2시간 테스트

3. **매개변수 검토**
   - PER_TRADE_RISK = 1~2% 권장
   - MAX_DAILY_LOSS = 5~10% 권장
   - MAX_DRAWDOWN = 15~20% 권장

### 실시간 모니터링

- 첫 30분: 콘솔에서 실시간 감시
- 1시간마다: 로그 파일 및 손익 확인
- 일 2회(아침/저녁): 종합 점검

### 중단 시점

- **리스크 한도 초과** → 자동 중단 (재시작 필요)
- **연속 5회 손실** → 수동 점검
- **네트워크 이슈** → 즉시 중단

### 거래 금지 시간대

- 변동성 극저 시간 (야간 02:00~08:00)
- 공급망 공지 예정 1시간 전후
- 긴급 뉴스/이벤트 시

---

## 기술 스택

| 항목        | 라이브러리       |
| ----------- | ---------------- |
| 거래소 API  | CCXT (Upbit)     |
| 데이터 분석 | Pandas, NumPy    |
| 비동기      | Asyncio, Aiohttp |
| 로깅        | Python logging   |
| 환경 설정   | python-dotenv    |

---

## 프로젝트 구조

```
copy-copy/
├── src/
│   ├── app/              # 봇 메인
│   │   ├── scalping_bot.py
│   │   └── config.py
│   ├── exchange/         # 거래소 연동
│   │   ├── upbit.py
│   │   └── paper.py
│   ├── strategy/         # 거래 전략
│   │   ├── scalping_strategy.py
│   │   └── fast_regime_detector.py
│   ├── risk/             # 리스크 관리
│   │   └── risk_manager.py
│   ├── exec/             # 주문 실행
│   │   ├── order_router.py
│   │   └── position_tracker.py
│   ├── monitor/          # 모니터링
│   │   ├── logger.py
│   │   └── alerts.py
│   └── core/             # 핵심 유틸
│       ├── types.py
│       └── utils.py
├── logs/                 # 거래 로그
├── tests/                # 단위 테스트
├── .env                  # 환경 설정 (예: API 키)
├── .env.example          # 템플릿
├── requirements.txt      # 의존성
└── README.md            # 이 파일
```

---

## 주의사항

⚠️ **이 프로젝트는 교육/연구 목적이며, 실거래 손실에 대한 책임은 전적으로 사용자에게 있습니다.**

- API 키와 잔고 보안에 유의하세요.
- 실거래 전 백테스트 및 소액 테스트를 필수로 수행하세요.
- 불안정한 네트워크에서는 실거래를 피하세요.
- 시스템 오류나 예상치 못한 손실에 대비하세요.

---

## 문제 해결

### 자주 발생하는 오류

**"insufficient_funds_ask"**

- 원인: 주문 수량이 보유량을 초과
- 해결: PER_TRADE_RISK 감소 또는 MAX_POSITION_SIZE 감소

**"Order timeout (타임아웃)"**

- 원인: 네트워크 지연 또는 거래소 과부하
- 해결: LIMIT_ORDER_TIMEOUT_SECONDS 증가

**"캔들 조회 오류"**

- 원인: Upbit API 일시 불안정
- 해결: 몇 분 대기 후 봇 재시작

### 로그 레벨 변경

```bash
LOG_LEVEL=DEBUG python3 -m src.app.scalping_bot  # 상세 로그
LOG_LEVEL=INFO python3 -m src.app.scalping_bot   # 일반 로그
```

---

## 지원 & 피드백

질문이나 버그 리포트는 프로젝트 이슈 트래커에 남겨주세요.

**마지막 업데이트**: 2025년 11월 21일
