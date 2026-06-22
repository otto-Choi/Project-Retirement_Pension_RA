# 소득 추정 파이프라인 — 작업 정리

## 목적

퇴직연금 포트폴리오 XAI 서비스 시연을 위해, 페르소나 데이터의 직업 정보를 바탕으로
**통계적으로 자연스러운 추정 소득과 퇴직연금 잔액**을 계산할 수 있도록
직업 대분류 매핑, salary_multiplier, 파생 계수, 연금 누적 공식을 구현.

최종 공식:
```
estimated_monthly = 통계 대분류 평균임금
                    × salary_multiplier
                    × seniority_multiplier(연차)
                    × education_multiplier
                    × region_multiplier
                    × random_noise

pension_balance = Σ(t=1 → years_of_service) [estimated_monthly(t)]
               = 통계 평균임금 × salary_multiplier × education_multiplier
                 × region_multiplier × random_noise
                 × Σ(t=1 → N) seniority_multiplier(t)
```

---

## 사용 데이터

| 파일 | 설명 |
|------|------|
| `persona_job_amount.csv` | 페르소나 50,000명 (uuid, sex, age, education_level, bachelors_field, occupation, district, province) |
| `persona_final_earnings.csv` | 원본 페르소나 전체 (150MB, CP949) — 직업·소득 파생 후 슬림화 |
| `직종_학력_연령계층_성별_임금_및_근로조건_*.csv` | 고용노동부 통계 — 직종 대분류별 월임금총액(천원), 2025년 기준 |

---

## 통계 기준값 (직종 대분류별 월임금총액, 천원)

| 코드 | 대분류 | 월임금총액 (천원) |
|------|--------|----------------|
| 1 | 관리자 | 12,563 |
| 2 | 전문가 및 관련종사자 | 5,149 |
| 3 | 사무 종사자 | 4,942 |
| 4 | 서비스 종사자 | 2,285 |
| 5 | 판매 종사자 | 4,104 |
| 6 | 농림·어업 숙련 종사자 | 3,111 |
| 7 | 기능원 및 관련 기능 종사자 | 4,147 |
| 8 | 장치·기계 조작 및 조립 종사자 | 4,215 |
| 9 | 단순노무 종사자 | 2,631 |
| — | 비경제활동/무직 | 0 |

---

## 수행 작업

### 1단계 — 직업 대분류 매핑 (`map_occupations.py`)

- `persona_job_amount.csv`의 `occupation` 컬럼에서 **1,406개 고유 직업** 추출
- 한국표준직업분류 9개 대분류로 규칙 기반 우선순위 매핑
- `전직 ` 접두어: 기저 직업으로 분류 후 multiplier에 **0.9배 할인** 적용
- `, 현재 구직중` 등 콤마 이후 상태 문자열 자동 제거
- 출력: `occupation_mapping.csv` (1,406행), `persona_job_mapped.csv` (50,000행)

**분류 결과:**

| 대분류 | 고유직업 수 | 평균 multiplier |
|--------|-----------|----------------|
| 관리자 | 73 | 1.02 |
| 전문가 및 관련종사자 | 479 | 1.06 |
| 사무 종사자 | 84 | 0.91 |
| 판매 종사자 | 65 | 0.97 |
| 기능원 및 관련 기능 종사자 | 208 | 0.97 |
| 장치·기계 조작 및 조립 종사자 | 274 | 0.94 |
| 농림·어업 숙련 종사자 | 13 | 0.98 |
| 단순노무 종사자 | 74 | 0.87 |
| 서비스 종사자 | 135 | 0.92 |
| 비경제활동/무직 | 1 | 0.00 |
| **합계** | **1,406** | |

### 2단계 — 소득·연금 계산 (`compute_earnings.py`)

`persona_final_earnings.csv` (CP949)를 읽어 파생 변수를 계산 후 UTF-8-sig로 재저장.

#### 사회 진입 연령 (`entry_age`)

취업준비기간 +1년 포함. 무학~중학교는 고졸과 동일 취급.

| 학력 | entry_age |
|------|-----------|
| 무학 / 초등학교 / 중학교 / 고등학교 | 20 |
| 2~3년제 전문대학 | 22 |
| 4년제 대학교 | 24 |
| 대학원 | 27 |

#### 군 복무 지연 (`military_delay`)

`sex == '남자'` → +2년, 여자 → 0년 (단순 일괄 적용)

#### 근속연수 (`years_of_service`)

```
years_of_service = max(0, age - entry_age - military_delay)
```

#### 연차별 호봉 계수 (`seniority_multiplier`)

현재 연차 기준 단일 계수 (월소득 표시용).

| 근속연수 | 계수 |
|---------|------|
| 0–3년 | 0.70 |
| 3–5년 | 0.80 |
| 5–10년 | 0.90 |
| 10–15년 | 1.00 |
| 15–20년 | 1.10 |
| 20–25년 | 1.15 |
| 25년+ | 1.10 |

#### 학력 프리미엄 (`education_multiplier`)

| 학력 | 계수 |
|------|------|
| 무학 / 초등학교 / 중학교 | 0.80 |
| 고등학교 | 0.90 |
| 2~3년제 전문대학 | 0.95 |
| 4년제 대학교 | 1.00 |
| 대학원 | 1.10 |

#### 지역 프리미엄 (`region_multiplier`)

| 지역 | 계수 |
|------|------|
| 서울 (province가 '서울'로 시작) | 1.08 |
| 기타 전국 | 1.00 |

#### 랜덤 노이즈 (`random_noise`)

```python
np.random.seed(42)
noise = np.random.lognormal(mean=0.0, sigma=0.15)
# 중앙값=1.0, 95% 구간 약 [0.74, 1.35]
```

#### 퇴직연금 잔액 (`pension_balance`)

현재 월급이 아닌, **1년차~현재 연차까지 각 연도 월급의 누적 합산**:

```
pension_balance = base × sal_mult × edu_mult × reg_mult × noise
                  × Σ(t=1 → years_of_service) seniority_mult(t)
```

무직(`salary_multiplier = 0.0`)은 자동으로 0 처리.

### 3단계 — 컬럼 슬림화 (`slim_csv.py`)

분석에 불필요한 서술형 페르소나 컬럼 19개 제거:
150MB → **11.2MB**

---

## 산출 통계 요약 (50,000명)

| 지표 | 값 |
|------|---|
| 추정 월소득 중앙값 | 3,514천원 (약 351만원) |
| 추정 월소득 평균 | 3,356천원 |
| 추정 월소득 최대 | 31,895천원 |
| 근속연수 중앙값 | 23년 |
| 근속연수 평균 | 22.5년 |
| 퇴직연금 잔액 중앙값 | 51,488천원 (약 5,150만원) |
| 퇴직연금 잔액 평균 | 64,245천원 |
| 퇴직연금 잔액 최대 | 934,955천원 (약 9.35억) |
| pension=0 비율 | 26.3% (무직 + years=0 신입) |

---

## 데이터 명세 — `persona_final_earnings.csv`

### 현재 스펙

| 항목 | 내용 |
|------|------|
| 행 수 | 50,000행 (헤더 제외) |
| 열 수 | 21개 |
| 인코딩 | UTF-8-sig |
| 파일 크기 | 11.2MB |

### 컬럼 명세

| # | 컬럼명 | 타입 | 설명 |
|---|--------|------|------|
| 1 | `uuid` | str | 페르소나 고유 식별자 |
| 2 | `sex` | str | 성별 (`남자` / `여자`) |
| 3 | `age` | int | 나이 (만 나이) |
| 4 | `education_level` | str | 최종 학력 (무학/초등/중학/고등/전문대/4년제/대학원) |
| 5 | `bachelors_field` | str | 전공 계열 (학사 기준) |
| 6 | `occupation` | str | 직업명 (원본, 전직 접두어 포함 가능) |
| 7 | `province` | str | 거주 시·도 (시·군·구 포함 형식) |
| 8 | `age_group` | str | 연령대 레이블 (예: `25-34_Early_Career`) |
| 9 | `job_category` | str | 한국표준직업분류 대분류 (9개 + 무직) |
| 10 | `salary_multiplier` | float | 직업별 상대 계수 (대분류 평균 대비, 무직=0.0) |
| 11 | `reasoning` | str | 분류 근거 설명 |
| 12 | `entry_age` | int | 추정 사회 진입 연령 (학력 기준, 취업준비 +1년) |
| 13 | `military_delay` | int | 군 복무 지연 연수 (남자=2, 여자=0) |
| 14 | `years_of_service` | int | 추정 근속연수 = max(0, age − entry_age − military_delay) |
| 15 | `seniority_multiplier` | float | 현재 연차 기준 호봉 계수 (0.70 ~ 1.15) |
| 16 | `education_multiplier` | float | 학력 프리미엄 계수 (0.80 ~ 1.10) |
| 17 | `region_multiplier` | float | 지역 프리미엄 계수 (서울=1.08, 기타=1.00) |
| 18 | `random_noise` | float | 개인 소득 변동성 (lognormal, seed=42, σ=0.15) |
| 19 | `estimated_monthly_salary` | float | 추정 월소득 (천원) |
| 20 | `estimated_annual_salary` | float | 추정 연소득 (천원) = 월소득 × 12 |
| 21 | `pension_balance` | float | 퇴직연금 잔액 추정 (천원), 연차별 누적 합산 |

### 제거된 컬럼 (19개)

| 제거 컬럼 | 제거 사유 |
|----------|----------|
| `professional_persona` ~ `career_goals_and_ambitions` (13개) | AI 생성 서술형 텍스트, 수치 분석과 무관 |
| `marital_status` | 소득·연금 산출에 미사용 |
| `military_status` | 자유 서술형 텍스트, `military_delay`로 대체 |
| `family_type` | 소득·연금 산출에 미사용 |
| `housing_type` | 소득·연금 산출에 미사용 |
| `district` | `province`로 충분 (시·군·구 포함) |
| `country` | 전원 대한민국으로 단일값 |

---

## 생성 파일 목록

| 파일 | 설명 |
|------|------|
| `occupation_mapping.csv` | 1,406개 직업 → 대분류 매핑 테이블 |
| `persona_job_mapped.csv` | 50,000행, 직업 매핑 컬럼 추가본 (중간 산출물) |
| `persona_final_earnings.csv` | **최종 출력**, 21컬럼, 11.2MB, UTF-8-sig |
| `map_occupations.py` | 직업 분류 스크립트 |
| `compute_earnings.py` | 소득·연금 계산 스크립트 |
| `slim_csv.py` | 불필요 컬럼 제거 스크립트 |

---

*최초 작성: 2026-05-23 / 최종 업데이트: 2026-05-23*
