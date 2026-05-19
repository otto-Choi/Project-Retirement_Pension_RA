"""
Step 5-B v3: BL + 모멘텀 뷰 (B+C 강화)

v2 대비 추가:
  [B] 음수 모멘텀 슬롯 필터링
      12개월 누적 수익률이 음수인 슬롯을 해당 분기 추정에서 제외.
      → valid_cols 자체를 줄여 Σ_down, Π 계산에 직접 반영.
      무위험(현금성)은 필터 제외 (항상 포함).

  [C] w_mkt 모멘텀 가중
      w_mkt = AUM × max(mom_ret, MOM_FLOOR) / Σ
      → 모멘텀 강한 자산에 높은 시장 비중 부여 → Π prior 자체가 달라짐.
      BL 뷰(VIEW_WEIGHT) 는 B+C로 대체되어 0.0으로 설정.

하이퍼파라미터:
  LOOKBACK_MOM  = 252
  MOM_FILTER    = True   (B)
  MOM_WMKT      = True   (C)
  MOM_FLOOR     = 0.02   (C: 음수 모멘텀 슬롯의 최소 w_mkt 승수)
  VIEW_WEIGHT   = 0.0    (B+C 사용하므로 BL 뷰 비활성)
  MIN_AUM_SLOTS = 4

출력 (results/step5b/):  — 파일 구조 Step5와 동일
"""

import warnings
import numpy as np
import pandas as pd
from pathlib import Path
from scipy.optimize import minimize

warnings.filterwarnings('ignore')

ROOT     = Path(__file__).parent.parent
DATA_DIR = ROOT / 'data'
OUT_DIR  = ROOT / 'results' / 'step5b'
OUT_DIR.mkdir(exist_ok=True)

# ─────────────────────────────────────────────
# 파라미터
# ─────────────────────────────────────────────
WIN_DAYS      = 1260
REBAL_DAYS    = 63
LAMBDA        = 3.0
W_MAX         = 0.40
W_MIN         = 0.01
MISSING_TOL   = 0.30
MIN_OOS_FILL  = 0.70
US_CAP        = 0.50
KR_CAP        = 0.50
EM_CAP        = 0.15

LOOKBACK_MOM  = 252
MOM_FILTER    = True   # [B] 음수 모멘텀 슬롯 제외
MOM_WMKT      = True   # [C] w_mkt 모멘텀 가중
MOM_FLOOR     = 0.02   # [C] 음수 모멘텀 슬롯의 최소 승수 (완전 제로 방지)
VIEW_WEIGHT   = 0.0    # BL view — B+C 대체로 비활성
MIN_AUM_SLOTS = 4
MIN_SLOTS_AFTER_FILTER = 3   # 필터 후 최소 슬롯 수 (미달 시 필터 스킵)
RF_SLOT       = '무위험(현금성)'  # 모멘텀 필터 제외 슬롯

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
US_SLOTS = {'미국주식_SP500', '미국주식_나스닥'}
KR_SLOTS = {'국내주식_코스피', '국내주식_코스닥'}
EM_SLOTS = {'신흥국_인도', '신흥국_중국'}

# ─────────────────────────────────────────────
# 데이터 로드
# ─────────────────────────────────────────────
print("▶ 데이터 로드...")
idx_rets  = pd.read_parquet(DATA_DIR / 'index_returns.parquet').reindex(columns=SLOTS).sort_index()
slot_rets = pd.read_parquet(DATA_DIR / 'slot_returns.parquet').reindex(columns=SLOTS).sort_index()

yeb = pd.read_csv(DATA_DIR / 'year_end_best.csv')
aum_by_year = {}
for yr, grp in yeb.groupby('year'):
    aum_by_year[int(yr)] = dict(zip(grp['slot'], grp['aum_억'].astype(float)))

_all_dates  = idx_rets.index.union(slot_rets.index)
mar_monthly = pd.read_parquet(DATA_DIR / 'mar_series.parquet')['mar_annual']
mar_daily   = (mar_monthly.resample('D').ffill()
               .reindex(_all_dates).ffill().bfill()) / 100
mar_rate    = mar_daily / 252

print(f"  MOM_FILTER={MOM_FILTER}  MOM_WMKT={MOM_WMKT}  "
      f"MOM_FLOOR={MOM_FLOOR}  LOOKBACK={LOOKBACK_MOM}d")

# ─────────────────────────────────────────────
# 유틸리티
# ─────────────────────────────────────────────
def downside_cov(rets_arr, mar_scalar):
    d = np.minimum(rets_arr - mar_scalar, 0.0)
    return (d.T @ d) / len(d)


def _build_constraints(valid_cols, n):
    cons = [{'type': 'eq', 'fun': lambda w: w.sum() - 1}]
    us_idx = [i for i, s in enumerate(valid_cols) if s in US_SLOTS]
    kr_idx = [i for i, s in enumerate(valid_cols) if s in KR_SLOTS]
    em_idx = [i for i, s in enumerate(valid_cols) if s in EM_SLOTS]
    if us_idx and (n - len(us_idx)) * W_MAX >= US_CAP:
        cons.append({'type': 'ineq', 'fun': lambda w, ix=us_idx: US_CAP - sum(w[i] for i in ix)})
    if kr_idx and (n - len(kr_idx)) * W_MAX >= KR_CAP:
        cons.append({'type': 'ineq', 'fun': lambda w, ix=kr_idx: KR_CAP - sum(w[i] for i in ix)})
    if em_idx and (n - len(em_idx)) * W_MAX >= EM_CAP:
        cons.append({'type': 'ineq', 'fun': lambda w, ix=em_idx: EM_CAP - sum(w[i] for i in ix)})
    return cons


def solve_sortino_max(sigma_down, mu, mar_q, valid_cols):
    n = len(mu)
    cons = _build_constraints(valid_cols, n)
    def neg_sortino(w):
        ret  = float(w @ mu) * REBAL_DAYS
        risk = np.sqrt(max(float(w @ sigma_down @ w) * REBAL_DAYS, 1e-12))
        return -(ret - mar_q) / risk
    res = minimize(neg_sortino, np.ones(n) / n, method='SLSQP',
                   bounds=[(W_MIN, W_MAX)] * n, constraints=cons,
                   options={'maxiter': 500, 'ftol': 1e-9})
    return res.x if res.success else np.ones(n) / n


def solve_mvp(sigma_down, valid_cols):
    n = sigma_down.shape[0]
    cons = _build_constraints(valid_cols, n)
    res = minimize(lambda w: float(w @ sigma_down @ w), np.ones(n) / n,
                   method='SLSQP', bounds=[(W_MIN, W_MAX)] * n,
                   constraints=cons, options={'maxiter': 500, 'ftol': 1e-9})
    return res.x if res.success else np.ones(n) / n


def calc_oos_perf(oos_sr, w_opt, valid_cols, mar_oos_d, rebal_date, ref_year):
    n_oos     = len(oos_sr)
    mar_oos_q = mar_oos_d * n_oos
    port_r    = oos_sr[valid_cols].fillna(0).values @ w_opt
    cum_r     = float((port_r + 1).prod() - 1)
    down_r    = np.minimum(port_r - mar_oos_d, 0.0)
    real_down = np.sqrt(max(float(np.mean(down_r ** 2)) * n_oos, 0))
    sortino   = (cum_r - mar_oos_q) / (real_down + 1e-10)
    w_dict    = dict(zip(valid_cols, w_opt))
    return {
        'date':           rebal_date, 'ref_year': ref_year,
        'n_slots':        len(valid_cols),
        'cum_ret_pct':    round(cum_r * 100, 3),
        'sortino':        round(sortino, 3),
        'down_risk_pct':  round(real_down * 100, 3),
        'mar_annual_pct': round(mar_oos_d * 252 * 100, 2),
        'eff_n':          round(1 / float(np.sum(w_opt ** 2)), 2),
        'us_alloc':       round(sum(w_dict.get(s, 0) for s in US_SLOTS), 4),
        'kr_alloc':       round(sum(w_dict.get(s, 0) for s in KR_SLOTS), 4),
        'em_alloc':       round(sum(w_dict.get(s, 0) for s in EM_SLOTS), 4),
    }


def make_w_row(w_opt, valid_cols, date):
    row = {'date': date}
    for s in SLOTS:
        row[s] = round(float(w_opt[valid_cols.index(s)]), 6) if s in valid_cols else 0.0
    return row


def check_binding(w_opt, valid_cols, tol=5e-3):
    w_dict = dict(zip(valid_cols, w_opt))
    us = sum(w_dict.get(s, 0) for s in US_SLOTS)
    kr = sum(w_dict.get(s, 0) for s in KR_SLOTS)
    em = sum(w_dict.get(s, 0) for s in EM_SLOTS)
    return {
        'us_binding': abs(us - US_CAP) < tol and any(s in US_SLOTS for s in valid_cols),
        'kr_binding': abs(kr - KR_CAP) < tol and any(s in KR_SLOTS for s in valid_cols),
        'em_binding': abs(em - EM_CAP) < tol and any(s in EM_SLOTS for s in valid_cols),
        'us_alloc': round(us, 4), 'kr_alloc': round(kr, 4), 'em_alloc': round(em, 4),
    }


# ─────────────────────────────────────────────
# Walk-forward
# ─────────────────────────────────────────────
print(f"\n▶ Walk-forward 시작...\n")

idx_dates = idx_rets.index
n_idx     = len(idx_dates)

rec_w_con = []; rec_p_con = []
rec_w_mvp = []; rec_p_mvp = []
rec_sigma = []; rec_pi_bl = []; rec_pi_prior = []; rec_bind = []

n_filtered   = 0   # B: 슬롯 제외 발생 횟수
n_equal_wmkt = 0   # AUM 균등 폴백 횟수
filter_log   = []  # 분기별 제외 슬롯 기록

for end_i in range(WIN_DAYS, n_idx - REBAL_DAYS, REBAL_DAYS):

    rebal_date = idx_dates[end_i]
    ref_year   = int(rebal_date.year) - 1
    if ref_year not in aum_by_year:
        continue

    yeb_slots = list(aum_by_year[ref_year].keys())
    sr_pos    = slot_rets.index.searchsorted(rebal_date)
    if sr_pos + int(REBAL_DAYS * MIN_OOS_FILL) >= len(slot_rets):
        continue

    oos_raw   = slot_rets[yeb_slots].iloc[sr_pos : sr_pos + REBAL_DAYS]
    oos_avail = [s for s in yeb_slots
                 if oos_raw[s].notna().sum() >= int(REBAL_DAYS * MIN_OOS_FILL)]
    if len(oos_avail) < 3:
        continue

    est        = idx_rets[oos_avail].iloc[end_i - WIN_DAYS : end_i]
    valid_cols = est.columns[est.isna().mean() < MISSING_TOL].tolist()
    if len(valid_cols) < 3:
        continue

    # ── 모멘텀 신호 계산 ──
    mom_start_i = max(end_i - LOOKBACK_MOM, 0)
    mom_win     = idx_rets[valid_cols].iloc[mom_start_i : end_i].dropna()
    if len(mom_win) >= LOOKBACK_MOM // 2:
        mom_map = {s: float((1 + mom_win[s]).prod() - 1) for s in valid_cols}
    else:
        mom_map = {s: 0.0 for s in valid_cols}

    # ── [B] 음수 모멘텀 슬롯 필터링 ──
    excluded = []
    if MOM_FILTER:
        filtered = [s for s in valid_cols
                    if mom_map[s] >= 0 or s == RF_SLOT]
        if len(filtered) >= MIN_SLOTS_AFTER_FILTER:
            excluded    = [s for s in valid_cols if s not in filtered]
            valid_cols  = filtered
            if excluded:
                n_filtered += 1
                filter_log.append({'date': rebal_date, 'excluded': excluded})

    est_v = est[valid_cols].dropna()
    if len(est_v) < WIN_DAYS // 4:
        continue

    # ── 하방공분산 (필터링 후 슬롯 기준) ──
    mar_est    = float(mar_rate.reindex(idx_rets.index[end_i - WIN_DAYS : end_i],
                                        method='ffill').mean())
    sigma_down = downside_cov(est_v.values, mar_est)

    # ── [C] w_mkt 모멘텀 가중 ──
    aum_known = [s for s in valid_cols if s in aum_by_year[ref_year]]
    aum_vals  = np.array([aum_by_year[ref_year].get(s, 1.0) for s in valid_cols], dtype=float)

    if MOM_WMKT:
        # 모멘텀 승수: 양수 모멘텀은 그대로, 음수는 MOM_FLOOR (필터 스킵된 경우 대비)
        mom_arr    = np.array([mom_map[s] for s in valid_cols])
        mom_scale  = np.where(mom_arr >= 0, 1.0 + mom_arr, MOM_FLOOR)
        if len(aum_known) >= MIN_AUM_SLOTS:
            w_mkt = (aum_vals * mom_scale) / (aum_vals * mom_scale).sum()
        else:
            w_mkt = mom_scale / mom_scale.sum()
            n_equal_wmkt += 1
    else:
        if len(aum_known) >= MIN_AUM_SLOTS:
            w_mkt = aum_vals / aum_vals.sum()
        else:
            w_mkt = np.ones(len(valid_cols)) / len(valid_cols)
            n_equal_wmkt += 1

    pi_prior = LAMBDA * sigma_down @ w_mkt
    mar_q    = mar_est * REBAL_DAYS

    # ── BL 뷰 (VIEW_WEIGHT=0이면 pi_prior 그대로) ──
    if VIEW_WEIGHT > 0:
        mom_arr2 = np.array([mom_map[s] for s in valid_cols])
        mom_std  = mom_arr2.std()
        if mom_std > 1e-10:
            z_mom  = (mom_arr2 - mom_arr2.mean()) / mom_std
            pi_std = pi_prior.std() if pi_prior.std() > 1e-12 else 1e-8
            Q      = pi_prior + 0.30 * z_mom * pi_std
            mu_bl  = (1 - VIEW_WEIGHT) * pi_prior + VIEW_WEIGHT * Q
        else:
            mu_bl = pi_prior.copy()
    else:
        mu_bl = pi_prior.copy()

    # ── 최적화 ──
    w_con = solve_sortino_max(sigma_down, mu_bl,   mar_q, valid_cols)
    w_mvp = solve_mvp(sigma_down, valid_cols)

    # ── OOS 성과 ──
    oos_sr    = oos_raw[valid_cols].fillna(0)
    mar_oos_d = float(mar_rate.reindex(oos_sr.index, method='ffill').mean())
    rec_p_con.append(calc_oos_perf(oos_sr, w_con, valid_cols, mar_oos_d, rebal_date, ref_year))
    rec_p_mvp.append(calc_oos_perf(oos_sr, w_mvp, valid_cols, mar_oos_d, rebal_date, ref_year))
    rec_w_con.append(make_w_row(w_con, valid_cols, rebal_date))
    rec_w_mvp.append(make_w_row(w_mvp, valid_cols, rebal_date))

    # ── 이력 ──
    sigma_row = {'date': rebal_date}
    for a in SLOTS:
        for b in SLOTS:
            sigma_row[f"{a}__{b}"] = (
                float(sigma_down[valid_cols.index(a), valid_cols.index(b)])
                if a in valid_cols and b in valid_cols else float('nan'))
    rec_sigma.append(sigma_row)

    bl_row = {'date': rebal_date}; prior_row = {'date': rebal_date}
    for s in SLOTS:
        bl_row[s]    = float(mu_bl[valid_cols.index(s)])    if s in valid_cols else float('nan')
        prior_row[s] = float(pi_prior[valid_cols.index(s)]) if s in valid_cols else float('nan')
    rec_pi_bl.append(bl_row); rec_pi_prior.append(prior_row)

    bind_info = check_binding(w_con, valid_cols)
    bind_info.update({'date': rebal_date, 'n_slots': len(valid_cols),
                      'n_excluded': len(excluded),
                      'sortino_con': rec_p_con[-1]['sortino']})
    rec_bind.append(bind_info)

print(f"  완료: {len(rec_w_con)}분기  |  "
      f"[B] 슬롯 제외 발생: {n_filtered}분기  |  "
      f"균등 w_mkt: {n_equal_wmkt}분기")

# 분기별 제외 슬롯 요약
if filter_log:
    from collections import Counter
    all_excluded = [s for row in filter_log for s in row['excluded']]
    excl_cnt = Counter(all_excluded)
    print(f"\n  제외 빈도 상위 슬롯:")
    for s, cnt in excl_cnt.most_common(5):
        print(f"    {s:<30} {cnt}회")

# ─────────────────────────────────────────────
# 결과 정리
# ─────────────────────────────────────────────
def to_df(recs, date_col='date'):
    return pd.DataFrame(recs).set_index(date_col)

perf_con  = to_df(rec_p_con);  perf_mvp  = to_df(rec_p_mvp)
w_con_df  = to_df(rec_w_con);  w_mvp_df  = to_df(rec_w_mvp)
sigma_df  = to_df(rec_sigma)
pi_bl_df  = to_df(rec_pi_bl);  pi_pri_df = to_df(rec_pi_prior)
bind_df   = to_df(rec_bind)


def max_dd(ret_pct):
    cum = (1 + ret_pct / 100).cumprod()
    return round(float(((cum - cum.cummax()) / cum.cummax()).min()) * 100, 2)


def summary(perf):
    rets = perf['cum_ret_pct']
    mar  = perf['mar_annual_pct'] / 4
    return {
        '누적수익률(%)':     round(((1 + rets / 100).prod() - 1) * 100, 2),
        '평균분기수익률(%)': round(rets.mean(), 2),
        'MAR초과분기(%)':   round((rets >= mar).mean() * 100, 1),
        '평균소르티노':      round(perf['sortino'].mean(), 3),
        'MDD(%)':           max_dd(rets),
        '평균유효자산수':    round(perf['eff_n'].mean(), 2),
        '평균US비중(%)':    round(perf['us_alloc'].mean() * 100, 1),
        '평균KR비중(%)':    round(perf['kr_alloc'].mean() * 100, 1),
        '평균EM비중(%)':    round(perf['em_alloc'].mean() * 100, 1),
    }


S5_DIR = ROOT / 'results' / 'step5'
try:
    perf_s5 = pd.read_parquet(S5_DIR / 'portfolio_performance_constrained.parquet')
    sts = {'Step5 (base)':      summary(perf_s5),
           'Step5b (B+C)':      summary(perf_con),
           'Step5b MVP':        summary(perf_mvp)}
except FileNotFoundError:
    sts = {'Step5b (B+C)': summary(perf_con), 'Step5b MVP': summary(perf_mvp)}

comparison = pd.DataFrame(sts)
print("\n" + "=" * 65)
print(f"[ Step5 vs Step5b (B+C)  |  MOM_FILTER={MOM_FILTER}  MOM_WMKT={MOM_WMKT} ]")
print("=" * 65)
print(comparison.to_string())

print(f"\n[ 제약 바인딩 ]  US {bind_df['us_binding'].sum()}/38  "
      f"KR {bind_df['kr_binding'].sum()}/38  EM {bind_df['em_binding'].sum()}/38")

# ─────────────────────────────────────────────
# 저장
# ─────────────────────────────────────────────
w_con_df.to_parquet(OUT_DIR / 'portfolio_weights_constrained.parquet')
perf_con.drop(columns=['ref_year'], errors='ignore').to_parquet(
    OUT_DIR / 'portfolio_performance_constrained.parquet')
w_mvp_df.to_parquet(OUT_DIR / 'portfolio_weights_mvp.parquet')
perf_mvp.drop(columns=['ref_year'], errors='ignore').to_parquet(
    OUT_DIR / 'portfolio_performance_mvp.parquet')
sigma_df.to_parquet(OUT_DIR / 'sigma_down_history.parquet')
pi_bl_df.to_parquet(OUT_DIR / 'pi_history.parquet')
pi_pri_df.to_parquet(OUT_DIR / 'pi_prior_history.parquet')
bind_df.to_parquet(OUT_DIR / 'binding_history.parquet')
comparison.to_csv(OUT_DIR / 'comparison.csv', encoding='utf-8-sig')
(w_con_df * 100).round(1).rename(index=lambda d: d.strftime('%Y-%m-%d')).to_csv(
    OUT_DIR / 'weights_constrained.csv', encoding='utf-8-sig')

print(f"\n[저장 완료] -> {OUT_DIR}")
