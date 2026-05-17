"""
Step 5: 지역별 집중도 제약 추가 + 비교 분석

제약 (신규):
  - 미국 주식 (SP500 + 나스닥) 합계 ≤ 50%
  - 국내 주식 (코스피 + 코스닥) 합계 ≤ 50%

비교:
  Step 4 비제약 vs Step 5 지역 제약
  - 성과: 소르티노 · 수익률 · 최대 낙폭 (MDD)
  - 분산: 유효 자산 수 (1/HHI) · 최대 지역 집중도

출력:
  Step 5/constrained_weights.parquet
  Step 5/constrained_performance.parquet
  Step 5/step5_comparison.csv
"""

import warnings
import numpy as np
import pandas as pd
from pathlib import Path
from scipy.optimize import minimize

warnings.filterwarnings('ignore')

BASE_DIR = Path(__file__).parent.parent   # Fintech/
DATA_DIR  = BASE_DIR / 'raw'
OUT_DIR   = Path(__file__).parent          # Fintech/Step 5/
OUT_DIR.mkdir(exist_ok=True)

# ═══════════════════════════════════════════════════════
# 파라미터
# ═══════════════════════════════════════════════════════
WIN_DAYS     = 1260
REBAL_DAYS   = 63
LAMBDA       = 2.5
W_MAX        = 0.40
W_MIN        = 0.01
MISSING_TOL  = 0.30
MIN_OOS_FILL = 0.70
REGION_CAP   = 0.50   # 지역별 주식 합계 상한

US_SLOTS = {'미국주식_SP500', '미국주식_나스닥'}
KR_SLOTS = {'국내주식_코스피', '국내주식_코스닥'}

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
# 1. 데이터 로드 (Step 4와 동일)
# ═══════════════════════════════════════════════════════
print("▶ 데이터 로드...")

idx_rets  = pd.read_parquet(DATA_DIR / 'index_returns.parquet').reindex(columns=SLOTS).sort_index()
slot_rets = pd.read_parquet(DATA_DIR / 'slot_returns.parquet').reindex(columns=SLOTS).sort_index()

yeb = pd.read_csv(DATA_DIR / 'year_end_best.csv')
aum_by_year = {}
for yr, grp in yeb.groupby('year'):
    aum_by_year[int(yr)] = dict(zip(grp['slot'], grp['aum_억'].astype(float)))

_all_dates = idx_rets.index.union(slot_rets.index)
mar_monthly = pd.read_parquet(DATA_DIR / 'mar_series.parquet')['mar_annual']
mar_daily   = (mar_monthly.resample('D').ffill()
               .reindex(_all_dates).ffill().bfill()) / 100
mar_rate    = mar_daily / 252

# ═══════════════════════════════════════════════════════
# 2. 유틸리티
# ═══════════════════════════════════════════════════════
def downside_cov(rets_arr, mar_scalar):
    d = np.minimum(rets_arr - mar_scalar, 0.0)
    return (d.T @ d) / len(d)

def solve_sortino(sigma_down, pi, mar_q, valid_cols, constrained):
    n = len(pi)
    def neg_sortino(w):
        ret  = float(w @ pi) * REBAL_DAYS
        risk = np.sqrt(max(float(w @ sigma_down @ w) * REBAL_DAYS, 1e-12))
        return -(ret - mar_q) / risk

    cons = [{'type': 'eq', 'fun': lambda w: w.sum() - 1}]

    if constrained:
        us_idx = [i for i, s in enumerate(valid_cols) if s in US_SLOTS]
        kr_idx = [i for i, s in enumerate(valid_cols) if s in KR_SLOTS]
        # 제약 실현가능성 확인: 비해당 슬롯의 최대 비중 합 ≥ REGION_CAP 이어야 함
        # (충족 못하면 W_MAX 제약과 충돌해 최적화 실패 → 제약 생략)
        if us_idx:
            non_us_max = (n - len(us_idx)) * W_MAX
            if non_us_max >= REGION_CAP:
                def us_cap(w, ix=us_idx): return REGION_CAP - sum(w[i] for i in ix)
                cons.append({'type': 'ineq', 'fun': us_cap})
        if kr_idx:
            non_kr_max = (n - len(kr_idx)) * W_MAX
            if non_kr_max >= REGION_CAP:
                def kr_cap(w, ix=kr_idx): return REGION_CAP - sum(w[i] for i in ix)
                cons.append({'type': 'ineq', 'fun': kr_cap})

    res = minimize(
        neg_sortino, np.ones(n) / n, method='SLSQP',
        bounds=[(W_MIN, W_MAX)] * n,
        constraints=cons,
        options={'maxiter': 500, 'ftol': 1e-9},
    )
    return res.x if res.success else np.ones(n) / n

def eff_n(weights):
    """유효 자산 수 = 1 / HHI (분산 지표, 높을수록 잘 분산된 포트폴리오)"""
    w = np.array(weights)
    w = w[w > 0]
    return 1.0 / float(np.sum(w ** 2)) if len(w) > 0 else 0.0

def region_alloc(w_dict, region_slots):
    return sum(w_dict.get(s, 0.0) for s in region_slots)

# ═══════════════════════════════════════════════════════
# 3. Walk-forward (두 버전 동시 실행)
# ═══════════════════════════════════════════════════════
print("▶ Walk-forward (비제약 · 지역제약 동시 실행)...\n")

idx_dates = idx_rets.index
n_idx     = len(idx_dates)

records_unc  = []   # 비제약 (Step 4 재현)
records_con  = []   # 지역 제약
records_w_unc = []
records_w_con = []

for end_i in range(WIN_DAYS, n_idx - REBAL_DAYS, REBAL_DAYS):

    rebal_date = idx_dates[end_i]
    ref_year   = int(rebal_date.year) - 1
    if ref_year not in aum_by_year:
        continue

    yeb_slots = list(aum_by_year[ref_year].keys())

    sr_pos = slot_rets.index.searchsorted(rebal_date)
    if sr_pos + int(REBAL_DAYS * MIN_OOS_FILL) >= len(slot_rets):
        continue

    oos_raw    = slot_rets[yeb_slots].iloc[sr_pos : sr_pos + REBAL_DAYS]
    oos_avail  = [s for s in yeb_slots
                  if oos_raw[s].notna().sum() >= int(REBAL_DAYS * MIN_OOS_FILL)]
    if len(oos_avail) < 3:
        continue

    est = idx_rets[oos_avail].iloc[end_i - WIN_DAYS : end_i]
    valid_cols = est.columns[est.isna().mean() < MISSING_TOL].tolist()
    if len(valid_cols) < 3:
        continue

    est_v = est[valid_cols].dropna()
    if len(est_v) < WIN_DAYS // 4:
        continue

    mar_est    = float(mar_rate.reindex(idx_rets.index[end_i - WIN_DAYS : end_i],
                                        method='ffill').mean())
    sigma_down = downside_cov(est_v.values, mar_est)

    aum_vals = np.array([aum_by_year[ref_year].get(s, 1.0) for s in valid_cols], dtype=float)
    w_mkt    = aum_vals / aum_vals.sum()
    pi       = LAMBDA * sigma_down @ w_mkt
    mar_q    = mar_est * REBAL_DAYS

    # ── 두 버전 최적화 ──
    w_unc = solve_sortino(sigma_down, pi, mar_q, valid_cols, constrained=False)
    w_con = solve_sortino(sigma_down, pi, mar_q, valid_cols, constrained=True)

    # ── OOS 성과 ──
    oos_sr    = oos_raw[valid_cols].fillna(0)
    n_oos     = len(oos_sr)
    oos_dates = oos_sr.index
    mar_oos_d = float(mar_rate.reindex(oos_dates, method='ffill').mean())
    mar_oos_q = mar_oos_d * n_oos

    def calc_perf(w_opt):
        port_r = oos_sr.values @ w_opt
        cum_r  = float((port_r + 1).prod() - 1)
        down_r = np.minimum(port_r - mar_oos_d, 0.0)
        real_down = np.sqrt(max(float(np.mean(down_r**2)) * n_oos, 0))
        sortino   = (cum_r - mar_oos_q) / (real_down + 1e-10)
        w_dict    = dict(zip(valid_cols, w_opt))
        return {
            'date':           rebal_date,
            'n_slots':        len(valid_cols),
            'cum_ret_pct':    round(cum_r * 100, 3),
            'sortino':        round(sortino, 3),
            'down_risk_pct':  round(real_down * 100, 3),
            'mar_annual_pct': round(mar_oos_d * 252 * 100, 2),
            'eff_n':          round(eff_n(w_opt), 2),
            'us_alloc':       round(region_alloc(w_dict, US_SLOTS) * 100, 1),
            'kr_alloc':       round(region_alloc(w_dict, KR_SLOTS) * 100, 1),
        }

    records_unc.append(calc_perf(w_unc))
    records_con.append(calc_perf(w_con))

    # 비중 저장
    def make_w_row(w_opt, date):
        row = {'date': date}
        for s in SLOTS:
            row[s] = round(float(w_opt[valid_cols.index(s)]), 6) if s in valid_cols else 0.0
        return row

    records_w_unc.append(make_w_row(w_unc, rebal_date))
    records_w_con.append(make_w_row(w_con, rebal_date))

print(f"  완료: {len(records_con)}개 리밸런싱 시점")

# ═══════════════════════════════════════════════════════
# 4. 비교 분석
# ═══════════════════════════════════════════════════════
perf_unc = pd.DataFrame(records_unc).set_index('date')
perf_con = pd.DataFrame(records_con).set_index('date')
w_unc_df = pd.DataFrame(records_w_unc).set_index('date')
w_con_df = pd.DataFrame(records_w_con).set_index('date')

def max_drawdown(ret_pct_series):
    """분기 수익률 시계열 → 최대 낙폭(%)"""
    cum = (1 + ret_pct_series / 100).cumprod()
    peak = cum.cummax()
    dd   = (cum - peak) / peak
    return round(float(dd.min()) * 100, 2)

def summary_stats(perf_df):
    rets = perf_df['cum_ret_pct']
    return {
        '누적수익률(%)':     round((1 + rets/100).prod() - 1, 4) * 100,
        '평균분기수익률(%)': round(rets.mean(), 2),
        '평균소르티노':      round(perf_df['sortino'].mean(), 3),
        '소르티노σ':        round(perf_df['sortino'].std(), 3),
        '소르티노>0(%)':    round((perf_df['sortino'] > 0).mean() * 100, 1),
        'MDD(%)':           max_drawdown(rets),
        '평균유효자산수':    round(perf_df['eff_n'].mean(), 2),
        '평균US비중(%)':    round(perf_df['us_alloc'].mean(), 1),
        '평균KR비중(%)':    round(perf_df['kr_alloc'].mean(), 1),
    }

sts_unc = summary_stats(perf_unc)
sts_con = summary_stats(perf_con)

comparison = pd.DataFrame({
    '비제약 (Step 4)': sts_unc,
    '지역제약 (Step 5)': sts_con,
    '차이 (제약-비제약)': {k: round(sts_con[k] - sts_unc[k], 3) for k in sts_unc},
})

print("\n" + "="*72)
print("【 Step 4 비제약 vs Step 5 지역제약 비교 】")
print("="*72)
print(comparison.to_string())

# 연도별 비교
print("\n【 연도별 소르티노 비교 】")
perf_unc['year'] = perf_unc.index.year
perf_con['year'] = perf_con.index.year
yr_unc = perf_unc.groupby('year')['sortino'].mean().rename('비제약')
yr_con = perf_con.groupby('year')['sortino'].mean().rename('지역제약')
yr_us  = perf_con.groupby('year')['us_alloc'].mean().rename('US비중(%)')
yr_kr  = perf_con.groupby('year')['kr_alloc'].mean().rename('KR비중(%)')
print(pd.concat([yr_unc, yr_con, yr_us, yr_kr], axis=1).round(2).to_string())

# 최근 리밸런싱 비중 비교
print(f"\n【 최근 리밸런싱 ({w_con_df.index[-1].date()}) 비중 비교 】")
last_unc = w_unc_df.iloc[-1]
last_con = w_con_df.iloc[-1]
active = sorted(
    [(s, last_unc[s], last_con[s]) for s in SLOTS if last_unc[s] > 0 or last_con[s] > 0],
    key=lambda x: -x[2]
)
print(f"{'슬롯':<28} {'비제약':>8} {'지역제약':>8}")
print("-" * 46)
for s, u, c in active:
    print(f"{s:<28} {u*100:>7.1f}% {c*100:>7.1f}%")

# ═══════════════════════════════════════════════════════
# 5. 저장
# ═══════════════════════════════════════════════════════
w_con_df.to_parquet(DATA_DIR / 'portfolio_weights_constrained.parquet')
perf_con.drop(columns='year').to_parquet(DATA_DIR / 'portfolio_performance_constrained.parquet')
comparison.to_csv(OUT_DIR / 'step5_comparison.csv', encoding='utf-8-sig')

# 비중 피벗 (CSV)
wpct = (w_con_df * 100).round(1)
wpct.index = wpct.index.strftime('%Y-%m-%d')
wpct.to_csv(OUT_DIR / 'step5_weights_constrained.csv', encoding='utf-8-sig')

print(f"\n[저장] portfolio_weights_constrained.parquet")
print(f"[저장] portfolio_performance_constrained.parquet")
print(f"[저장] step5_comparison.csv → {OUT_DIR}")
print(f"[저장] step5_weights_constrained.csv → {OUT_DIR}")
