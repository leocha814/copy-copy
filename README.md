# Upbit Trading Bot - Mean Reversion Strategy

업비트 거래소에서 동작하는 RSI + 볼린저밴드 기반 평균회귀 스캘핑 알고리즘입니다.

## 주요 특징

### 전략

- **시장 상태 감지**: ADX/ATR 기반 레짐 감지 (횡보/상승추세/하락추세)
- **평균회귀 진입**: RSI 과매도/과매수 + 볼린저밴드 이탈 조합
- **스마트 청산**: 중간 밴드 회귀 or ATR 기반 손절/익절
- **레짐별 분기**: 횡보장에서만 활성화, 추세장 시 일시정지

### 리스크 관리

- **포지션 사이징**: ATR 기반 동적 크기 조절
- **손절/익절**: ATR의 2배/3배 자동 설정
- **계좌 보호**: 일일 손실 한도 5%, 최대 드로우다운 15%
- **연속 손실 제한**: 5회 연속 손실 시 자동 중단
- **변동성 조절**: 급등 감지 시 포지션 축소

### 실행 효율

- **지정가 우선**: 슬리피지 최소화, 타임아웃 시 시장가 전환
- **부분 체결 처리**: 미체결 주문 추적 및 재주문
- **슬리피지 모니터링**: 실시간 체결 품질 추적

### 모니터링

- **구조적 로깅**: CSV 형식 (ts, lvl, src, sym, evt, msg, kv)
- **텔레그램 알림**: 포지션 개시/청산, 리스크 경고, 일일 요약
- **실시간 상태**: 계좌 잔고, 미실현손익, 연속손실 추적

## 시스템 구조

```
src/
├── core/         # 공용 타입, 유틸, 시간/가격 변환
├── exchange/     # CCXT 래퍼 (업비트 전용 구현)
├── indicators/   # RSI, BB, ADX, ATR, MAs
├── strategy/     # regime_detector, mean_reversion
├── risk/         # risk_manager (sizing, stops, DD control)
├── exec/         # order_router, position_tracker
├── monitor/      # logger (CSV), alerts (Telegram)
└── app/          # main (런처), config (.env 로딩)
```

## 설치 및 실행

### 1. 의존성 설치

```bash
pip install -r requirements.txt
```

### 2. 환경 설정

```bash
cp .env.example .env
# .env 파일을 열어 UPBIT_API_KEY와 UPBIT_API_SECRET 입력
```

### 3. 실행

```bash
python -m src.app.main
```

## 환경 변수 설정

`.env` 파일에서 다음 파라미터를 조정할 수 있습니다:

### 필수 설정

- `UPBIT_API_KEY`: 업비트 API 키
- `UPBIT_API_SECRET`: 업비트 API 시크릿

### 전략 파라미터

- `TRADING_SYMBOLS`: 거래 심볼 (쉼표 구분, 예: BTC/KRW,ETH/KRW)
- `TIMEFRAME`: 캔들 타임프레임 (1m, 5m, 15m, 1h 등)
- `RSI_PERIOD`: RSI 계산 기간 (기본: 14)
- `RSI_OVERSOLD`: RSI 과매도 기준 (기본: 30)
- `RSI_OVERBOUGHT`: RSI 과매수 기준 (기본: 70)
- `BB_PERIOD`: 볼린저밴드 기간 (기본: 20)
- `BB_STD_DEV`: 볼린저밴드 표준편차 배수 (기본: 2.0)
- `ADX_THRESHOLD_LOW`: 횡보장 판단 ADX 하한 (기본: 20)
- `ADX_THRESHOLD_HIGH`: 추세장 판단 ADX 상한 (기본: 25)

### 리스크 파라미터

- `PER_TRADE_RISK`: 거래당 리스크 % (기본: 2.0)
- `MAX_DAILY_LOSS`: 일일 최대 손실 % (기본: 5.0)
- `MAX_CONSECUTIVE_LOSSES`: 최대 연속 손실 횟수 (기본: 5)
- `MAX_DRAWDOWN`: 최대 드로우다운 % (기본: 15.0)
- `STOP_ATR_MULTIPLIER`: 손절 ATR 배수 (기본: 2.0)
- `TARGET_ATR_MULTIPLIER`: 익절 ATR 배수 (기본: 3.0)

### 텔레그램 알림 (선택사항)

- `TELEGRAM_BOT_TOKEN`: 텔레그램 봇 토큰
- `TELEGRAM_CHAT_ID`: 텔레그램 채팅 ID

## 안전 수칙

### ⚠️ 실전 운용 전 필수 체크리스트

1. **백테스트 수행**: 다양한 시장 상황에서 전략 검증
2. **소액 테스트**: 최소 금액으로 실전 테스트
3. **API 권한 제한**: 출금 권한 비활성화
4. **모니터링 체계**: 텔레그램 알림 설정
5. **리스크 한도 확인**: 일일 손실 한도 및 드로우다운 설정
6. **네트워크 안정성**: 안정적인 인터넷 연결 확보

### 🚨 주의사항

- **절대 실제 자금 전액 투입 금지**: 손실 감내 가능한 금액만 사용
- **API 키 보안**: .env 파일을 절대 공개 저장소에 커밋하지 말 것
- **시장 급변 대응**: 중요 경제 지표 발표 시 알고리즘 일시정지 고려
- **주기적 점검**: 전략 성과를 정기적으로 리뷰하고 파라미터 조정
- **슬리피지 모니터링**: 슬리피지가 과도하면 거래 규모 축소

## 로그 분석

로그는 `logs/` 디렉토리에 CSV 형식으로 저장됩니다.

### 로그 형식

```csv
ts,lvl,src,sym,evt,msg,kv
2024-01-01T12:00:00Z,INFO,strategy,BTC/KRW,signal,"Long signal: RSI=25",{"rsi":25,"bb_pos":-120}
```

### Python으로 로그 분석

```python
import pandas as pd

# 로그 읽기
df = pd.read_csv('logs/trading_20240101.csv')

# 신호 필터링
signals = df[df['evt'] == 'signal']

# 거래 통계
trades = df[df['evt'] == 'trade_closed']
print(f"Total trades: {len(trades)}")
print(f"Win rate: {(trades['msg'].str.contains('PnL: [0-9]+\\.').sum() / len(trades)) * 100:.1f}%")
```

## 개발 및 커스터마이징

### 새로운 지표 추가

`src/indicators/indicators.py`에 순수 함수로 구현:

```python
def calculate_my_indicator(prices: List[float], period: int) -> np.ndarray:
    # 구현
    return result
```

### 전략 수정

`src/strategy/mean_reversion.py`의 `generate_entry_signal()` 메서드 수정

### 리스크 규칙 조정

`src/risk/risk_manager.py`에서 한도 체크 로직 수정

## 라이선스

이 프로젝트는 교육 및 연구 목적으로 제공됩니다.
실제 거래에서 발생하는 손실에 대해 개발자는 책임지지 않습니다.

## 문의 및 기여

이슈 및 개선 제안은 GitHub Issues를 통해 제출해주세요.
