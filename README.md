# 업비트 1분봉 스캘핑 봇 (Upbit 1-Minute Scalping Bot)

## 1. 프로젝트 개요 (Overview)

업비트(Upbit) KRW 마켓 1분봉 초단기 스캘핑 봇입니다.

**핵심 동작**:
- **메인 루프**: 잔액조회 → 레짐 감지 → 진입 검증 → 100% 매수 → 포지션 보유 → 청산 신호 확인 → 100% 매도 → 반복
- **진입 전략**: ADX 필터 + Entry Score 시스템(0~100) + 레짐별 조건
- **청산 전략**: 고정 SL/TP (regime별 상이) + 기술적 청산 신호
- **포지션 관리**: 전량 매수·전량 매도 원칙 (부분 청산 시 즉시 재청산)

---

## 2. 주요 특징 (Features)

### 진입 신호 (Entry Signal)
- **Entry Score System**: MACD, Stochastic, ADX, EMA 크로스, 거래량을 가중치로 0~100점 산출
  - 60점 이상일 때만 진입 (기본 40점 + 지표별 가감)
- **ADX 필터**: ADX < 20이면 진입 차단 (약추세 회피)
- **거래량 확인**: 최근 거래량 ≥ 평균 × multiplier
- **레짐별 진입**:
  - **상승장(UPTREND)**: 가격이 EMA_fast ±0.5% 범위에서 RSI 35~55 + 스코어 60점 이상
  - **하락장(DOWNTREND)**: RSI ≤ 25 + BB lower < -40 (바운스 대기) + 거래량 스파이크 + 스코어 60점 이상
  - **횡보(RANGING)**: BB lower 근처 + RSI < 55 + 스코어 60점 이상

### 청산 신호 (Exit Signal)
- **고정 SL/TP** (현재 권장):
  - 상승장/횡보: SL -0.20%, TP +0.35%
  - 하락장(바운스): SL -0.15%, TP +0.20%
- **또는 ATR 기반**: `use_atr_sl_tp=true` 설정 시 ATR 배수로 동적 계산
- **기술적 청산**:
  - BB 상단 근처 + RSI > 60: 과매수 청산
  - 횡보 중 BB middle 회귀: 평균회귀 청산
  - 레짐 반전/거래량 급감: 방어 청산

### 주문 실행 (Order Execution)
- **매수**: 실시간 KRW free 잔액 100% 사용 (슬리피지 0.15% + 수수료 0.10% 버퍼 제외)
  - `slippage_fee_ratio = 1.0025` 로 정확하게 계산
- **매도**: 실시간 기본 통화(XRP 등) free 잔액 100% 사용
- **부분 체결**: 10회 폴링(0.5초 간격, 총 5초) 후 체결 여부 확인
- **타임아웃**: 진입 60초, 청산 60초 + 타임아웃 후 상태 재확인
- **슬리피지**: 초과해도 포지션은 열리고 경고만 기록 (안전 설계)

### 포지션 추적 (Position Management)
- 실제 체결가(order.average) 기반 진입/청산
- 부분 청산 시 즉시 나머지 수량 재청산 (전량 청산 원칙 준수)
- PnL 계산: 수수료(exit side만) 및 슬리피지 반영

### 리스크 관리 (Risk Management)
- **진입 전 검증**:
  - 주문 직전 KRW 잔액 재확인
  - 예상 수익성 체크 (RR ratio 기준)
  - 포지션 존재 시 재진입 금지
- **중복 청산 방지**: open_orders 조회 후 미체결 주문 확인
- **쿨다운**: 심볼별 최소 대기 시간 + 시간당 진입 횟수 제한

---

## 3. 설치 및 실행 (Installation & Usage)

### 3-1. 환경설정

**Python 버전**: 3.9 이상 권장

**의존성 설치**:
```bash
pip install -r requirements.txt
```

**.env 파일** (절대 저장소에 커밋 금지):
```
# Upbit API 키
UPBIT_API_KEY=your_api_key_here
UPBIT_API_SECRET=your_api_secret_here

# 거래 설정
TRADING_SYMBOLS=BTC/KRW,ETH/KRW,XRP/KRW
TIMEFRAME=1m
DRY_RUN=true              # 실거래 시 false로 변경

# 주문 설정
DEFAULT_ORDER_TYPE=market # 기본 시장가
PREFER_MAKER=false        # 메이커 우선 시도 (True 권장 아님)

# 기술적 지표 설정
RSI_PERIOD=14
BB_PERIOD=20
BB_STD_DEV=2.0
EMA_FAST_PERIOD=9
EMA_SLOW_PERIOD=21
MACD_FAST=12
MACD_SLOW=26
MACD_SIGNAL=9
STOCH_PERIOD=14
STOCH_K_SMOOTH=3
STOCH_D_SMOOTH=3
ADX_PERIOD=14

# 진입 필터
BB_WIDTH_MIN=0.5          # Bollinger Band 최소 폭(%)
BB_WIDTH_MAX=8.0          # Bollinger Band 최대 폭(%)
VOLUME_CONFIRM_MULTIPLIER=1.5  # 거래량 배수 (최근 >= 평균 * 배수)
ENTRY_COOLDOWN_SECONDS=30 # 진입 후 최소 대기(초)
MAX_ENTRIES_PER_HOUR=10   # 시간당 최대 진입 횟수

# SL/TP 설정
FIXED_STOP_LOSS_PCT=0.20  # 일반 손절(%)
FIXED_TAKE_PROFIT_PCT=0.35 # 일반 익절(%)
DOWNTREND_STOP_LOSS_PCT=0.15  # 하락장 손절(%)
DOWNTREND_TAKE_PROFIT_PCT=0.20 # 하락장 익절(%)

# ATR 기반 SL/TP (선택)
USE_ATR_SL_TP=false       # true일 때만 ATR 기반 사용
ATR_PERIOD=14
ATR_STOP_MULTIPLIER=2.0   # SL = ATR * 배수
ATR_TARGET_MULTIPLIER=3.0 # TP = ATR * 배수

# 점수 기반 사이징 (선택)
USE_SCORE_BASED_SIZING=false # true일 때 score별 사이징

# 거래 설정
FEE_RATE_PCT=0.10         # 수수료 0.1% (업비트 기본값)
SLIPPAGE_BUFFER_PCT=0.25  # 슬리피지 버퍼 0.25%
MAX_SLIPPAGE_PCT=0.5      # 최대 허용 슬리피지 0.5%

# 레짐 감지
EMA_SLOPE_THRESHOLD=2.0   # EMA 기울기 임계값(%)
```

> **⚠️ 보안 주의**:
> - API Key는 절대 코드에 하드코딩 금지
> - `.env` 파일은 `.gitignore`에 포함 필수
> - 로그 파일에서도 민감 정보 노출 금지

### 3-2. 실행

**드라이 런 (모의 거래)**:
```bash
DRY_RUN=true python -m src.app.scalping_bot
```

**실거래**:
```bash
DRY_RUN=false python -m src.app.scalping_bot
```

---

## 4. 시스템 아키텍처 (Architecture)

```
┌─────────────────────────────────────────────────────┐
│          ScalpingBot (메인 루프)                     │
├─────────────────────────────────────────────────────┤
│ • _process_iteration():                             │
│   - 심볼 순회                                        │
│   - 포지션 존재 여부로 진입/청산 분기               │
│                                                     │
│ • _check_entry():                                   │
│   - 진입 신호 생성 + 검증                           │
│   - 100% 매수 실행                                  │
│                                                     │
│ • _manage_position():                               │
│   - SL/TP + 청산 신호 확인                          │
│   - 100% 매도 실행                                  │
└─────────────────────────────────────────────────────┘
          ↓
┌─────────────────────────────────────────────────────┐
│       ScalpingStrategy (신호 생성 및 판정)          │
├─────────────────────────────────────────────────────┤
│ • generate_entry_signal():                          │
│   - 지표 계산 (RSI, BB, MACD, Stoch, ADX)          │
│   - Entry Score 계산                                │
│   - 레짐별 조건 검증                                │
│   - Signal 객체 반환                                │
│                                                     │
│ • should_exit():                                    │
│   - PnL % 계산                                      │
│   - SL/TP 확인                                      │
│   - 기술적 청산 신호 검증                           │
│                                                     │
│ • get_stops():                                      │
│   - SL/TP 가격 계산 (고정% 또는 ATR)              │
│                                                     │
│ • passes_profitability_check():                     │
│   - 예상 수익성 체크 (RR ratio)                    │
└─────────────────────────────────────────────────────┘
          ↓
┌─────────────────────────────────────────────────────┐
│    FastRegimeDetector (시장 레짐 감지)              │
├─────────────────────────────────────────────────────┤
│ • detect_regime():                                  │
│   - EMA(9/21) 기반 레짐 판정                        │
│   - ADX(14) 강도 계산                               │
│   - MarketRegime enum 반환                          │
│     (UPTREND / DOWNTREND / RANGING / UNKNOWN)      │
└─────────────────────────────────────────────────────┘
          ↓
┌─────────────────────────────────────────────────────┐
│       OrderRouter (주문 실행)                        │
├─────────────────────────────────────────────────────┤
│ • execute_signal():                                 │
│   - size=None → 100% 잔액 전략                     │
│   - LIMIT 시도 후 MARKET 폴백                      │
│                                                     │
│ • _execute_market_order():                          │
│   - BUY: KRW 100% 사용 (slippage_fee_ratio 적용) │
│   - SELL: base currency free 100% 사용             │
│   - 폴링 (10회, 0.5초 간격)                        │
│   - filled > 0 확인 후 반환                         │
│                                                     │
│ • close_position():                                 │
│   - 반대 방향 시장가 주문 + 100% 수량 청산          │
└─────────────────────────────────────────────────────┘
          ↓
┌─────────────────────────────────────────────────────┐
│      PositionTracker (포지션 기록)                   │
├─────────────────────────────────────────────────────┤
│ • open_position(): 포지션 오픈 기록                 │
│ • close_position(): 포지션 클로즈 + PnL 계산       │
│ • get_position(): 포지션 조회                       │
└─────────────────────────────────────────────────────┘
```

---

## 5. 핵심 로직 상세 (Core Logic Details)

### 5-1. Entry Score 계산 (0~100)

**Base**: 40점 (보수적 시작)

**지표별 가중치**:

| 지표 | 조건 | 점수 |
|------|------|------|
| **MACD** | 라인 > 신호 & \|Hist\| > 0.001 | +20 |
| | 라인 > 신호 (약함) | +10 |
| | 라인 < 신호 - 0.01 | -15 |
| **Stochastic K** | K < 20 | +15 |
| | 20 ≤ K < 30 | +10 |
| | 30 ≤ K ≤ 70 | -5 |
| | K > 80 | -10 |
| | K > D (상향 크로스) | +8 |
| **ADX(14)** | None 또는 < 20 | -15 |
| | 20 ≤ ADX < 25 | 0 |
| | 25 ≤ ADX < 35 | +5 |
| | ADX ≥ 35 | +10 |
| **EMA 크로스 신선도** | 직후 (1봉 내) | +25 |
| | 1~3봉 | +15 |
| | 4~7봉 | +5 |
| **거래량 스파이크** | 최근 ≥ 평균 × 2.0 | +15 |

**진입 기준**: **60점 이상**

### 5-2. 레짐별 진입 조건

#### A. 상승장 (UPTREND)

```
조건:
  • EMA_fast (9) > EMA_slow (21)
  • 가격이 EMA_fast ±0.5% 범위 (풀백)
  • RSI: 35 ~ 55
  • Entry Score: 60 이상

실행:
  → LONG (매수)
  → SL: -0.20% | TP: +0.35%
```

#### B. 하락장 (DOWNTREND) - 바운스 대기

```
조건 (Essential):
  • EMA_fast < EMA_slow (하락 중)
  • RSI ≤ 25 (극도의 약세)
  • BB_position < -40 (하단 터치)

조건 (Momentum 중 2개 이상):
  • 가격이 BB_lower 위로 약간 상승 (1.001배)
  • 거래량 스파이크 (≥ 평균 × 2.0)
  • RSI 턴 (직전 봉 대비 +2 이상)
  • MACD 히스토그램 상승

+ Entry Score: 60 이상

실행:
  → LONG (반등 매수)
  → SL: -0.15% | TP: +0.20% (타이트)
```

#### C. 횡보 (RANGING)

```
조건:
  • EMA 기울기 < threshold (약한 추세)
  • BB_position < 20 (하단 근처)
  • RSI < 55
  • Entry Score: 60 이상

실행:
  → LONG (평균회귀)
  → SL: -0.20% | TP: +0.35%
```

### 5-3. 청산 조건

#### 자동 청산 (SL/TP)

```
상승장/횡보:
  • Stop Loss (SL): -0.20% → 손절
  • Take Profit (TP): +0.35% → 익절

하락장 바운스:
  • Stop Loss (SL): -0.15% → 손절 (타이트)
  • Take Profit (TP): +0.20% → 익절 (빠름)
```

#### 기술적 청산

```
과매수 청산:
  • BB 상단 (position > 40) + RSI > 60

평균회귀 청산 (횡보):
  • 가격 ≥ BB_middle + RSI > 중립값

레짐 반전 방어 청산:
  • 레짐이 변경되었을 때
  • 거래량 급감 시
```

---

## 6. 파일/폴더 구조 (Folder Structure)

```
copy-copy/
├── src/
│   ├── app/
│   │   ├── scalping_bot.py          # 메인 루프 + 진입/청산 orchestration
│   │   └── config.py                 # 설정 로드 및 검증
│   │
│   ├── strategy/
│   │   ├── scalping_strategy.py      # 신호 생성, 청산 조건, SL/TP 계산
│   │   └── fast_regime_detector.py   # 시장 레짐 감지
│   │
│   ├── exec/
│   │   ├── order_router.py           # 주문 실행, 폴링, 슬리피지 계산
│   │   └── position_tracker.py       # 포지션/거래 기록 관리
│   │
│   ├── indicators/
│   │   └── indicators.py             # 기술적 지표 계산
│   │
│   ├── exchange/
│   │   └── interface.py              # Upbit API 래퍼
│   │
│   ├── core/
│   │   ├── types.py                  # 타입 정의 (Signal, Position, Trade 등)
│   │   └── utils.py                  # 유틸리티 함수
│   │
│   └── alerts/
│       └── telegram.py               # Telegram 알림 (선택)
│
├── requirements.txt                  # 패키지 의존성
├── README.md                         # 이 문서
└── .env                              # API 키 및 설정 (저장소 제외)
```

---

## 7. 주요 함수 및 메서드 (Key Functions)

### ScalpingBot

| 메서드 | 설명 |
|--------|------|
| `_process_iteration()` | 심볼 순회, 레짐 감지, 진입/청산 분기 |
| `_check_entry()` | 진입 신호 생성 및 검증, 100% 매수 실행 |
| `_manage_position()` | 청산 신호 확인, 100% 매도 실행, PnL 계산 |
| `_estimate_atr()` | ATR 계산 (선택 사항) |
| `_calc_balance_size()` | 사용 가능한 잔액 기반 사이징 |

### ScalpingStrategy

| 메서드 | 설명 |
|--------|------|
| `generate_entry_signal()` | 지표 계산 + Entry Score + 신호 생성 |
| `should_exit()` | PnL 기반 SL/TP + 기술적 청산 신호 |
| `get_stops()` | SL/TP 가격 계산 (고정% 또는 ATR) |
| `get_fixed_stops()` | 고정값 SL/TP |
| `passes_profitability_check()` | 예상 RR ratio 검증 |
| `_calculate_entry_score()` | Entry Score 계산 |

### OrderRouter

| 메서드 | 설명 |
|--------|------|
| `execute_signal()` | LIMIT → MARKET 폴백으로 신호 실행 |
| `close_position()` | 100% 청산 주문 실행 |
| `_execute_market_order()` | 시장가 주문 + 폴링 + 체결 확인 |
| `_extract_krw_free_balance()` | KRW free 잔액만 추출 |
| `_extract_base_balance_free()` | 기본 통화 free 잔액만 추출 |

### PositionTracker

| 메서드 | 설명 |
|--------|------|
| `open_position()` | 포지션 오픈 기록 |
| `close_position()` | 포지션 클로즈 + Trade 기록 + PnL 계산 |
| `get_position()` | 현재 포지션 조회 |
| `get_all_positions()` | 모든 오픈 포지션 조회 |

---

## 8. 에러 처리 및 안전장치 (Error Handling & Safety)

### 진입 단계

| 상황 | 동작 |
|------|------|
| 지표 계산 실패 | 진입 스킵 |
| 데이터 부족 | 진입 스킵 |
| ADX < 20 | 진입 차단 |
| Entry Score < 60 | 진입 스킵 |
| KRW 잔액 ≤ 0 | 진입 스킵 |
| 포지션 존재 | 진입 스킵 |
| 주문 타임아웃 (60초) | 취소 후 진입 취소 |
| 체결 안됨 (filled ≤ 0) | 진입 실패 처리 |

### 청산 단계

| 상황 | 동작 |
|------|------|
| open_orders 조회 타임아웃 | 청산 스킵 (다음 루프) |
| 이미 청산 주문 있음 | 중복 방지 + 대기 |
| 청산 타임아웃 (60초) | 상태 재확인 후 처리 |
| 부분 체결 (filled < position.size) | 즉시 나머지 재청산 |
| 타임아웃 후 미체결 | 다음 루프 재시도 |

### 폴링 로직 (Polling Logic)

```
주문 후:
  1. 10회 폴링 (0.5초 간격 = 총 5초)
  2. 각 폴링에서:
     - 상태 확인 (status → .lower()로 정규화)
     - filled > 0 이면 체결 → 반환
     - filled = 0 이면 미체결 → None 반환
  3. 폴링 완료 후:
     - filled > 0: 부분 체결도 허용 → 반환
     - state = "open": 취소 시도 → None 반환
     - 기타: None 반환
```

---

## 9. 거래 정확도 (Trade Accuracy)

### 진입가 (Entry Price)

- **신호 생성가**: `candles[-1].close` (마지막 봉의 종가)
- **실제 진입가**: `order_result.get("average")` (실제 체결가 평균)
  - 폴백: 체결가 없으면 신호 생성가 사용

### 청산가 (Exit Price)

- **신호 생성가**: `candles[-1].close` (마지막 봉의 종가)
- **실제 청산가**: `close_result.get("average")` (실제 체결가 평균)
  - 폴백: 체결가 없으면 신호 생성가 사용

### PnL 계산

```python
# BUY의 경우
gross_pnl = (exit_price - entry_price) * size
exit_fees = calculate_fees(size, exit_price)  # exit side만
net_pnl = gross_pnl - exit_fees

pnl_pct = ((exit_price / entry_price) - 1.0) * 100.0
```

---

## 10. 성능 고려사항 (Performance Notes)

### 슬리피지 관리

```
설정:
  • max_slippage_pct = 0.5% (기본)

동작:
  • 초과 시 경고 로깅
  • 포지션은 열리며 거래 기록됨
  • 위험: 손익에 영향
```

### 수수료

```
Upbit 기본값: 0.1% (taker)
계산:
  • Entry: included in KRW 계산
  • Exit: 포지션 클로즈 시 계산
  • Round-trip: 약 0.2% 가정
```

### 최소 수익 (Breakeven)

```
진입 전 체크:
  • 예상 TP pct - (수수료 2회 + 슬리피지) > 0
  • MIN_EXPECTED_RR (기본 0.5) 충족
```

---

## 11. 주의사항 및 제약 (Cautions & Limitations)

### 🔴 필수 주의

1. **API Key 보안**
   - `.env` 파일에만 저장
   - 코드에 절대 하드코딩 금지
   - 로그에서도 노출 금지

2. **실거래 리스크**
   - 실제 자산이 움직임
   - 테스트는 `DRY_RUN=true`로 충분히 수행 후 시작
   - 초기 금액은 최소 단위로 시작

3. **거래소 제약**
   - Rate limit 준수 필수
   - 주문 실패/미체결 가능성 존재
   - 네트워크 지연 대비

4. **시장 조건**
   - 변동성이 낮은 시간대는 수익 기대 어려움
   - 뉉스/공지사항 등 급변 가능성 고려

### ⚠️ 운영 주의

1. **포지션 관리**
   - 한 번에 한 심볼 최대 1개 포지션만 보유
   - 포지션 존재 시 재진입 불가능

2. **수익성 검증**
   - 예상 RR < 0.5는 진입 스킵
   - 수수료 + 슬리피지 버퍼 필수

3. **모니터링**
   - 시작 후 최소 1-2시간 모니터링 권장
   - 비정상 거래량/가격 변동 감시
   - 로그 파일 정기 확인

---

## 12. 향후 개선계획 (Future Work)

- [ ] 백테스트 엔진 통합
- [ ] 웹 대시보드 모니터링
- [ ] 동적 SL/TP 조정
- [ ] 멀티 심볼 동시 처리 (병렬화)
- [ ] ML 기반 Entry Score 최적화
- [ ] 변동성 군집화(VIX) 필터
- [ ] 트레일링 스탑 기능

---

## 13. 라이선스 (License)

프로젝트 소유자 정책에 따릅니다.

---

## 14. 기술 스택 (Tech Stack)

| 항목 | 스택 |
|------|------|
| **Language** | Python 3.9+ |
| **Exchange API** | Upbit (CCXT) |
| **Async** | asyncio |
| **Logging** | Python logging |
| **Notifications** | Telegram API (선택) |
| **Data** | pandas, numpy |

---

**최종 검수 일자**: 2025-11-21
**검수 등급**: A (우수 - 실제 운영 가능)
