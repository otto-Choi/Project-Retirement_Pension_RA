"""
Step 6b: 현재 시점 최적 배분 산출 (라이브 서비스용)

백테스트(Step 5)는 OOS 평가 기간이 필요해 마지막 리밸런싱이 2025-01-16에 멈춤.
새 투자자 서비스는 OOS 평가 없이 **현재 시점 기준** 최적 비중만 필요.

설계:
  - 추정 윈도우: index_returns 마지막 날짜 기준 5년(1260거래일) 이전 ~ 현재
  - w_mkt: year_end_best 최신 연도(2024) AUM 비중
  - Sortino-max + MVP 동시 산출 (제약: US≤50%, KR≤50%, EM≤15%)
  - Risk Score(외생변수) → w_risky → CAL 최종 배분

입력:
  data/index_returns.parquet
  data/year_end_best.csv
  data/mar_series.parquet

출력 (results/current/):
  current_weights_sortino.csv    ← Sortino-max 슬롯별 비중
  current_weights_mvp.csv        ← MVP 슬롯별 비중
  current_cal_allocations.csv    ← Risk Score별 CAL 최종 배분
  current_meta.json              ← 산출 기준일, 파라미터 등
"""

import argparse
import json
import sys
import numpy as np
import pandas as pd
from pathlib import Path
from scipy.optimize import minimize

# step3 이후 바로 실행하면 데이터 끝 날짜를 자동 감지하므로 별도 인수 불필요.
# 특정 날짜로 자르고 싶을 때: python step6b_current_allocation.py --as-of 2026-06-15
_parser = argparse.ArgumentParser()
_parser.add_argument('--as-of', default=None,
                     help='배분 기준일 (YYYY-MM-DD). 기본값: 데이터 마지막 날')
_args, _ = _parser.parse_known_args()
AS_OF = pd.Timestamp(_args.__dict__['as_of']) if _args.__dict__['as_of'] else None

ROOT     = Path(__file__).parent.parent
DATA_DIR = ROOT / 'data'
OUT_DIR  = ROOT / 'results' / 'current'
OUT_DIR.mkdir(exist_ok=True)

sys.path.insert(0, str(ROOT / 'src'))
from step6_cal import score_to_w_risky, compute_cal_allocation

# ─────────────────────────────────────────────
# 파라미터 (Step 5와 동일)
# ─────────────────────────────────────────────
WIN_DAYS    = 1260
REBAL_DAYS  = 63
LAMBDA      = 3.0
W_MAX       = 0.40
W_MIN       = 0.01
MISSING_TOL = 0.30
US_CAP      = 0.50
KR_CAP      = 0.50
EM_CAP      = 0.15

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

DEMO_SCORES = [2.0, 4.0, 5.0, 6.0, 7.2, 9.0]

# ─────────────────────────────────────────────
# 데이터 로드
# ─────────────────────────────────────────────
print("▶ 데이터 로드...")
idx_rets = pd.read_parquet(DATA_DIR / 'index_returns.parquet').reindex(columns=SLOTS).sort_index()

yeb = pd.read_csv(DATA_DIR / 'year_end_best.csv')
aum_by_year = {}
for yr, grp in yeb.groupby('year'):
    aum_by_year[int(yr)] = dict(zip(grp['slot'], grp['aum_억'].astype(float)))

mar_monthly = pd.read_parquet(DATA_DIR / 'mar_series.parquet')['mar_annual']
mar_daily   = (mar_monthly.resample('D').ffill()
               .reindex(idx_rets.index).ffill().bfill()) / 100
mar_rate    = mar_daily / 252

# ─────────────────────────────────────────────
# 현재 추정 윈도우 설정
# ─────────────────────────────────────────────
end_date   = AS_OF if AS_OF else idx_rets.index[-1]   # 기본: 데이터 마지막 날짜
end_i      = len(idx_rets) - 1
start_i    = max(end_i - WIN_DAYS, 0)
window     = idx_rets.iloc[start_i : end_i + 1]
start_date = idx_rets.index[start_i]

# w_mkt: 현재 연도 직전 연도말 AUM 사용 (2024년)
ref_year = end_date.year - 1
if ref_year not in aum_by_year:
    ref_year = max(aum_by_year.keys())

print(f"  추정 윈도우 : {start_date.date()} ~ {end_date.date()} ({end_i - start_i}거래일)")
print(f"  AUM 기준 연도: {ref_year}년")

# ─────────────────────────────────────────────
# 유효 슬롯 선별
# ─────────────────────────────────────────────
yeb_slots   = list(aum_by_year[ref_year].keys())
missing_pct = window[yeb_slots].isna().mean()
valid_cols  = missing_pct[missing_pct < MISSING_TOL].index.tolist()

est_v = window[valid_cols].dropna()
print(f"  유효 슬롯   : {len(valid_cols)}개 → {valid_cols}")
print(f"  결측 제거 후: {len(est_v)}거래일")

# ─────────────────────────────────────────────
# 하방공분산 & BL 내재수익률
# ─────────────────────────────────────────────
mar_est    = float(mar_rate.reindex(est_v.index, method='ffill').mean())
d          = np.minimum(est_v.values - mar_est, 0.0)
sigma_down = (d.T @ d) / len(d)
sigma_full = np.cov(est_v.values.T)           # 일반 공분산 (연환산용)

aum_vals = np.array([aum_by_year[ref_year].get(s, 1.0) for s in valid_cols], dtype=float)
w_mkt    = aum_vals / aum_vals.sum()
pi       = LAMBDA * sigma_down @ w_mkt
mar_q    = mar_est * REBAL_DAYS

n = len(valid_cols)

# ─────────────────────────────────────────────
# 최적화 함수
# ─────────────────────────────────────────────
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

cons = _build_constraints(valid_cols, n)

def neg_sortino(w):
    ret  = float(w @ pi) * REBAL_DAYS
    risk = np.sqrt(max(float(w @ sigma_down @ w) * REBAL_DAYS, 1e-12))
    return -(ret - mar_q) / risk

res_sortino = minimize(neg_sortino, np.ones(n) / n, method='SLSQP',
                       bounds=[(W_MIN, W_MAX)] * n, constraints=cons,
                       options={'maxiter': 500, 'ftol': 1e-9})
w_sortino = res_sortino.x if res_sortino.success else np.ones(n) / n

res_mvp = minimize(lambda w: float(w @ sigma_down @ w), np.ones(n) / n,
                   method='SLSQP', bounds=[(W_MIN, W_MAX)] * n,
                   constraints=cons, options={'maxiter': 500, 'ftol': 1e-9})
w_mvp = res_mvp.x if res_mvp.success else np.ones(n) / n

print(f"\n  최적화: Sortino-max {'성공' if res_sortino.success else '실패'}, "
      f"MVP {'성공' if res_mvp.success else '실패'}")

# ─────────────────────────────────────────────
# 결과 정리
# ─────────────────────────────────────────────
# 전체 SLOTS 기준 비중 Series (미사용 슬롯 = 0)
def to_full_series(w_opt, valid_cols):
    s = pd.Series(0.0, index=SLOTS)
    for slot, w in zip(valid_cols, w_opt):
        s[slot] = round(float(w), 6)
    return s

w_sortino_full = to_full_series(w_sortino, valid_cols)
w_mvp_full     = to_full_series(w_mvp, valid_cols)

# ─────────────────────────────────────────────
# 콘솔 출력
# ─────────────────────────────────────────────
print(f"\n{'슬롯':<28} {'Sortino-max':>12} {'MVP':>8}")
print("-" * 52)
for slot in SLOTS:
    ws = w_sortino_full[slot]
    wm = w_mvp_full[slot]
    if ws > 0.001 or wm > 0.001:
        print(f"{slot:<28} {ws*100:>11.1f}% {wm*100:>7.1f}%")

us_s = sum(w_sortino_full[s] for s in US_SLOTS) * 100
kr_s = sum(w_sortino_full[s] for s in KR_SLOTS) * 100
em_s = sum(w_sortino_full[s] for s in EM_SLOTS) * 100
print(f"\n  지역 합계: US={us_s:.1f}% (≤50%), KR={kr_s:.1f}% (≤50%), EM={em_s:.1f}% (≤15%)")

sortino_val = -neg_sortino(w_sortino)
print(f"  Sortino 비율: {sortino_val:.4f}  |  MAR(분기): {mar_q*100:.3f}%")

# CAL 최종 배분
print(f"\n{'위험군':<10} {'RS':>5} {'w_risky':>8} {'미국주식':>10} {'국내주식':>10} {'신흥국':>8} {'채권+금':>10} {'무위험':>8}")
print("-" * 75)
LABEL_MAP = {2.0:'초보수형', 4.0:'보수형', 5.0:'중립형', 6.0:'중립형+', 7.2:'성장형', 9.0:'공격형'}
for rs in DEMO_SCORES:
    final = compute_cal_allocation(rs, w_sortino_full.copy())
    us    = sum(final.get(s, 0) for s in US_SLOTS)
    kr    = sum(final.get(s, 0) for s in KR_SLOTS)
    em    = sum(final.get(s, 0) for s in EM_SLOTS)
    bond  = sum(final.get(s, 0) for s in SLOTS
                if '채권' in s or '금' in s)
    rf    = final.get('무위험(현금성)', 0)
    print(f"{LABEL_MAP[rs]:<10} {rs:>5.1f} {score_to_w_risky(rs)*100:>7.0f}%"
          f" {us*100:>9.1f}% {kr*100:>9.1f}% {em*100:>7.1f}% {bond*100:>9.1f}% {rf*100:>7.1f}%")

# ─────────────────────────────────────────────
# 리스크 스코어별 기대수익·위험 지표 계산
# ─────────────────────────────────────────────
def portfolio_risk_metrics(w_full: pd.Series) -> dict:
    """
    슬롯 전체 비중 Series → UI 표시용 위험 지표 4종 반환.

    - exp_ret_ann_pct  : 기대수익률 연환산 (BL 내재수익률 기준, %)
    - vol_ann_pct      : 변동성 연환산 (full covariance, %)
    - down_risk_q_pct  : 하방위험 분기 (Downside Std, %)
    - cvar_95_q_pct    : CVaR 95% 분기 (역사적 중첩 63일 윈도우, %)
                         음수 = 손실. e.g. -3.2 → "최악 5% 시나리오에서 분기 -3.2%"
    """
    w_v = np.array([float(w_full.get(s, 0)) for s in valid_cols])

    exp_ret_ann  = float(w_v @ pi) * 252 * 100
    down_risk_q  = np.sqrt(max(float(w_v @ sigma_down @ w_v) * REBAL_DAYS, 1e-12)) * 100
    vol_ann      = np.sqrt(max(float(w_v @ sigma_full @ w_v) * 252, 1e-12)) * 100

    # 역사적 중첩 63일 윈도우로 CVaR
    dp = est_v.values @ w_v
    q_rets = np.array([
        float(np.prod(1 + dp[i:i + REBAL_DAYS]) - 1) * 100
        for i in range(len(dp) - REBAL_DAYS + 1)
    ])
    var_95  = float(np.percentile(q_rets, 5))
    cvar_95 = float(q_rets[q_rets <= var_95].mean()) if (q_rets <= var_95).any() else var_95

    return {
        'exp_ret_ann_pct':  round(exp_ret_ann,  2),
        'vol_ann_pct':      round(vol_ann,       2),
        'down_risk_q_pct':  round(down_risk_q,   2),
        'cvar_95_q_pct':    round(cvar_95,        2),
    }

# ─────────────────────────────────────────────
# 저장
# ─────────────────────────────────────────────
# 비중 CSV
w_sortino_full.rename('weight').to_frame().assign(
    pct=lambda x: (x['weight'] * 100).round(2)
).to_csv(OUT_DIR / 'current_weights_sortino.csv', encoding='utf-8-sig')

w_mvp_full.rename('weight').to_frame().assign(
    pct=lambda x: (x['weight'] * 100).round(2)
).to_csv(OUT_DIR / 'current_weights_mvp.csv', encoding='utf-8-sig')

# CAL 배분 CSV (전체 Score 범위) + 위험 지표
cal_rows = []
for rs in np.arange(1.0, 10.1, 0.5):
    final   = compute_cal_allocation(float(rs), w_sortino_full.copy())
    metrics = portfolio_risk_metrics(final)
    row     = {'risk_score': round(rs, 1), 'w_risky': score_to_w_risky(rs)}
    row.update({s: round(float(final[s]), 6) for s in SLOTS})
    row.update(metrics)
    cal_rows.append(row)
pd.DataFrame(cal_rows).to_csv(OUT_DIR / 'current_cal_allocations.csv',
                               index=False, encoding='utf-8-sig')

# 메타 정보
meta = {
    'as_of_date':       str(end_date.date()),
    'window_start':     str(start_date.date()),
    'window_days':      int(end_i - start_i),
    'ref_year_aum':     ref_year,
    'n_valid_slots':    n,
    'valid_slots':      valid_cols,
    'lambda':           LAMBDA,
    'mar_q_pct':        round(mar_q * 100, 4),
    'sortino_ratio':    round(float(sortino_val), 4),
    'us_alloc_pct':     round(us_s, 2),
    'kr_alloc_pct':     round(kr_s, 2),
    'em_alloc_pct':     round(em_s, 2),
    'optimization_ok':  res_sortino.success,
}
with open(OUT_DIR / 'current_meta.json', 'w', encoding='utf-8') as f:
    json.dump(meta, f, ensure_ascii=False, indent=2)

print(f"\n[저장 완료] → {OUT_DIR}")
print(f"  current_weights_sortino.csv")
print(f"  current_weights_mvp.csv")
print(f"  current_cal_allocations.csv  ({len(cal_rows)}개 Risk Score, 위험지표 4종 포함)")
print(f"  current_meta.json")
