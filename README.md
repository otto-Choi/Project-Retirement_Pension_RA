# XAI 기반 퇴직연금 ETF 포트폴리오 최적화

> **학술제 발표 프로젝트** | DArt-B | 2026  
> **성격**: 데이터 기반 투자 **참고 정보** 시스템 (투자 일임·자문 아님)

---

## 한 줄 정의

한국 퇴직연금(DC/IRP) 가입자를 위해, 개인 Risk Score 기반으로 개인화된 ETF 포트폴리오 비중을 산출하고, XAI로 그 근거를 투명하게 제시하는 데이터 기반 참고 정보 시스템.

---

## 법적 고지

이 시스템의 모든 출력은 「자본시장법」 제6조에 따라 **투자 추천이 아닌 투자 참고 정보**입니다.  
의사결정권은 전적으로 투자자에게 있으며, XAI를 통해 분석 근거를 투명하게 공개합니다.

---

## 프로젝트 구조

```
퇴직연금 _XAI/
├── README.md                          ← 이 파일 (프로젝트 전체 아카이브)
├── CLAUDE.md                          ← Claude Code 작업 지침
│
├── src/                               ← 실행 스크립트 (Python)
│   ├── step3_collect_data.py          ← Step 3: 기초자산 지수 데이터 수집
│   ├── step3_window_analysis.py       ← Step 3: 최적 롤링 윈도우 탐색
│   ├── step4_portfolio.py             ← Step 4: BL 내재수익률 + Sortino-max 포트폴리오
│   ├── step5_constrained.py           ← Step 5: 지역 제약 포트폴리오 (확정 버전)
│   └── portfolio_engine.py            ← 통합 엔진: Risk Score → 포트폴리오 + XAI
│
├── data/                              ← 모든 입력 데이터 (통합)
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
│   ├── macro_monthly.csv              ← ECOS 거시지표 (월별)
│   ├── macro_annual.csv               ← ECOS 거시지표 (연간)
│   └── macro_daily.csv                ← 거시지표 일별 변환값
│
├── results/                           ← 파이프라인 출력 결과
│   ├── step3/
│   │   └── window_analysis_result.csv ← 윈도우별 4기준 성과 비교 → 5년 확정
│   ├── step4/
│   │   ├── portfolio_weights.parquet  ← 비제약 Sortino-max 분기별 비중
│   │   ├── portfolio_performance.parquet
│   │   ├── summary.csv
│   │   └── weights_pivot.csv
│   └── step5/
│       ├── portfolio_weights_constrained.parquet  ← 지역제약 포트폴리오 비중 (확정)
│       ├── portfolio_weights_mvp.parquet           ← MVP 포트폴리오 비중
│       ├── portfolio_performance_constrained.parquet
│       ├── portfolio_performance_mvp.parquet
│       ├── pi_history.parquet         ← 분기별 BL 내재수익률 Π 이력
│       ├── sigma_down_history.parquet ← 분기별 하방공분산 이력
│       ├── binding_history.parquet    ← 제약 활성화 이력 (XAI B3 소스)
│       ├── comparison.csv             ← 비제약 vs 지역제약 성과 비교
│       └── weights_constrained.csv    ← 최신 비중 (CSV, 가독용)
│
└── docs/                              ← 프로젝트 문서 (아래 목록 참조)
```

---

## 핵심 설계 파라미터

| 파라미터 | 값 | 근거 |
|---------|-----|------|
| 위험 측도 | 하방공분산 Σ_down (Estrada 2007) | 정규분포 가정 없이 하방위험만 포착 |
| 기대수익률 | BL 내재수익률 Π = λ·Σ_down·w_mkt | 시장 포트폴리오 역산, 추정 오류 최소화 |
| λ | 3.0 | He & Litterman(1999) 2.5 + 퇴직연금 보수성 반영 |
| MAR | ECOS 정기예금 수신금리 (시변) | 무위험 기준, 분기 시변 |
| 최적화 목적 | Sortino 비율 최대화 (SLSQP) | 하방위험 중심, 퇴직연금 특성 일관성 |
| 윈도우 | 5년 (1,260거래일) | Step 3 4기준 종합 선정 |
| 리밸런싱 | 분기 (63거래일) | 백테스트 기준 |
| 개별 자산 상한 | 40% | 단일 자산 과집중 방지 |
| 지역 제약 | US≤50%, KR≤50%, EM≤15% | Step 5 확정 |
| 위험자산 상한 | 70% | DC/IRP 법적 상한 |

---

## 13개 슬롯 구조

```
국내주식_코스피 / 국내주식_코스닥
미국주식_SP500 / 미국주식_나스닥
신흥국_인도 / 신흥국_중국
국내채권_국고채단중기 / 국내채권_국고채장기 / 국내채권_회사채 / 국내채권_종합
해외채권_미국국채
원자재_금
무위험(현금성)
```

---

## 백테스트 주요 결과 (2016~2025)

| 전략 | 누적수익률 | MDD | 평균 소르티노 |
|------|-----------|-----|-------------|
| Sortino-max (비제약, Step 4) | +120.6% | -34.8% | — |
| Sortino-max (지역제약, Step 5) | +94.9% | -24.4% | — |
| MVP (지역제약, Step 5) | — | — | — |

> Step 5 비교표: `notebooks/step5_results/comparison.csv`

---

## 개인화 파이프라인 (Risk Score → w_risky)

```
Risk Score (1~10점) =
  0.20 × 은퇴기간 점수  +  0.15 × 나이 점수
+ 0.15 × 직업 점수     +  0.20 × 자금여력 점수
+ 0.15 × 가족 점수     +  0.15 × 라이프스타일 점수

라이프스타일: 엔비디아 페르소나 텍스트 → ko-sroberta embedding
             → KMeans(500군집) → GPT 점수화 → Big Five z-score
             → 0.45×openness_z - 0.45×stability_z + 0.10×conscientiousness_z
             → qcut → 1~5등급

위험군 → w_risky:
  1~2점: 초보수형 → 0%   (전액 무위험)
  3~4점: 보수형   → 20%
  5~6점: 중립형   → 40%
  7~8점: 성장형   → 60%
  9~10점: 공격형  → 70%  (DC/IRP 법적 상한)

최종 배분 = w_risky × Sortino-max 포트폴리오
           + (1 - w_risky) × 무위험자산
```

---

## 스크립트 실행 순서

```bash
# 1. 기초자산 지수 데이터 수집 (pykrx, yfinance, ECOS)
python src/step3_collect_data.py

# 2. 최적 윈도우 탐색 (→ notebooks/step3_results/)
python src/step3_window_analysis.py

# 3. 비제약 Sortino-max 포트폴리오 (→ notebooks/step4_results/)
python src/step4_portfolio.py

# 4. 지역제약 포트폴리오 + MVP (→ notebooks/step5_results/)
python src/step5_constrained.py

# 5. 개별 사용자 조회 (portfolio_engine.py 직접 import)
from src.portfolio_engine import get_portfolio_for_user
result = get_portfolio_for_user(
    risk_score=6.5,
    query_date='2025-03-31',
    current_balance=50_000_000
)
```

---

## 진행 현황 (2026-05-15 기준)

| 단계 | 상태 | 산출물 |
|------|------|--------|
| Step 1~2: ETF 데이터 수집·정제 | ✅ 완료 | `notebooks/inputs/` |
| Step 3: 윈도우 탐색 (5yr 확정) | ✅ 완료 | `step3_results/window_analysis_result.csv` |
| Step 4: BL + Sortino-max | ✅ 완료 (λ=3.0 재실행) | `step4_results/` |
| Step 5: 지역제약 포트폴리오 | ✅ 완료 (EM≤15% 재실행) | `step5_results/` |
| portfolio_engine.py | ✅ 완료 | XAI Layer A(a0~a6) + B(b1~b4) |
| Risk Score 설계 | ✅ 문서 완성 | `docs/05_persona_risk_scoring.md` |
| 텍스트 파이프라인 기획 | ✅ 문서 완성 | `docs/05_persona_risk_scoring.md` §6 |
| Step 6~7 (CAL, 내재 λ) | ⚠️ 설계 완료, 코드 미구현 | engine 내 로직 포함 |
| CVaR / 스트레스 테스트 | ❌ 미구현 | `docs/10_todo.md` |
| Streamlit 데모 | ❌ 미구현 | `docs/10_todo.md` |

---

## 다음 우선 작업

1. `CVaR 모듈`: `get_cvar(w_risky, query_date)` — historical simulation 95%/99%
2. `CAL 동적 테이블`: `get_cal_curve(query_date)` — w_risky 0~70% 연속 산출
3. `스트레스 테스트`: 2020 COVID / 2022 금리충격 구간 성과
4. `텍스트 파이프라인 실행`: Embedding → KMeans → GPT 점수화 → z-score
5. `Streamlit 데모`: 4개 화면 프로토타입

---

## 문서 목록 (docs/)

| 파일 | 내용 |
|------|------|
| [01_project_overview.md](docs/01_project_overview.md) | 전체 개요, 파이프라인, 진행 현황, 발표 흐름 |
| [02_pipeline_design.md](docs/02_pipeline_design.md) | 포트폴리오 파트 설계 계획 |
| [03_xai_design.md](docs/03_xai_design.md) | XAI 레이어 A·B 전체 설계 (Step 8) |
| [04_progress_steps1_5.md](docs/04_progress_steps1_5.md) | Step 1~5 진행 기록 및 확정 파라미터 |
| [05_persona_risk_scoring.md](docs/05_persona_risk_scoring.md) | Risk Score 설계, 텍스트 처리 파이프라인, 리밸런싱 서비스 |
| [06_dataset_reference.md](docs/06_dataset_reference.md) | 데이터셋 명세서 |
| [07_meeting_notes.md](docs/07_meeting_notes.md) | 회의록 요약 (2026-05-05) |
| [08_feedback_log.md](docs/08_feedback_log.md) | Q&A 준비, 이론 근거, 발표 체크리스트 |
| [09_data_collection_plan.md](docs/09_data_collection_plan.md) | ETF 수집 절차 + 거시지표 수집 설계·현황 |
| [10_todo.md](docs/10_todo.md) | 남은 작업 목록 |
| [11_authored_feedback.md](docs/11_authored_feedback.md) | **직접 작성** — Step 1~5 피드백 원본 (구현 오류 발견·수정 지시·설계 결정 근거) |
| [project_proposal.pdf](docs/project_proposal.pdf) | 초기 기획서 |
| [etf_data_spec.pdf](docs/etf_data_spec.pdf) | ETF 데이터 명세서 |
| [legacy/document/](docs/legacy/document/) | 원본 document/ 보존 (001~010 원문) |
| [legacy/temp/](docs/legacy/temp/) | 원본 temp/ 보존 (Step 3~5 구버전 스크립트·페르소나 파일) |

---

## 기여자 — 최철원 (포트폴리오 파트 리드)

> 금융 도메인 전문 역할. 이론 설계·파라미터 결정·구현 검증·발표 대비 전 영역 주도.  
> 이 섹션은 회의록(07), 피드백 로그(08, 11) 원문을 기반으로 작성.

---

### 1. 전체 파이프라인 아키텍처 설계 (2026-05-05 회의)

팀 회의에서 전체 6단계 파이프라인을 직접 제안하고 확정:

```
1. 페르소나 데이터 → 변수 추출 → Risk Score (위험 허용 수준)
2. ETF 데이터 수집·필터링 → 13개 슬롯 대표 ETF 선정
3. 시점별 최적 포트폴리오 산출 (BL + Sortino-max)
4. Risk Score → w_risky → 위험/안전자산 비중 결정
5. 최종 포트폴리오 출력 + XAI 설명
6. (추가) ETF 상품 직접 매칭
```

- MPT, 샤프 지수, CML/SML 등 이론 방향 제시 및 설계 주도
- ETF 선별 기준, 리밸런싱 주기 등 핵심 의사결정 주도
- ETF 데이터 1,100여 개 직접 수집 완료
- 페르소나 텍스트 데이터는 보조 역할(고정값)로 최소화할 것을 강하게 주장 → 팀 합의 도출
- 회의 녹음·텍스트 추출·회의록 정리까지 담당

---

### 2. 구현 오류 발견 및 수정 지시 (2026-05, 문서 009)

초기 구현된 코드를 직접 검토하여 5개 설계 의도 위반을 발견하고 수정 지시:

| 발견한 문제 | 의도한 설계 | 영향 |
|------------|-----------|------|
| ETF 선정 기준: AUM 최대 단순 선정 | 총보수(50%)·거래대금(30%)·AUM(20%) 가중평균 순위 | 총보수 낮은 ETF 탈락 가능 |
| 롤링 윈도우 탐색: ETF 수익률 사용 | 기초자산 지수 사용 (ETF 상장 이전까지 소급) | 분석 기간이 2023년 이후밖에 안 됨 |
| 최적 윈도우 기준: Sortino 최대 단일 기준 | MAE·소르티노·일관성·이상치 4기준 종합 | 단일 지표로 선택 시 왜곡 |
| MAR: 연 2.5% 고정 | ECOS 정기예금 금리 시변 적용 | 하방공분산·소르티노 전체가 실전과 달라짐 |
| 리밸런싱 주기: 월별(21일) | 분기(63거래일) — 실전 주기와 일치 | 검증 기준 자체가 무효 |

→ 수정 우선순위 정리 후 팀에 공유. 수정 후 Step 3~5 전체 재실행.

---

### 3. 핵심 파라미터 결정 및 이론 근거 수립 (2026-05-13, 문서 010)

#### λ = 3.0 결정

He & Litterman(1999)의 표준값 2.5를 퇴직연금 맥락에서 상향 조정. 결정 근거를 직접 정리:

- He & Litterman(1999): 시장 중립값 2.5 (Sharpe ≈ 0.5 가정)
- Merton(1969): 장기 투자자 위험회피계수 범위 2~4, 은퇴 준비 투자자는 상단(3~4)
- Blitz & van Vliet(2007): 퇴직연금 운용자 실효 λ 평균 2.8~3.2 실증
- Sortino 목적함수와 방향성 일관성: 하방위험 페널티 강화 → λ 상향 정합

#### EM(신흥국) ≤ 15% 제약 추가

US ≤ 50% 적용 이후 중국 ETF가 1.8% → 16.5%로 급증하는 문제를 직접 발견. 추가 제약 필요성과 근거를 정리:

- MSCI ACWI 내 신흥국 비중 ~12% (2024)
- 국민연금 해외 신흥국 목표 비중 5~10%
- 중국 고유 리스크: 자본통제·회계 투명성·2021 테크 규제 등 공분산이 포착 못하는 테일 리스크
- US·KR 상한 존재 + EM 무상한은 제약 비대칭 → EM 상한 추가로 일관성 확보

#### MVP 구현 결정

Sortino-max 단독 구현에서 MVP를 병행 구현해야 하는 이유를 정리:

- CAL 구성 시 리스크자산 포트폴리오의 하한 경계점
- "왜 MVP 대신 Sortino-max인가"에 대한 정량 근거
- XAI에서 Shapley value로 두 포트폴리오 비중 차이를 설명 → 학술적 타당성
- Step 7 CVaR와 3방향 비교 가능

---

### 4. 발표 대비 종합 피드백 보고서 작성 (문서 002/008)

학술제 발표 전 전 영역에 걸친 종합 피드백 보고서를 직접 작성:

- **발표 주제 적절성** — 핵심 통계(83.3%, 58조원) 출처 명시 지시, 경쟁사 XAI 미도입의 구조적 이유 분석
- **방법론 공백 해소** — SHAP 메타 모델 X/Y 변수 명세, ETF 50종 선정 기준, 백테스팅 구간 선택 근거
- **재무이론 방어 논리** — 다중공선성 VIF 기반 처리 프로세스, 조정베타 Blume(1971) 인용, 꼬리 위험 CVaR 보완 방향
- **심사위원 Q&A 5개** 예상 질문 + 답변 전략 수립
- **팀원 필수 학습 자료** — Markowitz, Sharpe, Merton, Lundberg·Lee(SHAP), Kahneman·Tversky 등 17개 논문 정리
- **최종 체크리스트** — 🔴 즉시·🟡 권고·🟢 완성도 3단계 우선순위 구분

---

### 5. 거시지표 수집 설계 (문서 005)

ECOS에서 수집할 거시지표를 직접 선정하고 분류 체계를 수립:

- 수집 완료 지표 20개 확인 (금리 4·물가 3·유동성 2·대외 1·실물경기 8·심리 2)
- 최우선 추가 5개 (실질GDP 분기, 대출금리, 수출YoY, BSI, CCSI) 이유와 함께 정리
- 다중공선성 처리 전략: 스프레드 변환 → VIF 필터 → PCA 압축 → 정상성 확보 4단계
- 4분면 레짐 분류 모델(골디락스·과열·침체·스태그플레이션) 설계

---

### 기여 요약

| 영역 | 기여 내용 |
|------|----------|
| 아키텍처 | 6단계 전체 파이프라인 설계 및 팀 합의 주도 |
| 데이터 | ETF 1,100개 수집, 13개 슬롯 분류 체계 설계 |
| 이론 | BL+Sortino+하방공분산 이론 체계 수립, λ=3.0 근거 정리 |
| 검증 | 5개 구현 오류 발견·수정 지시, 4기준 윈도우 평가 설계 |
| 제약 설계 | EM 제약 추가 필요성 발견·근거 수립, MVP 병행 구현 결정 |
| 발표 대비 | 종합 피드백 보고서(17개 논문), Q&A 전략, 체크리스트 |
| 거시지표 | ECOS 수집 설계, 레짐 분류 모델 설계 |

---

## 이론 근거

- Estrada (2007): 하방공분산 행렬 정의
- Modigliani (1954): 생애주기 가설 (나이별 Risk Score)
- Bodie, Merton & Samuelson (1992): 투자 기간과 위험 수용 능력
- He & Litterman (1999): Black-Litterman λ 표준값
- OECD (2021): 퇴직연금 가이드라인 (TDF 단계)
- Chen, Roll & Ross (1986): APT 기반 거시 팩터 이론
