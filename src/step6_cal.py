"""
Step 6: CAL (Capital Allocation Line) — Risk Score → 최종 배분

설계:
  - Risk Score는 외생변수 (사용자 설문 결과로 주어짐, 1~10)
  - Risk Score → w_risky 선형 보간 → CAL 최종 배분
  - 최종 포트폴리오 = w_risky × Sortino-max + (1 - w_risky) × 무위험(현금성)
  - 법적 상한: DC/IRP 위험자산 70%

앵커 포인트 (plan 문서 §8-A1):
  Score 1 → 초보수형 → w_risky 0%
  Score 3 → 보수형   → w_risky 20%
  Score 5 → 중립형   → w_risky 40%
  Score 7 → 성장형   → w_risky 60%
  Score 9 → 공격형   → w_risky 70%

입력:
  results/step5/portfolio_weights_constrained.parquet   ← Sortino-max 비중
  results/step5/portfolio_performance_constrained.parquet

출력 (results/step6/):
  risk_score_map.csv             ← Risk Score 1~10 → w_risky 매핑표
  cal_demo_allocations.parquet   ← 대표 Risk Score별 × 분기별 최종 배분
  cal_demo_allocations.csv       ← 위의 CSV 버전 (읽기 편한 형식)
"""

import numpy as np
import pandas as pd
from pathlib import Path

ROOT    = Path(__file__).parent.parent
IN_DIR  = ROOT / 'results' / 'step5'
OUT_DIR = ROOT / 'results' / 'step6'
OUT_DIR.mkdir(exist_ok=True)

RISKFREE_SLOT = '무위험(현금성)'
W_RISKY_CAP   = 0.70   # DC/IRP 위험자산 법적 상한

# ─────────────────────────────────────────────
# Risk Score → w_risky 앵커 (선형 보간)
# ─────────────────────────────────────────────
_ANCHORS = np.array([1, 3, 5, 7, 9], dtype=float)
_W_RISKY = np.array([0.00, 0.20, 0.40, 0.60, 0.70], dtype=float)


def score_to_w_risky(risk_score: float) -> float:
    """Risk Score (1~10 실수) → w_risky 선형 보간, 상한 70% 클리핑."""
    w = float(np.interp(risk_score, _ANCHORS, _W_RISKY))
    return round(min(w, W_RISKY_CAP), 4)


def compute_cal_allocation(
    risk_score: float,
    sortino_weights: pd.Series,
) -> pd.Series:
    """
    단일 분기의 Sortino-max 비중(sortino_weights)에 CAL을 적용한 최종 배분 반환.

    Parameters
    ----------
    risk_score      : 외생변수 (1~10 실수)
    sortino_weights : SLOTS 인덱스를 가진 비중 Series (합계 ≈ 1)

    Returns
    -------
    final_weights   : 동일 인덱스의 최종 배분 Series
    """
    w_risky = score_to_w_risky(risk_score)

    # Sortino-max 전체에 w_risky를 곱하고, 무위험 슬롯에 (1-w_risky) 추가
    final = sortino_weights * w_risky
    final[RISKFREE_SLOT] = final.get(RISKFREE_SLOT, 0.0) + (1.0 - w_risky)
    return final.round(6)


# ─────────────────────────────────────────────
# 데이터 로드
# ─────────────────────────────────────────────
print("▶ Step 5 결과 로드...")
w_con = pd.read_parquet(IN_DIR / 'portfolio_weights_constrained.parquet')
perf  = pd.read_parquet(IN_DIR / 'portfolio_performance_constrained.parquet')

print(f"  분기 수: {len(w_con)}개 ({w_con.index.min().date()} ~ {w_con.index.max().date()})")

# ─────────────────────────────────────────────
# Risk Score 매핑표 저장
# ─────────────────────────────────────────────
scores = np.arange(1.0, 10.1, 0.5)
mapping = pd.DataFrame({
    'risk_score': scores,
    'w_risky':    [score_to_w_risky(s) for s in scores],
    'w_riskfree': [round(1 - score_to_w_risky(s), 4) for s in scores],
    '위험군':     pd.cut(
        scores,
        bins=[0, 2, 4, 6, 8, 10],
        labels=['초보수형', '보수형', '중립형', '성장형', '공격형'],
        right=True,
    ),
})
mapping.to_csv(OUT_DIR / 'risk_score_map.csv', index=False, encoding='utf-8-sig')
print("\n【 Risk Score → w_risky 매핑 (일부) 】")
print(mapping[mapping['risk_score'].isin([1, 3, 5, 7, 9, 10])].to_string(index=False))

# ─────────────────────────────────────────────
# 대표 Risk Score 5개 × 전 분기 CAL 배분 계산
# ─────────────────────────────────────────────
DEMO_SCORES = [2.0, 4.0, 6.0, 7.2, 9.0]   # 초보수/보수/중립/성장/공격 대표값

records = []
for rs in DEMO_SCORES:
    w_risky_val = score_to_w_risky(rs)
    for date, row in w_con.iterrows():
        final = compute_cal_allocation(rs, row.copy())
        rec = {'risk_score': rs, 'w_risky': w_risky_val, 'date': date}
        rec.update(final.to_dict())
        records.append(rec)

demo_df = (
    pd.DataFrame(records)
    .set_index(['risk_score', 'date'])
    .sort_index()
)

demo_df.to_parquet(OUT_DIR / 'cal_demo_allocations.parquet')

# CSV: risk_score별 최근 분기 비중만 (확인용)
last_date = w_con.index[-1]
last_rows = []
slots = [c for c in w_con.columns]
for rs in DEMO_SCORES:
    final = compute_cal_allocation(rs, w_con.loc[last_date].copy())
    row = {'risk_score': rs, 'w_risky': score_to_w_risky(rs), 'date': last_date.date()}
    row.update({s: round(final[s] * 100, 1) for s in slots})
    last_rows.append(row)

last_df = pd.DataFrame(last_rows)
last_df.to_csv(OUT_DIR / 'cal_demo_allocations.csv', index=False, encoding='utf-8-sig')

# ─────────────────────────────────────────────
# 콘솔 출력
# ─────────────────────────────────────────────
print(f"\n【 최근 리밸런싱 ({last_date.date()}) 대표 Risk Score별 최종 배분 (%) 】")
active_slots = [s for s in slots if last_df[[s]].astype(float).max().max() > 0]
header = f"{'슬롯':<28}" + "".join(f" RS{rs:>4.1f}" for rs in DEMO_SCORES)
print(header)
print("-" * (28 + 10 * len(DEMO_SCORES)))
for s in active_slots:
    vals = "".join(f" {last_df.loc[i, s]:>8.1f}%" for i in range(len(DEMO_SCORES)))
    print(f"{s:<28}{vals}")

print(f"\n  w_risky 값: " + ", ".join(f"RS{rs}→{score_to_w_risky(rs)*100:.0f}%" for rs in DEMO_SCORES))
print(f"\n[저장 완료] → {OUT_DIR}")
print(f"  risk_score_map.csv")
print(f"  cal_demo_allocations.parquet  ({len(demo_df)}행)")
print(f"  cal_demo_allocations.csv      (최근 분기 대표값)")
