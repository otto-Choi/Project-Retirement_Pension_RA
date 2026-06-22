# 하방위험 기반 ETF 포트폴리오 최적화 — 최종 데이터셋 설명서

> **작성일**: 2026-05-14  
> **현재 진행 상태**: Step 1~5 완료 / Step 6~7 진행 예정  
> **전달 목적**: Step 6(무위험자산 비중 배분 & CAL) 작업을 위한 데이터 인수인계

---

## 전체 파이프라인 현황

```
Step 1  우량 ETF 필터링                    ✅ 완료
Step 2  자산군 분류 & 대표 ETF 선정         ✅ 완료
Step 3  기초자산 지수 수집 & 최적 롤링윈도우  ✅ 완료
Step 4  내재수익률 & 하방위험 산출           ✅ 완료
Step 5  지역 집중도 제약 최적 포트폴리오      ✅ 완료  ← 현재 최종 포트폴리오
Step 6  무위험자산 비중 배분 & CAL          ⬜ 미완료  ← 다음 작업
Step 7  CVaR 산출 & 지표 제공              ⬜ 미완료
```

---

## 핵심 파라미터 (확정)

| 파라미터 | 값 | 결정 단계 |
|---------|-----|---------|
| 추정 윈도우 | **5년 (1260거래일)** | Step 3 |
| 리밸런싱 주기 | **분기 (63거래일)** | Step 3 |
| MAR | **ECOS 정기예금 6개월미만 수신금리 (시변)** | Step 3 |
| 하방공분산 방식 | **Estrada(2007)** `Σ = (D.T @ D) / T` | Step 3 |
| 위험회피계수 λ | **2.5** | Step 3 |
| 슬롯 개별 상한 | **40%** | Step 4 |
| 슬롯 개별 하한 | **1%** | Step 4 |
| 지역 제약 | **US 주식 ≤ 50%, KR 주식 ≤ 50%** | Step 5 |

---

## 폴더 구조

```
최종_데이터셋/
├── 데이터셋_설명서.md              ← 이 파일
│
├── 입력_데이터/                   ← Step 3·4·5 공통 원본 입력
│   ├── index_returns.parquet
│   ├── slot_returns.parquet
│   ├── mar_series.parquet
│   ├── year_end_best.csv
│   ├── year_end_universe.csv
│   └── filtered_universe.csv
│
├── step3_롤링윈도우/
│   └── window_analysis_result.csv
│
├── step4_비제약포트폴리오/         ← 비교 기준선 (참고용)
│   ├── step4_summary.csv
│   ├── step4_weights_pivot.csv
│   ├── portfolio_weights.parquet
│   └── portfolio_performance.parquet
│
└── step5_지역제약포트폴리오_최종/   ← Step 6 직접 입력값
    ├── step5_comparison.csv
    ├── step5_weights_constrained.csv
    ├── portfolio_weights_constrained.parquet
    └── portfolio_performance_constrained.parquet
```

---

## 데이터셋 상세 설명

### 입력_데이터/

---

#### `index_returns.parquet`
**기초자산 지수 일별 수익률**

| 항목 | 내용 |
|------|------|
| 크기 | 6,628행 × 13열 |
| 기간 | 2000-01-03 ~ 2025-04-30 |
| 인덱스 | 거래일 (DatetimeIndex) |
| 용도 | Step 3 윈도우 탐색, Step 4 Σ_down 추정 |

**열 구성 (13개 슬롯)**

| 열명 | 출처 | 변환 방식 |
|------|------|---------|
| 국내주식_코스피 | yfinance `^KS11` | `pct_change()` |
| 국내주식_코스닥 | yfinance `^KQ11` | `pct_change()` |
| 미국주식_SP500 | yfinance `^GSPC` | `pct_change()` |
| 미국주식_나스닥 | yfinance `^NDX` | `pct_change()` |
| 신흥국_인도 | yfinance `^NSEI` | `pct_change()` |
| 신흥국_중국 | yfinance `^HSI` | `pct_change()` |
| 국내채권_국고채단중기 | ECOS 국고채3년 | yield→price (MD=2.8) |
| 국내채권_국고채장기 | ECOS 국고채30년 | yield→price (MD=18.0) |
| 국내채권_회사채 | ECOS 회사채AA- | yield→price (MD=2.7) |
| 국내채권_종합 | ECOS (국고채3년50%+10년50%) | yield→price (MD=5.5) |
| 해외채권_미국국채 | yfinance `^IRX` | annualYTM/100/252 |
| 원자재_금 | yfinance `GC=F` | `pct_change()` |
| 무위험(현금성) | ECOS CD91일 | annualYield/100/252 |

> **채권 변환 공식**: `daily_ret ≈ YTM/252 − Modified_Duration × Δy`  
> ETF 대신 지수를 쓰는 이유: ETF는 상장이 2~8년에 불과해 금융위기(2008), 유럽재정위기(2011), 코로나(2020) 등 주요 국면을 포함하기 어려움

---

#### `slot_returns.parquet`
**실제 ETF 일별 수익률 (OOS 평가용)**

| 항목 | 내용 |
|------|------|
| 크기 | 2,290행 × 13열 |
| 기간 | 2016-01-04 ~ 2025-04-30 |
| 인덱스 | 거래일 (DatetimeIndex) |
| 용도 | Step 4 OOS 성과 평가 (실제 비용·추적오차 반영) |

열 구성은 `index_returns.parquet`과 동일한 13개 슬롯명.  
각 셀은 해당 시점 `year_end_best`에서 선정된 ETF의 일별 수익률.

---

#### `mar_series.parquet`
**최소 수용 수익률(MAR) 월별 시계열**

| 항목 | 내용 |
|------|------|
| 크기 | 304행 × 1열 (`mar_annual`) |
| 기간 | 2000-01-01 ~ 2025-04-01 |
| 단위 | 연율(%) — 예: `1.32` = 연 1.32% |
| 출처 | ECOS 121Y002/BEABAA2111 (정기예금 6개월미만 수신금리) |
| 용도 | 리밸런싱 구간별 MAR scalar 산출 |

| 통계 | 값 |
|------|-----|
| 최솟값 | 0.62% (2021년) |
| 최댓값 | 6.55% (2000년대 초) |
| 평균 | 3.00% |

> 사용법: 월별 → `resample('D').ffill()` → 거래일 reindex → 분기 구간 평균을 MAR scalar로 사용

---

#### `year_end_best.csv`
**연도별 × 슬롯별 최종 선정 ETF**

| 항목 | 내용 |
|------|------|
| 크기 | 71행 × 10열 |
| 기간 | 2015~2024년 (연도말 기준) |
| 용도 | 생존편향 없는 연도별 대표 ETF 결정 |

**주요 열**

| 열 | 설명 |
|----|------|
| `year` | 선정 연도 (다음 해 1년 적용) |
| `slot` | 자산군 슬롯명 |
| `ticker` | ETF 단축코드 |
| `name` | ETF 명칭 |
| `expense` | 총보수(%) |
| `aum_억` | AUM (억 원) |

> **선정 로직**: 순수지수 추종·비환헤지 우선 필터 후 `총보수×0.5 + 거래대금×0.3 + AUM×0.2` 가중평균 순위 최소값 선택

---

#### `year_end_universe.csv`
**연도별 투자 가능 ETF 전체 목록**

| 항목 | 내용 |
|------|------|
| 크기 | 596행 |
| 기간 | 2015~2024년 |
| 용도 | 슬롯별 후보군 전체 조회 / 감사 목적 |

---

#### `filtered_universe.csv`
**유동성 기준 우량 ETF 필터링 결과**

| 항목 | 내용 |
|------|------|
| 크기 | 196행 |
| 용도 | Step 1 산출물. 레버리지·인버스·상폐 제거 후 AUM ≥ 500억, 일평균거래대금 ≥ 10억 충족 ETF |

---

### step3_롤링윈도우/

---

#### `window_analysis_result.csv`
**1·2·3·5년 윈도우 Walk-forward 비교 결과**

| 열 | 설명 |
|----|------|
| `윈도우` | 1yr / 2yr / 3yr / 5yr |
| `검증 분기` | OOS 평가에 사용된 분기 수 |
| `① 평균 예측오차(%)` | MAE — Σ_down 추정 정확도 (낮을수록 좋음) |
| `② 실현 소르티노` | OOS 소르티노 평균 (높을수록 좋음) |
| `③ 소르티노 σ` | 소르티노 시계열의 표준편차 (낮을수록 일관성↑) |
| `④ 이상치 민감도` | 극단 분기 제거 전후 소르티노 차이 (낮을수록 좋음) |

**결과 요약**

| 윈도우 | ① MAE | ② 소르티노 | ③ σ | ④ 민감도 | 종합 점수 |
|--------|-------|-----------|-----|---------|---------|
| 1yr | 2.669 | 0.572 | 1.652 | 0.073 | 0.644 |
| 2yr | 2.937 | 0.561 | 1.691 | 0.009 | 0.267 |
| 3yr | 2.870 | 0.512 | 1.582 | 0.015 | 0.428 |
| **5yr** | **2.854** | **0.600** | **1.591** | **0.015** | **0.728 ★** |

→ **최적 윈도우: 5년** 확정 (소르티노 1위, 이상치 민감도 1yr 대비 5배 낮음)

---

### step4_비제약포트폴리오/

> 비교 기준선용 데이터입니다. 실제 최종 포트폴리오는 step5를 사용하세요.

---

#### `step4_summary.csv`
**연도별 포트폴리오 성과 요약**

| 열 | 설명 |
|----|------|
| `year` | 연도 |
| `리밸런싱` | 해당 연도 리밸런싱 횟수 |
| `평균슬롯` | 평균 유효 자산 수 |
| `평균수익률` | 평균 분기 수익률(%) |
| `누적수익률` | 연간 누적 수익률(%) |
| `평균소르티노` | 평균 소르티노 비율 |
| `소르티노σ` | 소르티노 표준편차 |
| `평균MAR` | 적용된 평균 MAR(%) |

---

#### `step4_weights_pivot.csv`
**분기별 슬롯 비중 이력 (비제약)**

| 열 | 설명 |
|----|------|
| `date` | 리밸런싱 시점 |
| 나머지 13열 | 각 슬롯 비중(%) |

기간: 2016-01-29 ~ 2025-01-16 (38개 분기)

---

#### `portfolio_weights.parquet` / `portfolio_performance.parquet`
Step 5와 비교할 때 사용하는 비제약 버전 parquet.  
`portfolio_performance.parquet` 열 구성: `n_slots`, `cum_ret_pct`, `sortino`, `down_risk_pct`, `mar_annual_pct`, `eff_n`, `us_alloc`, `kr_alloc`

---

### step5_지역제약포트폴리오_최종/

> **Step 6 작업 시 이 폴더의 parquet 2개를 직접 입력으로 사용하세요.**

---

#### `step5_comparison.csv`
**비제약(Step 4) vs 지역제약(Step 5) 종합 비교**

| 지표 | 비제약 | 지역제약 | 비고 |
|------|--------|---------|------|
| 누적수익률 | +120.6% | +94.9% | |
| 평균 소르티노 | 0.927 | 0.631 | |
| 소르티노 σ | 2.173 | 1.659 | 일관성 향상 |
| **MDD** | **-34.8%** | **-24.4%** | **10.5%p 개선** |
| 소르티노 > 0 비율 | 60.5% | 60.5% | 동일 |
| 평균 US 비중 | 33.5% | 22.4% | |
| 2025 관세충격 소르티노 | -1.08 | -0.58 | 방어력 개선 |

→ **최종 선택: 지역제약 포트폴리오** — MDD 10.5%p 개선이 수익 25.7%p 희생보다 중요

---

#### `step5_weights_constrained.csv`
**분기별 슬롯 비중 이력 (지역제약, CSV)**

| 열 | 설명 |
|----|------|
| `date` | 리밸런싱 시점 |
| 나머지 13열 | 각 슬롯 비중(%) |

기간: 2016-01-29 ~ 2025-01-16 (38개 분기)  
사람이 읽기 편한 CSV 형식 (parquet과 동일 내용)

---

#### `portfolio_weights_constrained.parquet` ← Step 6 핵심 입력
**지역제약 포트폴리오 분기별 비중**

| 항목 | 내용 |
|------|------|
| 크기 | 38행 × 13열 |
| 인덱스 | 리밸런싱 시점 (DatetimeIndex) |
| 값 | 슬롯별 비중 (0~1, 합계 = 1.0) |

```python
import pandas as pd
weights = pd.read_parquet('portfolio_weights_constrained.parquet')
# 최신 리밸런싱 비중
print(weights.iloc[-1])
```

---

#### `portfolio_performance_constrained.parquet` ← Step 6 핵심 입력
**지역제약 포트폴리오 분기별 성과 지표**

| 항목 | 내용 |
|------|------|
| 크기 | 38행 × 8열 |
| 인덱스 | 리밸런싱 시점 (DatetimeIndex) |

**열 설명**

| 열 | 단위 | 설명 |
|----|------|------|
| `n_slots` | 개 | 해당 분기 유효 슬롯 수 |
| `cum_ret_pct` | % | OOS 분기 누적 수익률 |
| `sortino` | — | OOS 분기 소르티노 비율 |
| `down_risk_pct` | % | 하방위험 (Σ_down 기반) |
| `mar_annual_pct` | % | 해당 분기 적용 MAR (연율) |
| `eff_n` | 개 | 유효 자산 수 (1/HHI) |
| `us_alloc` | 0~1 | US 주식 비중 합계 |
| `kr_alloc` | 0~1 | KR 주식 비중 합계 |

```python
import pandas as pd
perf = pd.read_parquet('portfolio_performance_constrained.parquet')
print(perf[['cum_ret_pct', 'sortino', 'down_risk_pct', 'mar_annual_pct']].tail())
```

---

## Step 6 작업 가이드

Step 6에서 해야 할 일: **무위험자산(현금성 ETF) 비중 배분 & 자본배분선(CAL) 도출**

### 필요 입력 파일
```
step5_지역제약포트폴리오_최종/portfolio_weights_constrained.parquet
step5_지역제약포트폴리오_최종/portfolio_performance_constrained.parquet
입력_데이터/mar_series.parquet
입력_데이터/slot_returns.parquet
```

### 핵심 수식 참고
```python
# 리스크자산 포트폴리오 기대수익 & 하방위험
E_r_risky    = w @ Pi * 63          # 분기 기대수익 (Pi = λ × Σ_down @ w_mkt)
sigma_risky  = sqrt(w @ Sigma_down @ w * 63)

# 전체 포트폴리오 (무위험자산 비중 α 포함)
E_r_total    = (1 - α) * E_r_risky + α * MAR_q
sigma_total  = (1 - α) * sigma_risky

# CAL 기울기 (= 소르티노 비율)
sharpe_like  = (E_r_risky - MAR_q) / sigma_risky
```

### 무위험자산 슬롯
`무위험(현금성)` = RISE 머니마켓액티브 (455890) — 이미 13개 슬롯에 포함되어 있음  
별도 처리 없이 해당 슬롯 비중이 α 역할을 할 수 있으나, 명시적 CAL 분리 여부는 팀 논의 필요

---

## 주의사항

1. **추정과 OOS 데이터 분리 원칙 유지**  
   Σ_down 추정 → `index_returns.parquet` 사용  
   OOS 성과 평가 → `slot_returns.parquet` 사용

2. **생존편향 차단**  
   ETF 선정 시 반드시 `year_end_best.csv`의 해당 연도 전년도 기준 ETF 사용  
   (예: 2021년 포트폴리오 → `year`=2020 행의 ETF)

3. **parquet 파일 의존성**  
   `slot_returns.parquet`의 각 슬롯은 `year_end_best.csv`의 연도별 선정 ETF 수익률을 이어붙인 시계열  
   두 파일은 반드시 함께 사용해야 의미가 있음
