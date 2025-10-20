# Upbit Automated Trading System

안전한 업비트 REST API 실거래 자동매매 프로젝트입니다.

RSI + 볼린저 밴드 되돌림 스캘핑 전략을 지원하며, 실시간 가격 모니터링과 수동/자동 거래가 가능합니다.

## 프로젝트 구조

```
├── README.md                    # 프로젝트 설명서
├── requirements.txt             # Python 의존성 패키지
├── .env.example                # 환경변수 템플릿
├── .env                        # 실제 API 키 (git ignore)
├── src/
│   ├── __init__.py
│   ├── config.py               # 환경설정 로딩
│   ├── upbit_api.py           # 업비트 API 래퍼 클래스
│   ├── trader.py              # 매매 로직 구현
│   ├── logger.py              # 로깅 설정
│   ├── price_watcher.py       # 실시간 가격 모니터링
│   ├── state_manager.py       # 거래 상태 관리
│   ├── runner.py              # 자동매매 메인 실행기
│   ├── strategy/
│   │   ├── __init__.py
│   │   ├── indicators.py      # 기술적 지표 (RSI, 볼린저밴드)
│   │   └── rsi_bollinger_scalper.py  # RSI+볼린저 스캘핑 전략
│   └── utils/
│       ├── __init__.py
│       └── signature.py       # JWT 서명 생성
├── scripts/
│   ├── check_connection.py    # API 연결 테스트
│   ├── manual_trade.py        # 수동 거래 인터페이스
│   ├── test_trading.py        # 거래 기능 테스트
│   └── test_order_types.py    # 주문 타입 테스트
├── tests/
│   ├── __init__.py
│   └── test_strategy.py       # 전략 단위 테스트
├── .state/                    # 거래 상태 저장
└── logs/                      # 로그 파일 저장소
```

## 각 파일의 역할

### 핵심 모듈
- **src/config.py**: .env 파일에서 API 키와 설정 로딩
- **src/upbit_api.py**: 업비트 API 호출 래퍼 (잔고조회, 시세조회, 주문, 취소)
- **src/trader.py**: 매수/매도 함수, 수량·가격 계산, 예외처리
- **src/logger.py**: 파일 및 콘솔 로깅 설정
- **src/price_watcher.py**: 실시간 가격 모니터링 (1초 주기)
- **src/state_manager.py**: 거래 상태 및 포지션 관리
- **src/runner.py**: 자동매매 메인 실행기

### 전략 모듈
- **src/strategy/indicators.py**: 기술적 지표 계산 (RSI, 볼린저 밴드)
- **src/strategy/rsi_bollinger_scalper.py**: RSI + 볼린저 되돌림 스캘핑 전략

### 유틸리티
- **src/utils/signature.py**: JWT 토큰 서명 생성 로직

### 스크립트
- **scripts/check_connection.py**: API 연결 및 기본 기능 테스트
- **scripts/manual_trade.py**: 콘솔 기반 수동 거래 인터페이스
- **scripts/test_trading.py**: 거래 기능 종합 테스트
- **scripts/test_order_types.py**: 주문 타입별 파라미터 테스트

### 테스트
- **tests/test_strategy.py**: 스캘핑 전략 단위 테스트

## 설치 및 설정

1. 의존성 설치:
```bash
pip install -r requirements.txt
```

2. 환경변수 설정:
```bash
cp .env.example .env
# .env 파일을 편집하여 업비트 API 키 입력
```

3. API 연결 테스트:
```bash
python scripts/check_connection.py
```

## 사용법

### 1. 수동 거래 (실시간 모니터링 + 콘솔 주문)
```bash
python scripts/manual_trade.py
```

사용 가능한 명령어:
- `buy BTC 50000 market` - BTC 50,000원 시장가 매수
- `buy ETH 0.1 100000` - ETH 0.1개 100,000원 지정가 매수  
- `sell BTC 0.001 market` - BTC 0.001개 시장가 매도
- `sell ETH 0.1 150000` - ETH 0.1개 150,000원 지정가 매도
- `cancel [UUID]` - 주문 취소
- `balance` - 잔고 조회
- `orders` - 미체결 주문 조회

### 2. 자동매매 (RSI + 볼린저 스캘핑)

#### DRYRUN 모드 (시뮬레이션, 권장)
```bash
python src/runner.py --market KRW-BTC --krw 10000 --mode DRYRUN
```

#### LIVE 모드 (실거래, 주의!)
```bash
python src/runner.py --market KRW-ETH --krw 5000 --mode LIVE
```

#### 환경변수로 모드 설정
```bash
export TRADING_MODE=DRYRUN
python src/runner.py --market KRW-BTC --krw 10000
```

### 3. 전략 설정 커스터마이징

```python
from src.strategy.rsi_bollinger_scalper import ScalperConfig, RSIBollingerScalper

# 커스텀 설정
config = ScalperConfig(
    rsi_window=14,           # RSI 계산 기간
    bb_window=20,            # 볼린저 밴드 기간  
    bb_std=2.0,              # 볼린저 밴드 표준편차 배수
    rsi_oversold=30.0,       # RSI 과매도 기준
    take_profit=0.005,       # 익절 기준 (0.5%)
    stop_loss=-0.004,        # 손절 기준 (-0.4%)
    max_hold_sec=300,        # 최대 보유시간 (5분)
    use_ranging_filter=True  # 횡보 필터 사용
)

strategy = RSIBollingerScalper(config)
```

## 전략 개요

### RSI + 볼린저 되돌림 스캘핑
- **목표**: 횡보장에서 짧은 시간 내 여러 번 진입/청산
- **진입 조건**: 가격이 볼린저 하단 하향 이탈 AND RSI < 30
- **청산 조건**: +0.5% 익절 OR -0.4% 손절 OR 보유 5분 경과
- **필터**: RSI 40~60 범위일 때만 활성화 (횡보 구간)

### 안전장치
- **기본 DRYRUN 모드**: 실제 주문 없이 시뮬레이션
- **API 레이트 리밋 준수**: 최소 1초 주기 실행
- **포지션 1개 제한**: 중복 진입 방지
- **쿨다운**: 주문 후 10초 대기
- **에러 핸들링**: 재시도 전 백오프 지연

## 테스트

### 전략 단위 테스트
```bash
python tests/test_strategy.py
```

### 거래 기능 테스트
```bash
python scripts/test_trading.py
python scripts/test_order_types.py
```

## 로그 및 상태 관리

- **거래 로그**: `logs/orders.log` - 모든 주문 기록
- **일반 로그**: `logs/trading_YYYYMMDD.log` - 일반 로그
- **상태 파일**: `.state/trade_state_krw_btc.json` - 포지션 상태 저장

## 보안 주의사항

- API 키는 절대 코드에 직접 포함하지 마세요
- .env 파일을 git에 커밋하지 마세요
- DRYRUN으로 충분히 테스트 후 LIVE 모드 사용
- 최소 주문단위와 잔고를 항상 확인하세요
- 실거래 시 소액으로 시작하세요

## 면책조항

이 프로젝트는 교육 목적으로 제공됩니다. 실거래 사용 시 발생하는 손실에 대해 책임지지 않습니다.
자동매매는 높은 위험을 수반하므로 충분한 이해와 테스트 후 사용하시기 바랍니다.