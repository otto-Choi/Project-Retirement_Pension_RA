# Step 8 — XAI 설명 레이어 설계 계획

> **작성일**: 2026-05-13  
> **선행 조건**: Step 5(지역제약 포트폴리오), Step 6(CAL), Step 7(내재λ 역산) 완료  
> **핵심 질문**: "왜 이 비중인가?" + "왜 이 투자자에게 이 배분인가?"

---

## ⚠️ 설계 철학 — "투자 추천"이 아닌 "투자 참고 정보 제공"

한국 「자본시장과 금융투자업에 관한 법률」상 특정 금융투자상품 취득·처분에 관한 **자문**은 **투자자문업**으로 분류되어 금융위 등록이 필요하다. 시스템이 포트폴리오를 "추천"하는 형태면 이 경계를 넘을 수 있다.

**본 Step 8의 모든 출력은 투자 판단의 참고 정보로 제시되어야 하며, 의사결정권은 전적으로 투자자에게 있다.** XAI가 이 포지셔닝의 핵심 근거다 — "추천"이 아닌 "근거 제시"이므로, 분석 논리를 투명하게 공개하는 것이 시스템의 본질적 역할이다.

| 사용 금지 표현 | 대체 표현 |
|-------------|---------|
| "이 포트폴리오를 추천합니다" | "유사 성향 투자자의 역사적 시뮬레이션 결과입니다" |
| "최적 비중" | "역사적 효율적 비중" |
| "당신에게 최적화된 포트폴리오" | "참고용 포트폴리오 분석 정보" |

---

## Step 4/5 사전 작업 (Step 8 구현 전 필수)

### 1. 신흥국 상한 제약 추가 (Step 5)

US ≤ 50% 제약 후 중국 ETF가 1.8% → 16.5%로 급증. EM 상한 추가로 차단.

> **상한값 0.15 근거**: MSCI EM 전체 시가총액 비중 약 12%(2024 기준) 대비 약 1배 수준.
> 시장 비중 수준을 상한으로 설정하여 신흥국 테일 리스크(자본통제, 규제 돌발 등)를 공분산 행렬이 포착하지 못하는 구간에서 차단.

```
기존: Σ(US) ≤ 0.50,  Σ(KR) ≤ 0.50
신규: Σ(EM)  ≤ 0.15  [중국, 인도, 기타 EM 합계]
```

→ Step 5 재실행 필요.

### 2. λ=3.0 변경 (Step 4)

```python
lambda_ = 3.0   # 기존 2.5 → 3.0
Pi = lambda_ * Sigma_down @ w_mkt
```

민감도 분석: λ ∈ {2.0, 2.5, 3.0, 3.5} 성과 비교표. → Step 4→5 연쇄 재실행 필요.

### 3. 분기별 Σ_down, Π 저장 (Step 4/5 스크립트)

8-B1(MCDR), 8-B2(BL 산포도)에서 사용.

```python
# 분기별 루프 내 — 기존 저장 코드 뒤에 추가
sigma_flat = pd.Series(Sigma_down.flatten(),
                       index=[f"{a}__{b}" for a in slot_names for b in slot_names])
sigma_records.append({'date': rebal_date, **sigma_flat})
pi_records.append({'date': rebal_date, **dict(zip(slot_names, Pi))})

# 루프 종료 후
pd.DataFrame(sigma_records).set_index('date').to_parquet('raw/sigma_down_history.parquet')
pd.DataFrame(pi_records).set_index('date').to_parquet('raw/pi_history.parquet')
```

### 4. MVP 구현 (Step 5 추가)

8-A6 비교 및 안정추구형 대안 제시에 사용.

```python
def min_variance_portfolio(Sigma_down, constraints_list, bounds):
    n = Sigma_down.shape[0]
    result = minimize(
        fun=lambda w: w @ Sigma_down @ w,
        x0=np.ones(n) / n,
        method='SLSQP',
        bounds=bounds,
        constraints=constraints_list  # sum=1, US≤0.50, KR≤0.50, EM≤0.15
    )
    return result.x if result.success else None
# 저장: raw/portfolio_weights_mvp.parquet, raw/portfolio_performance_mvp.parquet
```

---

## Step 8를 추가하는 이유

**1. 블랙박스 문제**: Step 1~5는 최적 비중을 산출하지만 "왜 나스닥 40%인가"에 대한 설명이 없다. XAI 없이는 투자자가 결과를 신뢰할 근거가 없다.

**2. 개인화 연결 부재**: Risk Score(나이·은퇴기간·직업·자금·가족·라이프스타일) 파이프라인과 포트폴리오 파이프라인이 Step 8 없이는 연결되지 않는다. "나에게 맞는 배분"이 아닌 "평균적인 배분"에 불과해진다.

**3. 규제 대응**: "추천"이 아닌 "근거 제시"로 포지셔닝하려면, 실제로 근거가 투명하게 공개되어야 한다. XAI가 없으면 이 포지셔닝이 공허해진다.

**4. 학술적 완결성**: BL 모델 + Sortino 최적화 결과에 설명 레이어가 없으면 "블랙박스 최적화기"와 차별화가 없다.

---

## 전체 구조

```
Step 8 XAI
│
├── [레이어 A — 사용자 대면]  개인화 의사결정 설명
│   ├── 8-A0  기회비용 시뮬레이션      — 방치(원리금보장) vs 참고 포트폴리오 미래 자산
│   ├── 8-A1  Risk Score → CAL 배분  — 나이·성향·자금이 w_risky를 결정한 과정
│   ├── 8-A2  Risk Score 하위변수 분해 — "은퇴기간 때문에 +0.8점" 워터폴 차트
│   ├── 8-A3  Big Five 텍스트 연결    — 라이프스타일 문장 → 투자성향 점수 경로
│   ├── 8-A4  손실 감내도 시각화      — "최대 X만원 손실" 금액 기준 제시
│   ├── 8-A5  내재 λ 역산 & 성향 지표 — "시장 평균 대비 당신은 얼마나 보수적인가"
│   └── 8-A6  MVP vs Sortino-max    — 성향별 전략 선택 안내
│
└── [레이어 B — 분석용]        포트폴리오 내부 분석
    ├── 8-B1  MCDR 분해              — 자산별 하방위험 기여
    ├── 8-B2  수익/위험 산포도        — 최적화기의 판단 시각화
    ├── 8-B3  제약 활성화 분석        — 제약이 언제, 얼마나 비용을 치렀는가
    └── 8-B4  성과 기여 분해         — 수익 원천 추적
```

**입력 파일**

| 파일 | 사용 단계 |
|------|---------|
| `raw/portfolio_weights_constrained.parquet` | 8-A6, 8-B1~4 |
| `raw/portfolio_performance_constrained.parquet` | 8-A0, 8-B2, 8-B4 |
| `raw/portfolio_weights_mvp.parquet` | 8-A6 |
| `raw/sigma_down_history.parquet` | 8-B1, 8-B2 |
| `raw/pi_history.parquet` | 8-B2 |
| Step 6 CAL 결과 (w_risky) | 8-A0, 8-A1 |
| Step 7 내재 λ 역산 결과 | 8-A5 |
| Risk Score 하위 변수 벡터 | 8-A1, 8-A2 |
| Big Five z-score 결과 | 8-A3 |
| 적립금·연봉·은퇴기간 입력값 | 8-A0, 8-A4 |

---

## 레이어 A — 사용자 대면 XAI

### 8-A0. 기회비용 시뮬레이션

현재 포트폴리오(원리금보장형 방치)와 참고 포트폴리오의 미래 자산 차이를 금액으로 제시.

```python
FV_benchmark = current_balance * (1+benchmark_return)**years
              + (annual_salary/12) * ((1+benchmark_return)**years - 1) / benchmark_return
FV_portfolio  = (동일 구조, portfolio_return 적용)
opportunity_cost = FV_portfolio - FV_benchmark
```

> "현재 적립금 1억 원을 원리금보장형으로 25년 유지하면 약 X억 원,  
> 이 참고 포트폴리오 역사적 수익률 기준으로는 약 Y억 원으로 차이는 Z억 원입니다.  
> 미래 수익을 보장하지 않습니다."

---

### 8-A1. Risk Score → w_risky → CAL 배분 설명

> **핵심 수정**: 기존 설계의 "페르소나→λ_investor→CAL"은 잘못된 흐름이다.  
> λ_investor는 Step 7에서 역산되는 **결과물**이지 **입력값**이 아니다.  
> 올바른 흐름: Risk Score → 위험군 분류 → w_risky 조회 → 최종 배분.

```
[Risk Score 계산]
  0.15×나이 + 0.20×은퇴기간 + 0.15×직업 + 0.20×자금여력 + 0.15×가족 + 0.15×라이프스타일
       ↓
[위험군 분류 → w_risky 조회]
  Score 1→초보수형→0%,  3→보수형→20%,  5→중립형→40%,  7→성장형→60%,  9→공격형→70%
  상한: 70% (DC/IRP 위험자산 법적 한도)
       ↓
[최종 배분]
  w_risky × Sortino-max 포트폴리오 + (1 - w_risky) × 무위험자산
```

> "Risk Score 7.2점(성장형)에서 참고 리스크자산 비중은 **60%**, 무위험자산 **40%**입니다."

---

### 8-A2. Risk Score 하위변수 기여 분해

선형 가중합이므로 SHAP 없이 직접 계산 가능.

```python
# 각 변수의 평균 기준 상대 기여
weights = {'나이':0.15, '은퇴기간':0.20, '직업':0.15, '자금':0.20, '가족':0.15, '라이프':0.15}
delta = {k: weights[k] * (sub_scores[k] - 5) for k in weights}  # 5점이 평균 기준
```

시각화: 워터폴 차트 — 기준 Risk Score에서 각 변수가 점수를 올리고 내린 크기.

> "은퇴기간(30년) +0.8점 / 나이(35세) +0.3점 / 가족부담(배우자+자녀) -0.4점"

---

### 8-A3. Big Five 텍스트 → 라이프스타일 점수 연결

텍스트 처리 경로를 투명하게 공개.

```
라이프스타일 문장
  → ko-sroberta 임베딩 → KMeans(500)
  → 대표 문장 GPT 점수화 (openness, conscientiousness, stability_preference: 1~5)
  → 전체 전파 → z-score
  → risk_score = 0.45×openness_z - 0.45×stability_z + 0.10×conscientiousness_z
  → qcut → 라이프스타일 점수 1~5등급 (Risk Score의 15%)
```

> "개방성: 중간(3/5) / 계획성: 높음(4/5) / 안정선호: 높음(4/5)  
> → 라이프스타일 투자성향: 안정-중립형(2등급)"

---

### 8-A4. 손실 감내도 시각화

추상적인 MDD(%)를 실제 금액으로 변환 (04번 문서 Part 1 기반).

```python
expected_loss_krw = current_balance * abs(portfolio_mdd)
loss_vs_contribution = expected_loss_krw / (annual_salary / 12)  # 몇 개월 치 기여금
```

> "이 참고 포트폴리오의 역사적 MDD -15.2% 기준, 현재 적립금(1억 원)에서  
> 최대 평가손실 가능액은 약 **1,520만 원** (연간 기여금의 약 3배)입니다."

---

### 8-A5. 내재 λ 역산 & 성향 지표

```python
# 올바른 역산 수식: λ = (E[R_p] - R_f) / (w * Var_down_p) = Sortino / (w * σ_down_p)
sigma_down_p = np.sqrt(w_risky_vec @ Sigma_down @ w_risky_vec * 63)  # 분기 기준 하방표준편차
sortino_ratio = (portfolio_return_q - mar_q) / sigma_down_p
lambda_implied = sortino_ratio / (w_risky_chosen * sigma_down_p)
```

> "선택하신 리스크자산 비중(60%)에 내재된 위험회피계수는 **λ = 2.8**입니다.  
> 시장 중립 기준(λ = 2.5)보다 다소 보수적인 수준입니다."

---

### 8-A6. MVP vs Sortino-max 비교

| 지표 | Sortino-max | MVP | 성향별 |
|------|-------------|-----|--------|
| 누적 수익률 | 높음 | 낮음 | 위험추구형 → Sortino-max |
| MDD | 높음 | 낮음 | 안정추구형 → MVP |
| 소르티노 | 높음 (설계상) | 낮음 | — |

> "안정추구형(Score 3~4)에서는 MVP가 MDD를 X%p 낮추는 대신 수익률이 Y%p 낮았습니다."

---

## 레이어 B — 분석용 XAI

### 8-B1. MCDR (Marginal Contribution to Downside Risk)

```python
def compute_mcdr(w, Sigma_down):
    portfolio_var = w @ Sigma_down @ w
    return (Sigma_down @ w) * w / portfolio_var  # sum = 1
```

시각화: 분기별 MCDR 누적 영역 차트 + 비중 vs MCDR 비교 바 차트.

---

### 8-B2. 내재수익률 vs MCDR 산포도

```
x축: Π_i (연환산),  y축: MCDR_i,  버블: w_i
```

> "오른쪽 아래(고수익·저위험) 자산에 높은 비중이 배분된다.  
> EM 제약이 binding된 분기에서는 신흥국 버블이 작아지고 그 자리를 다른 자산이 채운다."

---

### 8-B3. 제약 활성화 분석

```python
em_binding  = abs(sum(w_em) - 0.30) < 1e-4
constraint_cost = sortino_unconstrained - sortino_constrained
```

시각화: 분기×제약 히트맵(binding 여부) + 제약 비용 바 차트.

---

### 8-B4. 성과 기여 분해

```python
contrib = weights_df.shift(1) * slot_returns_df  # 전기 비중 × 당기 수익
```

시각화: 자산별 누적 기여 영역 차트 + 분기별 기여 히트맵.

---

## Step 8 추가의 효과

| 효과 | 내용 |
|------|------|
| **신뢰 제고** | "왜 이 비중인가"를 설명 → 투자자가 결과를 검증·신뢰할 수 있게 됨 |
| **개인화 완성** | Risk Score 파이프라인과 포트폴리오 파이프라인을 연결 |
| **규제 대응** | "근거 제시" 구조가 투자자문업 경계 회피의 설계적 근거 |
| **차별화** | 기회비용 금액 기준 + 손실 금액 기준 제시는 기존 로보어드바이저와 차별화 |

---

## 출력 파일 구조

```
Step 8/
├── 08a_step8_user_xai.py
├── 08b_step8_analysis_xai.py
├── step8_mcdr_history.csv
├── step8_attribution.csv
├── step8_constraint_activity.csv
└── figures/
    ├── opportunity_cost_sim.png
    ├── risk_score_cal_flow.png
    ├── risk_score_waterfall.png
    ├── lifestyle_score_path.png
    ├── loss_amount_gauge.png
    ├── lambda_gauge.png
    ├── mvp_vs_sortino_compare.png
    ├── mcdr_area.png
    ├── bl_scatter_{quarter}.png
    ├── constraint_heatmap.png
    ├── constraint_cost.png
    ├── attribution_area.png
    └── attribution_heatmap.png
```

---

## 발표 스토리라인

```
[포지셔닝] "투자 참고 정보, 결정은 투자자 본인"

1. 왜 퇴직연금 ETF인가?
   → 8-A0 기회비용: 방치 vs 참고 포트폴리오 금액 차이

2. 어떻게 개인화하는가?
   → 8-A1 Risk Score → w_risky → CAL
   → 8-A2 하위변수 분해: "은퇴기간이 길어서 +0.8점"
   → 8-A3 텍스트 처리: 라이프스타일 → Big Five → 성향 점수

3. 위험은 어떻게 알려주는가?
   → 8-A4 손실 금액: "최대 1,520만원"
   → 8-A5 내재 λ: 시장 평균 대비 보수성 위치

4. 두 전략 비교
   → 8-A6 MVP vs Sortino-max

5. 포트폴리오는 왜 이렇게 구성되어 있는가?
   → 8-B1 MCDR + 8-B2 BL 산포도

6. 제약은 필요했는가?
   → 8-B3 제약 활성화: 방어 vs 수익 포기 트레이드오프

7. 10년 수익은 어디서 왔는가?
   → 8-B4 성과 기여
```

---

## 선행 작업 체크리스트

- [ ] EM ≤ 0.15 추가 후 Step 5 재실행
- [ ] λ=3.0 + 민감도 분석 후 Step 4→5 재실행
- [ ] 분기별 `Σ_down`, `Π` 저장 추가 (Step 4/5 스크립트)
- [ ] 제약 binding 플래그 Step 5 출력에 포함
- [ ] MVP 구현 (07b_step5_mvp.py)
- [ ] Step 6 완료 (CAL, w_risky 저장)
- [ ] Step 7 완료 (내재 λ 역산 저장)
- [ ] 시스템 전체 "추천" → "참고 정보" 표현 일괄 교체
