# Dev Standards

- 코드 스타일: PEP8 + 타입힌트 필수. public 함수에 docstring.
- 디렉터리 설계(권장):
  src/
  core/ # 공용 타입, 유틸, 시간/가격 변환
  exchange/ # CCXT 래퍼(업비트 전용 구현 + 인터페이스)
  indicators/ # RSI, BB, ADX, ATR, MAs
  strategy/ # regime_detector.py, mean_reversion.py, momentum.py
  risk/ # risk_manager.py (sizing, stops, DD control)
  exec/ # order_router.py (시장/지정가), position_tracker.py
  sim/ # backtest_engine.py, cost_model.py, data_feed.py
  monitor/ # logger.py, alerts.py(텔레그램 훅), dashboard_stub.py
  app/ # main.py(런처), config.py(.env 로딩)
- 로깅: CSV(기본). 컬럼: ts, lvl, src, sym, evt, msg, kv(json)
- 설정: .env -> config.py에서 읽기(예: UPBIT_API_KEY, MAX_DD, PER_TRADE_RISK 등)
- 예외 메시지: 사용자가 원인·조치 파악 가능하게 작성
