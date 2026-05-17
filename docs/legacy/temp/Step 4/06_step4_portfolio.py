"""
Step 4: 내재수익률 & 하방위험 산출 + 분기별 최적 포트폴리오 비중

입력:
  raw/index_returns.parquet   ← 하방공분산 추정 (5yr 윈도우)
  raw/slot_returns.parquet    ← OOS 성과 평가 (실제 ETF 수익률)
  raw/year_end_best.csv       ← 연도별×슬롯별 선정 ETF + AUM (w_mkt용)
  raw/mar_series.parquet      ← 시변 MAR (ECOS 정기예금)

출력:
  raw/portfolio_weights.parquet      ← 리밸런싱 시점별 슬롯 비중
  raw/portfolio_performance.parquet  ← 분기별 성과 지표
  Step 4/step4_summary.csv           ← 연도별 요약 테이블
  Step 4/step4_weights_pivot.csv     ← 비중 피벗 (읽기 편한 형식)

설계:
  - 추정: index_returns 5yr 윈도우 (Step 3 결과, 기초자산 지수)
  - OOS:  slot_returns (실제 ETF, 생존편향 없는 시점별 선정)
  - w_mkt: year_end_best AUM 비중 (블랙-리터만 내재수익률 산출)
  - 슬롯: year_end_best[전년도] ∩ 추정 데이터 충분 ∩ ETF OOS 데이터 있음
  - 리밸런싱: 분기 (63거래일), 슬롯 상하한 1%~40%
"""

import warnings
import numpy as np
import pandas as pd
from pathlib import Path
from scipy.optimize import minimize

warnings.filterwarnings('ignore')

BASE_DIR = Path(__file__).parent.parent   # Fintech/
DATA_DIR  = BASE_DIR / 'raw'
OUT_DIR   = Path(__file__).parent          # Fintech/Step 4/
OUT_DIR.mkdir(exist_ok=True)

# ═══════════════════════════════════════════════════════
# 파라미터 (Step 3 확정값)
# ═══════════════════════════════════════════════════════
WIN_DAYS    = 1260   # 5년 (Step 3 최적 윈도우)
REBAL_DAYS  = 63     # 분기
LAMBDA      = 2.5
W_MAX       = 0.40
W_MIN       = 0.01
MISSING_TOL = 0.30   # 윈도우 내 결측 허용 비율
MIN_OOS_FILL = 0.70  # OOS 최소 데이터 충족 비율

SLOTS = [
    '국내주식_코스피', '국내주식_코스닥',
    '미국주식_SP500',  '미국주식_나스닥',
    '신흥국_인도',     '신흥국_중국',
    '국내채권_국고채단중기', '국내채권_국고채장기',
    '국내채권_회사채', '국내채권_종합',
    '해외채권_미국국채',
    '원자재_금',
    '무위험(현금성)',
]

# ═══════════════════════════════════════════════════════
# 1. 데이터 로드
# ═══════════════════════════════════════════════════════
print("▶ 데이터 로드...")

idx_rets  = pd.read_parquet(DATA_DIR / 'index_returns.parquet').reindex(columns=SLOTS).sort_index()
slot_rets = pd.read_parquet(DATA_DIR / 'slot_returns.parquet').reindex(columns=SLOTS).sort_index()

yeb = pd.read_csv(DATA_DIR / 'year_end_best.csv')
aum_by_year = {}
for yr, grp in yeb.groupby('year'):
    aum_by_year[int(yr)] = dict(zip(grp['slot'], grp['aum_억'].astype(float)))

# MAR: 모든 날짜에 사용 가능한 일별 시계열 구성
mar_monthly = pd.read_parquet(DATA_DIR / 'mar_series.parquet')['mar_annual']
_all_dates  = idx_rets.index.union(slot_rets.index)
mar_daily   = (mar_monthly.resample('D').ffill()
               .reindex(_all_dates).ffill().bfill()) / 100     # % → 소수
mar_rate    = mar_daily / 252                                  # 연율 → 일별

print(f"  index_returns : {idx_rets.index.min().date()} ~ {idx_rets.index.max().date()} "
      f"({len(idx_rets)}일)")
print(f"  slot_returns  : {slot_rets.index.min().date()} ~ {slot_rets.index.max().date()} "
      f"({len(slot_rets)}일)")
print(f"  MAR 범위      : {mar_daily.min()*100:.2f}% ~ {mar_daily.max()*100:.2f}%")

# ═══════════════════════════════════════════════════════
# 2. 유틸리티
# ═══════════════════════════════════════════════════════
def downside_cov(rets_arr, mar_scalar):
    """Estrada(2007) 하방 공분산 행렬."""
    d = np.minimum(rets_arr - mar_scalar, 0.0)
    return (d.T @ d) / len(d)

def solve_max_sortino(sigma_down, pi, mar_q):
    """소르티노 최대화 (SLSQP). 실패 시 균등 비중 반환."""
    n = len(pi)
    def neg_sortino(w):
        ret  = float(w @ pi) * REBAL_DAYS
        risk = np.sqrt(max(float(w @ sigma_down @ w) * REBAL_DAYS, 1e-12))
        return -(ret - mar_q) / risk
    res = minimize(
        neg_sortino,
        np.ones(n) / n,
        method='SLSQP',
        bounds=[(W_MIN, W_MAX)] * n,
        constraints=[{'type': 'eq', 'fun': lambda w: w.sum() - 1}],
        options={'maxiter': 500, 'ftol': 1e-9},
    )
    return res.x if res.success else np.ones(n) / n

# ═══════════════════════════════════════════════════════
# 3. Walk-forward (분기, 2016~2025)
# ═══════════════════════════════════════════════════════
print("\n▶ Walk-forward 시작 (5년 윈도우 · 분기 리밸런싱)...\n")

idx_dates = idx_rets.index
n_idx     = len(idx_dates)

records_w = []   # 비중
records_p = []   # 성과

for end_i in range(WIN_DAYS, n_idx - REBAL_DAYS, REBAL_DAYS):

    rebal_date = idx_dates[end_i]

    # ── year_end_best 연도 결정 ──
    # 당해 연도 리밸런싱 → 전년도 연도말 선정 ETF 사용
    ref_year = int(rebal_date.year) - 1
    if ref_year not in aum_by_year:
        continue   # year_end_best 데이터 없음 (2015 이전)

    yeb_slots = list(aum_by_year[ref_year].keys())

    # ── OOS 슬롯 확인 (slot_returns 기준) ──
    sr_pos = slot_rets.index.searchsorted(rebal_date)
    if sr_pos + int(REBAL_DAYS * MIN_OOS_FILL) >= len(slot_rets):
        continue   # OOS 기간 데이터 부족

    oos_raw = slot_rets[yeb_slots].iloc[sr_pos : sr_pos + REBAL_DAYS]
    oos_avail = [s for s in yeb_slots
                 if oos_raw[s].notna().sum() >= int(REBAL_DAYS * MIN_OOS_FILL)]
    if len(oos_avail) < 3:
        continue

    # ── 추정 슬롯 확인 (index_returns 5yr) ──
    est = idx_rets[oos_avail].iloc[end_i - WIN_DAYS : end_i]
    valid_cols = est.columns[est.isna().mean() < MISSING_TOL].tolist()
    if len(valid_cols) < 3:
        continue

    est_v = est[valid_cols].dropna()
    if len(est_v) < WIN_DAYS // 4:
        continue

    # ── 하방공분산 & BL 내재수익률 ──
    mar_est = float(mar_rate.reindex(idx_rets.index[end_i - WIN_DAYS : end_i],
                                     method='ffill').mean())
    sigma_down = downside_cov(est_v.values, mar_est)

    # AUM 기반 w_mkt
    aum_vals = np.array([aum_by_year[ref_year].get(s, 1.0) for s in valid_cols],
                        dtype=float)
    w_mkt = aum_vals / aum_vals.sum()
    pi    = LAMBDA * sigma_down @ w_mkt   # BL 내재수익률

    # ── 최적 비중 ──
    mar_q = mar_est * REBAL_DAYS
    w_opt = solve_max_sortino(sigma_down, pi, mar_q)

    # ── OOS 성과 계산 (실제 ETF) ──
    oos_sr    = oos_raw[valid_cols].fillna(0)
    n_oos     = len(oos_sr)
    oos_dates = oos_sr.index

    mar_oos_daily = float(mar_rate.reindex(oos_dates, method='ffill').mean())
    mar_oos_q     = mar_oos_daily * n_oos

    port_r   = oos_sr.values @ w_opt
    cum_r    = float((port_r + 1).prod() - 1)
    down_r   = np.minimum(port_r - mar_oos_daily, 0.0)
    real_down = np.sqrt(max(float(np.mean(down_r ** 2)) * n_oos, 0))
    sortino  = (cum_r - mar_oos_q) / (real_down + 1e-10)

    # ── 비중 저장 (전체 슬롯 컬럼, 미사용은 0) ──
    w_row = {'date': rebal_date}
    for s in SLOTS:
        w_row[s] = round(float(w_opt[valid_cols.index(s)]), 6) if s in valid_cols else 0.0
    records_w.append(w_row)

    # ── 성과 저장 ──
    top2 = sorted(zip(valid_cols, w_opt), key=lambda x: -x[1])[:2]
    records_p.append({
        'date':         rebal_date,
        'ref_year':     ref_year,
        'n_slots':      len(valid_cols),
        'slots':        ','.join(valid_cols),
        'cum_ret_pct':  round(cum_r  * 100, 3),
        'sortino':      round(sortino, 3),
        'down_risk_pct': round(real_down * 100, 3),
        'mar_annual_pct': round(mar_oos_daily * 252 * 100, 2),
        'top2_slots':   ' / '.join(f"{s}({w*100:.1f}%)" for s, w in top2),
    })

print(f"  완료: 총 {len(records_w)}개 리밸런싱 시점")

# ═══════════════════════════════════════════════════════
# 4. 결과 정리
# ═══════════════════════════════════════════════════════
weights_df = pd.DataFrame(records_w).set_index('date')
perf_df    = pd.DataFrame(records_p).set_index('date')

# ── 연도별 요약 ──
perf_df['year'] = perf_df.index.year
annual = perf_df.groupby('year').agg(
    리밸런싱=('sortino',     'count'),
    평균슬롯=('n_slots',     'mean'),
    평균수익률=('cum_ret_pct', 'mean'),
    누적수익률=('cum_ret_pct', 'sum'),
    평균소르티노=('sortino',  'mean'),
    소르티노σ=('sortino',    'std'),
    평균MAR=('mar_annual_pct','mean'),
).round(2)

print("\n" + "="*75)
print("【 Step 4 — 연도별 분기 성과 요약 】")
print("="*75)
print(annual.to_string())

print(f"\n▶ 전체 기간 ({perf_df.index.min().date()} ~ {perf_df.index.max().date()})")
print(f"  평균 소르티노     : {perf_df['sortino'].mean():.3f}")
print(f"  소르티노 > 0 비율 : {(perf_df['sortino'] > 0).mean()*100:.1f}%")
print(f"  평균 분기 수익률  : {perf_df['cum_ret_pct'].mean():.2f}%")
print(f"  평균 슬롯 수      : {perf_df['n_slots'].mean():.1f}")

# ── 최근 리밸런싱 비중 확인 ──
last_w = weights_df.iloc[-1]
last_active = last_w[last_w > 0].sort_values(ascending=False)
print(f"\n▶ 최근 리밸런싱 ({weights_df.index[-1].date()}) 비중:")
for s, w in last_active.items():
    print(f"  {s:<30} {w*100:.1f}%")

# ═══════════════════════════════════════════════════════
# 5. 저장
# ═══════════════════════════════════════════════════════
weights_df.to_parquet(DATA_DIR / 'portfolio_weights.parquet')
perf_df.drop(columns='year').to_parquet(DATA_DIR / 'portfolio_performance.parquet')

annual.to_csv(OUT_DIR / 'step4_summary.csv', encoding='utf-8-sig')

# 비중 피벗 (날짜 × 슬롯, CSV)
weights_pct = (weights_df * 100).round(1)
weights_pct.index = weights_pct.index.strftime('%Y-%m-%d')
weights_pct.to_csv(OUT_DIR / 'step4_weights_pivot.csv', encoding='utf-8-sig')

print(f"\n[저장] portfolio_weights.parquet      → {weights_df.shape[0]}행 × {weights_df.shape[1]}슬롯")
print(f"[저장] portfolio_performance.parquet  → {perf_df.shape[0]}행")
print(f"[저장] step4_summary.csv              → {OUT_DIR}")
print(f"[저장] step4_weights_pivot.csv        → {OUT_DIR}")
