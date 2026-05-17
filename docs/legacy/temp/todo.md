# 포트폴리오 엔진 잔여 작업

## 1. CVaR 모듈
- [ ] `slot_returns` 기반 historical simulation CVaR (95%, 99%)
- [ ] w_risky별 최종 수익률 분포 → VaR / CVaR 산출
- [ ] `portfolio_engine.py`에 `get_cvar(w_risky, query_date)` 추가

## 2. CAL 동적 테이블
- [ ] w_risky 0~70% 구간 → (E[R], σ_down, CVaR_95) 연속 산출
- [ ] `get_cal_curve(query_date)` → 프론트 슬라이더 지원용 dict 반환

## 3. 스트레스 테스트
- [ ] 2020 COVID (2020-02-01 ~ 2020-04-30) 구간 성과
- [ ] 2022 금리충격 (2022-01-01 ~ 2022-12-31) 구간 성과
- [ ] w_risky별 최대손실(MDD), CVaR 비교표
- [ ] `get_stress_test(scenario)` 추가

## 4. 기대/요구수익률 표시 명확화
- [ ] BL 기대수익률(Π 기반, 모델 내부용) vs 역사적 평균수익률(사용자 표시용) 분리
- [ ] `get_portfolio()` 반환에 `expected_return_display` 필드 추가 (역사적 롤링 평균)

## 5. 리밸런싱 — 즉석 계산 지원
- [ ] 분기 리밸런싱 기준: `portfolio_weights_constrained.parquet` 사용 (기본)
- [ ] 임의 시점 즉석 계산: `get_portfolio(query_date, realtime=True)` → 해당 시점 5yr 윈도우로 Σ_down, Π 재산출 후 최적화
- [ ] 두 결과(정기 vs 즉석) 병기하여 차이 표시

## 6. 금액 환산
- [ ] `current_balance` 있으면 `portfolio` 반환에 `amount_krw` 필드 추가
- [ ] 슬롯별 "X만원" 표시 문자열 포함
