"""
Step 8-A: 사용자 대면 XAI — 개인화 의사결정 설명

모듈 목록:
  8-A0  기회비용 시뮬레이션      (원리금보장 방치 vs 참고 포트폴리오)
  8-A1  Risk Score → CAL 흐름   (점수 → 비중 결정 과정 시각화)
  8-A2  Risk Score 하위변수 분해  (워터폴 차트)
  8-A3  Big Five 라이프스타일 경로 (텍스트 → 투자성향 점수 경로)
  8-A4  손실 감내도 시각화        (MDD를 금액으로 변환)
  8-A5  내재 λ 성향 지표          (시장 기준 대비 위험회피 수준)
  8-A6  MVP vs Sortino-max 비교

외생변수 (사용자 입력):
  risk_score    : 설문 합산 점수 (1~10 실수)
  sub_scores    : 하위변수 점수 dict (나이·은퇴기간·직업·자금·가족·라이프, 각 1~10)
  big5          : Big Five dict (openness·conscientiousness·stability, 각 1~5)
                  ※ 8-A3 전용, 해당 파이프라인 미완성 시 None 전달 가능
  current_balance  : 현재 퇴직연금 적립금 (만원)
  annual_salary    : 연봉 (만원)
  years_to_retire  : 은퇴까지 남은 연수

출력: results/step8/figures/ 에 PNG 저장
"""

import sys
import warnings
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyArrowPatch
from pathlib import Path

warnings.filterwarnings('ignore')

ROOT    = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'src'))

from step6_cal import score_to_w_risky, compute_cal_allocation

S5_DIR  = ROOT / 'results' / 'step5'
S7_DIR  = ROOT / 'results' / 'step7'
CUR_DIR = ROOT / 'results' / 'current'
FIG_DIR = ROOT / 'results' / 'step8' / 'figures'
FIG_DIR.mkdir(parents=True, exist_ok=True)

plt.rcParams['font.family']      = 'Malgun Gothic'
plt.rcParams['axes.unicode_minus'] = False
plt.rcParams['figure.dpi']       = 120

DISCLAIMER = "※ 이 정보는 투자 참고용이며, 미래 수익을 보장하지 않습니다. 투자 결정은 투자자 본인이 합니다."

SLOTS = [
    '국내주식_코스피', '국내주식_코스닥',
    '미국주식_SP500',  '미국주식_나스닥',
    '신흥국_인도',     '신흥국_중국',
    '국내채권_국고채단중기', '국내채권_국고채장기',
    '국내채권_회사채', '국내채권_종합',
    '해외채권_미국국채', '원자재_금', '무위험(현금성)',
]
SLOTS_GROUPED = {
    '국내주식': ['국내주식_코스피', '국내주식_코스닥'],
    '미국주식': ['미국주식_SP500', '미국주식_나스닥'],
    '신흥국':   ['신흥국_인도', '신흥국_중국'],
    '국내채권': ['국내채권_국고채단중기','국내채권_국고채장기','국내채권_회사채','국내채권_종합'],
    '해외채권': ['해외채권_미국국채'],
    '원자재':   ['원자재_금'],
    '무위험':   ['무위험(현금성)'],
}
GROUP_COLORS = ['#4e79a7','#f28e2b','#e15759','#76b7b2','#59a14f','#edc948','#b07aa1']

# ══════════════════════════════════════════════════════════════
# 데이터 로드 (공통)
# ══════════════════════════════════════════════════════════════
perf_con = pd.read_parquet(S5_DIR / 'portfolio_performance_constrained.parquet')
perf_mvp = pd.read_parquet(S5_DIR / 'portfolio_performance_mvp.parquet')
lam_df   = pd.read_parquet(S7_DIR / 'lambda_implied.parquet').reset_index()
cur_w    = pd.read_csv(CUR_DIR / 'current_weights_sortino.csv', index_col=0)['weight']
cur_mvp  = pd.read_csv(CUR_DIR / 'current_weights_mvp.csv',    index_col=0)['weight']

# 누적수익률 시리즈
cum_con = (1 + perf_con['cum_ret_pct'] / 100).cumprod()
cum_mvp = (1 + perf_mvp['cum_ret_pct'] / 100).cumprod()

def _mdd(cum_series: pd.Series) -> float:
    peak = cum_series.cummax()
    return float(((cum_series - peak) / peak).min())

MDD_CON  = _mdd(cum_con)          # Sortino-max 역사적 MDD
MDD_MVP  = _mdd(cum_mvp)
ANN_RET_CON = float(cum_con.iloc[-1] ** (4 / len(cum_con)) - 1)   # 연환산 수익률
ANN_RET_MVP = float(cum_mvp.iloc[-1] ** (4 / len(cum_mvp)) - 1)

BENCH_RETURN = 0.025   # 원리금보장형 대표 연수익률 (정기예금 2.5% 수준)


# ══════════════════════════════════════════════════════════════
# 8-A0: 기회비용 시뮬레이션
# ══════════════════════════════════════════════════════════════
def plot_a0_opportunity_cost(
    current_balance: float,
    annual_salary: float,
    years_to_retire: float,
    risk_score: float,
    portfolio_return: float = ANN_RET_CON,
    bench_return: float = BENCH_RETURN,
) -> str:
    monthly_contrib = annual_salary / 12
    years = years_to_retire

    def fv(balance, monthly_c, ann_r, yrs):
        if ann_r < 1e-6:
            return balance + monthly_c * 12 * yrs
        fv_lump  = balance * (1 + ann_r) ** yrs
        fv_annuity = monthly_c * ((1 + ann_r) ** yrs - 1) / (ann_r / 12)
        return fv_lump + fv_annuity

    fv_bench = fv(current_balance, monthly_contrib, bench_return, years)
    fv_port  = fv(current_balance, monthly_contrib, portfolio_return, years)
    opp_cost = fv_port - fv_bench

    # 연도별 시뮬레이션 경로
    yr_range = np.arange(0, years + 1)
    path_bench = [fv(current_balance, monthly_contrib, bench_return, y) for y in yr_range]
    path_port  = [fv(current_balance, monthly_contrib, portfolio_return, y) for y in yr_range]

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(yr_range, [v / 1e4 for v in path_bench], '--', color='steelblue',
            lw=2, label=f'원리금보장형 방치 ({bench_return*100:.1f}%/년)')
    ax.plot(yr_range, [v / 1e4 for v in path_port], '-', color='tomato',
            lw=2.5, label=f'참고 포트폴리오 (역사적 {portfolio_return*100:.1f}%/년)')
    ax.fill_between(yr_range, [v/1e4 for v in path_bench], [v/1e4 for v in path_port],
                    alpha=0.15, color='tomato')

    ax.annotate(f'+{opp_cost/1e4:,.0f}억원\n차이',
                xy=(years, fv_port/1e4),
                xytext=(-40, 20), textcoords='offset points',
                fontsize=11, fontweight='bold', color='tomato',
                arrowprops=dict(arrowstyle='->', color='tomato'))

    ax.set_xlabel('경과 연수')
    ax.set_ylabel('예상 자산 (억원)')
    ax.set_title(f'[8-A0] 기회비용 시뮬레이션\n'
                 f'적립금 {current_balance/1e4:.0f}억원 · 연봉 {annual_salary/1e4:.1f}억원 · {years:.0f}년 후 은퇴')
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f'{x:.0f}억'))
    ax.legend(fontsize=9)
    ax.grid(alpha=0.3)

    note = (f"은퇴 시 예상 자산: 원리금보장 {fv_bench/1e4:.1f}억 → 참고 포트폴리오 {fv_port/1e4:.1f}억  "
            f"(차이 {opp_cost/1e4:+.1f}억)")
    ax.text(0.01, -0.13, DISCLAIMER, transform=ax.transAxes,
            fontsize=7, color='gray', style='italic')
    ax.text(0.01, -0.09, note, transform=ax.transAxes, fontsize=8.5)

    plt.tight_layout()
    path = FIG_DIR / 'a0_opportunity_cost.png'
    plt.savefig(path, bbox_inches='tight')
    plt.show()
    print(f"  저장: {path.name}")
    return str(path)


# ══════════════════════════════════════════════════════════════
# 8-A1: Risk Score → CAL 배분 흐름
# ══════════════════════════════════════════════════════════════
def plot_a1_cal_flow(risk_score: float) -> str:
    w_risky = score_to_w_risky(risk_score)
    final   = compute_cal_allocation(risk_score, cur_w.copy())

    TIER_ANCHORS = [(1,'초보수형',0.00),(3,'보수형',0.20),
                    (5,'중립형',0.40),(7,'성장형',0.60),(9,'공격형',0.70)]
    tier_name = '초보수형'
    for score, name, _ in TIER_ANCHORS:
        if risk_score >= score:
            tier_name = name

    # 자산군별 최종 비중
    groups = {g: sum(final.get(s, 0) for s in slots)
              for g, slots in SLOTS_GROUPED.items()}

    fig, axes = plt.subplots(1, 2, figsize=(12, 5),
                             gridspec_kw={'width_ratios': [1, 1.2]})

    # ─── 왼쪽: 흐름 다이어그램 ───
    ax = axes[0]
    ax.set_xlim(0, 10); ax.set_ylim(0, 10); ax.axis('off')

    boxes = [
        (5, 8.5, f'Risk Score\n{risk_score:.1f}점 ({tier_name})', '#4e79a7'),
        (5, 6.0, f'w_risky = {w_risky*100:.0f}%\n(DC/IRP 법적 상한 70%)', '#f28e2b'),
        (2, 3.2, f'Sortino-max\n포트폴리오\n({w_risky*100:.0f}%)', '#e15759'),
        (8, 3.2, f'무위험자산\n(원리금보장)\n({(1-w_risky)*100:.0f}%)', '#76b7b2'),
    ]
    for x, y, txt, color in boxes:
        ax.add_patch(plt.Rectangle((x-2.2, y-0.9), 4.4, 1.8,
                                   facecolor=color, alpha=0.25, edgecolor=color, lw=1.5))
        ax.text(x, y, txt, ha='center', va='center', fontsize=9, fontweight='bold')

    for (x1,y1), (x2,y2) in [((5,7.6),(5,6.9)), ((5,5.1),(2,4.1)), ((5,5.1),(8,4.1))]:
        ax.annotate('', xy=(x2,y2), xytext=(x1,y1),
                    arrowprops=dict(arrowstyle='->', lw=1.5, color='#555'))

    ax.text(5, 1.5,
            f'최종: 위험 {w_risky*100:.0f}% + 무위험 {(1-w_risky)*100:.0f}%',
            ha='center', fontsize=10, color='#333',
            bbox=dict(boxstyle='round,pad=0.4', facecolor='#ffffcc', edgecolor='#ccc'))
    ax.set_title('[8-A1] Risk Score → CAL 배분 결정 흐름', fontsize=11, pad=10)

    # ─── 오른쪽: 최종 배분 도넛 ───
    ax2 = axes[1]
    vals   = [v for v in groups.values() if v > 0.001]
    labels = [k for k, v in groups.items() if v > 0.001]
    colors = [GROUP_COLORS[i] for i, (k, v) in enumerate(groups.items()) if v > 0.001]
    wedges, texts = ax2.pie(vals, labels=None, colors=colors, startangle=90,
                            wedgeprops=dict(width=0.55), pctdistance=0.75)
    ax2.text(0, 0, f"무위험\n{groups['무위험']*100:.0f}%",
             ha='center', va='center', fontsize=10, fontweight='bold')

    legend_labels = [f"{l}  {v*100:.1f}%" for l, v in zip(labels, vals)]
    ax2.legend(wedges, legend_labels, loc='lower center',
               ncol=2, fontsize=8, bbox_to_anchor=(0.5, -0.18))
    ax2.set_title(f'최종 배분 (RS {risk_score:.1f}, {tier_name})', fontsize=11)

    fig.text(0.5, -0.02, DISCLAIMER, ha='center', fontsize=7, color='gray', style='italic')
    plt.tight_layout()
    path = FIG_DIR / 'a1_cal_flow.png'
    plt.savefig(path, bbox_inches='tight')
    plt.show()
    print(f"  저장: {path.name}")
    return str(path)


# ══════════════════════════════════════════════════════════════
# 8-A2: Risk Score 하위변수 기여 분해 (워터폴)
# ══════════════════════════════════════════════════════════════
def plot_a2_waterfall(sub_scores: dict) -> str:
    weights = {'나이': 0.15, '은퇴기간': 0.20, '직업': 0.15,
               '자금': 0.20, '가족': 0.15, '라이프': 0.15}
    BASE = 5.0
    deltas = {k: weights[k] * (sub_scores[k] - BASE) for k in weights}
    total  = BASE + sum(deltas.values())

    keys   = list(deltas.keys())
    vals   = list(deltas.values())
    colors = ['#e15759' if v >= 0 else '#4e79a7' for v in vals]

    fig, ax = plt.subplots(figsize=(10, 5))

    # 워터폴: 누적 기준값
    running = BASE
    bar_bottoms, bar_heights = [], []
    for v in vals:
        bar_bottoms.append(running if v >= 0 else running + v)
        bar_heights.append(abs(v))
        running += v

    x = np.arange(len(keys) + 2)

    # 기준값 막대
    ax.bar(0, BASE, color='#aaaaaa', alpha=0.7, width=0.6, label='기준(5점)')
    ax.text(0, BASE + 0.05, f'{BASE:.1f}', ha='center', va='bottom', fontsize=9)

    # 각 변수 기여
    for i, (k, v, bot, h, c) in enumerate(zip(keys, vals, bar_bottoms, bar_heights, colors)):
        ax.bar(i + 1, h, bottom=bot, color=c, alpha=0.8, width=0.6)
        sign = '+' if v >= 0 else ''
        ax.text(i + 1, bot + h + 0.05 if v >= 0 else bot - 0.12,
                f'{sign}{v:.2f}', ha='center', va='bottom', fontsize=8.5)

    # 최종 합계 막대
    ax.bar(len(keys) + 1, total, color='#59a14f', alpha=0.8, width=0.6, label='최종 Risk Score')
    ax.text(len(keys) + 1, total + 0.05, f'{total:.1f}', ha='center',
            va='bottom', fontsize=10, fontweight='bold', color='#59a14f')

    # 연결선
    running = BASE
    for i, v in enumerate(vals):
        ax.plot([i + 0.3, i + 0.7], [running, running], 'k--', lw=0.7, alpha=0.4)
        running += v

    ax.set_xticks(range(len(keys) + 2))
    ax.set_xticklabels(['기준\n(5점)'] + [f'{k}\n({sub_scores[k]:.0f}점)' for k in keys]
                       + ['최종\nRisk Score'], fontsize=9)
    ax.set_ylabel('Risk Score 기여')
    ax.set_title('[8-A2] Risk Score 하위변수 기여 분해')
    ax.axhline(total, ls=':', color='#59a14f', lw=1, alpha=0.5)
    ax.grid(axis='y', alpha=0.3)

    # 범례
    ax.legend(handles=[
        mpatches.Patch(color='#e15759', alpha=0.8, label='위험 성향 ↑ (점수 상향)'),
        mpatches.Patch(color='#4e79a7', alpha=0.8, label='안전 성향 ↑ (점수 하향)'),
    ], fontsize=8, loc='upper left')

    fig.text(0.5, -0.02, DISCLAIMER, ha='center', fontsize=7, color='gray', style='italic')
    plt.tight_layout()
    path = FIG_DIR / 'a2_risk_waterfall.png'
    plt.savefig(path, bbox_inches='tight')
    plt.show()
    print(f"  저장: {path.name}")
    return str(path)


# ══════════════════════════════════════════════════════════════
# 8-A3: Big Five 라이프스타일 경로
# ══════════════════════════════════════════════════════════════
def plot_a3_lifestyle_path(big5: dict | None, lifestyle_score: int) -> str:
    """
    big5: {'openness': 1~5, 'conscientiousness': 1~5, 'stability': 1~5}
          None이면 파이프라인 미완성 안내만 표시
    lifestyle_score: 최종 라이프스타일 등급 (1~5)
    """
    fig, ax = plt.subplots(figsize=(11, 5))
    ax.axis('off')
    ax.set_xlim(0, 12); ax.set_ylim(0, 6)
    ax.set_title('[8-A3] 라이프스타일 → 투자성향 점수 연결 경로', fontsize=11, pad=10)

    STEPS = [
        (1.2, 3.0, '라이프스타일\n문장 입력'),
        (3.2, 3.0, 'ko-sroberta\n임베딩'),
        (5.2, 3.0, 'KMeans(500)\n클러스터링'),
        (7.2, 3.0, 'GPT 점수화\n(Big Five)'),
        (9.2, 3.0, 'z-score\n→ 가중합'),
        (11.0, 3.0, f'라이프스타일\n점수: {lifestyle_score}등급'),
    ]
    box_colors = ['#dde8f0','#dde8f0','#dde8f0','#dde8f0','#dde8f0','#d4edda']
    for (x, y, txt), c in zip(STEPS, box_colors):
        ax.add_patch(plt.Rectangle((x-0.95, y-0.8), 1.9, 1.6,
                                   facecolor=c, edgecolor='#888', lw=1.2, zorder=2))
        ax.text(x, y, txt, ha='center', va='center', fontsize=8.5, zorder=3)

    for i in range(len(STEPS) - 1):
        x1, x2 = STEPS[i][0] + 0.95, STEPS[i+1][0] - 0.95
        ax.annotate('', xy=(x2, 3.0), xytext=(x1, 3.0),
                    arrowprops=dict(arrowstyle='->', lw=1.3, color='#555'), zorder=4)

    # Big Five 점수 표시
    if big5:
        score_txt = (f"개방성(Openness): {big5['openness']}/5   "
                     f"계획성(Conscientiousness): {big5['conscientiousness']}/5   "
                     f"안정선호(Stability): {big5['stability']}/5")
        # 가중합 수식
        z_open  = big5['openness']  - 3
        z_cons  = big5['conscientiousness'] - 3
        z_stab  = big5['stability'] - 3
        raw = 0.45 * z_open - 0.45 * z_stab + 0.10 * z_cons
        formula = f"risk = 0.45×open_z({z_open:+.0f}) - 0.45×stab_z({-z_stab:+.0f}) + 0.10×cons_z({z_cons:+.0f}) = {raw:+.2f}"

        ax.text(6, 1.5, score_txt, ha='center', fontsize=9,
                bbox=dict(boxstyle='round', facecolor='#fffbe6', edgecolor='#ccc'))
        ax.text(6, 0.7, formula, ha='center', fontsize=8.5, color='#555',
                family='monospace')
    else:
        ax.text(6, 1.1,
                '※ Big Five 점수 파이프라인 미연동 — 설문 텍스트 처리 후 자동 산출',
                ha='center', fontsize=9, color='#888', style='italic')

    TIER_LABELS = {1:'안전선호', 2:'안정-중립', 3:'중립형', 4:'중립-성장', 5:'성장-공격'}
    ax.text(11.0, 1.7, f'→ {TIER_LABELS.get(lifestyle_score, "")}',
            ha='center', fontsize=9, color='#2d6a4f', fontweight='bold')

    fig.text(0.5, -0.01, DISCLAIMER, ha='center', fontsize=7, color='gray', style='italic')
    plt.tight_layout()
    path = FIG_DIR / 'a3_lifestyle_path.png'
    plt.savefig(path, bbox_inches='tight')
    plt.show()
    print(f"  저장: {path.name}")
    return str(path)


# ══════════════════════════════════════════════════════════════
# 8-A4: 손실 감내도 시각화
# ══════════════════════════════════════════════════════════════
def plot_a4_loss_gauge(
    current_balance: float,
    annual_salary: float,
    risk_score: float,
    mdd: float = MDD_CON,
) -> str:
    w_risky = score_to_w_risky(risk_score)
    # CAL 적용 후 실질 MDD = w_risky × Sortino-max MDD (무위험은 손실 없음)
    cal_mdd            = mdd * w_risky
    expected_loss_krw  = current_balance * abs(cal_mdd)
    monthly_contrib    = annual_salary / 12
    loss_vs_months     = expected_loss_krw / monthly_contrib

    fig, axes = plt.subplots(1, 2, figsize=(12, 5))

    # ─── 왼쪽: MDD 비율 게이지 ───
    ax = axes[0]
    categories = ['원리금보장\n(0%)', f'참고 포트폴리오\n(RS {risk_score:.1f})\n{cal_mdd*100:.1f}%',
                  'Sortino-max\n100%\n{:.1f}%'.format(mdd*100)]
    mdd_pcts   = [0.0, abs(cal_mdd) * 100, abs(mdd) * 100]
    bar_colors = ['#76b7b2', '#f28e2b', '#e15759']
    bars = ax.barh(categories, mdd_pcts, color=bar_colors, alpha=0.8, height=0.5)
    ax.bar_label(bars, fmt='%.1f%%', padding=4, fontsize=10)
    ax.set_xlabel('역사적 최대 낙폭 (%)')
    ax.set_title('[8-A4] 역사적 MDD 비교')
    ax.set_xlim(0, abs(mdd) * 115)
    ax.grid(axis='x', alpha=0.3)

    # ─── 오른쪽: 금액 환산 ───
    ax2 = axes[1]
    ax2.axis('off')
    ax2.set_xlim(0, 10); ax2.set_ylim(0, 8)
    ax2.set_title('[8-A4] 최대 예상 손실 금액', fontsize=11)

    info_lines = [
        ('현재 적립금',           f'{current_balance/1e4:.1f}억원'),
        ('적용 MDD',              f'{cal_mdd*100:.1f}% (w_risky {w_risky*100:.0f}% 적용)'),
        ('최대 예상 평가손실',     f'{expected_loss_krw/1e4:.1f}억원'),
        ('월 기여금 대비',         f'약 {loss_vs_months:.1f}개월치'),
    ]
    for i, (label, val) in enumerate(info_lines):
        y = 6.5 - i * 1.4
        ax2.add_patch(plt.Rectangle((0.5, y - 0.5), 9, 1.1,
                                    facecolor='#f8f9fa', edgecolor='#dee2e6', lw=1))
        ax2.text(1.2, y + 0.05, label, va='center', fontsize=10, color='#555')
        ax2.text(8.5, y + 0.05, val,   va='center', fontsize=11,
                 fontweight='bold', ha='right',
                 color='#e15759' if '손실' in label else '#333')

    ax2.text(5, 0.4,
             '이 금액은 역사적 최악 시나리오 기준이며,\n실제 손실은 이보다 크거나 작을 수 있습니다.',
             ha='center', fontsize=8, color='#888', style='italic')

    fig.text(0.5, -0.02, DISCLAIMER, ha='center', fontsize=7, color='gray', style='italic')
    plt.tight_layout()
    path = FIG_DIR / 'a4_loss_gauge.png'
    plt.savefig(path, bbox_inches='tight')
    plt.show()
    print(f"  저장: {path.name}")
    return str(path)


# ══════════════════════════════════════════════════════════════
# 8-A5: 내재 λ 성향 지표
# ══════════════════════════════════════════════════════════════
def plot_a5_lambda_gauge(risk_score: float) -> str:
    LAMBDA_MARKET = 3.0
    w_risky = score_to_w_risky(risk_score)

    # 해당 Risk Score의 λ 분포 (역사적)
    sub = lam_df[lam_df['risk_score'].apply(
        lambda x: abs(x - risk_score) < 0.1
    )]['lambda_implied'].dropna()

    # 가장 가까운 데모 Risk Score 사용
    demo_scores = lam_df['risk_score'].unique()
    nearest_rs  = demo_scores[np.argmin(np.abs(demo_scores - risk_score))]
    sub = lam_df[lam_df['risk_score'] == nearest_rs]['lambda_implied'].dropna()

    lam_median = float(sub.median())
    lam_mean   = float(sub.mean())

    # 전체 RS별 중앙값 λ (정규화 기준)
    lam_by_rs  = (lam_df.groupby('risk_score')['lambda_implied']
                  .median().sort_index())

    fig, axes = plt.subplots(1, 2, figsize=(12, 5))

    # ─── 왼쪽: RS별 λ 중앙값 바 차트 ───
    ax = axes[0]
    rs_list = lam_by_rs.index.tolist()
    lam_list = lam_by_rs.values.tolist()
    bar_colors_rs = ['#e15759' if rs == nearest_rs else '#aec7e8' for rs in rs_list]
    bars = ax.bar([f'RS\n{rs}' for rs in rs_list], lam_list,
                  color=bar_colors_rs, alpha=0.85, width=0.55)
    ax.axhline(LAMBDA_MARKET, ls='--', color='#555', lw=1.5,
               label=f'λ_market = {LAMBDA_MARKET} (BL 기준)')
    ax.bar_label(bars, fmt='%.2f', padding=3, fontsize=8.5)
    ax.set_ylabel('λ_implied (중앙값)')
    ax.set_title('[8-A5] Risk Score별 내재 위험회피계수')
    ax.legend(fontsize=9)
    ax.grid(axis='y', alpha=0.3)

    # ─── 오른쪽: 해당 투자자 성향 요약 ───
    ax2 = axes[1]
    ax2.axis('off')
    ax2.set_xlim(0, 10); ax2.set_ylim(0, 8)
    ax2.set_title(f'RS {risk_score:.1f} 투자자 위험회피 프로파일', fontsize=11)

    conserv_vs_neutral = lam_median / lam_by_rs.get(5.0, lam_by_rs.iloc[len(lam_by_rs)//2])
    direction = '보수적' if lam_median > LAMBDA_MARKET else '공격적'
    direction_color = '#4e79a7' if lam_median > LAMBDA_MARKET else '#e15759'

    info = [
        ('Risk Score',          f'{risk_score:.1f}점'),
        ('위험자산 비중 (w_risky)', f'{w_risky*100:.0f}%'),
        ('λ_implied (중앙값)',   f'{lam_median:.3f}'),
        ('λ_market 기준',        f'{LAMBDA_MARKET:.1f}'),
        ('시장 대비 성향',       direction),
    ]
    for i, (label, val) in enumerate(info):
        y = 7.0 - i * 1.3
        ax2.add_patch(plt.Rectangle((0.5, y-0.5), 9, 1.0,
                                    facecolor='#f8f9fa', edgecolor='#dee2e6', lw=1))
        ax2.text(1.2, y, label, va='center', fontsize=10, color='#555')
        color = direction_color if label == '시장 대비 성향' else '#333'
        fw    = 'bold' if label == '시장 대비 성향' else 'normal'
        ax2.text(8.8, y, val, va='center', fontsize=11, ha='right',
                 color=color, fontweight=fw)

    ax2.text(5, 0.5,
             'λ_implied: 해당 w_risky 선택에 내재된 위험회피 수준\n'
             '(BL 기대수익 / 하방분산 기반 역산, 중앙값 기준)',
             ha='center', fontsize=8, color='#888', style='italic')

    fig.text(0.5, -0.02, DISCLAIMER, ha='center', fontsize=7, color='gray', style='italic')
    plt.tight_layout()
    path = FIG_DIR / 'a5_lambda_gauge.png'
    plt.savefig(path, bbox_inches='tight')
    plt.show()
    print(f"  저장: {path.name}")
    return str(path)


# ══════════════════════════════════════════════════════════════
# 8-A6: MVP vs Sortino-max 비교
# ══════════════════════════════════════════════════════════════
def plot_a6_mvp_vs_sortino(risk_score: float) -> str:
    w_risky = score_to_w_risky(risk_score)

    # CAL 적용 후 누적 수익률 (w_risky 스케일)
    cal_cum_con = (cum_con - 1) * w_risky          # 근사: 무위험 0%
    cal_cum_mvp = (cum_mvp - 1) * w_risky

    cal_mdd_con = MDD_CON * w_risky
    cal_mdd_mvp = MDD_MVP * w_risky
    cal_ret_con = ANN_RET_CON * w_risky
    cal_ret_mvp = ANN_RET_MVP * w_risky

    fig, axes = plt.subplots(1, 3, figsize=(14, 5))

    # ─── 누적 수익률 시계열 ───
    ax = axes[0]
    ax.plot(cal_cum_con.index, cal_cum_con.values * 100, color='#e15759',
            lw=2, label=f'Sortino-max (w={w_risky*100:.0f}%)')
    ax.plot(cal_cum_mvp.index, cal_cum_mvp.values * 100, color='#4e79a7',
            lw=2, ls='--', label=f'MVP (w={w_risky*100:.0f}%)')
    ax.axhline(0, color='gray', lw=0.8)
    ax.set_ylabel('누적 수익률 (%)')
    ax.set_title('누적 수익률 비교')
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)

    # ─── 성과 지표 바 차트 ───
    ax2 = axes[1]
    metrics = ['연환산\n수익률(%)', '역사적\nMDD(%)', '평균\n소르티노']
    con_vals = [cal_ret_con * 100, cal_mdd_con * 100, float(perf_con['sortino'].mean())]
    mvp_vals = [cal_ret_mvp * 100, cal_mdd_mvp * 100, float(perf_mvp['sortino'].mean())]

    x = np.arange(len(metrics))
    w = 0.3
    ax2.bar(x - w/2, con_vals, w, label='Sortino-max', color='#e15759', alpha=0.8)
    ax2.bar(x + w/2, mvp_vals, w, label='MVP',          color='#4e79a7', alpha=0.8)
    ax2.set_xticks(x); ax2.set_xticklabels(metrics, fontsize=9)
    ax2.set_title('성과 지표 비교')
    ax2.legend(fontsize=8)
    ax2.grid(axis='y', alpha=0.3)
    for bar in ax2.patches:
        v = bar.get_height()
        ax2.text(bar.get_x() + bar.get_width()/2, v + (0.2 if v >= 0 else -0.8),
                 f'{v:.1f}', ha='center', fontsize=8)

    # ─── 성향별 추천 요약 ───
    ax3 = axes[2]
    ax3.axis('off')
    ax3.set_xlim(0, 10); ax3.set_ylim(0, 8)
    ax3.set_title(f'RS {risk_score:.1f} 전략 권고', fontsize=11)

    ret_diff  = (cal_ret_con - cal_ret_mvp) * 100
    mdd_diff  = (cal_mdd_mvp - cal_mdd_con) * 100   # 양수면 MVP가 MDD 낮음
    recommend = 'Sortino-max' if risk_score >= 5 else 'MVP'
    rec_color = '#e15759' if recommend == 'Sortino-max' else '#4e79a7'

    rows = [
        ('수익률 우위', f'Sortino-max +{ret_diff:.1f}%p', '#e15759'),
        ('MDD 개선',   f'MVP {mdd_diff:.1f}%p 낮음',     '#4e79a7'),
        ('권고 전략',  recommend,                         rec_color),
    ]
    for i, (label, val, color) in enumerate(rows):
        y = 6.0 - i * 1.8
        ax3.add_patch(plt.Rectangle((0.5, y-0.6), 9, 1.3,
                                    facecolor='#f8f9fa', edgecolor='#dee2e6', lw=1))
        ax3.text(1.2, y, label, va='center', fontsize=10, color='#555')
        ax3.text(8.8, y, val, va='center', fontsize=11, ha='right',
                 color=color, fontweight='bold')

    reason = ('수익률 추구형 — MDD 감수 가능' if risk_score >= 5
              else '안정추구형 — MDD 최소화 우선')
    ax3.text(5, 1.2, reason, ha='center', fontsize=9, color='#555', style='italic')

    fig.text(0.5, -0.02, DISCLAIMER, ha='center', fontsize=7, color='gray', style='italic')
    plt.tight_layout()
    path = FIG_DIR / 'a6_mvp_vs_sortino.png'
    plt.savefig(path, bbox_inches='tight')
    plt.show()
    print(f"  저장: {path.name}")
    return str(path)


# ══════════════════════════════════════════════════════════════
# 전체 실행 — 데모 투자자 프로파일
# ══════════════════════════════════════════════════════════════
if __name__ == '__main__':
    # ── 데모 투자자 (외생변수) ──
    USER = dict(
        risk_score      = 7.2,       # 설문 합산 결과
        sub_scores      = {          # 각 하위변수 점수 (1~10)
            '나이':    7.0,   # 35세 → 젊을수록 높음
            '은퇴기간': 9.0,   # 30년
            '직업':    6.0,   # 안정적 직군
            '자금':    6.0,   # 여유 있음
            '가족':    5.0,   # 배우자+자녀 있음
            '라이프':  8.0,   # 개방적 라이프스타일
        },
        big5            = {          # Big Five 점수 (1~5)
            'openness':          3,
            'conscientiousness': 4,
            'stability':         4,
        },
        lifestyle_score = 4,         # 라이프스타일 등급 (1~5)
        current_balance = 10000,     # 만원 (1억)
        annual_salary   = 6000,      # 만원 (6천만)
        years_to_retire = 25,        # 년
    )

    print("=" * 60)
    print(f"[ Step 8-A ] 데모 투자자 XAI 생성")
    print(f"  Risk Score  : {USER['risk_score']}")
    print(f"  적립금      : {USER['current_balance']/1e4:.1f}억")
    print(f"  연봉        : {USER['annual_salary']/1e4:.1f}억")
    print(f"  은퇴까지    : {USER['years_to_retire']}년")
    print("=" * 60)

    print("\n▶ 8-A0 기회비용 시뮬레이션")
    plot_a0_opportunity_cost(
        USER['current_balance'], USER['annual_salary'],
        USER['years_to_retire'], USER['risk_score']
    )

    print("\n▶ 8-A1 Risk Score → CAL 흐름")
    plot_a1_cal_flow(USER['risk_score'])

    print("\n▶ 8-A2 하위변수 기여 분해")
    plot_a2_waterfall(USER['sub_scores'])

    print("\n▶ 8-A3 라이프스타일 경로")
    plot_a3_lifestyle_path(USER['big5'], USER['lifestyle_score'])

    print("\n▶ 8-A4 손실 감내도")
    plot_a4_loss_gauge(
        USER['current_balance'], USER['annual_salary'], USER['risk_score']
    )

    print("\n▶ 8-A5 내재 λ 성향 지표")
    plot_a5_lambda_gauge(USER['risk_score'])

    print("\n▶ 8-A6 MVP vs Sortino-max")
    plot_a6_mvp_vs_sortino(USER['risk_score'])

    print(f"\n[완료] 그림 저장 위치: {FIG_DIR}")
