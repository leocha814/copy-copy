# 🚀 초단타 스캘핑 봇 가이드

업비트 거래소에서 동작하는 **초단타(Ultra-Short Term Scalping)** 자동매매 봇입니다.

---

## 📊 핵심 특징

### ⚡ 초단타 최적화
- **타임프레임**: 1분봉 (1m)
- **체크 간격**: 20초
- **목표 보유 시간**: 1~5분
- **거래 빈도**: 하루 10~50회
- **수익 목표**: 0.2~0.3% (작고 빠른 수익)

### 🎯 전략
- **모든 장 대응**: 상승장/하락장/횡보장 모두 거래
- **UPTREND**: 풀백 매수 (EMA 근처 RSI 40~50)
- **DOWNTREND**: 반등 공매도 (EMA 근처 RSI 50~60)
- **RANGING**: 평균회귀 (BB 밴드 터치)

### 💰 리스크 관리 (스캘핑 특화)
- **고정 손절**: 0.15%
- **고정 익절**: 0.25%
- **시간 손절**: 5분 경과 시 강제 청산
- **거래당 리스크**: 0.5%
- **일일 손실 한도**: 2%
- **연속 손실 제한**: 3회

### 🔄 빠른 실행
- **쿨다운**: 20초 (빠른 재진입)
- **지정가 타임아웃**: 5초 (빠른 시장가 전환)
- **간소화된 레짐 감지**: EMA만 사용 (속도 우선)

---

## 🆚 기존 전략과의 차이

| 항목 | 기존 (스윙) | 초단타 (스캘핑) |
|------|------------|----------------|
| 타임프레임 | 5분봉 | **1분봉** |
| 체크 간격 | 60초 | **20초** |
| 보유 시간 | 10~30분 | **1~5분** |
| 거래 빈도 | 하루 1~5회 | **하루 10~50회** |
| 손절/익절 | ATR 2배/3배 | **고정 0.15%/0.25%** |
| 쿨다운 | 5분 | **20초** |
| 장 대응 | 횡보장만 | **모든 장** |
| 레짐 감지 | ADX+ATR+RSI+MA | **EMA만** |
| 진입 조건 | RSI < 30 (극단) | **RSI 40~60 (완화)** |
| 거래당 리스크 | 2% | **0.5%** |

---

## 🔧 설치 및 설정

### 1. 의존성 설치
```bash
pip install -r requirements.txt
```

### 2. 환경 설정
```bash
cp .env.example .env
# .env 파일 수정
```

**`.env` 파일 핵심 설정**:
```bash
# 필수: API 키
UPBIT_API_KEY=your_api_key_here
UPBIT_API_SECRET=your_api_secret_here

# 초단타 설정
TRADING_SYMBOLS=BTC/KRW              # 1개 심볼 집중 권장
TIMEFRAME=1m                         # 1분봉
CHECK_INTERVAL_SECONDS=20            # 20초 체크

# 전략 파라미터
RSI_OVERSOLD=40                      # 완화된 진입 (기존 30)
RSI_OVERBOUGHT=60                    # 완화된 진입 (기존 70)
RSI_EXIT_NEUTRAL=50
ENTRY_COOLDOWN_SECONDS=20            # 20초 쿨다운
BB_WIDTH_MIN=0.3                     # 좁은 BB도 허용
BB_WIDTH_MAX=15.0
TIME_STOP_MINUTES=5                  # 5분 강제 청산

# 리스크 관리
PER_TRADE_RISK=0.5                   # 거래당 0.5%
MAX_DAILY_LOSS=2.0                   # 일일 2%
MAX_CONSECUTIVE_LOSSES=3             # 3회 연속 손실
MAX_DRAWDOWN=5.0
MAX_POSITION_SIZE=30.0

# 고정 손익 (스캘핑 핵심)
USE_FIXED_STOPS=true                 # 반드시 true
FIXED_STOP_LOSS_PCT=0.15             # 0.15% 손절
FIXED_TAKE_PROFIT_PCT=0.25           # 0.25% 익절

# 시스템
LIMIT_ORDER_TIMEOUT_SECONDS=5        # 5초 타임아웃
```

### 3. 실행
```bash
# 초단타 봇 실행
python -m src.app.scalping_bot
```

---

## 📈 거래 로직 상세

### 레짐 감지 (Fast Regime Detector)
```python
EMA_fast(9) > EMA_slow(21) AND Price > EMA_fast
→ UPTREND

EMA_fast(9) < EMA_slow(21) AND Price < EMA_fast
→ DOWNTREND

EMA 차이 < 0.5% OR Price between EMAs
→ RANGING
```

### 진입 조건

#### 🟢 상승장 (UPTREND)
```
조건:
- EMA 정배열 (fast > slow)
- 가격이 EMA_fast 근처 (풀백)
- RSI 40~50 (과매도 아닌 가벼운 조정)

진입: 매수 (LONG)
청산: +0.25% 익절 OR -0.15% 손절 OR 5분 경과
```

#### 🔴 하락장 (DOWNTREND)
```
조건:
- EMA 역배열 (fast < slow)
- 가격이 EMA_fast 근처 (반등)
- RSI 50~60 (과매수 아닌 가벼운 반등)

진입: 공매도 (SHORT)
청산: +0.25% 익절 OR -0.15% 손절 OR 5분 경과
```

#### ⚪ 횡보장 (RANGING)
```
LONG 조건:
- BB position < -30 (하단 근처)
- RSI < 50

SHORT 조건:
- BB position > 30 (상단 근처)
- RSI > 50

청산: BB 중간선 도달 OR 고정 손익 OR 5분 경과
```

### 청산 우선순위
1. **고정 익절**: +0.25% 도달 즉시
2. **고정 손절**: -0.15% 도달 즉시
3. **시간 손절**: 5분 경과 시 무조건
4. **빠른 반전**: RSI 중립선 교차 + BB 중간선 도달

---

## 💡 사용 팁

### ✅ 권장 사항
1. **1개 심볼 집중**: BTC/KRW 또는 ETH/KRW 한 가지만
2. **변동성 높은 시간대**: 9시~11시, 14시~16시, 21시~23시
3. **소액 테스트**: 10만원으로 먼저 테스트
4. **모니터링**: 처음 1시간은 반드시 관찰
5. **손절 엄수**: 시스템이 자동으로 하지만 수동 개입 금지

### ❌ 피해야 할 것
1. **쿨다운 무시**: 20초 기다리기
2. **수동 개입**: 봇 로직 믿고 기다리기
3. **여러 심볼 동시**: 리소스 분산 방지
4. **저변동성 시간**: 새벽 2~6시 거래 비추천
5. **파라미터 과도 조정**: 최소 1주일 운영 후 조정

---

## 📊 예상 성과

### 이상적 환경 (변동성 높은 날)
- 거래 빈도: 30~50회/일
- 승률: 55~65%
- 평균 수익: +0.2%
- 평균 손실: -0.15%
- 일일 기대 수익: +1~3%

### 일반적 환경 (보통 날)
- 거래 빈도: 10~20회/일
- 승률: 50~60%
- 일일 기대 수익: +0.5~1.5%

### 나쁜 환경 (저변동성)
- 거래 빈도: 5~10회/일
- 승률: 45~55%
- 일일 수익: -0.5~+0.5%

**중요**: 초단타는 **거래 빈도**가 핵심입니다. 변동성 없는 날은 거래가 적어 수익도 적습니다.

---

## 🛡️ 리스크 관리

### 자동 중단 조건
```python
if daily_loss >= 2%:           # 하루 손실 2% 도달
    halt("Daily loss limit")

if consecutive_losses >= 3:    # 연속 3회 손실
    halt("Consecutive losses")

if drawdown >= 5%:             # 누적 낙폭 5%
    halt("Max drawdown")
```

### 거래 제한
- **동시 포지션**: 1개만 (멀티 포지션 불가)
- **포지션 크기**: 계좌의 30% 이하
- **최소 잔고**: 5만원 이상 유지

---

## 🔍 모니터링

### 실시간 로그
```bash
# 터미널 출력
[BTC/KRW] Regime: UPTREND | EMA_fast=51234567 | Price=51230000
[BTC/KRW] 📊 Entry signal: SCALP LONG (UPTREND): pullback to EMA
[BTC/KRW] ✅ Position opened: BUY 0.00195
[BTC/KRW] 🔔 Exit signal: TP hit: +0.26% >= +0.25%
[BTC/KRW] ✅ Position closed | PnL: +133 KRW
```

### CSV 로그
```bash
logs/trading_20250120.csv  # 거래 내역
logs/signals_20250120.csv  # 시그널 로그
logs/positions_20250120.csv  # 포지션 로그
```

---

## ⚙️ 성능 튜닝

### 더 공격적으로 (거래 빈도 ↑)
```bash
RSI_OVERSOLD=45              # 진입 쉽게
RSI_OVERBOUGHT=55
ENTRY_COOLDOWN_SECONDS=10    # 쿨다운 짧게
BB_WIDTH_MIN=0.1             # BB 폭 제한 완화
```

### 더 보수적으로 (승률 ↑)
```bash
RSI_OVERSOLD=35              # 진입 까다롭게
RSI_OVERBOUGHT=65
ENTRY_COOLDOWN_SECONDS=30    # 쿨다운 길게
FIXED_TAKE_PROFIT_PCT=0.3    # 익절 크게
```

### 빠른 회전 (단기)
```bash
TIME_STOP_MINUTES=3          # 3분 강제 청산
FIXED_TAKE_PROFIT_PCT=0.2    # 작은 익절
ENTRY_COOLDOWN_SECONDS=15
```

---

## 🚨 주의사항

### ⚠️ 중요
1. **슬리피지 주의**: 업비트는 시장가 주문 시 슬리피지 발생 가능
2. **API 제한**: 분당 200회 호출 제한 (초단타는 괜찮음)
3. **네트워크 안정성**: 인터넷 끊김 = 포지션 관리 불가
4. **변동성 의존**: 변동성 없으면 수익 없음

### 🔴 절대 금지
1. ❌ 레버리지 사용
2. ❌ 전액 투입 (최대 50%)
3. ❌ 손절 무시
4. ❌ 수동 거래 병행
5. ❌ 파라미터 매일 변경

---

## 📞 문제 해결

### Q1: 거래가 전혀 안 일어남
```
원인: 진입 조건이 충족되지 않음
해결:
- RSI 조건 완화 (40→45, 60→55)
- BB_WIDTH_MIN 낮추기 (0.3→0.1)
- 변동성 높은 시간대 대기
```

### Q2: 손실만 계속 발생
```
원인: 변동성 너무 낮거나 추세 없음
해결:
- 시간대 변경 (9-11시, 14-16시)
- 심볼 변경 (ETH/KRW, XRP/KRW 등)
- 하루 쉬기
```

### Q3: 너무 자주 거래함
```
원인: 쿨다운이 너무 짧음
해결:
- ENTRY_COOLDOWN_SECONDS 늘리기 (20→30)
- RSI 조건 엄격하게 (45→40)
```

### Q4: 익절이 안 됨
```
원인: 0.25% 도달 전에 반전
해결:
- FIXED_TAKE_PROFIT_PCT 낮추기 (0.25→0.2)
- TIME_STOP_MINUTES 줄이기 (5→3)
```

---

## 📝 체크리스트

### 실행 전
- [ ] `.env` 파일 설정 완료
- [ ] API 키 발급 및 입력
- [ ] 계좌 잔고 확인 (최소 5만원)
- [ ] `USE_FIXED_STOPS=true` 확인
- [ ] `TIMEFRAME=1m` 확인
- [ ] 네트워크 안정성 확인

### 실행 중
- [ ] 첫 1시간 모니터링
- [ ] 첫 거래 발생 확인
- [ ] 손익 로그 확인
- [ ] 리스크 한도 동작 확인

### 실행 후
- [ ] CSV 로그 분석
- [ ] 승률 계산
- [ ] 평균 보유 시간 확인
- [ ] 거래 빈도 확인

---

## 🎓 학습 가이드

### 1주차: 관찰
- 봇 실행만 하고 관찰
- 로그 분석법 익히기
- 레짐 변화 패턴 파악

### 2주차: 소액 테스트
- 10만원으로 실전 테스트
- 파라미터 조정 실험
- 성과 분석

### 3주차: 최적화
- 최적 파라미터 찾기
- 시간대별 성과 분석
- 심볼별 성과 비교

### 4주차: 스케일업
- 자금 점진적 증액
- 리스크 관리 강화
- 장기 운영 시작

---

## 🔗 참고 자료

- [업비트 API 문서](https://docs.upbit.com/)
- [CCXT 문서](https://docs.ccxt.com/)
- [스캘핑 전략 가이드](https://www.investopedia.com/articles/trading/05/scalping.asp)

---

**면책 조항**: 이 봇은 교육 및 연구 목적으로 제공됩니다. 실제 거래에서 발생하는 손실에 대해 개발자는 책임지지 않습니다. 반드시 소액으로 테스트한 후 사용하세요.
