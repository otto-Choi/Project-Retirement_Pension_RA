# 포트폴리오 파트 통합 아카이브
## XAI 기반 퇴직연금 ETF 포트폴리오 최적화 시스템

> **작성일**: 2026-06-10  
> **성격**: 포트폴리오 파트 전체 설계·구현·결과의 단일 아카이브 파일  
> **구성**: 이론 설계 → 데이터 파이프라인 → 최적화 알고리즘 → XAI → 통합 엔진 → 실행 결과  
> **법적 고지**: 이 시스템의 모든 출력은 「자본시장법」 제6조에 따라 **투자 추천이 아닌 투자 참고 정보**입니다.

---

## 목차

1. [프로젝트 개요](#1-프로젝트-개요)
2. [파일 구조](#2-파일-구조)
3. [이론적 배경 및 핵심 설계 파라미터](#3-이론적-배경-및-핵심-설계-파라미터)
4. [13개 슬롯 구조 및 대표 ETF](#4-13개-슬롯-구조-및-대표-etf)
5. [Step 1~2: ETF 필터링 및 연도말 유니버스 확정](#5-step-12-etf-필터링-및-연도말-유니버스-확정)
6. [Step 3: 기초자산 지수 수집 및 최적 윈도우 탐색](#6-step-3-기초자산-지수-수집-및-최적-윈도우-탐색)
7. [Step 4: BL 내재수익률 + 비제약 Sortino-max 포트폴리오](#7-step-4-bl-내재수익률--비제약-sortino-max-포트폴리오)
8. [Step 5: 지역제약 포트폴리오 + MVP (최종 확정)](#8-step-5-지역제약-포트폴리오--mvp-최종-확정)
9. [Step 5b: 모멘텀 뷰 추가 실험](#9-step-5b-모멘텀-뷰-추가-실험)
10. [Step 6: CAL 및 Risk Score → w_risky 매핑](#10-step-6-cal-및-risk-score--w_risky-매핑)
11. [Step 6b: 현재 시점 배분 산출 (라이브 서비스용)](#11-step-6b-현재-시점-배분-산출-라이브-서비스용)
12. [Step 7: 내재 위험회피계수 λ_implied 역산](#12-step-7-내재-위험회피계수-λ_implied-역산)
13. [Step 8-A: 사용자 대면 XAI 설계 및 구현](#13-step-8-a-사용자-대면-xai-설계-및-구현)
14. [XAI 설계 철학 및 레이어 구조](#14-xai-설계-철학-및-레이어-구조)
15. [Risk Score 설계 (페르소나 파이프라인)](#15-risk-score-설계-페르소나-파이프라인)
16. [통합 엔진 (portfolio_engine.py)](#16-통합-엔진-portfolio_enginepy)
17. [백테스트 주요 결과 요약](#17-백테스트-주요-결과-요약)
18. [구현 오류 발견 및 수정 이력](#18-구현-오류-발견-및-수정-이력)

---

## 1. 프로젝트 개요

한국 퇴직연금(DC/IRP) 가입자를 위해, 개인 **Risk Score** 기반으로 개인화된 ETF 포트폴리오 비중을 산출하고, **XAI**로 그 근거를 투명하게 제시하는 데이터 기반 참고 정보 시스템.

### 전체 파이프라인 흐름

```
[페르소나 파이프라인 (다른 팀)]
  엔비디아 페르소나 텍스트 → ko-sroberta → KMeans → GPT → Big Five z-score
  + 나이·직업·자금여력·가족·은퇴기간 설문
  → Risk Score (1~10점)
         ↓
[포트폴리오 파이프라인 (본 파트)]
  Step 3: 기초자산 지수 수집 → 최적 윈도우 탐색 → 5년 확정
  Step 4: Σ_down + BL 내재수익률 Π + Sortino-max 최적화 (비제약)
  Step 5: 지역제약(US≤50%/KR≤50%/EM≤15%) + MVP 병행 → 최종 포트폴리오
  Step 6: Risk Score → w_risky → CAL 최종 배분
  Step 7: λ_implied 역산
  Step 8: XAI (Layer A 사용자 대면 / Layer B 포트폴리오 내부)
         ↓
[통합 엔진: portfolio_engine.py]
  Risk Score + query_date + user_info → 포트폴리오 비중 + XAI 딕셔너리
```

### 개인화 배분 요약

```
Risk Score → 위험군 → w_risky → 최종 포트폴리오

1~2점: 초보수형 → w_risky  0%  → 전액 무위험
3~4점: 보수형   → w_risky 20%
5~6점: 중립형   → w_risky 40%
7~8점: 성장형   → w_risky 60%
9~10점: 공격형  → w_risky 70%  (DC/IRP 법적 상한)

최종 배분 = w_risky × Sortino-max 포트폴리오
           + (1 - w_risky) × 무위험자산
```

---

## 2. 파일 구조

```
퇴직연금 _XAI/
├── README.md
├── STRUCTURE.md
├── CLAUDE.md
│
├── src/
│   ├── step3_collect_data.py          ← Step 3: 기초자산 지수 데이터 수집
│   ├── step3_window_analysis.py       ← Step 3: 최적 롤링 윈도우 탐색
│   ├── step4_portfolio.py             ← Step 4: BL + Sortino-max (비제약)
│   ├── step5_constrained.py           ← Step 5: 지역제약 + MVP (확정 버전)
│   ├── step5b_momentum_views.py       ← Step 5b: 모멘텀 뷰 실험
│   ├── step6_cal.py                   ← Step 6: CAL + Risk Score 매핑
│   ├── step6b_current_allocation.py   ← Step 6b: 현재 시점 배분
│   ├── step7_lambda_implied.py        ← Step 7: 내재 λ 추정
│   ├── 08a_step8_user_xai.py          ← Step 8a: 사용자 XAI 시각화
│   └── portfolio_engine.py            ← 통합 엔진
│
├── notebooks/
│   ├── briefing_20260518.ipynb
│   ├── step6_7_check.ipynb
│   ├── step8a_user_xai.ipynb
│   └── step8b_analysis_xai.ipynb
│
├── data/
│   ├── index_returns.parquet          ← 기초자산 지수 일별 수익률
│   ├── slot_returns.parquet           ← ETF 슬롯별 일별 수익률
│   ├── mar_series.parquet             ← 시변 MAR (ECOS 정기예금)
│   ├── year_end_best.csv              ← 연도별×슬롯별 선정 ETF + AUM
│   └── ...
│
├── results/
│   ├── current/                       ← 현재 시점 최신 배분
│   ├── step3/                         ← 윈도우 분석 결과
│   ├── step4/                         ← 비제약 포트폴리오
│   ├── step5/                         ← 지역제약 포트폴리오 (최종)
│   ├── step5b/                        ← 모멘텀 실험
│   ├── step6/                         ← CAL 배분
│   ├── step7/                         ← λ_implied
│   └── step8/figures/                 ← XAI 시각화
│
└── docs/
    ├── 01_project_overview.md
    ├── 02_pipeline_design.md
    ├── 03_xai_design.md
    ├── 04_progress_steps1_5.md
    ├── 05_persona_risk_scoring.md
    ├── 06_dataset_reference.md
    ├── 07_meeting_notes.md
    ├── 08_feedback_log.md
    ├── 09_data_collection_plan.md
    ├── 10_todo.md
    ├── 11_authored_feedback.md
    ├── 12_step8_plan.md
    └── 13_model_review_and_improvement.md
```

---

## 3. 이론적 배경 및 핵심 설계 파라미터

### 이론 근거

| 이론 | 내용 | 적용 |
|------|------|------|
| Estrada (2007) | 하방공분산 행렬 정의 | Σ_down = (D.T @ D) / T, D = min(r - MAR, 0) |
| He & Litterman (1999) | Black-Litterman λ 표준값 2.5 | λ=3.0으로 상향 (퇴직연금 보수성 반영) |
| Merton (1969) | 장기 투자자 위험회피계수 2~4 | 은퇴 준비 투자자 → 상단(3~4) |
| Modigliani (1954) | 생애주기 가설 | 나이별 Risk Score |
| Bodie, Merton & Samuelson (1992) | 투자기간과 위험 수용 능력 | 은퇴기간별 점수 |
| OECD (2021) | 퇴직연금 가이드라인 | TDF 단계 참고 |
| Chen, Roll & Ross (1986) | APT 기반 거시 팩터 | 거시지표 설계 참고 |

### 확정 파라미터

| 파라미터 | 값 | 결정 근거 |
|---------|-----|----------|
| 위험 측도 | 하방공분산 Σ_down (Estrada 2007) | 정규분포 가정 없이 하방위험만 포착 |
| 기대수익률 | BL 내재수익률 Π = λ·Σ_down·w_mkt | 시장 포트폴리오 역산, 추정 오류 최소화 |
| λ | **3.0** | He & Litterman(1999) 2.5 + 퇴직연금 보수성 |
| MAR | ECOS 정기예금 수신금리 (시변) | 무위험 기준, 분기 시변 |
| 최적화 목적 | Sortino 비율 최대화 (SLSQP) | 하방위험 중심 |
| 윈도우 | **5년 (1,260거래일)** | 4기준 종합 점수 0.728 (1위) |
| 리밸런싱 | **분기 (63거래일)** | 실전 운용 주기와 일치 |
| 개별 자산 상한 | **40%** | 단일 자산 과집중 방지 |
| 개별 자산 하한 | **1%** | — |
| US 주식 상한 | **50%** | SP500 + 나스닥 합계 |
| KR 주식 상한 | **50%** | 코스피 + 코스닥 합계 |
| EM 주식 상한 | **15%** | MSCI EM 시가총액 비중 ~12% 대비 |
| 위험자산 상한 | **70%** | DC/IRP 법적 상한 |

### λ = 3.0 결정 근거

- He & Litterman(1999): 시장 중립값 2.5 (Sharpe ≈ 0.5 가정)
- Merton(1969): 장기 투자자 위험회피계수 범위 2~4, 은퇴 준비 투자자는 상단(3~4)
- Blitz & van Vliet(2007): 퇴직연금 운용자 실효 λ 평균 2.8~3.2 실증
- Sortino 목적함수와 방향성 일관성: 하방위험 페널티 강화 → λ 상향 정합

### EM ≤ 15% 제약 근거

- US ≤ 50% 적용 이후 중국 ETF가 1.8% → 16.5%로 급증
- MSCI ACWI 내 신흥국 비중 ~12% (2024)
- 국민연금 해외 신흥국 목표 비중 5~10%
- 중국 고유 리스크: 자본통제·회계 투명성·2021 테크 규제 등 공분산이 포착 못하는 테일 리스크
- US·KR 상한 존재 + EM 무상한은 제약 비대칭

---

## 4. 13개 슬롯 구조 및 대표 ETF

```
국내주식_코스피 / 국내주식_코스닥
미국주식_SP500 / 미국주식_나스닥
신흥국_인도 / 신흥국_중국
국내채권_국고채단중기 / 국내채권_국고채장기 / 국내채권_회사채 / 국내채권_종합
해외채권_미국국채
원자재_금
무위험(현금성)
```

| 슬롯 | 대표 ETF | 티커 | 비고 |
|------|---------|------|------|
| 국내주식_코스피 | KODEX 200 | 069500 | |
| 국내주식_코스닥 | KODEX 코스닥150 | 229200 | |
| 미국주식_SP500 | TIGER 미국S&P500 | 360750 | |
| 미국주식_나스닥 | KODEX 미국나스닥100 | 379810 | |
| 신흥국_인도 | KODEX 인도Nifty50 | 453810 | |
| 신흥국_중국 | TIGER 차이나항셍테크 | 371160 | |
| 국내채권_국고채단중기 | KODEX 국고채3년 | 114260 | |
| 국내채권_국고채장기 | RISE KIS국고채30년Enhanced | 385560 | |
| 국내채권_회사채 | SOL 중단기회사채(A-이상)액티브 | 0016X0 | |
| 국내채권_종합 | KODEX 종합채권(AA-이상)액티브 | 273130 | |
| 해외채권_미국국채 | TIGER 미국초단기(3개월이하)국채 | 0046A0 | 비환헤지 초단기 |
| 원자재_금 | ACE KRX금현물 | 411060 | |
| 무위험(현금성) | KODEX 머니마켓액티브 | 488770 | |

**해외채권_미국국채 선정 근거**: USD/KRW 환율 효과 반영을 위해 비환헤지 초단기물 선택. 단, 초단기 선택으로 듀레이션 효과(주식과의 음의 상관관계)는 포기하는 트레이드오프 인지 후 결정.

### 슬롯별 데이터 첫 등장 연도

| 슬롯 | 첫 데이터 연도 |
|------|------------|
| 국내주식_코스피·코스닥, 무위험(현금성) | 2015~ |
| 국내채권_종합 | 2017~ |
| 국내채권_국고채장기 | 2018~ |
| 국내채권_국고채단중기 | 2019, 2024만 존재 |
| 미국주식_SP500·나스닥, 신흥국_중국 | 2020~ |
| 원자재_금 | 2021~ |
| 국내채권_회사채 | 2022~ |
| 신흥국_인도, 해외채권_미국국채 | 2023~ |

---

## 5. Step 1~2: ETF 필터링 및 연도말 유니버스 확정

### Step 1: 우량 ETF 필터링

| 필터 | 기준 |
|------|------|
| 레버리지·인버스·상폐 제거 | `추적배수 == '일반'` & `is_delisted == False` |
| AUM | ≥ 500억 원 |
| 일평균 거래대금 | ≥ 10억 원 (최근 250거래일 기준) |
| 총보수 | ≤ 전체 평균 + 1σ |

출력: `data/filtered_universe.csv`

### Step 2: 연도말 유니버스 확정 원칙

- 각 연도말 기준으로 필터를 재적용해 그 시점에 실제 투자 가능했던 ETF 목록 확정
- **생존편향 차단**: 현재 대표 ETF를 과거에 소급 적용하지 않음
- **대표 ETF 선정 우선순위**: 순수 지수 추종(plain) → 비환헤지 우선 → AUM 최대
- 커버 기간: 2015~2024 (10개년)

출력: `data/year_end_universe.csv`, `data/year_end_best.csv` (71행)

---

## 6. Step 3: 기초자산 지수 수집 및 최적 윈도우 탐색

### 6-1. 데이터 수집 설계 (`src/step3_collect_data.py`)

**슬롯별 데이터 소스:**

| 슬롯 | 소스 | API |
|------|------|-----|
| 국내주식_코스피·코스닥, 미국주식, 신흥국, 금 | 가격 수익률 | yfinance |
| 해외채권_미국국채 | ^IRX (13주 T-bill), 연율할인율/252 | yfinance |
| 국내채권_국고채단중기 | 국고채3년 (MD=2.8) | ECOS 817Y002/010200000 |
| 국내채권_국고채장기 | 국고채30년 (MD=18.0) | ECOS 817Y002/010230000 |
| 국내채권_회사채 | 회사채AA- 3년 (MD=2.7) | ECOS 817Y002/010300000 |
| 국내채권_종합 | 국고채3년(50%)+10년(50%) (MD=5.5) | ECOS |
| 무위험(현금성) | CD91일 / 252 | ECOS 817Y002/010502000 |
| MAR | 정기예금6개월미만 (월별) | ECOS 121Y002/BEABAA2111 |

**채권 수익률 변환:**
```python
def yield_to_ret(yield_pct, modified_duration):
    y = yield_pct / 100
    carry   = y / 252
    delta_y = y.diff()
    return (carry - modified_duration * delta_y).dropna()
```

**수집 스크립트 전체:**

```python
"""
피드백 2: 롤링 윈도우 탐색용 기초자산 지수 데이터 수집
출력:
  data/index_returns.parquet   ← 슬롯별 일간 수익률
  data/mar_series.parquet      ← 월별 정기예금 금리 (MAR)
"""

import argparse, warnings, numpy as np, pandas as pd, requests
import yfinance as yf
from pathlib import Path

warnings.filterwarnings('ignore')

parser = argparse.ArgumentParser()
parser.add_argument('--end', default=pd.Timestamp.today().strftime('%Y-%m-%d'))
args = parser.parse_args()

DATA_DIR = Path(__file__).parent.parent / 'data'
ECOS_KEY = '1J5840GM10SEKX5HM748'
START_YF = '2000-01-01'
END_YF   = args.end
_end_ecos   = pd.Timestamp(END_YF).strftime('%Y%m%d')
_end_ecos_m = pd.Timestamp(END_YF).strftime('%Y%m')

SLOTS = [
    '국내주식_코스피', '국내주식_코스닥',
    '미국주식_SP500',  '미국주식_나스닥',
    '신흥국_인도',     '신흥국_중국',
    '국내채권_국고채단중기', '국내채권_국고채장기',
    '국내채권_회사채', '국내채권_종합',
    '해외채권_미국국채', '원자재_금', '무위험(현금성)',
]

def ecos_fetch(stat_code, item_code, cycle='D', start='20000101', end=None):
    if end is None:
        end = _end_ecos
    if cycle == 'M':
        start = start[:6]; end = end[:6]
    url = (f"https://ecos.bok.or.kr/api/StatisticSearch/{ECOS_KEY}/json/kr/1/100000/"
           f"{stat_code}/{cycle}/{start}/{end}/{item_code}")
    try:
        r = requests.get(url, timeout=30); js = r.json()
    except Exception as e:
        return None
    if 'StatisticSearch' not in js:
        return None
    rows = js['StatisticSearch'].get('row', [])
    if not rows:
        return None
    df = pd.DataFrame(rows)[['TIME', 'DATA_VALUE']].copy()
    fmt = '%Y%m%d' if cycle == 'D' else '%Y%m'
    df['date']  = pd.to_datetime(df['TIME'], format=fmt, errors='coerce')
    df['value'] = pd.to_numeric(df['DATA_VALUE'], errors='coerce')
    s = df.dropna(subset=['date','value']).set_index('date')['value'].sort_index()
    return s if len(s) > 0 else None

def yield_to_ret(yield_pct, modified_duration):
    y = yield_pct / 100
    carry   = y / 252
    delta_y = y.diff()
    return (carry - modified_duration * delta_y).dropna()

def dl_yf(ticker, name):
    try:
        df = yf.download(ticker, start=START_YF, end=END_YF, progress=False, auto_adjust=True)
        if df.empty:
            raise ValueError("빈 데이터")
        close = df['Close'].squeeze()
        close.index = pd.to_datetime(close.index)
        if close.index.tz is not None:
            close.index = close.index.tz_localize(None)
        return close.pct_change().dropna()
    except Exception as e:
        return None

# 주식·금 (yfinance)
yf_map = {
    '국내주식_코스피': ('^KS11','코스피'), '국내주식_코스닥': ('^KQ11','코스닥'),
    '미국주식_SP500': ('^GSPC','S&P 500'), '미국주식_나스닥': ('^NDX','NASDAQ 100'),
    '신흥국_인도': ('^NSEI','Nifty 50'), '신흥국_중국': ('^HSI','항셍지수'),
    '원자재_금': ('GC=F','금 선물'),
}
rets = {slot: dl_yf(ticker, name) for slot, (ticker, name) in yf_map.items()
        if dl_yf(ticker, name) is not None}

# 미국 단기국채 (^IRX)
try:
    df_irx = yf.download('^IRX', start=START_YF, end=END_YF, progress=False, auto_adjust=True)
    irx = df_irx['Close'].squeeze()
    irx.index = pd.to_datetime(irx.index)
    if irx.index.tz is not None:
        irx.index = irx.index.tz_localize(None)
    rets['해외채권_미국국채'] = (irx.dropna() / 100) / 252
except:
    pass

# 국내채권·CD (ECOS)
ecos_items = {
    'y3':  ('010200000', '국고채(3년)'),   'y10': ('010210000', '국고채(10년)'),
    'y30': ('010230000', '국고채(30년)'),  'ycc': ('010300000', '회사채(3년,AA-)'),
    'cd':  ('010502000', 'CD(91일)'),
}
raw_yields = {key: ecos_fetch('817Y002', code)
              for key, (code, _) in ecos_items.items()
              if ecos_fetch('817Y002', code) is not None}

bond_cfg = [('국내채권_국고채단중기','y3',2.8), ('국내채권_국고채장기','y30',18.0),
            ('국내채권_회사채','ycc',2.7)]
for slot, key, md in bond_cfg:
    if key in raw_yields:
        rets[slot] = yield_to_ret(raw_yields[key], md)

if 'y3' in raw_yields and 'y10' in raw_yields:
    idx_c = raw_yields['y3'].index.intersection(raw_yields['y10'].index)
    y_agg = raw_yields['y3'][idx_c] * 0.5 + raw_yields['y10'][idx_c] * 0.5
    rets['국내채권_종합'] = yield_to_ret(y_agg, 5.5)

if 'cd' in raw_yields:
    rets['무위험(현금성)'] = raw_yields['cd'] / 100 / 252

# MAR (ECOS 정기예금 6개월미만)
mar_series = ecos_fetch('121Y002', 'BEABAA2111', cycle='M',
                         start='200001', end=_end_ecos_m)

# 저장
idx_df = pd.DataFrame({slot: s for slot, s in rets.items() if slot in SLOTS}).sort_index()
idx_df.to_parquet(DATA_DIR / 'index_returns.parquet')
mar_series.rename('mar_annual').to_frame().to_parquet(DATA_DIR / 'mar_series.parquet')
```

### 6-2. 최적 롤링 윈도우 탐색 (`src/step3_window_analysis.py`)

**핵심 설계 원칙:**
- 입력: ETF 수익률이 아닌 **기초자산 지수 수익률** (ETF 상장 이전까지 소급 가능)
- 평가: 단일 기준이 아닌 **4가지 종합 기준**

**평가 기준 (가중치):**

| 기준 | 설명 | 가중치 |
|------|------|-------|
| ① 평균 예측 오차 (MAE) | 예측 하방위험 vs 실제 하방위험 MAE | **35%** |
| ② 실현 소르티노 비율 | 평균 → 최대화 | **30%** |
| ③ 오차 일관성 (σ) | 소르티노 시계열 표준편차 → 최소화 | **25%** |
| ④ 이상치 민감도 | 이상치 포함/제외 소르티노 차이 → 최소화 | **10%** |

**윈도우 비교 결과:**

| 윈도우 | 검증 분기 | ① MAE(%) | ② 소르티노 | ③ 소르티노σ | ④ 민감도 | **종합 점수** |
|--------|---------|---------|-----------|------------|---------|-------------|
| 1yr (252일) | 101 | 2.669 | 0.572 | 1.652 | 0.073 | 0.644 |
| 2yr (504일) | 97 | 2.937 | 0.561 | 1.691 | 0.009 | 0.267 |
| 3yr (756일) | 93 | 2.870 | 0.512 | 1.582 | 0.015 | 0.428 |
| **5yr (1260일)** | **85** | **2.854** | **0.600** | **1.591** | **0.015** | **0.728 ★** |

> **5년 선정 근거**: 소르티노 평균 1위(0.600), 이상치 민감도 공동 1위(0.015). 1yr는 MAE 우위이나 이상치 민감도가 5배 높아 COVID·금리급등 구간에서 성과 왜곡이 큼.

**walk-forward 핵심 로직:**

```python
WIN_DAYS  = 1260   # 5년
REBAL_DAYS = 63    # 분기
LAMBDA    = 2.5    # Step 3에서는 2.5 사용

def downside_cov(rets_arr, mar_daily_scalar):
    """Estrada(2007) 하방 공분산 — MAR: 일별 소수"""
    d = np.minimum(rets_arr - mar_daily_scalar, 0.0)
    return (d.T @ d) / len(d)

def solve_max_sortino(sigma_down, pi, mar_q, w_min, w_max):
    n = len(pi)
    def neg_sortino(w):
        ret  = float(w @ pi) * REBAL_DAYS
        risk = np.sqrt(max(float(w @ sigma_down @ w) * REBAL_DAYS, 1e-12))
        return -(ret - mar_q) / risk
    res = minimize(neg_sortino, np.ones(n) / n, method='SLSQP',
                   bounds=[(w_min, w_max)] * n,
                   constraints=[{'type': 'eq', 'fun': lambda w: w.sum() - 1}],
                   options={'maxiter': 500, 'ftol': 1e-9})
    return res.x if res.success else np.ones(n) / n
```

출력: `results/step3/window_analysis_result.csv`

---

## 7. Step 4: BL 내재수익률 + 비제약 Sortino-max 포트폴리오

**스크립트**: `src/step4_portfolio.py`

### 핵심 수식

```python
# 하방공분산 (Estrada 2007)
D          = np.minimum(r - MAR_daily, 0.0)    # r: T×N, MAR_daily: 일별 scalar
Sigma_down = (D.T @ D) / len(D)               # N×N 하방공분산 행렬

# BL 내재수익률 (λ=3.0)
Pi = lambda_ * Sigma_down @ w_mkt             # w_mkt = 전년도 AUM 비중

# 소르티노 최대화 (SLSQP)
maximize  (w @ Pi * 63 - MAR_q) / sqrt(w @ Sigma_down @ w * 63)
subject to: sum(w) = 1,  0.01 ≤ w_i ≤ 0.40
```

### 설계 원칙

- **추정**: `index_returns.parquet` (기초자산 지수, 25년) — 윈도우 교정 일관성
- **OOS 평가**: `slot_returns.parquet` (실제 ETF 수익률) — 실제 보수·추적오차 반영
- **w_mkt**: `year_end_best.csv` AUM 비중 (당해 연도 → 전년도 연도말 ETF 사용)
- **MAR**: ECOS 정기예금 시변 적용 (고정 2.5% → 교체)

### 전체 기간 요약 (2016 Q1 ~ 2025 Q1)

| 지표 | 값 |
|------|-----|
| 누적 수익률 | **+120.6%** |
| 평균 분기 수익률 | +2.52% (~연 10%) |
| 평균 소르티노 | 0.927 |
| MDD | **-34.8%** |
| 소르티노 > 0 비율 | 60.5% |

### 발견된 문제 → Step 5 이관

2023년 이후 SP500(40%) + 나스닥(40%) = US 주식 **80% 집중**.  
→ Step 5에서 지역별 합계 상한(US ≤ 50%, KR ≤ 50%) 제약 추가.

### 스크립트 핵심 부분

```python
WIN_DAYS    = 1260; REBAL_DAYS  = 63; LAMBDA = 2.5  # Step 4는 λ=2.5
W_MAX = 0.40; W_MIN = 0.01; MISSING_TOL = 0.30; MIN_OOS_FILL = 0.70

for end_i in range(WIN_DAYS, n_idx - REBAL_DAYS, REBAL_DAYS):
    rebal_date = idx_dates[end_i]
    ref_year   = int(rebal_date.year) - 1

    # OOS 슬롯 확인
    oos_raw   = slot_rets[yeb_slots].iloc[sr_pos : sr_pos + REBAL_DAYS]
    oos_avail = [s for s in yeb_slots
                 if oos_raw[s].notna().sum() >= int(REBAL_DAYS * MIN_OOS_FILL)]

    # 5년 추정 윈도우
    est_v = idx_rets[valid_cols].iloc[end_i - WIN_DAYS : end_i].dropna()

    # 하방공분산 & BL 내재수익률
    mar_est    = float(mar_rate.reindex(idx_rets.index[end_i-WIN_DAYS:end_i], method='ffill').mean())
    sigma_down = downside_cov(est_v.values, mar_est)
    aum_vals   = np.array([aum_by_year[ref_year].get(s, 1.0) for s in valid_cols], dtype=float)
    w_mkt      = aum_vals / aum_vals.sum()
    pi         = LAMBDA * sigma_down @ w_mkt

    w_opt = solve_max_sortino(sigma_down, pi, mar_est * REBAL_DAYS)

    # OOS 성과 (실제 ETF 수익률)
    port_r  = oos_sr.values @ w_opt
    cum_r   = float((port_r + 1).prod() - 1)
    down_r  = np.minimum(port_r - mar_oos_daily, 0.0)
    real_down = np.sqrt(max(float(np.mean(down_r ** 2)) * n_oos, 0))
    sortino = (cum_r - mar_oos_q) / (real_down + 1e-10)
```

출력: `results/step4/portfolio_weights.parquet`, `portfolio_performance.parquet`, `summary.csv`, `weights_pivot.csv`

---

## 8. Step 5: 지역제약 포트폴리오 + MVP (최종 확정)

**스크립트**: `src/step5_constrained.py`

### 추가된 제약 조건

```
기존 (Step 4):  0.01 ≤ w_i ≤ 0.40,  sum(w) = 1

신규 (Step 5):  + Σ(US 주식) ≤ 0.50   [SP500 + 나스닥]
               + Σ(KR 주식) ≤ 0.50   [코스피 + 코스닥]
               + Σ(EM 주식) ≤ 0.15   [인도 + 중국]
               
★ λ = 3.0  (기존 2.5에서 상향)
```

### 3가지 포트폴리오 동시 산출

```python
LAMBDA   = 3.0     # ★ 2.5 → 3.0
US_CAP   = 0.50
KR_CAP   = 0.50
EM_CAP   = 0.15    # ★ 신규

def _build_constraints(valid_cols, n):
    cons = [{'type': 'eq', 'fun': lambda w: w.sum() - 1}]
    us_idx = [i for i, s in enumerate(valid_cols) if s in US_SLOTS]
    kr_idx = [i for i, s in enumerate(valid_cols) if s in KR_SLOTS]
    em_idx = [i for i, s in enumerate(valid_cols) if s in EM_SLOTS]
    if us_idx:
        cons.append({'type': 'ineq', 'fun': lambda w, ix=us_idx: US_CAP - sum(w[i] for i in ix)})
    if kr_idx:
        cons.append({'type': 'ineq', 'fun': lambda w, ix=kr_idx: KR_CAP - sum(w[i] for i in ix)})
    if em_idx:
        cons.append({'type': 'ineq', 'fun': lambda w, ix=em_idx: EM_CAP - sum(w[i] for i in ix)})
    return cons

def solve_sortino_max(sigma_down, pi, mar_q, valid_cols):
    """소르티노 최대화 (지역 제약 포함)."""
    n = len(pi)
    cons = _build_constraints(valid_cols, n)
    def neg_sortino(w):
        ret  = float(w @ pi) * REBAL_DAYS
        risk = np.sqrt(max(float(w @ sigma_down @ w) * REBAL_DAYS, 1e-12))
        return -(ret - mar_q) / risk
    res = minimize(neg_sortino, np.ones(n) / n, method='SLSQP',
                   bounds=[(W_MIN, W_MAX)] * n, constraints=cons,
                   options={'maxiter': 500, 'ftol': 1e-9})
    return res.x if res.success else np.ones(n) / n

def solve_mvp(sigma_down, valid_cols):
    """최소 하방분산 포트폴리오 (MVP)."""
    n = sigma_down.shape[0]
    cons = _build_constraints(valid_cols, n)
    res = minimize(lambda w: float(w @ sigma_down @ w), np.ones(n) / n,
                   method='SLSQP', bounds=[(W_MIN, W_MAX)] * n,
                   constraints=cons, options={'maxiter': 500, 'ftol': 1e-9})
    return res.x if res.success else np.ones(n) / n

# 분기별 Σ_down, Π, 제약 바인딩 이력 저장
sigma_row = {'date': rebal_date}
for a in SLOTS:
    for b in SLOTS:
        key = f"{a}__{b}"
        if a in valid_cols and b in valid_cols:
            sigma_row[key] = float(sigma_down[valid_cols.index(a), valid_cols.index(b)])
        else:
            sigma_row[key] = float('nan')
rec_sigma.append(sigma_row)

pi_row = {'date': rebal_date}
for s in SLOTS:
    pi_row[s] = float(pi[valid_cols.index(s)]) if s in valid_cols else float('nan')
rec_pi.append(pi_row)
```

### 비제약 vs 지역제약 종합 비교

| 지표 | 비제약 (Step 4) | **지역제약 (Step 5)** | 차이 |
|------|----------------|----------------------|------|
| 누적 수익률 | +120.6% | **+94.9%** | -25.7%p |
| 평균 분기 수익률 | +2.52% | **+2.00%** | -0.52%p |
| 평균 소르티노 | 0.927 | **0.631** | -0.296 |
| 소르티노 σ | 2.173 | **1.659** | **-0.514** ↓ |
| **MDD** | -34.8% | **-24.4%** | **+10.5%p 개선** |
| 소르티노 > 0 비율 | 60.5% | 60.5% | 동일 |
| 평균 유효 자산 수 | 2.93 | **3.09** | +0.16 ↑ |

### ★ 최종 선택: 지역제약 포트폴리오 (Step 5)

실전 투자자 관점에서 **MDD 개선(+10.5%p)이 수익 포기(-25.7%p)보다 중요**.  
퇴직연금 맥락에서 원금 손실 최소화는 수익 극대화와 동등하거나 더 높은 우선순위를 갖는다.

### MVP 병행 구현 이유

1. CAL 구성 시 리스크자산 포트폴리오의 하한 경계점
2. "왜 MVP 대신 Sortino-max인가"에 대한 정량 근거
3. XAI에서 두 포트폴리오 비중 차이를 설명 → 학술적 타당성
4. Step 7 CVaR와 3방향 비교 가능

### 최근 리밸런싱 비중 (2025-01-16)

| 슬롯 | Sortino-max | MVP |
|------|-------------|-----|
| 미국주식_나스닥 | 40.0% | — |
| 미국주식_SP500 | 10.0% | — |
| 국내주식_코스닥 | 24.5% | — |
| ... | ... | ... |

출력:
- `results/step5/portfolio_weights_constrained.parquet`
- `results/step5/portfolio_performance_constrained.parquet`
- `results/step5/portfolio_weights_mvp.parquet`
- `results/step5/portfolio_performance_mvp.parquet`
- `results/step5/sigma_down_history.parquet`
- `results/step5/pi_history.parquet`
- `results/step5/binding_history.parquet`
- `results/step5/comparison.csv`
- `results/step5/weights_constrained.csv`

---

## 9. Step 5b: 모멘텀 뷰 추가 실험

**스크립트**: `src/step5b_momentum_views.py`

Step 5 대비 두 가지 모멘텀 강화 기능 추가 (실험 목적, 기본 파이프라인에 미채택):

**[B] 음수 모멘텀 슬롯 필터링**
```python
LOOKBACK_MOM = 252   # 12개월
MOM_FILTER   = True

# 12개월 누적 수익률이 음수인 슬롯을 해당 분기 추정에서 제외
# 무위험(현금성)은 필터 제외 (항상 포함)
filtered = [s for s in valid_cols
            if mom_map[s] >= 0 or s == RF_SLOT]
if len(filtered) >= MIN_SLOTS_AFTER_FILTER:
    valid_cols = filtered
```

**[C] w_mkt 모멘텀 가중**
```python
MOM_WMKT  = True
MOM_FLOOR = 0.02   # 음수 모멘텀 슬롯의 최소 w_mkt 승수

# 모멘텀 강한 자산에 높은 시장 비중 → Π prior 자체가 달라짐
mom_scale = np.where(mom_arr >= 0, 1.0 + mom_arr, MOM_FLOOR)
w_mkt = (aum_vals * mom_scale) / (aum_vals * mom_scale).sum()
pi_prior = LAMBDA * sigma_down @ w_mkt
```

출력: `results/step5b/` (Step 5와 동일 구조)

---

## 10. Step 6: CAL 및 Risk Score → w_risky 매핑

**스크립트**: `src/step6_cal.py`

### Risk Score → w_risky 앵커 (선형 보간)

```python
_ANCHORS = np.array([1, 3, 5, 7, 9], dtype=float)
_W_RISKY = np.array([0.00, 0.20, 0.40, 0.60, 0.70], dtype=float)

def score_to_w_risky(risk_score: float) -> float:
    """Risk Score (1~10 실수) → w_risky 선형 보간, 상한 70% 클리핑."""
    w = float(np.interp(risk_score, _ANCHORS, _W_RISKY))
    return round(min(w, W_RISKY_CAP), 4)   # W_RISKY_CAP = 0.70
```

### CAL 배분 계산

```python
def compute_cal_allocation(risk_score, sortino_weights):
    """
    최종 배분 = w_risky × Sortino-max + (1-w_risky) → 무위험 슬롯
    """
    w_risky = score_to_w_risky(risk_score)
    final = sortino_weights * w_risky
    final[RISKFREE_SLOT] = final.get(RISKFREE_SLOT, 0.0) + (1.0 - w_risky)
    return final.round(6)
```

### Risk Score → w_risky 전체 매핑표

| Risk Score | w_risky | w_riskfree | 위험군 |
|------------|---------|------------|--------|
| 1.0 | 0.00 | 1.00 | 초보수형 |
| 2.0 | 0.10 | 0.90 | 초보수형 |
| 3.0 | 0.20 | 0.80 | 보수형 |
| 4.0 | 0.30 | 0.70 | 보수형 |
| 5.0 | 0.40 | 0.60 | 중립형 |
| 6.0 | 0.50 | 0.50 | 중립형 |
| 7.0 | 0.60 | 0.40 | 성장형 |
| 8.0 | 0.65 | 0.35 | 성장형 |
| 9.0 | 0.70 | 0.30 | 공격형 |
| 10.0 | 0.70 | 0.30 | 공격형 |

출력: `results/step6/risk_score_map.csv`, `cal_demo_allocations.parquet`, `cal_demo_allocations.csv`

---

## 11. Step 6b: 현재 시점 배분 산출 (라이브 서비스용)

**스크립트**: `src/step6b_current_allocation.py`

백테스트(Step 5)는 OOS 평가 기간이 필요해 마지막 리밸런싱이 2025-01-16에 멈춤.  
새 투자자 서비스는 OOS 평가 없이 **현재 시점 기준** 최적 비중만 필요.

```python
# 현재 추정 윈도우 (기본: 데이터 마지막 날짜 기준 5년)
end_date = AS_OF if AS_OF else idx_rets.index[-1]
window   = idx_rets.iloc[start_i : end_i + 1]

# w_mkt: 현재 연도 직전 연도말 AUM
ref_year = end_date.year - 1

# 동일 최적화 로직 (Step 5 파라미터 동일)
# Sortino-max + MVP 동시 산출

def portfolio_risk_metrics(w_full):
    """
    UI 표시용 위험 지표 4종:
    - exp_ret_ann_pct  : 기대수익률 연환산 (BL 기준, %)
    - vol_ann_pct      : 변동성 연환산 (full covariance, %)
    - down_risk_q_pct  : 하방위험 분기 (Downside Std, %)
    - cvar_95_q_pct    : CVaR 95% 분기 (역사적 중첩 63일 윈도우, %)
    """
    w_v = np.array([float(w_full.get(s, 0)) for s in valid_cols])
    exp_ret_ann  = float(w_v @ pi) * 252 * 100
    down_risk_q  = np.sqrt(max(float(w_v @ sigma_down @ w_v) * REBAL_DAYS, 1e-12)) * 100
    vol_ann      = np.sqrt(max(float(w_v @ sigma_full @ w_v) * 252, 1e-12)) * 100

    # 역사적 중첩 63일 윈도우로 CVaR
    dp = est_v.values @ w_v
    q_rets = np.array([float(np.prod(1 + dp[i:i+REBAL_DAYS]) - 1) * 100
                       for i in range(len(dp) - REBAL_DAYS + 1)])
    var_95  = float(np.percentile(q_rets, 5))
    cvar_95 = float(q_rets[q_rets <= var_95].mean()) if (q_rets <= var_95).any() else var_95
    return {
        'exp_ret_ann_pct': round(exp_ret_ann, 2),
        'vol_ann_pct':     round(vol_ann, 2),
        'down_risk_q_pct': round(down_risk_q, 2),
        'cvar_95_q_pct':   round(cvar_95, 2),
    }
```

출력:
- `results/current/current_weights_sortino.csv`
- `results/current/current_weights_mvp.csv`
- `results/current/current_cal_allocations.csv` (Risk Score별 CAL 배분 + 위험지표 4종)
- `results/current/current_meta.json`

---

## 12. Step 7: 내재 위험회피계수 λ_implied 역산

**스크립트**: `src/step7_lambda_implied.py`

### 설계 원칙

λ_implied는 **BL 내재수익률(Π) 기반**으로 계산 (OOS 실현수익률 X).
- 목적: "이 w_risky 선택에 내재된 위험회피 수준이 시장 기준(λ=3.0)과 얼마나 다른가"
- 실현수익률은 분기마다 노이즈가 크므로 기대수익률(Π) 사용이 안정적

### 역산 수식

```
CAL 최적 조건 (mean-downside variance 효용 최대화):
  w_risky* = (E[R_risky] - R_f) / (λ × DownVar_risky)
  => λ = (E[R_risky] - MAR_q) / (w_risky × DownVar_risky)
```

```python
def calc_lambda_implied(w_sortino, pi_vec, sigma_down, mar_q, w_risky):
    """
    DownVar_risky는 100% 리스크자산 포트폴리오 기준.
    CAL로 스케일된 비중으로 계산하면 w_risky³이 분모에 들어가 발산.
    """
    if w_risky < 1e-4:
        return np.nan

    e_r_q       = float(w_sortino @ pi_vec) * REBAL_DAYS      # 분기 기대수익
    var_risky_q = float(w_sortino @ sigma_down @ w_sortino) * REBAL_DAYS  # 분기 하방분산
    excess_q    = e_r_q - mar_q
    denom       = w_risky * var_risky_q

    return round(excess_q / denom, 4) if denom > 1e-12 else np.nan
```

### 해석

- `λ > λ_market(3.0)` → 모델 대비 보수적 (주어진 리스크에서 더 높은 수익률 요구)
- `λ < λ_market(3.0)` → 모델 대비 공격적

출력: `results/step7/lambda_implied.parquet`, `lambda_implied.csv`

---

## 13. Step 8-A: 사용자 대면 XAI 설계 및 구현

**스크립트**: `src/08a_step8_user_xai.py`

### 8-A0: 기회비용 시뮬레이션

```python
def plot_a0_opportunity_cost(current_balance, annual_salary, years_to_retire, risk_score):
    """원리금보장 방치 vs 참고 포트폴리오 미래 자산 비교"""
    def fv(balance, monthly_c, ann_r, yrs):
        if ann_r < 1e-6:
            return balance + monthly_c * 12 * yrs
        fv_lump    = balance * (1 + ann_r) ** yrs
        fv_annuity = monthly_c * ((1 + ann_r) ** yrs - 1) / (ann_r / 12)
        return fv_lump + fv_annuity

    fv_bench = fv(current_balance, monthly_contrib, bench_return, years)
    fv_port  = fv(current_balance, monthly_contrib, portfolio_return, years)
    opp_cost = fv_port - fv_bench
    # → 시계열 경로 라인 차트 + 차이 주석
```

### 8-A1: Risk Score → CAL 흐름

```
[Risk Score 7.2점 (성장형)]
    ↓
[w_risky = 60%]  (DC/IRP 법적 상한 70%)
   ↙               ↘
[Sortino-max 60%]  [무위험자산 40%]
    ↓
[최종: 위험 60% + 무위험 40%]
```

### 8-A2: Risk Score 하위변수 기여 분해 (워터폴)

```python
weights = {'나이':0.15, '은퇴기간':0.20, '직업':0.15,
           '자금':0.20, '가족':0.15, '라이프':0.15}
BASE = 5.0
deltas = {k: weights[k] * (sub_scores[k] - BASE) for k in weights}
total  = BASE + sum(deltas.values())
# → 워터폴 차트: 기준(5점) + 각 변수 기여 + 최종 Risk Score
```

### 8-A3: Big Five 라이프스타일 경로

```
라이프스타일 문장 입력
  → ko-sroberta 임베딩 (768차원)
  → KMeans(500) 클러스터링
  → 대표 문장 GPT 점수화 (openness, conscientiousness, stability: 1~5)
  → 전체 전파 → z-score 표준화
  → risk = 0.45×openness_z - 0.45×stability_z + 0.10×conscientiousness_z
  → qcut → 라이프스타일 점수 1~5등급
```

### 8-A4: 손실 감내도 시각화

```python
def plot_a4_loss_gauge(current_balance, annual_salary, risk_score, mdd=MDD_CON):
    w_risky            = score_to_w_risky(risk_score)
    cal_mdd            = mdd * w_risky          # CAL 적용 후 실질 MDD
    expected_loss_krw  = current_balance * abs(cal_mdd)
    loss_vs_months     = expected_loss_krw / (annual_salary / 12)
    # → MDD 비율 게이지 + 금액 환산 정보 카드
```

### 8-A5: 내재 λ 성향 지표

```python
def plot_a5_lambda_gauge(risk_score):
    # RS별 λ_implied 중앙값 바 차트 + 해당 투자자 프로파일 카드
    # λ_market = 3.0 기준선 표시
    direction = '보수적' if lam_median > LAMBDA_MARKET else '공격적'
```

### 8-A6: MVP vs Sortino-max 비교

```python
def plot_a6_mvp_vs_sortino(risk_score):
    w_risky     = score_to_w_risky(risk_score)
    cal_cum_con = (cum_con - 1) * w_risky    # CAL 적용 후 누적 수익률
    cal_mdd_con = MDD_CON * w_risky

    recommend = 'Sortino-max' if risk_score >= 5 else 'MVP'
    # → 누적 수익률 시계열 + 성과 지표 바 차트 + 성향별 추천
```

---

## 14. XAI 설계 철학 및 레이어 구조

### 설계 철학 — "투자 추천"이 아닌 "투자 참고 정보 제공"

| 사용 금지 표현 | 대체 표현 |
|-------------|---------|
| "이 포트폴리오를 추천합니다" | "유사 성향 투자자의 역사적 시뮬레이션 결과입니다" |
| "최적 비중" | "역사적 효율적 비중" |
| "당신에게 최적화된 포트폴리오" | "참고용 포트폴리오 분석 정보" |

### XAI 필요 이유

1. **블랙박스 문제**: Step 1~5는 최적 비중을 산출하지만 "왜 나스닥 40%인가"에 대한 설명이 없음
2. **개인화 연결 부재**: Risk Score 파이프라인과 포트폴리오 파이프라인이 Step 8 없이는 연결되지 않음
3. **규제 대응**: "추천"이 아닌 "근거 제시"로 포지셔닝하려면, 실제로 근거가 투명하게 공개되어야 함
4. **학술적 완결성**: BL + Sortino 최적화 결과에 설명 레이어가 없으면 블랙박스 최적화기와 차별화 없음

### 전체 구조

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

### 레이어 B 핵심 수식

**8-B1 MCDR (Marginal Contribution to Downside Risk):**
```python
def compute_mcdr(w, Sigma_down):
    portfolio_var = w @ Sigma_down @ w
    return (Sigma_down @ w) * w / portfolio_var  # sum = 1
```

**8-B2 BL 내재수익률 vs MCDR 산포도:**
```
x축: Π_i (연환산, %)  y축: MCDR_i  버블 크기: w_i
"오른쪽 아래(고수익·저위험) 자산에 높은 비중이 배분된다"
```

**8-B3 제약 바인딩 비용:**
```python
constraint_cost = sortino_unconstrained - sortino_constrained
```

**8-B4 성과 기여 분해:**
```python
contrib = weights_df.shift(1) * slot_returns_df  # 전기 비중 × 당기 수익
```

---

## 15. Risk Score 설계 (페르소나 파이프라인)

### 최종 산정식

```
Risk Score (1~10점) =
  0.20 × 은퇴기간 점수
+ 0.15 × 나이 점수
+ 0.15 × 직업 점수
+ 0.20 × 자금여력 점수
+ 0.15 × 가족 점수
+ 0.15 × 라이프스타일 점수
```

### 하위 변수별 점수 기준

**나이 점수** (이론: Modigliani 1954 생애주기 가설):

| 나이 구간 | 점수 |
|---------|------|
| 20대 (20~29세) | **10점** |
| 30대 (30~39세) | **8점** |
| 40대 (40~49세) | **6점** |
| 50대 (50~59세) | **4점** |
| 60세 이상 | **2점** |

**은퇴기간 점수** (이론: Bodie, Merton & Samuelson 1992; OECD 2021):

| 은퇴까지 기간 | 점수 |
|------------|------|
| 30년 이상 | **10점** |
| 20~30년 | **8점** |
| 10~20년 | **6점** |
| 5~10년 | **3점** |
| 5년 미만 | **1점** |

**직업 안정성 점수:**

| 직업 유형 | 점수 |
|---------|------|
| 공무원, 공기업, 교사, 정규직 전문직 | 9~10 |
| 대기업/중견기업 정규직 | 7~8 |
| 일반 사무직/서비스직 정규직 | 5~7 |
| 자영업, 프리랜서, 계약직 | 3~5 |
| 무직, 소득 불안정 | 1~3 |

**자금여력 점수:**
```
자금여력 점수 = Part1(손실감내도) × 0.40
             + Part2(기여안정성) × 0.35
             + Part3(리밸런싱여력) × 0.25

Part3 핵심: 위험자산 추가 여력 = 70% - 현재 위험자산 비중
```

**라이프스타일 점수 (텍스트 파이프라인):**

```python
# Big Five 3축 → 투자성향 점수
risk_score_lifestyle = (
    0.45 * openness_z
  - 0.45 * stability_preference_z
  + 0.10 * conscientiousness_z
)
# → qcut → 1~5등급

# 텍스트 처리 파이프라인
# 1. ko-sroberta-multitask 임베딩 (768차원)
# 2. KMeans(500) 클러스터링
# 3. 대표 문장 GPT 점수화 (openness, conscientiousness, stability: 1~5)
# 4. 전체 전파 → z-score 표준화
# 5. 가중합 → qcut
```

### 위험군 분류 룩업 테이블

```python
_RISK_TABLE = [
    (0,  2,  '초보수형', 0.00),
    (2,  4,  '보수형',   0.20),
    (4,  6,  '중립형',   0.40),
    (6,  8,  '성장형',   0.60),
    (8,  10, '공격형',   0.70),
]
```

### 2단계 개인화 (같은 Risk Score 문제)

```
1단계: Risk Score → 위험군(그룹) → w_risky 기본 비중
2단계: 하위 점수 프로필 → w_risky 내 세부 조정
       예) 은퇴기간 짧음 → 주식 비중 축소
           자금여력 낮음 → 현금성 확대
           가족부담 높음 → 고변동 ETF 축소
```

---

## 16. 통합 엔진 (portfolio_engine.py)

**경로**: `src/portfolio_engine.py`

### API 사용법

```python
from portfolio_engine import PortfolioEngine

engine = PortfolioEngine()
result = engine.get_portfolio(
    risk_score=7.2,
    query_date="2024-10-01",
    user_info={
        "current_balance":  100_000_000,   # 현재 적립금 (원)
        "annual_salary":     48_000_000,   # 연봉 (원)
        "retirement_years":  25,           # 은퇴까지 남은 기간 (년)
        "sub_scores": {                    # 선택 — 있을 때만 A2 워터폴 산출
            "나이": 8, "은퇴기간": 8, "직업": 6,
            "자금여력": 7, "가족": 5, "라이프스타일": 7
        },
    }
)
```

### 반환값 구조

```python
{
    "rebal_date":     str,           # 실제 기준 리밸런싱 시점
    "risk_group":     str,           # 위험군 (초보수형 ~ 공격형)
    "w_risky":        float,         # 위험자산 배분 비율 (0 ~ 0.70)
    "portfolio": {                   # ETF명 → 최종 비중 (합계 1.0)
        "ETF명칭": float, ...
    },
    "portfolio_by_slot": {           # 슬롯명 → 최종 비중
        "슬롯명": float, ...
    },
    "xai": {
        "layer_a": {
            "a1_cal_flow":        {...},   # Risk Score → CAL 흐름
            "a2_risk_breakdown":  {...},   # 하위변수 기여 분해 (선택)
            "a4_loss_amount":     {...},   # 손실 감내도 (선택)
            "a5_implied_lambda":  {...},   # 내재 λ (선택)
            "a6_mvp_vs_sortino":  {...},   # MVP vs Sortino-max 비교
            "a0_opportunity_cost":{...},   # 기회비용 (선택)
        },
        "layer_b": {
            "b1_mcdr":      {...},   # 자산별 하방위험 기여
            "b2_bl_scatter":{...},   # BL 내재수익률 vs MCDR 산포도
            "b3_constraint":{...},   # 제약 활성화 분석
            "b4_attribution":{...},  # 성과 기여 분해
        }
    }
}
```

### 핵심 클래스 구조

```python
class PortfolioEngine:
    # 지연 로딩 (cached_property)
    _weights:       분기별 슬롯 비중 (Sortino-max)
    _weights_mvp:   분기별 슬롯 비중 (MVP)
    _perf:          분기별 성과 지표
    _sigma_hist:    분기별 Σ_down 이력
    _pi_hist:       분기별 Π 이력
    _bind_hist:     분기별 제약 바인딩 이력
    _slot_rets:     ETF 슬롯별 수익률
    _mar:           일별 MAR 시계열
    _yeb:           연도별 ETF 매핑

    def get_portfolio(risk_score, query_date, user_info) -> dict
    def get_latest_portfolio(risk_score, user_info) -> dict
    def list_rebalancing_dates() -> list[str]
    def performance_summary() -> dict

    # 내부 메서드
    def _apply_cal(risky_slot_w, w_risky) -> pd.Series
    def _compute_xai(...) -> dict
    def _get_quarterly_params(rebal_date) -> (sigma_mat, pi_vec, valid_cols)
    def _layer_a(...) -> dict
    def _layer_b(...) -> dict

    # Layer A
    def _a1_cal_flow(risk_score, risk_group, w_risky) -> dict
    def _a2_risk_breakdown(sub_scores, total_score) -> dict
    def _a4_loss_amount(balance, salary, down_risk_pct, w_risky) -> dict
    def _a5_implied_lambda(risky_slot_w, sigma_down_q, pi_q, ...) -> dict
    def _a6_strategy_comparison(risk_group) -> dict
    def _a0_opportunity_cost(balance, salary, years, rf_annual, port_annual) -> dict

    # Layer B
    def _b1_mcdr(risky_slot_w, sigma_down_q, valid_cols_q) -> dict
    def _b2_bl_scatter(risky_slot_w, sigma_down_q, pi_q, valid_cols_q) -> dict
    def _b3_constraint(rebal_date) -> dict
    def _b4_attribution() -> dict
```

### 데이터 흐름 (get_portfolio)

```
query_date → 기준 리밸런싱 시점 선택 (이전 가장 최근)
          ↓
risky_slot_w = _weights[rebal_date]
          ↓
risk_group, w_risky = _lookup_risk(risk_score)
          ↓
final_slot_w = _apply_cal(risky_slot_w, w_risky)
  = risky_slot_w × w_risky  (무위험 슬롯에는 +1-w_risky)
          ↓
etf_map = _get_etf_map(rebal_date)  ← query_date 전년도 ETF 선정
          ↓
portfolio = {etf_map[s]: final_slot_w[s] for s in SLOTS}
          ↓
xai = _compute_xai(...)
  → Layer A: a1_cal_flow, a2_risk_breakdown, a4_loss_amount, a5_implied_lambda,
             a6_mvp_vs_sortino, a0_opportunity_cost
  → Layer B: b1_mcdr, b2_bl_scatter, b3_constraint, b4_attribution
```

### 내재 λ 역산 수식 (A5)

```python
def _a5_implied_lambda(risky_slot_w, sigma_down_q, pi_q, valid_cols_q,
                       w_risky, mar_q):
    w_v_norm    = w_v / w_v.sum()
    sigma_down_p = sqrt(w_v_norm @ sigma_down_q @ w_v_norm * REBAL_DAYS)
    exp_ret_q    = (w_v_norm @ pi_q) * REBAL_DAYS
    sortino_q    = (exp_ret_q - mar_q) / (sigma_down_p + 1e-10)

    lambda_implied = sortino_q / (w_risky * sigma_down_p + 1e-10)

    ratio = lambda_implied / LAMBDA_MKT  # LAMBDA_MKT = 3.0
    if ratio < 0.85:   position = '공격적 (시장 평균 대비 위험 추구)'
    elif ratio > 1.15: position = '보수적 (시장 평균 대비 위험 회피)'
    else:              position = '중립적 (시장 평균 수준)'
```

### 성과 요약 예시 출력

```
▶ 포트폴리오 엔진 초기화 완료
  리밸런싱 이력: 38개

기준 리밸런싱: 2024-10-03
위험군: 성장형 (w_risky=60%)

【 최종 포트폴리오 비중 】
  KODEX 머니마켓액티브 (488770)             52.5%
  KODEX 미국나스닥100 (379810)              24.0%
  KODEX 코스닥150 (229200)                  14.7%
  TIGER 미국S&P500 (360750)                  6.0%
  ...

【 A1 CAL 흐름 】
  Risk Score 7.2점 → 성장형 | 참고 위험자산 비중: 60% | ...

【 전체 성과 요약 】
  누적수익률: 94.9%  MDD: -24.4%  평균 소르티노: 0.631
```

---

## 17. 백테스트 주요 결과 요약

### 전략별 성과 비교 (2016~2025)

| 전략 | 누적수익률 | MDD | 평균 소르티노 | 평균EM비중 |
|------|-----------|-----|-------------|---------|
| Sortino-max (비제약, Step 4) | +120.6% | -34.8% | 0.927 | — |
| **Sortino-max (지역제약, Step 5)** | **+94.9%** | **-24.4%** | **0.631** | ~8% |
| MVP (지역제약, Step 5) | — | — | — | — |

### 윈도우 탐색 결과 요약

```
★ 최적 윈도우: 5년 (1260거래일)
  - 종합 점수: 0.728 (1위)
  - 소르티노 평균: 0.600 (1위)
  - 이상치 민감도: 0.015 (공동 1위)
  - 검증 분기: 85개
```

### 제약 바인딩 통계 (Step 5 기준)

```
US 바인딩: N/38 분기
KR 바인딩: N/38 분기  
EM 바인딩: N/38 분기
평균 제약비용 (소르티노): ~0.xxx
```

### 진행 현황 (2026-05-15 기준)

| 단계 | 상태 | 산출물 |
|------|------|--------|
| Step 1~2: ETF 데이터 수집·정제 | ✅ 완료 | `data/` |
| Step 3: 윈도우 탐색 (5yr 확정) | ✅ 완료 | `results/step3/` |
| Step 4: BL + Sortino-max | ✅ 완료 (λ=3.0 재실행) | `results/step4/` |
| Step 5: 지역제약 포트폴리오 | ✅ 완료 (EM≤15% 재실행) | `results/step5/` |
| portfolio_engine.py | ✅ 완료 | XAI Layer A(a0~a6) + B(b1~b4) |
| Risk Score 설계 | ✅ 문서 완성 | `docs/05_persona_risk_scoring.md` |
| Step 6~7 (CAL, 내재 λ) | ✅ 완료 | `results/step6/`, `results/step7/` |
| Step 8-A (XAI 시각화) | ✅ 완료 | `results/step8/figures/` |
| CVaR / 스트레스 테스트 | ❌ 미구현 | `docs/10_todo.md` |
| Streamlit 데모 | ❌ 미구현 | `docs/10_todo.md` |

---

## 18. 구현 오류 발견 및 수정 이력

초기 구현된 코드를 직접 검토하여 5개 설계 의도 위반을 발견하고 수정 지시:

| 발견한 문제 | 의도한 설계 | 영향 |
|------------|-----------|------|
| ETF 선정 기준: AUM 최대 단순 선정 | 총보수(50%)·거래대금(30%)·AUM(20%) 가중평균 순위 | 총보수 낮은 ETF 탈락 가능 |
| 롤링 윈도우 탐색: ETF 수익률 사용 | 기초자산 지수 사용 (ETF 상장 이전까지 소급) | 분석 기간이 2023년 이후밖에 안 됨 |
| 최적 윈도우 기준: Sortino 최대 단일 기준 | MAE·소르티노·일관성·이상치 4기준 종합 | 단일 지표로 선택 시 왜곡 |
| MAR: 연 2.5% 고정 | ECOS 정기예금 금리 시변 적용 | 하방공분산·소르티노 전체가 실전과 달라짐 |
| 리밸런싱 주기: 월별(21일) | 분기(63거래일) — 실전 주기와 일치 | 검증 기준 자체가 무효 |

→ 수정 우선순위 정리 후 Step 3~5 전체 재실행.

---

## 부록 A: 실행 순서

```bash
# 1. 기초자산 지수 데이터 수집 (pykrx, yfinance, ECOS)
python src/step3_collect_data.py

# 2. 최적 윈도우 탐색 (→ results/step3/)
python src/step3_window_analysis.py

# 3. 비제약 Sortino-max 포트폴리오 (→ results/step4/)
python src/step4_portfolio.py

# 4. 지역제약 포트폴리오 + MVP (→ results/step5/)
python src/step5_constrained.py

# 5. CAL 매핑 (→ results/step6/)
python src/step6_cal.py

# 6. 현재 시점 배분 (→ results/current/)
python src/step6b_current_allocation.py

# 7. 내재 λ 역산 (→ results/step7/)
python src/step7_lambda_implied.py

# 8. XAI 시각화 (→ results/step8/figures/)
python src/08a_step8_user_xai.py

# 9. 개별 사용자 조회 (API 방식)
from src.portfolio_engine import PortfolioEngine

engine = PortfolioEngine()
result = engine.get_portfolio(
    risk_score=6.5,
    query_date='2025-03-31',
    user_info={
        'current_balance':  50_000_000,
        'annual_salary':    40_000_000,
        'retirement_years': 20,
    }
)
```

---

## 부록 B: 데이터 의존 관계

```
[ECOS + yfinance]
    ↓
data/index_returns.parquet   ← Step 3 출력 (기초자산 지수)
data/slot_returns.parquet    ← Step 2 출력 (ETF 수익률)
data/mar_series.parquet      ← Step 3 출력 (시변 MAR)
data/year_end_best.csv       ← Step 2 출력 (연도별 ETF + AUM)
    ↓
results/step5/ (portfolio_weights_constrained, sigma_down_history, pi_history, ...)
    ↓
results/step6/ (CAL 매핑)
results/step7/ (λ_implied)
results/current/ (현재 시점 배분)
    ↓
portfolio_engine.py  ←  [Risk Score 외생입력]  →  최종 포트폴리오 + XAI
```

---

*이 파일은 포트폴리오 파트의 모든 설계·구현·결과를 단일 문서로 통합한 아카이브입니다.*  
*생성일: 2026-06-10 | 기준 프로젝트 상태: 2026-05-19*
