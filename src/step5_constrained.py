"""
Step 5 재실행 — λ=3.0 + EM≤15% + Σ_down/Π 이력 저장 + MVP

변경 내용 (기존 07_step5_constrained.py 대비):
  1. LAMBDA = 3.0 (기존 2.5)
  2. EM_SLOTS (신흥국_인도, 신흥국_중국) ≤ 15% 제약 추가
  3. 분기별 Σ_down, Π 이력 저장 → sigma_down_history.parquet, pi_history.parquet
  4. MVP 포트폴리오 동시 산출 → portfolio_weights_mvp.parquet
  5. 제약 바인딩 이력 저장 → binding_history.parquet
  6. 데이터 경로를 data/ 디렉터리로 수정

입력:
  data/index_returns.parquet
  data/slot_returns.parquet
  data/year_end_best.csv
  data/mar_series.parquet

출력 (results/step5/):
  portfolio_weights_constrained.parquet   (덮어쓰기)
  portfolio_performance_constrained.parquet (덮어쓰기)
  portfolio_weights_mvp.parquet           (신규)
  portfolio_performance_mvp.parquet       (신규)
  sigma_down_history.parquet              (신규)
  pi_history.parquet                      (신규)
  binding_history.parquet                 (신규)
  weights_constrained.csv                 (덮어쓰기)
  comparison.csv                          (덮어쓰기)
"""

import warnings
import numpy as np
import pandas as pd
from pathlib import Path
from scipy.optimize import minimize

warnings.filterwarnings('ignore')

# ─────────────────────────────────────────────
# 경로 설정
# ─────────────────────────────────────────────
ROOT     = Path(__file__).parent.parent                 # 퇴직연금 _XAI/
DATA_DIR = ROOT / 'data'
OUT_DIR  = ROOT / 'results' / 'step5'
OUT_DIR.mkdir(exist_ok=True)

# ─────────────────────────────────────────────
# 파라미터 (확정)
# ─────────────────────────────────────────────
WIN_DAYS     = 1260    # 5년 (Step 3 최적 윈도우)
REBAL_DAYS   = 63      # 분기
LAMBDA       = 3.0     # ★ 2.5 → 3.0 (퇴직연금 보수성 반영)
W_MAX        = 0.40    # 개별 슬롯 상한
W_MIN        = 0.01    # 개별 슬롯 하한
MISSING_TOL  = 0.30
MIN_OOS_FILL = 0.70
US_CAP       = 0.50    # 미국 주식 합계 상한
KR_CAP       = 0.50    # 국내 주식 합계 상한
EM_CAP       = 0.15    # ★ 신흥국 합계 상한 (신규)

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

print(f"  index_returns : {idx_rets.index.min().date()} ~ {idx_rets.index.max().date()} ({len(idx_rets)}일)")
print(f"  slot_returns  : {slot_rets.index.min().date()} ~ {slot_rets.index.max().date()} ({len(slot_rets)}일)")

# ─────────────────────────────────────────────
# 유틸리티
# ─────────────────────────────────────────────
def downside_cov(rets_arr: np.ndarray, mar_scalar: float) -> np.ndarray:
    """Estrada(2007) 하방 공분산 행렬."""
    d = np.minimum(rets_arr - mar_scalar, 0.0)
    return (d.T @ d) / len(d)


def _build_constraints(valid_cols: list, n: int) -> list:
    """공통 제약 조건 리스트 구성 (US, KR, EM 각 상한 + sum=1)."""
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


def solve_sortino_max(sigma_down: np.ndarray, pi: np.ndarray,
                      mar_q: float, valid_cols: list) -> np.ndarray:
    """소르티노 최대화 (제약 포함)."""
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


def solve_sortino_unconstrained(sigma_down: np.ndarray, pi: np.ndarray,
                                mar_q: float, n: int) -> np.ndarray:
    """소르티노 최대화 (지역 제약 없음, 비교용)."""
    def neg_sortino(w):
        ret  = float(w @ pi) * REBAL_DAYS
        risk = np.sqrt(max(float(w @ sigma_down @ w) * REBAL_DAYS, 1e-12))
        return -(ret - mar_q) / risk

    res = minimize(neg_sortino, np.ones(n) / n, method='SLSQP',
                   bounds=[(W_MIN, W_MAX)] * n,
                   constraints=[{'type': 'eq', 'fun': lambda w: w.sum() - 1}],
                   options={'maxiter': 500, 'ftol': 1e-9})
    return res.x if res.success else np.ones(n) / n


def solve_mvp(sigma_down: np.ndarray, valid_cols: list) -> np.ndarray:
    """최소 하방분산 포트폴리오 (MVP, 동일 제약)."""
    n = sigma_down.shape[0]
    cons = _build_constraints(valid_cols, n)

    res = minimize(lambda w: float(w @ sigma_down @ w), np.ones(n) / n,
                   method='SLSQP', bounds=[(W_MIN, W_MAX)] * n,
                   constraints=cons, options={'maxiter': 500, 'ftol': 1e-9})
    return res.x if res.success else np.ones(n) / n


def calc_oos_perf(oos_sr: pd.DataFrame, w_opt: np.ndarray,
                  valid_cols: list, mar_oos_d: float,
                  rebal_date: pd.Timestamp, ref_year: int) -> dict:
    """OOS 분기 성과 산출."""
    n_oos    = len(oos_sr)
    mar_oos_q = mar_oos_d * n_oos
    port_r   = oos_sr[valid_cols].fillna(0).values @ w_opt
    cum_r    = float((port_r + 1).prod() - 1)
    down_r   = np.minimum(port_r - mar_oos_d, 0.0)
    real_down = np.sqrt(max(float(np.mean(down_r ** 2)) * n_oos, 0))
    sortino  = (cum_r - mar_oos_q) / (real_down + 1e-10)
    w_dict   = dict(zip(valid_cols, w_opt))

    us_alloc = sum(w_dict.get(s, 0) for s in US_SLOTS)
    kr_alloc = sum(w_dict.get(s, 0) for s in KR_SLOTS)
    em_alloc = sum(w_dict.get(s, 0) for s in EM_SLOTS)
    eff_n_val = 1 / float(np.sum(w_opt ** 2)) if np.sum(w_opt ** 2) > 0 else 0

    return {
        'date':            rebal_date,
        'ref_year':        ref_year,
        'n_slots':         len(valid_cols),
        'cum_ret_pct':     round(cum_r * 100, 3),
        'sortino':         round(sortino, 3),
        'down_risk_pct':   round(real_down * 100, 3),
        'mar_annual_pct':  round(mar_oos_d * 252 * 100, 2),
        'eff_n':           round(eff_n_val, 2),
        'us_alloc':        round(us_alloc, 4),
        'kr_alloc':        round(kr_alloc, 4),
        'em_alloc':        round(em_alloc, 4),
    }


def make_w_row(w_opt: np.ndarray, valid_cols: list, date: pd.Timestamp) -> dict:
    """전체 SLOTS 기준 비중 행 생성 (미사용 슬롯은 0)."""
    row = {'date': date}
    for s in SLOTS:
        row[s] = round(float(w_opt[valid_cols.index(s)]), 6) if s in valid_cols else 0.0
    return row


def check_binding(w_opt: np.ndarray, valid_cols: list, tol: float = 5e-3) -> dict:
    """제약 바인딩 여부 확인."""
    w_dict = dict(zip(valid_cols, w_opt))
    us = sum(w_dict.get(s, 0) for s in US_SLOTS)
    kr = sum(w_dict.get(s, 0) for s in KR_SLOTS)
    em = sum(w_dict.get(s, 0) for s in EM_SLOTS)
    return {
        'us_binding': abs(us - US_CAP) < tol and any(s in US_SLOTS for s in valid_cols),
        'kr_binding': abs(kr - KR_CAP) < tol and any(s in KR_SLOTS for s in valid_cols),
        'em_binding': abs(em - EM_CAP) < tol and any(s in EM_SLOTS for s in valid_cols),
        'us_alloc':   round(us, 4),
        'kr_alloc':   round(kr, 4),
        'em_alloc':   round(em, 4),
    }


# ─────────────────────────────────────────────
# Walk-forward (2016~2025)
# ─────────────────────────────────────────────
print(f"\n▶ Walk-forward 시작 (λ={LAMBDA}, US≤{US_CAP*100:.0f}%, KR≤{KR_CAP*100:.0f}%, EM≤{EM_CAP*100:.0f}%)...\n")

idx_dates = idx_rets.index
n_idx     = len(idx_dates)

rec_w_unc = [];  rec_p_unc = []   # 비제약
rec_w_con = [];  rec_p_con = []   # 지역제약 (Sortino-max)
rec_w_mvp = [];  rec_p_mvp = []   # MVP
rec_sigma  = []                    # Σ_down 이력
rec_pi     = []                    # Π 이력
rec_bind   = []                    # 제약 바인딩 이력

for end_i in range(WIN_DAYS, n_idx - REBAL_DAYS, REBAL_DAYS):

    rebal_date = idx_dates[end_i]
    ref_year   = int(rebal_date.year) - 1
    if ref_year not in aum_by_year:
        continue

    yeb_slots = list(aum_by_year[ref_year].keys())

    # OOS 슬롯 확인
    sr_pos = slot_rets.index.searchsorted(rebal_date)
    if sr_pos + int(REBAL_DAYS * MIN_OOS_FILL) >= len(slot_rets):
        continue

    oos_raw   = slot_rets[yeb_slots].iloc[sr_pos : sr_pos + REBAL_DAYS]
    oos_avail = [s for s in yeb_slots
                 if oos_raw[s].notna().sum() >= int(REBAL_DAYS * MIN_OOS_FILL)]
    if len(oos_avail) < 3:
        continue

    # 추정 슬롯 확인 (5년 윈도우)
    est       = idx_rets[oos_avail].iloc[end_i - WIN_DAYS : end_i]
    valid_cols = est.columns[est.isna().mean() < MISSING_TOL].tolist()
    if len(valid_cols) < 3:
        continue

    est_v = est[valid_cols].dropna()
    if len(est_v) < WIN_DAYS // 4:
        continue

    # 하방공분산 & BL 내재수익률
    mar_est    = float(mar_rate.reindex(idx_rets.index[end_i - WIN_DAYS : end_i],
                                        method='ffill').mean())
    sigma_down = downside_cov(est_v.values, mar_est)

    aum_vals = np.array([aum_by_year[ref_year].get(s, 1.0) for s in valid_cols], dtype=float)
    w_mkt    = aum_vals / aum_vals.sum()
    pi       = LAMBDA * sigma_down @ w_mkt
    mar_q    = mar_est * REBAL_DAYS

    # 세 버전 최적화
    n = len(valid_cols)
    w_unc = solve_sortino_unconstrained(sigma_down, pi, mar_q, n)
    w_con = solve_sortino_max(sigma_down, pi, mar_q, valid_cols)
    w_mvp = solve_mvp(sigma_down, valid_cols)

    # OOS 성과
    oos_sr    = oos_raw[valid_cols].fillna(0)
    mar_oos_d = float(mar_rate.reindex(oos_sr.index, method='ffill').mean())

    rec_p_unc.append(calc_oos_perf(oos_sr, w_unc, valid_cols, mar_oos_d, rebal_date, ref_year))
    rec_p_con.append(calc_oos_perf(oos_sr, w_con, valid_cols, mar_oos_d, rebal_date, ref_year))
    rec_p_mvp.append(calc_oos_perf(oos_sr, w_mvp, valid_cols, mar_oos_d, rebal_date, ref_year))

    # 비중 저장
    rec_w_unc.append(make_w_row(w_unc, valid_cols, rebal_date))
    rec_w_con.append(make_w_row(w_con, valid_cols, rebal_date))
    rec_w_mvp.append(make_w_row(w_mvp, valid_cols, rebal_date))

    # Σ_down 이력 (full 13×13, 미사용 슬롯은 NaN)
    sigma_row = {'date': rebal_date}
    for a in SLOTS:
        for b in SLOTS:
            key = f"{a}__{b}"
            if a in valid_cols and b in valid_cols:
                sigma_row[key] = float(sigma_down[valid_cols.index(a), valid_cols.index(b)])
            else:
                sigma_row[key] = float('nan')
    rec_sigma.append(sigma_row)

    # Π 이력
    pi_row = {'date': rebal_date}
    for s in SLOTS:
        pi_row[s] = float(pi[valid_cols.index(s)]) if s in valid_cols else float('nan')
    rec_pi.append(pi_row)

    # 제약 바인딩 이력 (지역제약 포트폴리오 기준)
    bind_info = check_binding(w_con, valid_cols)
    bind_info['date']     = rebal_date
    bind_info['n_slots']  = len(valid_cols)
    bind_info['sortino_con'] = rec_p_con[-1]['sortino']
    bind_info['sortino_unc'] = rec_p_unc[-1]['sortino']
    bind_info['constraint_cost'] = round(rec_p_unc[-1]['sortino'] - rec_p_con[-1]['sortino'], 3)
    rec_bind.append(bind_info)

print(f"  완료: {len(rec_w_con)}개 리밸런싱 시점")

# ─────────────────────────────────────────────
# 결과 정리
# ─────────────────────────────────────────────
def to_df(records: list, date_col: str = 'date') -> pd.DataFrame:
    return pd.DataFrame(records).set_index(date_col)


perf_unc = to_df(rec_p_unc)
perf_con = to_df(rec_p_con)
perf_mvp = to_df(rec_p_mvp)
w_unc_df = to_df(rec_w_unc)
w_con_df = to_df(rec_w_con)
w_mvp_df = to_df(rec_w_mvp)
sigma_df = to_df(rec_sigma)
pi_df    = to_df(rec_pi)
bind_df  = to_df(rec_bind)


def max_drawdown(ret_pct: pd.Series) -> float:
    cum  = (1 + ret_pct / 100).cumprod()
    peak = cum.cummax()
    return round(float(((cum - peak) / peak).min()) * 100, 2)


def summary_stats(perf: pd.DataFrame) -> dict:
    rets = perf['cum_ret_pct']
    return {
        '누적수익률(%)':      round((1 + rets / 100).prod() - 1, 4) * 100,
        '평균분기수익률(%)':  round(rets.mean(), 2),
        '평균소르티노':       round(perf['sortino'].mean(), 3),
        '소르티노σ':         round(perf['sortino'].std(), 3),
        '소르티노>0(%)':     round((perf['sortino'] > 0).mean() * 100, 1),
        'MDD(%)':            max_drawdown(rets),
        '평균유효자산수':     round(perf['eff_n'].mean(), 2),
        '평균US비중(%)':     round(perf['us_alloc'].mean() * 100, 1),
        '평균KR비중(%)':     round(perf['kr_alloc'].mean() * 100, 1),
        '평균EM비중(%)':     round(perf['em_alloc'].mean() * 100, 1),
    }


sts = {
    '비제약':      summary_stats(perf_unc),
    '지역제약(최종)': summary_stats(perf_con),
    'MVP':         summary_stats(perf_mvp),
}

comparison = pd.DataFrame(sts)
print("\n" + "=" * 72)
print(f"[ Step 5 재실행 결과 - lambda={LAMBDA}, EM<={EM_CAP*100:.0f}% ]")
print("=" * 72)
print(comparison.to_string())

# 최근 리밸런싱 비중
last_date = w_con_df.index[-1]
last_con  = w_con_df.iloc[-1]
last_mvp  = w_mvp_df.iloc[-1]
active    = sorted(
    [(s, last_con[s], last_mvp[s]) for s in SLOTS if last_con[s] > 0 or last_mvp[s] > 0],
    key=lambda x: -x[1]
)
print(f"\n【 최근 리밸런싱 ({last_date.date()}) 비중 비교 】")
print(f"{'슬롯':<28} {'Sortino-max':>11} {'MVP':>8}")
print("-" * 50)
for s, c, m in active:
    print(f"{s:<28} {c*100:>10.1f}% {m*100:>7.1f}%")

# 제약 바인딩 요약
print(f"\n【 제약 바인딩 통계 】")
print(f"  US 바인딩  : {bind_df['us_binding'].sum()}/{len(bind_df)} 분기")
print(f"  KR 바인딩  : {bind_df['kr_binding'].sum()}/{len(bind_df)} 분기")
print(f"  EM 바인딩  : {bind_df['em_binding'].sum()}/{len(bind_df)} 분기")
print(f"  평균 제약비용 (소르티노): {bind_df['constraint_cost'].mean():.3f}")

# ─────────────────────────────────────────────
# 저장
# ─────────────────────────────────────────────
# 지역제약 포트폴리오 (최종)
w_con_df.to_parquet(OUT_DIR / 'portfolio_weights_constrained.parquet')
perf_con.drop(columns=['ref_year'], errors='ignore').to_parquet(
    OUT_DIR / 'portfolio_performance_constrained.parquet')

# MVP 포트폴리오
w_mvp_df.to_parquet(OUT_DIR / 'portfolio_weights_mvp.parquet')
perf_mvp.drop(columns=['ref_year'], errors='ignore').to_parquet(
    OUT_DIR / 'portfolio_performance_mvp.parquet')

# Σ_down / Π / Binding 이력
sigma_df.to_parquet(OUT_DIR / 'sigma_down_history.parquet')
pi_df.to_parquet(OUT_DIR / 'pi_history.parquet')
bind_df.to_parquet(OUT_DIR / 'binding_history.parquet')

# 비교 요약
comparison.to_csv(OUT_DIR / 'comparison.csv', encoding='utf-8-sig')

# 비중 CSV (읽기 편한 형식)
wpct = (w_con_df * 100).round(1)
wpct.index = wpct.index.strftime('%Y-%m-%d')
wpct.to_csv(OUT_DIR / 'weights_constrained.csv', encoding='utf-8-sig')

print(f"\n[저장 완료] → {OUT_DIR}")
print(f"  portfolio_weights_constrained.parquet   ({w_con_df.shape[0]}행 × {w_con_df.shape[1]}슬롯)")
print(f"  portfolio_performance_constrained.parquet")
print(f"  portfolio_weights_mvp.parquet")
print(f"  portfolio_performance_mvp.parquet")
print(f"  sigma_down_history.parquet              ({sigma_df.shape[0]}분기 × {sigma_df.shape[1]}원소)")
print(f"  pi_history.parquet                      ({pi_df.shape[0]}분기 × {pi_df.shape[1]}슬롯)")
print(f"  binding_history.parquet                 ({bind_df.shape[0]}분기)")
print(f"  comparison.csv")
print(f"  weights_constrained.csv")
