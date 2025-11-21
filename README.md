# README

## 1. 프로젝트 개요 (Overview)
업비트 KRW 마켓 1분봉 초단기 스캘핑 봇. 메인 루프는 **“잔액조회 → 진입검증 → 100% 매수 → 청산검증 → 100% 매도 → 반복”** 단일 흐름을 강제하며, 부분 청산 없이 전량 매수·전량 매도로 포지션을 관리합니다. 레짐(상승/하락/횡보) 감지 후 레짐별 진입/청산 로직을 적용하고, 수익성·리스크 필터를 선행합니다.

## 2. 주요 기능 (Features)
- EMA 기반 **Fast Regime Detector** + ADX(14)로 상승/하락/횡보 및 추세 강도 컨텍스트 제공
- RSI, Bollinger Band, 거래량 필터를 적용한 진입 로직
- MACD(12/26/9), Stochastic(14/3/3)을 포함한 Entry Score 시스템(0~100)으로 신호 강도 판단
- 고정 % 또는 ATR 기반 SL/TP 계산, 사전 수익성(RR) 체크
- 심볼별 쿨다운, 시간당 진입 횟수 제한
- 메이커 우선 지정가 재시도 후 시장가 폴백
- 전량 청산 원칙(부분 청산 없음), 포지션/거래 기록 관리
- Telegram 알림(선택), 구조화 로깅

## 3. 전체 구조 (Architecture Flow)
```
[Fetch Balance] → [Regime Detection] → [Entry Check]
  └ 잔액 0 or 포지션 존재 → 스킵
  └ 필터 통과 시 → [100% 매수 실행]
                     ↓
               [포지션 보유(HOLD)]
                     ↓
           [Exit Check: SL/TP/조건]
                     ↓
               [100% 매도 실행]
                     ↓
                [상태/잔액 갱신]
                     ↓
                  (반복)
```
※ Regime Detection 후 ADX 필터(약추세 차단), Entry Score 계산(지표 가중) → 진입 여부 결정

## 4. 설치 및 실행 방법 (Installation & Usage)

### 4-1. 환경설정
- Python 3.9+ 권장
- 의존성 설치
```bash
pip install -r requirements.txt
```
- `.env` 예시 (절대 저장소에 커밋 금지)
```
UPBIT_API_KEY=your_key
UPBIT_API_SECRET=your_secret
TRADING_SYMBOLS=BTC/KRW,ETH/KRW
TIMEFRAME=1m
DRY_RUN=true           # 실거래 시 false
DEFAULT_ORDER_TYPE=market
PREFER_MAKER=false     # 메이커 우선 사용 시 true
# 추세/모멘텀은 스코어 기반으로 자동 적용
TREND_RSI_MIN=60
TREND_BB_POS_MIN=60
TREND_PRICE_ABOVE_EMA_PCT=0.3
TREND_VOLUME_MULTIPLIER=2.0
BB_WIDTH_MIN=0.5
BB_WIDTH_MAX=8.0
VOLUME_CONFIRM_MULTIPLIER=1.5
MIN_EXPECTED_RR=0.5
FEE_RATE_PCT=0.10
SLIPPAGE_BUFFER_PCT=0.25
```
> ⚠️ **API Key 보안**: 키는 .env로 관리하고 .gitignore에 포함하세요.

### 4-2. 실행
```bash
python -m src.app.scalping_bot
```
- 드라이런: `DRY_RUN=true`
- 실거래: `DRY_RUN=false` + 실제 API 키

## 5. 전략 설명 (Strategy Logic)

### 5-1. 진입 조건

#### 5-1-A. Entry Score System (0-100)
- Base: 40점 (보수적 시작)
- MACD (12/26/9): 라인 > 시그널 & |Hist|>0.001 → +20, 약하면 +10 / 라인 < 시그널-0.01 → -15
- Stochastic (14/3/3): K<20 → +15, 20-30 → +10, 30-70 → -5, >80 → -10, K>D 상향 크로스 → +8
- ADX(14): None/<20 → -15, 20-25 → 0, 25-35 → +5, ≥35 → +10
- EMA 크로스 신선도: 직후 +25, 1~3봉 +15, 4~7봉 +5
- 거래량 스파이크(최근 ≥ 평균×2): +15
- **진입 기준: 60점 이상일 때만 진입**

#### 5-1-B. 레짐·필터
- 레짐: FastRegimeDetector(EMA9/21) + ADX 14주기 컨텍스트
  - ADX < 20: 진입 차단
  - ADX 20~25: 중립, 25~35: 강, 35+: 매우 강
- 필터: BB 폭 `bb_width_min~max`, 거래량 `volume_confirm_multiplier`, 쿨다운/횟수 제한

#### 5-1-C. 패턴별 진입
- 상승장(풀백): 가격/EMA_fast ±0.5%, RSI 35~55, 기본 스코어 충족 시 진입
- 하락장 바운스(반등):
  - Essential 3: EMA_trend 하락, RSI ≤ 25, BB_position < -40
  - Momentum 4 중 2개 이상: 가격 반등 시작, 거래량 스파이크(≥2x), RSI 턴(+2 이상), MACD 히스토그램 상승
- 횡보: BB 포지션 하단(예: <20) + RSI<55, 필터/스코어 충족 시 평균회귀 진입

### 5-2. Downtrend Bounce (Counter-trend)
- 진입 조건:
  - Essential 3: EMA_trend 하락, RSI ≤ 25, BB_position < -40
  - Momentum 4 중 2개 이상: 가격 반등 시작, 거래량 스파이크(≥2x), RSI 턴(+2 이상), MACD 히스토그램 상승
- 청산: SL -0.15%, TP +0.20%

### 5-3. 청산 조건 (100% 매도)
- 일반: SL -0.20%, TP +0.35% (고정) 또는 ATR 기반 사용 시 설정값 적용
- 하락장 바운스: SL -0.15%, TP +0.20%
- 기술적 청산: BB 상단+RSI 과매수(>60~70), 횡보 중단선 회귀, 레짐 반전/거래량 급감 시 방어 청산
- 시간 스탑: 사용하지 않음 (옵션 제거)
- **부분 청산 없음**: 항상 전량 매도

### 5-3. 리스크 관리 방식
- 전량 진입/전량 청산 기본, 점수 기반 사이징/ATR 사이징 옵션 제공
- 슬리피지 경고(`max_slippage_pct`) 및 사전 스프레드 체크
- 리스크 매개변수: `fixed_stop_loss_pct`, `fixed_take_profit_pct`, `use_atr_sl_tp`, `atr_stop_multiplier`, `atr_target_multiplier`
- 진입 전 잔액 확인, 포지션 존재 시 재진입 금지

## 6. 파일/폴더 구조 설명 (Folder Structure)
```
src/
  app/
    scalping_bot.py        # 메인 루프, 진입/청산 orchestration
    config.py              # 설정 로드/검증
  strategy/
    scalping_strategy.py   # 진입/청산 로직, 지표 필터, SL/TP 계산, 수익성 체크
    fast_regime_detector.py# EMA 기반 레짐/기울기 감지
  exec/
    order_router.py        # 메이커 우선/시장가 주문, 슬리피지/수수료 계산
    position_tracker.py    # 포지션/거래 기록
  core/
    types.py, utils.py     # 공통 타입/유틸
```

## 7. 주요 함수 및 모듈 설명
- `ScalpingBot._process_iteration()`: 심볼 순회, 포지션 여부로 진입/청산 분기
- `ScalpingBot._check_entry()`: 잔액 조회 → 필터/수익성 확인 → 100% 매수 실행
- `ScalpingBot._manage_position()`: SL/TP 및 전략 청산 조건 확인 → 100% 매도
- `ScalpingStrategy.generate_entry_signal()`: 지표 계산, 필터 적용, 신호 생성
- `ScalpingStrategy.should_exit()`: 전량 청산 조건 판정
- `ScalpingStrategy.get_stops()`: 고정% 또는 ATR 기반 SL/TP 계산
- `FastRegimeDetector.detect_regime()`: EMA 기반 레짐/EMA 기울기 산출
- `OrderRouter.execute_signal()`: 메이커 우선 지정가 재시도 후 시장가 폴백
- `OrderRouter.close_position()`: 전량 시장가/지정가 청산 지원
- `PositionTracker.open/close_position()`: 포지션 수명주기 관리, PnL 계산

## 8. 에러 처리/예외 처리 구조 (Error Handling)
- 지표 계산 실패, 데이터 부족, 가격/수량 비정상 시 진입 스킵
- 주문 타임아웃 시 지정가 취소 후 시장가 폴백(또는 재시도 후 실패 처리)
- 청산 타임아웃 시 주문 상태 재조회, 미체결이면 다음 루프 재시도
- 슬리피지 초과 경고 로깅, 리스크 한도 초과 시 진입 중단
- 모든 외부 호출(fetch_ohlcv/balance/ticker 등)에 타임아웃 적용

## 9. 주의사항
- **API Key 보안**: .env로 관리, 저장소/로그에 노출 금지
- **거래소 제약**: Rate Limit 준수, 주문 실패/미체결 가능성 고려
- **슬리피지**: 급변동 시 시장가 슬리피지 확대 가능, `prefer_maker` 사용 시 체결 실패 리스크 존재
- **수수료**: 업비트 왕복 약 0.1% 가정, TP/SL 설정 시 수수료+슬리피지 버퍼 반영 필수
- **포지션 단일성**: 부분 청산 없음, 포지션 존재 시 재진입 불가

## 10. 향후 개선계획 (Future Work)
- 백테스트/시뮬레이터 통합 및 리포트 자동화
- 슬리피지 예측/동적 가격 개선 로직
- 체결 실패 재시도 전략 고도화(호가 스냅샷 기반)
- 레짐 필터 강화(ADX, 변동성 군집화 추가)
- 모니터링 대시보드/지표 알림 고도화

## 11. 라이선스 (License)
- 프로젝트 소유자 정책에 따릅니다. (미정 시 “All rights reserved” 명시)
