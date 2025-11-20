# 스캘핑 봇 전략 요약 (코드 기반)

이 문서는 현재 코드 기준(기본 설정: 1분봉, 드라이런 가능)의 매매 로직을 요약합니다. 각 섹션에 관련 코드 경로를 명시했습니다.

## 1. 레짐 감지 (FastRegimeDetector)

- 파일: `src/strategy/fast_regime_detector.py`
- 로직: EMA 9/21 교차와 괴리도(디폴트 0.3%)로 상승장/하락장/횡보장 판별.

```python
ema_divergence_pct = 0.3
if EMA_fast > EMA_slow and div>=0.3% and price>EMA_slow -> UPTREND
if EMA_fast < EMA_slow and div>=0.3% and price<EMA_slow -> DOWNTREND
else RANGING
```

## 2. 지표 계산 (RSI/BB/EMA)

- 파일: `src/strategy/scalping_strategy.py`, `_compute_indicators`
- 사용 지표: RSI(기본 35/65), Bollinger Bands(20, 2.0), EMA 9/21, BB 폭/포지션.
- BB 폭 필터: 기본 0.2% 이상 15% 이하.

## 3. 진입 조건 (generate_entry_signal)

- 파일: `src/strategy/scalping_strategy.py`
- 쿨다운: 기본 15초(환경변수 ENTRY_COOLDOWN_SECONDS).
- 공통 필터: BB 폭 범위 통과, 쿨다운 통과.
- 상승장(UPTREND):
  - 가격이 EMA_fast 근처(±0.5%), RSI 35~55, EMA 정배열.
- 하락장(DOWNTREND) 바운스:
  - RSI ≤ rsi_oversold(기본 35), BB 포지션 < -40, 가격이 BB 하단보다 약간 위(반등 시동).
- 횡보장(RANGING):
  - BB 포지션 < -20, RSI < 50 → 롱 진입(평균회귀).

## 4. 청산 조건 (should_exit)

- 파일: `src/strategy/scalping_strategy.py`
- 고정 손절/익절: 기본 SL 0.18%, TP 0.30% (다운트렌드 바운스는 SL 0.15%, TP 0.20%).
- 시간 종료: 진입 후 5분 경과.
- 보조 청산:
  - 상승/횡보 포지션에서 BB 상단 + RSI>60, 또는 RSI≥70 & 수익구간.
  - 횡보 포지션은 BB 중단선 회귀 + RSI>RSI_EXIT_NEUTRAL(50) 시 청산.

## 5. 포지션 사이징 (RiskManager)

- 파일: `src/risk/risk_manager.py`, `src/core/utils.py`
- per_trade_risk_pct(기본 0.5%), max_position_size_pct(기본 30%).
- 현재 stop_distance를 ATR 대체값으로 넣어 `calculate_position_size_atr` 호출:
  - 위험금액 = 계좌 \* (위험%)
  - 스탑 거리(종가-손절가)로 크기 산출 → 최대 포지션 한도 적용.

## 6. 주문 실행 (OrderRouter)

- 파일: `src/exec/order_router.py`
- 기본 시장가(default_order_type=market).
- 슬리피지 경고: max_slippage_pct 기본 0.5%.
- 주문 실패/타임아웃 시 한글 메시지 로깅.

## 7. 로그 & 요약

- 파일: `src/monitor/logger.py`, `src/app/scalping_bot.py`
- INFO: 루프 번호, 진입/청산, 요약(잔고/일손익/현재가/레짐).
- DEBUG: 지표/필터 조건 통과 여부(쿨다운, BB 폭, RSI/EMA/BB 포지션 값).
- CSV: `logs/trading_YYYYMMDD.csv`에 구조화 기록.

## 8. 실행 메모

- DRY_RUN=true → 종이거래소 사용.
- 실거래는 업비트 허용 IP 및 네트워크 접근 필요(미인증 IP/DNS 오류 시 실패).
- 요약만 보고 싶으면 `LOG_LEVEL=INFO`, 조건 상세까지 보려면 `LOG_LEVEL=DEBUG`.
