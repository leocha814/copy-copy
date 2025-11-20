# Review Checklist

- [Regime] ADX/ATR로 range/trend 정확히 분기하는가?
- [Entry] range일 때만 RSI+BB 진입? 추가 확인(캔들/거래량) 반영?
- [Exit] 중간밴드/ATR 기반, 시간제한 청산 구현?
- [Risk] per-trade % 위험, 일손실 %, 연속 손실 N, Max DD 트리거 동작?
- [Slippage] 비용모델(수수료+슬리피지) 백테스트에 반영?
- [Fail-safe] API 타임아웃/주문 미체결/부분체결 처리 완비?
- [Pause] 변동성 급증/레인지 붕괴 시 자동 일시정지?
- [Config] 모든 매개변수 .env/설정으로 분리?
- [Logs] 체결/신호/상태변화/에러 로그가 재현 가능성을 담보?
- [Tests] 지표·리스크 핵심 함수에 단위 테스트?
