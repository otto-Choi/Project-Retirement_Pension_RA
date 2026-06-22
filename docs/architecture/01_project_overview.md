# 퇴직연금 ETF 포트폴리오 최적화 with XAI — 전체 프로젝트 개요

> **최종 업데이트**: 2026-05-19
> **목적**: 프로젝트 전체 맥락, 진행 현황, 계획, 발표 흐름을 한 파일에 정리

---

## ⚠️ 투자 추천 워딩 경고 — 반드시 숙지

**이 시스템의 모든 출력은 "투자 추천"이 아닌 "투자 참고 정보"여야 한다.**

### 법적 근거

한국 「자본시장과 금융투자업에 관한 법률」 제6조: 특정 금융투자상품의 취득·처분 여부 및 방법에 관한 **자문**을 업으로 하는 것은 **투자자문업**으로 분류 → 금융위원회 등록 필요.

학술 프로젝트라도 시스템이 "이 포트폴리오를 투자하세요"라고 말하면 규제 위반 소지 발생.

### 금지/대체 표현 일람

| 절대 금지 표현 | 반드시 사용할 대체 표현 |
|-------------|---------------------|
| "이 포트폴리오를 추천합니다" | "유사 성향 투자자의 역사적 시뮬레이션 결과입니다" |
| "이 ETF를 X% 투자하세요" | "이 비중은 과거 X년간 소르티노 X, MDD X%를 기록했습니다" |
| "최적 포트폴리오" | "역사적 효율적 포트폴리오" |
| "당신에게 맞는 포트폴리오" | "참고용 포트폴리오 분석 정보" |
| "최적 비중" | "역사적 효율적 비중" |
| "이 배분이 가장 좋습니다" | "이 구성은 과거 데이터 기준 이 성과를 보였습니다" |

### 발표용 한 줄 포지션

> "본 시스템은 투자 일임·자문이 아닌, 데이터 기반 투자 참고 정보를 제공합니다.
> 의사결정권은 전적으로 투자자에게 있으며, XAI를 통해 분석 근거를 투명하게 공개합니다."

**XAI가 이 포지셔닝의 핵심 근거다**: "추천"이 아닌 "근거 제시"이므로, 분석 논리를 투명하게 공개하는 것이 시스템의 본질적 역할이 된다.

---

## 1. 프로젝트 개요

### 1-A. 한 줄 정의

> 한국 퇴직연금(DC/IRP) 가입자를 위해, 개인 Risk Score 기반으로 개인화된 ETF 포트폴리오 비중을 산출하고, XAI로 그 근거를 투명하게 제시하는 데이터 기반 참고 정보 시스템

### 1-B. 핵심 문제 의식

1. **방치 문제**: 퇴직연금 가입자의 대다수가 원리금보장형 100%에 적립금을 방치. 기회비용이 수천만 원에 달함.
2. **블랙박스 문제**: 기존 로보어드바이저는 결과만 제시하고 근거를 설명하지 않음.
3. **개인화 부재**: 모든 투자자에게 동일한 포트폴리오를 제공하거나, 단순 설문으로만 성향을 분류.

### 1-C. 핵심 차별화

| 차별화 요소 | 내용 |
|-----------|------|
| **하방위험 중심 최적화** | Sortino 비율 최대화 (MDD/변동성 대신 하방위험에 집중) |
| **Black-Litterman + 퇴직연금 특화** | BL 내재수익률(Σ_down 기반, λ=3.0) + 지역 제약(US≤50%, KR≤50%, EM≤15%) |
| **두 파이프라인 통합** | 텍스트 기반 Big Five 성향 분석 + 정량 Risk Score → 개인화 w_risky 결정 |
| **XAI 설명 레이어** | MCDR, 제약 비용, 성과 기여 + 개인화 경로 투명 공개 |
| **퇴직연금 맥락** | DC/IRP 70% 위험자산 법적 상한 반영, 기회비용 금액 기준 제시 |

---

## 2. 전체 파이프라인 구조

### 2-A. 포트폴리오 파이프라인 (Step 1~8)

```
[데이터 수집]
Step 1. ETF 데이터 수집 (국내·해외 ETF, ECOS 금리)
Step 2. 데이터 정제 (결측 처리, 수익률 계산, 슬롯 매핑)
Step 3. 시장 포트폴리오 구성 (슬롯별 시가총액 가중 w_mkt)
        ↓
[포트폴리오 최적화]
Step 4. BL 내재수익률 산출
        · Σ_down = D.T @ D / T  (D = min(r - MAR, 0))
        · Π = λ * Σ_down @ w_mkt  (λ=3.0)
        · MAR: ECOS 정기예금 6개월미만 수신금리 (분기 시변)
Step 5. Sortino-max 포트폴리오 (Walk-forward 백테스트)
        · SLSQP: max (w@Π*63 - MAR_q) / sqrt(w@Σ_down@w*63)
        · 제약: sum=1, US≤50%, KR≤50%, EM≤15%, 개별 0.01≤w≤0.40
        · MVP도 동일 제약으로 병렬 구현
        ↓
[개인화 & XAI]
Step 6. CAL (Capital Allocation Line)
        · 무위험자산: ECOS 금리
        · 리스크자산: Sortino-max 포트폴리오
        · Risk Score → w_risky → 최종 배분
Step 7. 내재 λ 역산
        · 투자자 선택 w_risky에서 λ_implied 역산
        · λ_implied = Sortino_ratio / (w_risky · σ_down_p)
Step 8. XAI 설명 레이어
        · 레이어 A (사용자 대면): 개인화 경로 설명
        · 레이어 B (분석용): 포트폴리오 내부 분석
```

### 2-B. Risk Score 파이프라인

```
[엔비디아 페르소나 데이터]
직업, 가족여부, 라이프스타일 텍스트
        ↓
[텍스트 처리 (텍스트_리스크_스코어.ipynb)]
Embedding (ko-sroberta-multitask) + 키워드 피처
  → Ridge Regression → openness, conscientiousness, stability_preference (1~5)
  → z-score 표준화
  → PCA 1성분: risk_tendency_score = 0.7072×openness_z + 0.006×conscientiousness_z - 0.707×stability_z
  → job_stability_score, family_score 변수 생성

[사용자 정형 입력]

Part 1. Capital / Career Capacity Score
  calculate_capital_career_capacity_score(
      investable_capital, years_worked, years_to_retire, income_dependency
  ) → Part 1 점수 (0~1)

Part 2. 퇴직연금 기여 안정성 Score
  calculate_pension_contribution_stability_score(
      job_type, expected_contribution, income_level
  ) → Part 2 점수 (0~1)

[Risk Score 계산]
= total_score    × 0.30   ← 자금 (Part 1 · Part 2 조합)
  + time_horizon_score × 0.30
  + job_stability_score × 0.25
  + family_score       × 0.15

[위험군 분류 → w_risky 조회]
· Score 1~2: 초보수형 → w_risky 0% (전액 무위험자산)
· Score 3~4: 보수형 → w_risky 20%
· Score 5~6: 중립형 → w_risky 40%
· Score 7~8: 성장형 → w_risky 60%
· Score 9~10: 공격형 → w_risky 70% (DC/IRP 법적 상한)

[최종 배분]
= w_risky × Sortino-max 포트폴리오 + (1 - w_risky) × 무위험자산
```

### 2-C. 엔비디아 데이터 역할

엔비디아 페르소나 데이터는 **예측 모델 학습용이 아닌**, 한국 인구통계 특성을 반영한 가상 사용자군 구성 및 Risk Score 하위 변수(가족·직업·라이프스타일) 점수화를 위한 기반 데이터.

- 엔비디아 데이터 담당 범위: job_stability_score, family_score (가중치 합산 0.40)
- 사용자 추가 입력 담당: total_score(자금), time_horizon_score (가중치 합산 0.60)

---

## 3. 지금까지 완료된 작업

| 단계 | 상태 | 결과 |
|------|------|------|
| Step 1~3 | ✅ 완료 | ETF 데이터 수집·정제·슬롯 매핑 완료, 5yr 윈도우 확정 |
| Step 4 | ✅ 완료 (λ=3.0 재실행) | BL 내재수익률 산출, 비제약 포트폴리오 +120.6%, MDD -34.8% |
| Step 5 | ✅ 완료 (EM≤15% 재실행) | 지역제약 포트폴리오 +94.9%, MDD -24.4% |
| portfolio_engine.py | ✅ 완료 | Risk Score → 포트폴리오 + XAI Layer A/B 전체 구현 |
| 텍스트 파이프라인 기획 | ✅ 문서 완성 | Big Five GPT 점수화 프롬프트, 클러스터링 코드, risk_score 공식 확정 |
| Risk Score 설계 | ✅ 문서 완성 | 6개 변수·가중치·w_risky 조회 테이블 확정 |
| Step 6~7 | ❌ 미구현 (엔진 내 설계 완료) | CAL + 내재 λ → portfolio_engine.py 의 XAI a1/a5에 로직 포함 |
| Step 8 | ✅ 설계 완료, 코드 구현 완료 | XAI 레이어 A(a0~a6) + 레이어 B(b1~b4) — portfolio_engine.py |

---

## 4. 발표 흐름 예시 (학술제)

```
[도입] 왜 퇴직연금 ETF인가?
  → 원리금보장형 100% 방치의 기회비용 (금액 기준)
  → "이 시스템은 투자 참고 정보를 제공합니다. 결정은 투자자 본인이 합니다."

[파트 1: 어떻게 만들었는가 — 포트폴리오 파이프라인]
  Step 1~3: ETF 선택 기준 + 슬롯 구조
  Step 4:   BL + 하방공분산(λ=3.0 선택 근거 포함)
  Step 5:   Sortino 최대화 + 지역 제약 (US·KR·EM 상한 및 근거)
  결과:     10년 백테스트 성과 (누적수익률, MDD, 소르티노)

[파트 2: 어떻게 개인화하는가 — Risk Score 파이프라인]
  텍스트 → Big Five → 라이프스타일 점수 (8-A3)
  6개 변수 → Risk Score → 위험군 → w_risky (8-A1, 8-A2)
  손실 금액 기준 위험 제시 (8-A4)
  내재 λ 역산: "당신의 선택은 시장 평균 대비 이 위치" (8-A5)

[파트 3: 두 전략 비교 — MVP vs Sortino-max]
  안정추구형 vs 위험추구형 프로파일에 따른 전략 선택 안내 (8-A6)

[파트 4: 왜 이 포트폴리오인가 — 분석용 XAI]
  MCDR 분해: 자산별 하방위험 기여 (8-B1)
  BL 산포도: 최적화기 의사결정 시각화 (8-B2)
  제약 활성화: EM 제약이 실제 binding된 분기와 비용 (8-B3)
  성과 기여: 10년 수익의 원천 (8-B4)

[마무리] 종합 평가 및 한계
  → 거래비용 0.3% 미반영 (성과에 미미한 영향)
  → Walk-forward 백테스트 방법론으로 생존 편향 배제
  → 미래 수익 보장 없음 — 참고 정보임을 재강조
```

---

## 5. 주요 설계 결정 사항 및 근거

### 6-A. 기술적 선택

| 결정 | 선택값 | 근거 |
|------|--------|------|
| 위험 측도 | 하방공분산 Σ_down | Estrada(2007) — 정규분포 가정 없이 하방위험만 포착 |
| 기대수익률 | BL 내재수익률 Π | 시장 포트폴리오에서 역산 → 추정 오류 최소화 |
| 최적화 목적함수 | Sortino 비율 최대화 | 하방위험 중심, 퇴직연금 특성과 일관성 |
| λ 값 | 3.0 | He & Litterman(1999) 표준값 2.5에서 퇴직연금 보수성 반영 상향; Merton(1969) 장기투자자 λ 범위 2~4 중 상단 |
| MAR | ECOS 정기예금 금리 | 시변 무위험 기준, 시장 금리 반영 |
| 백테스트 방식 | Walk-forward (5년 window) | 생존 편향 배제 |

### 6-B. 제약 설계

| 제약 | 값 | 근거 |
|------|-----|------|
| 미국 주식 상한 | ≤ 50% | 단일 시장 집중 방지 |
| 한국 주식 상한 | ≤ 50% | 홈 바이어스 상한 |
| 신흥국 상한 | ≤ 15% | MSCI EM 비중(~12%), 중국 테일 리스크 |
| 개별 자산 | 0.01~0.40 | 최소 분산 투자 + 단일 자산 과집중 방지 |
| 위험자산 상한 | ≤ 70% | DC/IRP 법적 한도 |

### 6-C. Risk Score 구조

```
전체 Risk Score (0~1)
  = total_score       × 0.30   ← 자금
  + time_horizon_score × 0.30
  + job_stability_score × 0.25
  + family_score        × 0.15

자금 total_score 하위 구조:
  Part 1. Capital / Career Capacity Score (0~1)
      입력: investable_capital, years_worked, years_to_retire, income_dependency
  Part 2. 퇴직연금 기여 안정성 Score (0~1)
      입력: job_type, expected_contribution, income_level

job_stability_score / family_score:
  엔비디아 페르소나 텍스트 → Ridge 예측 (openness, conscientiousness, stability_preference)
  → PCA risk_tendency_score → 변수별 점수로 변환
```

### 6-D. 거래비용

분기별 리밸런싱 거래비용 약 0.3% 수준. 연간 최대 ~1.2%p. 누적 수익률(+94.9%) 및 MDD(-24.4%) 비교의 주요 결론에 영향 없어 명시적으로 고려하지 않음.
