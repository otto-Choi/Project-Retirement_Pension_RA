# 프로젝트 파일 구조

> 마지막 업데이트: 2026-05-19

```
퇴직연금 _XAI/
├── README.md                          ← 프로젝트 전체 아카이브
├── STRUCTURE.md                       ← 이 파일 (파일 구조 명세)
├── CLAUDE.md                          ← Claude Code 작업 지침
│
├── src/                               ← 실행 스크립트 (Python)
│   ├── step3_collect_data.py          ← Step 3: 기초자산 지수 데이터 수집
│   ├── step3_window_analysis.py       ← Step 3: 최적 롤링 윈도우 탐색
│   ├── step4_portfolio.py             ← Step 4: BL 내재수익률 + Sortino-max 포트폴리오
│   ├── step5_constrained.py           ← Step 5: 지역 제약 포트폴리오 (확정 버전)
│   ├── step5b_momentum_views.py       ← Step 5b: 모멘텀 뷰 추가 실험
│   ├── step6_cal.py                   ← Step 6: CAL 및 Risk Score → w_risky 매핑
│   ├── step6b_current_allocation.py   ← Step 6b: 현재 시점 배분 산출
│   ├── step7_lambda_implied.py        ← Step 7: 내재 λ 추정
│   ├── 08a_step8_user_xai.py          ← Step 8a: 사용자 XAI 출력
│   └── portfolio_engine.py            ← 통합 엔진: Risk Score → 포트폴리오 + XAI
│
├── notebooks/                         ← 분석·검증 노트북
│   ├── README.md
│   ├── briefing_20260518.ipynb        ← 2026-05-18 브리핑용 종합 결과
│   ├── step6_7_check.ipynb            ← Step 6~7 검증
│   ├── step8a_user_xai.ipynb          ← Step 8a: 사용자 XAI 탐색
│   └── step8b_analysis_xai.ipynb      ← Step 8b: 분석용 XAI 탐색
│
├── data/                              ← 모든 입력 데이터 (통합)
│   ├── README.md
│   ├── index_returns.parquet          ← 기초자산 지수 일별 수익률 (추정용)
│   ├── slot_returns.parquet           ← ETF 슬롯별 일별 수익률 (OOS 평가용)
│   ├── mar_series.parquet             ← 시변 MAR (ECOS 정기예금 금리)
│   ├── year_end_best.csv              ← 연도별×슬롯별 선정 ETF + AUM
│   ├── year_end_universe.csv          ← 연도별 투자 가능 ETF 유니버스
│   ├── filtered_universe.csv          ← 레버리지·인버스 제거 후 최종 ETF 목록
│   ├── etf_listed.csv                 ← KRX 현재 상장 ETF 기본정보
│   ├── etf_delisted.csv               ← KIND 상장폐지 ETF 목록
│   ├── etf_analysis_list.csv          ← 슬롯 매핑·분석 대상 ETF 목록
│   ├── etf_prices.csv                 ← ETF 가격 시계열
│   ├── 001_상장_ETF.csv               ← KRX 원본 상장 ETF 데이터
│   ├── 002_상폐_ETF.csv               ← KIND 원본 상장폐지 ETF 데이터
│   ├── macro_monthly.csv              ← ECOS 거시지표 (월별)
│   ├── macro_annual.csv               ← ECOS 거시지표 (연간)
│   └── macro_daily.csv                ← 거시지표 일별 변환값
│
├── results/                           ← 파이프라인 출력 결과
│   ├── current/                       ← 현재 시점 최신 배분 결과
│   │   ├── current_meta.json
│   │   ├── current_weights_sortino.csv
│   │   ├── current_weights_mvp.csv
│   │   └── current_cal_allocations.csv
│   ├── step3/
│   │   └── window_analysis_result.csv ← 윈도우별 4기준 성과 비교 → 5년 확정
│   ├── step4/
│   │   ├── portfolio_weights.parquet  ← 비제약 Sortino-max 분기별 비중
│   │   ├── portfolio_performance.parquet
│   │   ├── summary.csv
│   │   └── weights_pivot.csv
│   ├── step5/                         ← 지역제약 포트폴리오 (US≤50%, KR≤50%, EM≤15%)
│   │   ├── portfolio_weights_constrained.parquet
│   │   ├── portfolio_weights_mvp.parquet
│   │   ├── portfolio_performance_constrained.parquet
│   │   ├── portfolio_performance_mvp.parquet
│   │   ├── pi_history.parquet
│   │   ├── sigma_down_history.parquet
│   │   ├── binding_history.parquet
│   │   ├── comparison.csv
│   │   └── weights_constrained.csv
│   ├── step5b/                        ← 모멘텀 뷰 추가 실험 결과
│   │   ├── portfolio_weights_constrained.parquet
│   │   ├── portfolio_weights_mvp.parquet
│   │   ├── portfolio_performance_constrained.parquet
│   │   ├── portfolio_performance_mvp.parquet
│   │   ├── pi_history.parquet
│   │   ├── pi_prior_history.parquet
│   │   ├── sigma_down_history.parquet
│   │   ├── binding_history.parquet
│   │   ├── comparison.csv
│   │   └── weights_constrained.csv
│   ├── step6/
│   │   ├── cal_demo_allocations.csv
│   │   ├── cal_demo_allocations.parquet
│   │   └── risk_score_map.csv
│   ├── step7/
│   │   ├── lambda_implied.csv
│   │   └── lambda_implied.parquet
│   └── step8/
│       └── figures/                   ← XAI 시각화 출력 이미지
│           ├── a0_opportunity_cost.png
│           ├── a1_cal_flow.png
│           ├── a2_risk_waterfall.png
│           ├── a3_lifestyle_path.png
│           ├── a4_loss_gauge.png
│           ├── a5_lambda_gauge.png
│           └── a6_mvp_vs_sortino.png
│
├── docs/                              ← 프로젝트 문서
│   ├── 01_project_overview.md         ← 전체 개요, 파이프라인, 진행 현황, 발표 흐름
│   ├── 02_pipeline_design.md          ← 포트폴리오 파트 설계 계획
│   ├── 03_xai_design.md               ← XAI 레이어 A·B 전체 설계 (Step 8)
│   ├── 04_progress_steps1_5.md        ← Step 1~5 진행 기록 및 확정 파라미터
│   ├── 05_persona_risk_scoring.md     ← Risk Score 설계, 텍스트 처리 파이프라인
│   ├── 06_dataset_reference.md        ← 데이터셋 명세서
│   ├── 07_meeting_notes.md            ← 회의록 요약 (2026-05-05)
│   ├── 08_feedback_log.md             ← Q&A 준비, 이론 근거, 발표 체크리스트
│   ├── 09_data_collection_plan.md     ← ETF 수집 절차 + 거시지표 수집 설계·현황
│   ├── 10_todo.md                     ← 남은 작업 목록
│   ├── 11_authored_feedback.md        ← 직접 작성 — Step 1~5 피드백 원본
│   ├── 12_step8_plan.md               ← Step 8 구현 계획
│   ├── 13_model_review_and_improvement.md ← 모델 검토 및 개선 사항
│   ├── project_proposal.pdf           ← 초기 기획서
│   ├── etf_data_spec.pdf              ← ETF 데이터 명세서
│   └── legacy/                        ← 원본 문서 보존
│       ├── document/                  ← 001~010 원문 (md, pdf)
│       └── notebooks/                 ← 구버전 분석 노트 (md)
│
└── documents/                         ← 팀 공유 문서
    ├── README.md
    └── 003_데이터_수집_계획.md
```
