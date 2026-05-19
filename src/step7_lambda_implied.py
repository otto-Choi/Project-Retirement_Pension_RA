"""
Step 7: 내재 위험회피계수 (λ_implied) 역산

설계:
  - Risk Score → w_risky (Step 6 매핑)
  - λ_implied는 BL 내재수익률(Π) 기반으로 계산 (OOS 실현수익률 X)
    → 8-A5 목적: "이 w_risky 선택에 내재된 위험회피 수준이 시장 기준(λ=3.0)과 얼마나 다른가"
    → 실현수익률은 분기마다 노이즈가 크므로 기대수익률(Π) 사용이 안정적

  역산 수식:
    E_R_q     = (w_sortino @ Π) × REBAL_DAYS        ← BL 기대 분기수익률
    σ_down_p  = sqrt(w_scaled @ Σ_down @ w_scaled × REBAL_DAYS)   ← w_scaled = w_sortino × w_risky
    MAR_q     = mar_annual / 4
    λ_implied = (E_R_q - MAR_q) / (w_risky × σ_down_p²)

  λ > λ_market(3.0) → 모델 대비 보수적 (주어진 리스크에서 더 높은 수익률 요구)
  λ < λ_market(3.0) → 모델 대비 공격적

입력:
  results/step5/portfolio_weights_constrained.parquet
  results/step5/sigma_down_history.parquet
  results/step5/pi_history.parquet

출력 (results/step7/):
  lambda_implied.parquet
  lambda_implied.csv
"""

import numpy as np
import pandas as pd
from pathlib import Path
import sys

ROOT    = Path(__file__).parent.parent
S5_DIR  = ROOT / 'results' / 'step5'
OUT_DIR = ROOT / 'results' / 'step7'
OUT_DIR.mkdir(exist_ok=True)

sys.path.insert(0, str(ROOT / 'src'))
from step6_cal import score_to_w_risky

REBAL_DAYS    = 63
LAMBDA_MARKET = 3.0
RISKFREE_SLOT = '무위험(현금성)'

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

DEMO_SCORES = [2.0, 4.0, 6.0, 7.2, 9.0]

# ─────────────────────────────────────────────
# 데이터 로드
# ─────────────────────────────────────────────
print("▶ 데이터 로드...")
w_con   = pd.read_parquet(S5_DIR / 'portfolio_weights_constrained.parquet')
sigma_h = pd.read_parquet(S5_DIR / 'sigma_down_history.parquet')
pi_h    = pd.read_parquet(S5_DIR / 'pi_history.parquet')

# MAR: pi_history에는 없으므로 performance에서 가져옴
perf = pd.read_parquet(S5_DIR / 'portfolio_performance_constrained.parquet')
mar_q_series = perf['mar_annual_pct'] / 100 / 4   # 연율 → 분기

print(f"  분기 수: {len(w_con)}개 ({w_con.index.min().date()} ~ {w_con.index.max().date()})")


def get_sigma_matrix(date: pd.Timestamp, valid_slots: list) -> np.ndarray:
    row = sigma_h.loc[date]
    n   = len(valid_slots)
    mat = np.zeros((n, n))
    for i, a in enumerate(valid_slots):
        for j, b in enumerate(valid_slots):
            val = row.get(f"{a}__{b}", np.nan)
            mat[i, j] = 0.0 if np.isnan(val) else val
    return mat


def calc_lambda_implied(
    w_sortino: np.ndarray,
    pi_vec: np.ndarray,
    sigma_down: np.ndarray,
    mar_q: float,
    w_risky: float,
) -> float:
    """
    BL 기대수익률 기반 λ_implied 역산.

    CAL 최적 조건 (mean-downside variance 효용 최대화):
      w_risky* = (E[R_risky] - R_f) / (λ × DownVar_risky)
      => λ = (E[R_risky] - MAR_q) / (w_risky × DownVar_risky)

    DownVar_risky는 100% 리스크자산 포트폴리오 기준 (w_risky로 스케일하지 않음).
    CAL로 스케일된 비중(w_scaled=w×w_risky)으로 계산하면 w_risky³이 분모에 들어가 발산함.

    Parameters
    ----------
    w_sortino  : Sortino-max 비중 벡터 (합계 ≈ 1, 100% 리스크자산)
    pi_vec     : BL 내재수익률 (일별)
    sigma_down : 하방 공분산 행렬 (일별)
    mar_q      : 분기 MAR
    w_risky    : CAL 위험자산 비중 (외생변수에서 매핑)
    """
    if w_risky < 1e-4:
        return np.nan

    # 100% 리스크자산 포트폴리오 BL 기대 분기수익률
    e_r_q = float(w_sortino @ pi_vec) * REBAL_DAYS

    # 100% 리스크자산 포트폴리오 하방분산 (분기)
    var_risky_q = float(w_sortino @ sigma_down @ w_sortino) * REBAL_DAYS

    excess_q = e_r_q - mar_q
    denom    = w_risky * var_risky_q
    if denom < 1e-12:
        return np.nan
    return round(excess_q / denom, 4)


# ─────────────────────────────────────────────
# 분기 × Risk Score별 λ_implied 계산
# ─────────────────────────────────────────────
common_dates = w_con.index.intersection(sigma_h.index).intersection(pi_h.index)
print(f"  공통 분기: {len(common_dates)}개")

records = []
for date in common_dates:
    if date not in mar_q_series.index:
        continue

    w_row  = w_con.loc[date]
    pi_row = pi_h.loc[date]
    mar_q  = float(mar_q_series.loc[date])

    valid_slots = [s for s in SLOTS if w_row.get(s, 0.0) > 1e-5 and not np.isnan(pi_row.get(s, np.nan))]
    if len(valid_slots) < 2:
        continue

    sigma_mat = get_sigma_matrix(date, valid_slots)
    w_sortino = np.array([w_row[s] for s in valid_slots])
    pi_vec    = np.array([pi_row[s] for s in valid_slots])

    for rs in DEMO_SCORES:
        w_risky = score_to_w_risky(rs)
        lam = calc_lambda_implied(w_sortino, pi_vec, sigma_mat, mar_q, w_risky)

        records.append({
            'date':           date,
            'risk_score':     rs,
            'w_risky':        w_risky,
            'lambda_implied': lam,
            'lambda_market':  LAMBDA_MARKET,
            'lambda_ratio':   round(lam / LAMBDA_MARKET, 4) if lam is not None and not np.isnan(lam) else np.nan,
        })

result_df = pd.DataFrame(records).set_index(['date', 'risk_score']).sort_index()
result_df.to_parquet(OUT_DIR / 'lambda_implied.parquet')
result_df.reset_index().to_csv(OUT_DIR / 'lambda_implied.csv', index=False, encoding='utf-8-sig')

# ─────────────────────────────────────────────
# 콘솔 요약
# ─────────────────────────────────────────────
LABELS = {2.0: '초보수형', 4.0: '보수형', 6.0: '중립형', 7.2: '성장형', 9.0: '공격형'}

print(f"\n【 λ_implied 요약 통계 (분기 평균, BL 기대수익률 기반) 】")
print(f"  λ_market(기준) = {LAMBDA_MARKET}  (Step 5 확정값)")
print(f"\n  {'Risk Score':<10} {'평균 λ':>8} {'σ':>8} {'중앙값':>8} {'λ>λ_mkt(%)':>12}  해석")
print("  " + "-" * 60)
for rs in DEMO_SCORES:
    sub = result_df.xs(rs, level='risk_score')['lambda_implied'].dropna()
    if len(sub) == 0:
        continue
    pct_above = (sub > LAMBDA_MARKET).mean() * 100
    conserv = '보수적' if sub.mean() > LAMBDA_MARKET else '공격적'
    label   = LABELS.get(rs, '')
    print(f"  RS {rs:<6.1f}  {sub.mean():>8.3f} {sub.std():>8.3f} {sub.median():>8.3f} {pct_above:>11.1f}%  {label}({conserv})")

# 최근 분기
last_date = common_dates[-1]
print(f"\n【 최근 분기 ({last_date.date()}) λ_implied 】")
last = result_df.xs(last_date, level='date')['lambda_implied']
for rs, lam in last.items():
    if np.isnan(lam):
        print(f"  RS {rs:.1f}  λ= N/A")
        continue
    cmp = '↑보수' if lam > LAMBDA_MARKET else '↓공격'
    label = LABELS.get(rs, '')
    print(f"  RS {rs:.1f} ({label:<5})  λ={lam:>7.3f}  (λ_mkt={LAMBDA_MARKET} 대비 {cmp})")

print(f"\n[저장 완료] → {OUT_DIR}")
print(f"  lambda_implied.parquet  ({len(result_df)}행: {len(common_dates)}분기 × {len(DEMO_SCORES)}점수대)")
print(f"  lambda_implied.csv")
