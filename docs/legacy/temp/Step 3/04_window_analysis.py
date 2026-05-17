"""
Step 3: 최적 롤링 윈도우 탐색 (피드백 2·3·4·5 반영)

주요 변경:
  피드백 1 — 리밸런싱 주기: 분기 63거래일 (기존 월별→분기 수정 완료)
  피드백 2 — 입력 데이터: ETF 수익률 → 기초자산 지수 수익률 (index_returns.parquet)
  피드백 3 — MAR: 고정 2.5% → ECOS 정기예금 금리 시계열 (mar_series.parquet)
  피드백 5 — 평가 기준: 4가지 종합 (MAE / 소르티노 / 오차σ / 이상치 민감도)

평가 기준 4가지:
  ① 평균 예측 오차 (예측 하방위험 vs 실제 하방위험 MAE) → 최소화
  ② 실현 소르티노 비율 → 최대화
  ③ 오차 들쭉날쭉함 (오차 시계열 σ) → 최소화
  ④ 이상치 통제 (이상치 포함/제외 민감도) → 차이 최소화

가중치: ①MAE 35% / ②소르티노 30% / ③일관성 25% / ④이상치 10%
"""

import warnings
import numpy as np
import pandas as pd
from pathlib import Path
from scipy.optimize import minimize

warnings.filterwarnings('ignore')

BASE_DIR = Path(__file__).parent.parent   # /Users/djs/Desktop/Fintech
DATA_DIR = BASE_DIR / 'raw'
OUT_DIR  = Path(__file__).parent          # /Users/djs/Desktop/Fintech/Step 3

# ═══════════════════════════════════════════════════════
# 파라미터
# ═══════════════════════════════════════════════════════
WINDOWS     = {'1yr': 252, '2yr': 504, '3yr': 756, '5yr': 1260}
REBAL_DAYS  = 63        # 분기
LAMBDA      = 2.5
W_MAX       = 0.40
W_MIN       = 0.01
MISSING_TOL = 0.30      # 윈도우 내 결측 허용 비율
MIN_T_N     = 3         # 최소 조건: 거래일 수 / 슬롯 수 ≥ 3
MIN_QUARTERS= 4         # 최소 검증 분기 = 슬롯 수 × 4
OUTLIER_IQR = 1.5

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
print("▶ 기초자산 지수 수익률 로드 (index_returns.parquet)...")

idx_path = DATA_DIR / 'index_returns.parquet'
if not idx_path.exists():
    raise FileNotFoundError(
        "index_returns.parquet 없음 — 05_collect_index_data.py 먼저 실행하세요."
    )

slot_rets = (pd.read_parquet(idx_path)
             .reindex(columns=SLOTS)
             .sort_index())

print(f"기간: {slot_rets.index.min().date()} ~ {slot_rets.index.max().date()} "
      f"| {len(slot_rets)}거래일 | {slot_rets.notna().any().sum()}슬롯")

# ═══════════════════════════════════════════════════════
# 2. MAR 일별 시계열 구성
#    출처: mar_series.parquet (ECOS 정기예금 수신금리, 월별)
#    → 거래일 기준 forward-fill
# ═══════════════════════════════════════════════════════
print("\n▶ MAR 시계열 로드 (mar_series.parquet)...")

mar_path = DATA_DIR / 'mar_series.parquet'
if mar_path.exists():
    mar_monthly = pd.read_parquet(mar_path)['mar_annual']
    # 모든 거래일 날짜로 리인덱싱 후 ffill
    mar_daily = (mar_monthly
                 .resample('D').ffill()
                 .reindex(slot_rets.index)
                 .ffill()
                 .bfill())
    mar_daily /= 100   # % → decimal
    print(f"  MAR 범위: {mar_daily.min()*100:.2f}% ~ {mar_daily.max()*100:.2f}%")
    print(f"  MAR 평균: {mar_daily.mean()*100:.2f}%  (연율)")
else:
    print("  ⚠ mar_series.parquet 없음 → 2.5% 고정 사용")
    mar_daily = pd.Series(0.025, index=slot_rets.index)

# 일별 → 분기 MAR (누적 개념: annual / 4)
mar_daily_rate = mar_daily / 252   # 일별 소수 비율


# ═══════════════════════════════════════════════════════
# 3. 유틸리티
# ═══════════════════════════════════════════════════════
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
    res = minimize(
        neg_sortino, np.ones(n) / n, method='SLSQP',
        bounds=[(w_min, w_max)] * n,
        constraints=[{'type': 'eq', 'fun': lambda w: w.sum() - 1}],
        options={'maxiter': 500, 'ftol': 1e-9},
    )
    return res.x if res.success else np.ones(n) / n


# ═══════════════════════════════════════════════════════
# 4. Walk-forward (분기 단위, 시변 MAR)
# ═══════════════════════════════════════════════════════
print("\n▶ Walk-forward 시작 (분기 기준, 실제 MAR 적용)...\n")

all_dates = slot_rets.index.values
n_dates   = len(all_dates)
results   = {}

for win_name, win_days in WINDOWS.items():
    records     = []
    end_indices = range(win_days, n_dates - REBAL_DAYS, REBAL_DAYS)

    for end_idx in end_indices:
        est = slot_rets.iloc[end_idx - win_days : end_idx]

        # 가용 슬롯 선별
        valid_cols = est.columns[est.isna().mean() < MISSING_TOL].tolist()
        if len(valid_cols) < 3:
            continue
        est_v = est[valid_cols].dropna()
        if len(est_v) / len(valid_cols) < MIN_T_N:
            continue

        # 윈도우 구간 평균 MAR (일별 소수)
        mar_win_scalar = float(mar_daily_rate.iloc[end_idx - win_days : end_idx].mean())

        sigma_down = downside_cov(est_v.values, mar_win_scalar)

        # 시장 비중: 지수 데이터이므로 균등 비중 사용
        w_mkt = np.ones(len(valid_cols)) / len(valid_cols)
        pi    = LAMBDA * sigma_down @ w_mkt

        w_opt = solve_max_sortino(
            sigma_down, pi,
            mar_win_scalar * REBAL_DAYS,   # 분기 MAR (추정 구간 기준)
            W_MIN, W_MAX
        )

        # 예측 하방위험 (분기 스케일)
        pred_down_risk = np.sqrt(max(float(w_opt @ sigma_down @ w_opt) * REBAL_DAYS, 0))

        # 다음 분기 실현 성과
        oos = slot_rets[valid_cols].iloc[end_idx : end_idx + REBAL_DAYS].fillna(0).values
        if len(oos) < int(REBAL_DAYS * 0.7):
            continue

        # OOS 구간 MAR (실현 구간)
        mar_oos_daily = float(mar_daily_rate.iloc[end_idx : end_idx + REBAL_DAYS].mean())
        mar_oos_q     = mar_oos_daily * REBAL_DAYS   # 분기 환산

        port_r = oos @ w_opt
        cum_r  = float((port_r + 1).prod() - 1)
        down_r = np.minimum(port_r - mar_oos_daily, 0.0)

        real_down_risk = np.sqrt(max(float(np.mean(down_r ** 2)) * REBAL_DAYS, 0))
        real_sortino   = (cum_r - mar_oos_q) / (real_down_risk + 1e-10)
        pred_error     = abs(pred_down_risk - real_down_risk)

        records.append({
            'date':           pd.Timestamp(all_dates[end_idx]),
            'n_slots':        len(valid_cols),
            'pred_down_risk': pred_down_risk,
            'real_down_risk': real_down_risk,
            'pred_error':     pred_error,
            'real_sortino':   real_sortino,
            'mar_oos_annual': mar_oos_daily * 252 * 100,  # 참고용 %
        })

    results[win_name] = records
    n = len(records)
    if n > 0:
        e = [r['pred_error']   for r in records]
        s = [r['real_sortino'] for r in records]
        m = [r['mar_oos_annual'] for r in records]
        print(f"  [{win_name}] 검증 {n:>2}분기 | "
              f"평균예측오차 {np.mean(e)*100:.2f}% | "
              f"실현소르티노 {np.mean(s):+.3f} | "
              f"평균MAR {np.mean(m):.2f}%")
    else:
        print(f"  [{win_name}] 데이터 부족 — 건너뜀")


# ═══════════════════════════════════════════════════════
# 5. 4가지 기준 집계
# ═══════════════════════════════════════════════════════
print("\n▶ 기준별 집계 (4가지)...")

summary_rows = []

for win_name, records in results.items():
    if not records:
        continue

    errors   = np.array([r['pred_error']   for r in records])
    sortinos = np.array([r['real_sortino'] for r in records])
    n        = len(records)
    avg_slots = np.mean([r['n_slots'] for r in records])

    min_q_required = avg_slots * MIN_QUARTERS
    meets_min = n >= min_q_required

    mae           = float(np.mean(errors))
    mean_sortino  = float(np.mean(sortinos))
    sortino_std   = float(np.std(sortinos))   # ③ 소르티노 비율의 σ (피드백 3)

    q1, q3 = np.percentile(errors, 25), np.percentile(errors, 75)
    iqr    = q3 - q1
    outlier_mask = errors > (q3 + OUTLIER_IQR * iqr)
    n_outliers   = int(outlier_mask.sum())

    if (~outlier_mask).sum() > 3:
        mae_no_out      = float(np.mean(errors[~outlier_mask]))
        sortino_no_out  = float(np.mean(sortinos[~outlier_mask]))
    else:
        mae_no_out     = mae
        sortino_no_out = mean_sortino

    outlier_sensitivity = abs(mean_sortino - sortino_no_out)  # 소르티노 기준 민감도

    summary_rows.append({
        '윈도우':               win_name,
        '검증 분기':            n,
        '평균 슬롯 수':         round(avg_slots, 1),
        '최소조건 충족':         '✓' if meets_min else '✗',
        '① 평균 예측오차(%)':   round(mae * 100, 3),
        '② 실현 소르티노':      round(mean_sortino, 3),
        '③ 소르티노 σ':         round(sortino_std, 3),
        '④ 이상치 분기 수':     n_outliers,
        '④ 이상치 제외 소르티노': round(sortino_no_out, 3),
        '④ 이상치 민감도':      round(outlier_sensitivity, 3),
    })

summary_df = pd.DataFrame(summary_rows)


# ═══════════════════════════════════════════════════════
# 6. 결과 출력 및 최적 윈도우 선정
# ═══════════════════════════════════════════════════════
print("\n" + "="*80)
print("【 롤링 윈도우 분석 결과 (분기 기준 · 기초자산 지수 · 실제 MAR) 】")
print("="*80)
print(summary_df.to_string(index=False))

candidates = summary_df[summary_df['최소조건 충족'] == '✓'].copy()
if len(candidates) == 0:
    print("\n⚠ 최소조건 통과 윈도우 없음 — 전체 후보 사용")
    candidates = summary_df.copy()


def norm_score(s, higher_better=True):
    rng = s.max() - s.min()
    if rng < 1e-10:
        return pd.Series(0.5, index=s.index)
    n = (s - s.min()) / rng
    return n if higher_better else 1 - n


if len(candidates) > 1:
    c = candidates.reset_index(drop=True)
    c['sc_mae']     = norm_score(c['① 평균 예측오차(%)'],     higher_better=False)
    c['sc_sortino'] = norm_score(c['② 실현 소르티노'],         higher_better=True)
    c['sc_consist'] = norm_score(c['③ 소르티노 σ'],            higher_better=False)
    c['sc_outlier'] = norm_score(c['④ 이상치 민감도'],         higher_better=False)

    c['종합 점수'] = (
        c['sc_mae']     * 0.35 +
        c['sc_sortino'] * 0.30 +
        c['sc_consist'] * 0.25 +
        c['sc_outlier'] * 0.10
    )

    best_idx    = c['종합 점수'].idxmax()
    best_window = c.loc[best_idx, '윈도우']

    print("\n【 종합 점수 (①MAE 35% / ②소르티노 30% / ③일관성 25% / ④이상치 10%) 】")
    print(c[['윈도우', 'sc_mae', 'sc_sortino', 'sc_consist',
              'sc_outlier', '종합 점수']].round(3).to_string(index=False))
    print(f"\n★ 최적 윈도우: {best_window}  "
          f"(종합 점수 {c.loc[best_idx, '종합 점수']:.3f})")
else:
    best_window = candidates.iloc[0]['윈도우']
    print(f"\n★ 단일 후보: {best_window}")

print(f"\n[데이터 출처]")
print(f"  수익률: 기초자산 지수 (pykrx / yfinance / ECOS)")
print(f"  MAR   : ECOS 정기예금 수신금리 (월별 → 일별 ffill)")


# ═══════════════════════════════════════════════════════
# 7. 저장
# ═══════════════════════════════════════════════════════
summary_df.to_csv(OUT_DIR / 'window_analysis_result.csv',
                  index=False, encoding='utf-8-sig')
print(f"\n[저장] window_analysis_result.csv → {OUT_DIR}")
