"""
ETF 포트폴리오 엔진 — 위기수용정도(Risk Score) 기반 포트폴리오 산출 + XAI

사용법:
    from portfolio_engine import PortfolioEngine

    engine = PortfolioEngine()
    result = engine.get_portfolio(
        risk_score=7.2,
        query_date="2024-10-01",
        user_info={
            "current_balance": 100_000_000,   # 현재 적립금 (원)
            "annual_salary":    48_000_000,   # 연봉 (원)
            "retirement_years": 25,           # 은퇴까지 남은 기간 (년)
            "sub_scores": {                   # 선택 — 있을 때만 A2 워터폴 산출
                "나이": 8, "은퇴기간": 8, "직업": 6,
                "자금여력": 7, "가족": 5, "라이프스타일": 7
            },
        }
    )

반환값:
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
            "layer_a": { ... },          # 사용자 대면 설명
            "layer_b": { ... },          # 포트폴리오 내부 분석
        }
    }

⚠️ 이 시스템의 모든 출력은 투자 판단의 참고 정보이며,
   의사결정권은 전적으로 투자자에게 있습니다.
"""

from __future__ import annotations

import warnings
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Optional
from functools import cached_property

warnings.filterwarnings('ignore')

# ─────────────────────────────────────────────
# 경로 설정 (이 파일의 위치 기준)
# ─────────────────────────────────────────────
_HERE     = Path(__file__).parent                          # src/
_ROOT     = _HERE.parent                                   # 퇴직연금 _XAI/
_IN       = _ROOT / 'data'
_S5       = _ROOT / 'results' / 'step5'

# ─────────────────────────────────────────────
# 상수
# ─────────────────────────────────────────────
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
RISKFREE_SLOT = '무위험(현금성)'

US_SLOTS = {'미국주식_SP500', '미국주식_나스닥'}
KR_SLOTS = {'국내주식_코스피', '국내주식_코스닥'}
EM_SLOTS = {'신흥국_인도', '신흥국_중국'}

REBAL_DAYS = 63   # 분기 거래일 수
WIN_DAYS   = 1260 # 5년 거래일 수
LAMBDA_MKT = 3.0  # 시장 중립 위험회피계수 (Step 5 재실행 값)
LEGAL_CAP  = 0.70 # DC/IRP 위험자산 법적 상한

# Risk Score → (위험군, w_risky) 룩업 테이블
_RISK_TABLE = [
    (0,  2,  '초보수형', 0.00),
    (2,  4,  '보수형',   0.20),
    (4,  6,  '중립형',   0.40),
    (6,  8,  '성장형',   0.60),
    (8,  10, '공격형',   0.70),
]

# Risk Score 하위변수 가중치 (8-A2 워터폴용)
_SUB_WEIGHTS = {
    '나이': 0.15, '은퇴기간': 0.20, '직업': 0.15,
    '자금여력': 0.20, '가족': 0.15, '라이프스타일': 0.15,
}


def _lookup_risk(score: float) -> tuple[str, float]:
    """Risk Score → (위험군, w_risky)"""
    score = max(0.0, min(10.0, float(score)))
    for lo, hi, group, w in _RISK_TABLE:
        if lo <= score <= hi:
            return group, w
    return '중립형', 0.40


# ─────────────────────────────────────────────
# 엔진 클래스
# ─────────────────────────────────────────────
class PortfolioEngine:
    """
    위기수용정도(Risk Score) 기반 ETF 포트폴리오 산출 + XAI 설명 엔진.

    Parameters
    ----------
    data_dir : Path | str, optional
        데이터 루트 디렉터리 (기본값: notebooks/ 디렉터리 자동 탐색)
    """

    def __init__(self, data_dir: Optional[Path | str] = None):
        if data_dir is not None:
            data_dir = Path(data_dir)
            self._in = data_dir / '입력_데이터'
            self._s5 = data_dir / 'step5_지역제약포트폴리오_최종'
        else:
            self._in = _IN
            self._s5 = _S5
        self._validate_paths()

    def _validate_paths(self):
        required = [
            self._in / 'index_returns.parquet',
            self._in / 'slot_returns.parquet',
            self._in / 'mar_series.parquet',
            self._in / 'year_end_best.csv',
            self._s5 / 'portfolio_weights_constrained.parquet',
            self._s5 / 'portfolio_performance_constrained.parquet',
        ]
        missing = [str(p) for p in required if not p.exists()]
        if missing:
            raise FileNotFoundError(
                "필수 데이터 파일 없음:\n" + "\n".join(f"  {m}" for m in missing)
            )

    # ── 지연 로딩 (첫 호출 시 파일 읽기) ─────────────
    @cached_property
    def _weights(self) -> pd.DataFrame:
        return pd.read_parquet(self._s5 / 'portfolio_weights_constrained.parquet')

    @cached_property
    def _weights_mvp(self) -> Optional[pd.DataFrame]:
        p = self._s5 / 'portfolio_weights_mvp.parquet'
        return pd.read_parquet(p) if p.exists() else None

    @cached_property
    def _perf(self) -> pd.DataFrame:
        return pd.read_parquet(self._s5 / 'portfolio_performance_constrained.parquet')

    @cached_property
    def _perf_mvp(self) -> Optional[pd.DataFrame]:
        p = self._s5 / 'portfolio_performance_mvp.parquet'
        return pd.read_parquet(p) if p.exists() else None

    @cached_property
    def _sigma_hist(self) -> Optional[pd.DataFrame]:
        p = self._s5 / 'sigma_down_history.parquet'
        return pd.read_parquet(p) if p.exists() else None

    @cached_property
    def _pi_hist(self) -> Optional[pd.DataFrame]:
        p = self._s5 / 'pi_history.parquet'
        return pd.read_parquet(p) if p.exists() else None

    @cached_property
    def _bind_hist(self) -> Optional[pd.DataFrame]:
        p = self._s5 / 'binding_history.parquet'
        return pd.read_parquet(p) if p.exists() else None

    @cached_property
    def _slot_rets(self) -> pd.DataFrame:
        return pd.read_parquet(self._in / 'slot_returns.parquet').reindex(columns=SLOTS)

    @cached_property
    def _mar(self) -> pd.Series:
        """일별 MAR (소수, 일 단위)."""
        all_dates  = self._weights.index.union(self._slot_rets.index)
        mar_monthly = pd.read_parquet(self._in / 'mar_series.parquet')['mar_annual']
        mar_daily   = (mar_monthly.resample('D').ffill()
                       .reindex(all_dates).ffill().bfill()) / 100
        return mar_daily / 252

    @cached_property
    def _yeb(self) -> pd.DataFrame:
        return pd.read_csv(self._in / 'year_end_best.csv')

    # ── ETF 매핑 ─────────────────────────────
    def _get_etf_map(self, query_date: pd.Timestamp) -> dict[str, str]:
        """슬롯 → ETF 명칭 (query_date 기준 전년도 ETF 선정 기준)."""
        ref_year = query_date.year - 1
        subset = self._yeb[self._yeb['year'] == ref_year][['slot', 'name', 'ticker']]
        if subset.empty:
            ref_year = self._yeb['year'].max()
            subset = self._yeb[self._yeb['year'] == ref_year][['slot', 'name', 'ticker']]
        return dict(zip(subset['slot'], subset['name'] + ' (' + subset['ticker'].astype(str) + ')'))

    # ── 핵심 공개 메서드 ──────────────────────
    def get_portfolio(
        self,
        risk_score: float,
        query_date: str,
        user_info: Optional[dict] = None,
    ) -> dict:
        """
        위기수용정도 스코어와 조회 시점을 입력받아 최종 포트폴리오 + XAI를 반환.

        Parameters
        ----------
        risk_score : float
            위기수용정도 스코어 (1~10). 다른 팀에서 산출된 값.
        query_date : str
            포트폴리오 조회 기준 시점 ("YYYY-MM-DD").
        user_info : dict, optional
            XAI 상세화를 위한 추가 정보:
              current_balance  : 현재 적립금 (원)
              annual_salary    : 연봉 (원)
              retirement_years : 은퇴까지 남은 기간 (년)
              sub_scores       : 하위 변수별 점수 (1~10) → A2 워터폴
        """
        qdate = pd.Timestamp(query_date)

        # ① 기준 리밸런싱 시점 선택 (query_date 이전 가장 최근)
        rebal_dates = self._weights.index[self._weights.index <= qdate]
        if rebal_dates.empty:
            rebal_dates = self._weights.index
        rebal_date = rebal_dates[-1]

        # ② 슬롯 비중 로드
        risky_slot_w = self._weights.loc[rebal_date]

        # ③ Risk Score → 위험군 + w_risky
        risk_group, w_risky = _lookup_risk(risk_score)

        # ④ CAL 적용: 최종 슬롯 비중
        final_slot_w = self._apply_cal(risky_slot_w, w_risky)

        # ⑤ 슬롯 → ETF 이름 매핑
        etf_map  = self._get_etf_map(rebal_date)
        portfolio = {
            etf_map.get(s, s): float(final_slot_w[s])
            for s in SLOTS if float(final_slot_w[s]) > 1e-6
        }

        # ⑥ XAI 산출
        xai = self._compute_xai(
            risk_score=risk_score,
            risk_group=risk_group,
            w_risky=w_risky,
            risky_slot_w=risky_slot_w,
            rebal_date=rebal_date,
            user_info=user_info or {},
        )

        return {
            'rebal_date':        rebal_date.strftime('%Y-%m-%d'),
            'risk_group':        risk_group,
            'w_risky':           round(w_risky, 4),
            'portfolio':         portfolio,
            'portfolio_by_slot': {s: round(float(final_slot_w[s]), 6)
                                  for s in SLOTS},
            'xai':               xai,
        }

    # ── CAL 적용 ─────────────────────────────
    @staticmethod
    def _apply_cal(risky_slot_w: pd.Series, w_risky: float) -> pd.Series:
        """
        최종 슬롯 비중 = w_risky × 위험자산 포트폴리오 + (1 - w_risky) → 무위험 슬롯.
        무위험 슬롯의 최종 비중 = w_risky × rf_slot_w + (1 - w_risky)
        """
        final_w = risky_slot_w.copy() * w_risky
        final_w[RISKFREE_SLOT] = (risky_slot_w[RISKFREE_SLOT] * w_risky
                                   + (1.0 - w_risky))
        return final_w

    # ── XAI 통합 ─────────────────────────────
    def _compute_xai(
        self,
        risk_score: float,
        risk_group: str,
        w_risky: float,
        risky_slot_w: pd.Series,
        rebal_date: pd.Timestamp,
        user_info: dict,
    ) -> dict:

        # 해당 분기 Σ_down, Π, MAR 복원
        sigma_down_q, pi_q, valid_cols_q = self._get_quarterly_params(rebal_date)

        perf_q = self._perf.loc[rebal_date] if rebal_date in self._perf.index else None
        mar_q_scalar = float(
            self._mar.reindex(pd.date_range(rebal_date, periods=REBAL_DAYS, freq='B'),
                              method='ffill').mean()
        ) * REBAL_DAYS if hasattr(self._mar, 'reindex') else 0.0

        layer_a = self._layer_a(
            risk_score, risk_group, w_risky, risky_slot_w,
            sigma_down_q, pi_q, valid_cols_q, mar_q_scalar, perf_q, user_info
        )
        layer_b = self._layer_b(rebal_date, risky_slot_w, sigma_down_q,
                                pi_q, valid_cols_q)

        return {'layer_a': layer_a, 'layer_b': layer_b}

    def _get_quarterly_params(
        self, rebal_date: pd.Timestamp
    ) -> tuple[Optional[np.ndarray], Optional[np.ndarray], list]:
        """해당 리밸런싱 시점의 Σ_down 행렬, Π 벡터, 유효 슬롯 목록 반환."""
        if self._sigma_hist is None or rebal_date not in self._sigma_hist.index:
            return None, None, []

        sigma_row = self._sigma_hist.loc[rebal_date]
        pi_row    = self._pi_hist.loc[rebal_date] if self._pi_hist is not None else None

        # 유효 슬롯 식별 (대각선 값이 NaN이 아닌 슬롯)
        valid_cols = [s for s in SLOTS
                      if pd.notna(sigma_row.get(f"{s}__{s}", float('nan')))]

        if len(valid_cols) == 0:
            return None, None, []

        n = len(valid_cols)
        sigma_mat = np.zeros((n, n))
        for i, a in enumerate(valid_cols):
            for j, b in enumerate(valid_cols):
                sigma_mat[i, j] = float(sigma_row.get(f"{a}__{b}", 0.0) or 0.0)

        pi_vec = None
        if pi_row is not None:
            pi_vec = np.array([float(pi_row.get(s, 0.0) or 0.0) for s in valid_cols])

        return sigma_mat, pi_vec, valid_cols

    # ── Layer A: 사용자 대면 XAI ─────────────
    def _layer_a(
        self,
        risk_score, risk_group, w_risky,
        risky_slot_w, sigma_down_q, pi_q, valid_cols_q,
        mar_q_scalar, perf_q, user_info,
    ) -> dict:
        result = {}

        # A1: CAL 흐름 설명
        result['a1_cal_flow'] = self._a1_cal_flow(
            risk_score, risk_group, w_risky)

        # A2: 하위변수 기여 분해 (sub_scores가 있을 때만)
        if 'sub_scores' in user_info:
            result['a2_risk_breakdown'] = self._a2_risk_breakdown(
                user_info['sub_scores'], risk_score)

        # A4: 손실 감내도 (적립금 있을 때)
        if 'current_balance' in user_info and perf_q is not None:
            result['a4_loss_amount'] = self._a4_loss_amount(
                user_info['current_balance'],
                user_info.get('annual_salary'),
                float(perf_q.get('down_risk_pct', 0)),
                w_risky,
            )

        # A5: 내재 λ 역산
        if sigma_down_q is not None and pi_q is not None and len(valid_cols_q) > 0:
            result['a5_implied_lambda'] = self._a5_implied_lambda(
                risky_slot_w, sigma_down_q, pi_q, valid_cols_q,
                w_risky, mar_q_scalar
            )

        # A6: MVP vs Sortino-max 비교
        result['a6_mvp_vs_sortino'] = self._a6_strategy_comparison(risk_group)

        # A0: 기회비용 시뮬레이션 (적립금 + 연봉 + 은퇴기간 있을 때)
        has_a0 = all(k in user_info for k in ('current_balance', 'annual_salary', 'retirement_years'))
        if has_a0 and perf_q is not None:
            result['a0_opportunity_cost'] = self._a0_opportunity_cost(
                user_info['current_balance'],
                user_info['annual_salary'],
                user_info['retirement_years'],
                float(perf_q.get('mar_annual_pct', 3.0)) / 100,
                self._perf['cum_ret_pct'].mean() / 100 * 4,  # 분기 평균 → 연율
            )

        return result

    def _a1_cal_flow(self, risk_score: float, risk_group: str, w_risky: float) -> dict:
        """Risk Score → 위험군 → w_risky → 최종 배분 흐름 설명."""
        w_safe = round(1.0 - w_risky, 4)
        lines = [
            f"Risk Score {risk_score:.1f}점 → {risk_group}",
            f"참고 위험자산 비중: {w_risky*100:.0f}%",
            f"참고 무위험자산 비중: {w_safe*100:.0f}%",
            f"DC/IRP 법적 위험자산 상한: {LEGAL_CAP*100:.0f}%",
        ]
        return {
            'risk_score':    round(risk_score, 2),
            'risk_group':    risk_group,
            'w_risky':       w_risky,
            'w_safe':        w_safe,
            'legal_max':     LEGAL_CAP,
            'score_table':   [
                {'range': '1~2점', 'group': '초보수형', 'w_risky': 0.00},
                {'range': '2~4점', 'group': '보수형',   'w_risky': 0.20},
                {'range': '4~6점', 'group': '중립형',   'w_risky': 0.40},
                {'range': '6~8점', 'group': '성장형',   'w_risky': 0.60},
                {'range': '8~10점','group': '공격형',   'w_risky': 0.70},
            ],
            'explanation':   ' | '.join(lines),
            'disclaimer':    '역사적 시뮬레이션 결과이며 미래 수익을 보장하지 않습니다.',
        }

    def _a2_risk_breakdown(self, sub_scores: dict, total_score: float) -> dict:
        """하위변수 기여 분해 — 워터폴 차트 데이터."""
        base = 5.0   # 평균 기준점
        contributions = {
            k: round(_SUB_WEIGHTS.get(k, 0) * (sub_scores.get(k, 5.0) - base), 3)
            for k in _SUB_WEIGHTS
        }
        computed_total = base + sum(contributions.values())

        waterfall = []
        running = base
        for k, delta in contributions.items():
            waterfall.append({
                'variable':     k,
                'weight':       _SUB_WEIGHTS.get(k, 0),
                'sub_score':    sub_scores.get(k, 5.0),
                'contribution': delta,
                'cumulative':   round(running + delta, 3),
                'direction':    '상승' if delta > 0 else ('하락' if delta < 0 else '중립'),
            })
            running += delta

        return {
            'base_score':     base,
            'contributions':  contributions,
            'computed_total': round(computed_total, 2),
            'input_total':    round(total_score, 2),
            'waterfall':      waterfall,
            'weights':        _SUB_WEIGHTS,
            'note': ('sub_scores 합산 결과와 입력 risk_score 간 차이가 있으면 '
                     '다른 팀의 추가 처리(예: 정규화, 텍스트 파이프라인)가 반영된 것입니다.'),
        }

    def _a4_loss_amount(
        self, current_balance: float, annual_salary: Optional[float],
        down_risk_pct: float, w_risky: float
    ) -> dict:
        """손실 감내도 — 추상적 MDD(%)를 실제 금액으로 변환."""
        effective_risky = current_balance * w_risky
        expected_loss   = effective_risky * (down_risk_pct / 100)

        result = {
            'current_balance_krw':   current_balance,
            'effective_risky_krw':   effective_risky,
            'down_risk_pct':         down_risk_pct,
            'w_risky':               w_risky,
            'expected_loss_krw':     round(expected_loss),
            'expected_loss_display': f"{expected_loss / 1e4:.0f}만원",
            'disclaimer':            '역사적 하방위험 기준이며 미래 손실을 보장하지 않습니다.',
        }

        if annual_salary and annual_salary > 0:
            monthly = annual_salary / 12
            result['monthly_contribution_krw']    = round(monthly)
            result['loss_vs_months_contribution'] = round(expected_loss / monthly, 1)
            result['explanation'] = (
                f"참고 포트폴리오 역사적 하방위험 {down_risk_pct:.1f}% 기준, "
                f"위험자산 {w_risky*100:.0f}% 배분 시 "
                f"최대 평가손실 가능액 약 {expected_loss/1e4:.0f}만원 "
                f"(월 기여금의 약 {expected_loss/monthly:.1f}배)"
            )

        return result

    def _a5_implied_lambda(
        self, risky_slot_w: pd.Series,
        sigma_down_q: np.ndarray, pi_q: np.ndarray,
        valid_cols_q: list, w_risky: float, mar_q: float
    ) -> dict:
        """내재 위험회피계수 λ 역산 및 시장 중립 대비 포지션."""
        idx = [valid_cols_q.index(s) for s in valid_cols_q if s in risky_slot_w.index]
        w_v = np.array([float(risky_slot_w[s]) for s in valid_cols_q], dtype=float)
        w_v_norm = w_v / (w_v.sum() + 1e-10)

        sigma_down_p = float(np.sqrt(max(w_v_norm @ sigma_down_q @ w_v_norm * REBAL_DAYS, 1e-12)))
        exp_ret_q    = float(w_v_norm @ pi_q) * REBAL_DAYS
        sortino_q    = (exp_ret_q - mar_q) / (sigma_down_p + 1e-10)

        if w_risky > 0 and sigma_down_p > 0:
            lambda_implied = sortino_q / (w_risky * sigma_down_p + 1e-10)
        else:
            lambda_implied = LAMBDA_MKT

        ratio = lambda_implied / LAMBDA_MKT
        if ratio < 0.85:
            position = '공격적 (시장 평균 대비 위험 추구)'
        elif ratio > 1.15:
            position = '보수적 (시장 평균 대비 위험 회피)'
        else:
            position = '중립적 (시장 평균 수준)'

        return {
            'lambda_implied':    round(lambda_implied, 3),
            'lambda_market':     LAMBDA_MKT,
            'lambda_ratio':      round(ratio, 3),
            'position':          position,
            'w_risky':           w_risky,
            'sigma_down_p':      round(sigma_down_p, 6),
            'sortino_q':         round(sortino_q, 3),
            'explanation': (
                f"선택하신 위험자산 비중({w_risky*100:.0f}%)에 내재된 위험회피계수는 "
                f"λ ≈ {lambda_implied:.2f}입니다. "
                f"시장 중립 기준(λ = {LAMBDA_MKT}) 대비 {position}."
            ),
            'disclaimer': '내재 λ는 역사적 하방위험 기반 추정값입니다.',
        }

    def _a6_strategy_comparison(self, risk_group: str) -> dict:
        """MVP vs Sortino-max 전략 비교."""
        if self._perf_mvp is None or self._perf is None:
            return {'available': False,
                    'note': 'MVP 데이터 없음 (07b_step5_rerun.py 실행 필요)'}

        def _mdd(ret_pct: pd.Series) -> float:
            cum  = (1 + ret_pct / 100).cumprod()
            peak = cum.cummax()
            return round(float(((cum - peak) / peak).min()) * 100, 2)

        def _summary(perf: pd.DataFrame) -> dict:
            rets = perf['cum_ret_pct']
            return {
                'cum_ret_pct':  round((1 + rets / 100).prod() - 1, 4) * 100,
                'mdd_pct':      _mdd(rets),
                'avg_sortino':  round(perf['sortino'].mean(), 3),
            }

        sortino_stats = _summary(self._perf)
        mvp_stats     = _summary(self._perf_mvp)

        aggressive_groups = {'성장형', '공격형'}
        if risk_group in aggressive_groups:
            recommendation = (
                f"{risk_group} 성향에서는 Sortino-max 전략이 참고 대상입니다. "
                f"누적수익률 {sortino_stats['cum_ret_pct']:.1f}% (MDD {abs(sortino_stats['mdd_pct']):.1f}%)"
            )
        else:
            recommendation = (
                f"{risk_group} 성향에서는 MVP 전략도 검토할 수 있습니다. "
                f"MDD {abs(mvp_stats['mdd_pct']):.1f}% (Sortino-max 대비 "
                f"{abs(sortino_stats['mdd_pct']) - abs(mvp_stats['mdd_pct']):.1f}%p 개선)"
            )

        return {
            'sortino_max':    sortino_stats,
            'mvp':            mvp_stats,
            'recommendation': recommendation,
            'disclaimer':     '역사적 시뮬레이션 결과이며 미래 성과를 보장하지 않습니다.',
        }

    def _a0_opportunity_cost(
        self, balance: float, salary: float, years: int,
        rf_annual: float, portfolio_annual: float
    ) -> dict:
        """기회비용 시뮬레이션 — 원리금보장형 vs 참고 포트폴리오 미래 자산 비교."""
        def _fv(b, c, r, n):
            """미래가치: FV = b*(1+r)^n + c/r * ((1+r)^n - 1)"""
            if r < 1e-9:
                return b + c * n
            return b * (1 + r) ** n + (c / r) * ((1 + r) ** n - 1)

        monthly_contrib = salary / 12
        fv_rf   = _fv(balance, monthly_contrib * 12, rf_annual, years)
        fv_port = _fv(balance, monthly_contrib * 12, portfolio_annual, years)

        return {
            'years':                  years,
            'current_balance_krw':    balance,
            'annual_salary_krw':      salary,
            'rf_annual_pct':          round(rf_annual * 100, 2),
            'portfolio_annual_pct':   round(portfolio_annual * 100, 2),
            'fv_rf_krw':              round(fv_rf),
            'fv_portfolio_krw':       round(fv_port),
            'opportunity_cost_krw':   round(fv_port - fv_rf),
            'fv_rf_display':          f"{fv_rf / 1e8:.1f}억원",
            'fv_portfolio_display':   f"{fv_port / 1e8:.1f}억원",
            'opp_display':            f"{abs(fv_port - fv_rf) / 1e8:.1f}억원",
            'explanation': (
                f"현재 적립금 {balance/1e8:.1f}억원을 원리금보장형({rf_annual*100:.1f}%) 유지 시 "
                f"{years}년 후 약 {fv_rf/1e8:.1f}억원, "
                f"참고 포트폴리오({portfolio_annual*100:.1f}% 역사적 연수익률) 기준 "
                f"약 {fv_port/1e8:.1f}억원으로 차이는 약 {abs(fv_port-fv_rf)/1e8:.1f}억원입니다."
            ),
            'disclaimer': '미래 수익을 보장하지 않습니다. 과거 수익률 기반 시뮬레이션입니다.',
        }

    # ── Layer B: 포트폴리오 내부 분석 XAI ────
    def _layer_b(
        self,
        rebal_date: pd.Timestamp,
        risky_slot_w: pd.Series,
        sigma_down_q: Optional[np.ndarray],
        pi_q: Optional[np.ndarray],
        valid_cols_q: list,
    ) -> dict:
        result = {}

        # B1: MCDR (Marginal Contribution to Downside Risk)
        if sigma_down_q is not None and len(valid_cols_q) > 0:
            result['b1_mcdr'] = self._b1_mcdr(
                risky_slot_w, sigma_down_q, valid_cols_q)

        # B2: BL 내재수익률 vs MCDR 산포도
        if sigma_down_q is not None and pi_q is not None and len(valid_cols_q) > 0:
            result['b2_bl_scatter'] = self._b2_bl_scatter(
                risky_slot_w, sigma_down_q, pi_q, valid_cols_q)

        # B3: 제약 활성화 분석
        if self._bind_hist is not None:
            result['b3_constraint'] = self._b3_constraint(rebal_date)

        # B4: 성과 기여 분해
        if self._weights is not None and self._slot_rets is not None:
            result['b4_attribution'] = self._b4_attribution()

        return result

    def _b1_mcdr(
        self, risky_slot_w: pd.Series,
        sigma_down_q: np.ndarray, valid_cols_q: list
    ) -> dict:
        """MCDR — 자산별 하방위험 기여 비율."""
        w_v = np.array([float(risky_slot_w.get(s, 0.0)) for s in valid_cols_q])
        port_var = float(w_v @ sigma_down_q @ w_v)

        if port_var < 1e-12:
            return {'available': False, 'note': '포트폴리오 하방분산 = 0'}

        mcdr_raw = (sigma_down_q @ w_v) * w_v / port_var
        comparison = []
        for i, s in enumerate(valid_cols_q):
            comparison.append({
                'slot':   s,
                'weight': round(float(w_v[i]), 4),
                'mcdr':   round(float(mcdr_raw[i]), 4),
                'label':  ('과도기여' if mcdr_raw[i] > w_v[i] * 1.2
                           else ('과소기여' if mcdr_raw[i] < w_v[i] * 0.8
                                 else '균형')),
            })
        comparison.sort(key=lambda x: -x['mcdr'])

        return {
            'mcdr_by_slot':   {row['slot']: row['mcdr'] for row in comparison},
            'weights_by_slot':{row['slot']: row['weight'] for row in comparison},
            'comparison':     comparison,
            'interpretation': (
                '비중 대비 MCDR가 높은 자산은 포트폴리오 하방위험에 과도하게 기여합니다. '
                'BL 내재수익률이 이를 보상하는지 B2 산포도를 확인하세요.'
            ),
        }

    def _b2_bl_scatter(
        self, risky_slot_w: pd.Series,
        sigma_down_q: np.ndarray, pi_q: np.ndarray,
        valid_cols_q: list
    ) -> dict:
        """BL 내재수익률 vs MCDR 산포도 데이터."""
        w_v      = np.array([float(risky_slot_w.get(s, 0.0)) for s in valid_cols_q])
        port_var = float(w_v @ sigma_down_q @ w_v)

        if port_var < 1e-12:
            return {'available': False}

        mcdr_raw = (sigma_down_q @ w_v) * w_v / port_var
        points = []
        for i, s in enumerate(valid_cols_q):
            points.append({
                'slot':       s,
                'pi_annual':  round(float(pi_q[i]) * 252 * 100, 2),  # 연율(%)
                'mcdr':       round(float(mcdr_raw[i]), 4),
                'weight':     round(float(w_v[i]), 4),
                'efficient':  (pi_q[i] * 252 * 100 > 0 and mcdr_raw[i] < 0.15),
            })

        return {
            'points': points,
            'x_label': 'BL 내재수익률 (연율, %)',
            'y_label': 'MCDR (하방위험 기여율)',
            'bubble_label': '포트폴리오 비중',
            'interpretation': (
                '오른쪽 아래(고수익·저위험) 영역 자산에 높은 비중이 배분됩니다. '
                'EM 제약이 active인 분기에서는 신흥국 버블이 작아집니다.'
            ),
        }

    def _b3_constraint(self, rebal_date: pd.Timestamp) -> dict:
        """제약 활성화 이력 — 특정 분기 및 전체 통계."""
        bd = self._bind_hist

        # 전체 기간 통계
        history = bd[['us_binding', 'kr_binding', 'em_binding',
                       'us_alloc', 'kr_alloc', 'em_alloc', 'constraint_cost']].copy()
        history.index = history.index.strftime('%Y-%m-%d')

        # 해당 분기 바인딩 상태
        if rebal_date in bd.index:
            current = bd.loc[rebal_date].to_dict()
        else:
            current = {}

        return {
            'current_period':  current,
            'history':         history.reset_index().rename(columns={'index': 'date'}).to_dict('records'),
            'summary': {
                'us_binding_quarters': int(bd['us_binding'].sum()),
                'kr_binding_quarters': int(bd['kr_binding'].sum()),
                'em_binding_quarters': int(bd['em_binding'].sum()),
                'total_quarters':      len(bd),
                'avg_constraint_cost': round(float(bd['constraint_cost'].mean()), 3),
            },
            'interpretation': (
                '제약 바인딩 분기에서 소르티노가 낮아질 수 있습니다. '
                '"제약 비용 = 비제약 소르티노 - 제약 소르티노"가 양수이면 제약이 실제로 작동한 분기입니다.'
            ),
        }

    def _b4_attribution(self) -> dict:
        """성과 기여 분해 — 슬롯별 누적 수익 기여."""
        w_df    = self._weights.reindex(columns=SLOTS, fill_value=0.0)
        ret_df  = self._slot_rets.reindex(columns=SLOTS, fill_value=0.0)

        # 분기별 기여: 전기 비중 × 당기 수익 (OOS 기간 합산)
        rebal_dates = w_df.index.tolist()
        records = []

        for i, rd in enumerate(rebal_dates):
            next_rd = rebal_dates[i + 1] if i + 1 < len(rebal_dates) else None
            if next_rd is None:
                continue
            period_rets = ret_df.loc[
                (ret_df.index > rd) & (ret_df.index <= next_rd)
            ]
            if period_rets.empty:
                continue
            slot_w = w_df.loc[rd]
            for s in SLOTS:
                contrib = float(slot_w[s] * period_rets[s].fillna(0).sum())
                records.append({'date': rd, 'slot': s, 'contribution_pct': round(contrib * 100, 4)})

        if not records:
            return {'available': False}

        attr_df = pd.DataFrame(records)
        cum_by_slot = (attr_df.groupby('slot')['contribution_pct']
                       .sum().sort_values(ascending=False).round(2).to_dict())

        return {
            'cumulative_by_slot': cum_by_slot,
            'detail':             attr_df.to_dict('records'),
            'top_contributor':    max(cum_by_slot, key=cum_by_slot.get),
            'interpretation': (
                '누적 기여가 가장 큰 자산이 역사적 성과의 주요 원천입니다. '
                '음수 기여 슬롯은 손실을 발생시킨 구간이 있었음을 의미합니다.'
            ),
        }

    # ── 편의 메서드 ──────────────────────────
    def get_latest_portfolio(
        self, risk_score: float, user_info: Optional[dict] = None
    ) -> dict:
        """최신 리밸런싱 시점 기준 포트폴리오."""
        latest_date = self._weights.index[-1].strftime('%Y-%m-%d')
        return self.get_portfolio(risk_score, latest_date, user_info)

    def list_rebalancing_dates(self) -> list[str]:
        """전체 리밸런싱 시점 목록."""
        return [d.strftime('%Y-%m-%d') for d in self._weights.index]

    def performance_summary(self) -> dict:
        """포트폴리오 전체 성과 요약."""
        rets = self._perf['cum_ret_pct']
        cum  = (1 + rets / 100).cumprod()
        peak = cum.cummax()
        mdd  = float(((cum - peak) / peak).min()) * 100
        return {
            'cumulative_return_pct': round((cum.iloc[-1] - 1) * 100, 2),
            'avg_quarterly_ret_pct': round(float(rets.mean()), 2),
            'avg_sortino':           round(float(self._perf['sortino'].mean()), 3),
            'sortino_std':           round(float(self._perf['sortino'].std()), 3),
            'mdd_pct':               round(mdd, 2),
            'sortino_positive_pct':  round(float((self._perf['sortino'] > 0).mean()) * 100, 1),
            'n_rebalancing':         len(self._perf),
            'period': {
                'start': self._perf.index[0].strftime('%Y-%m-%d'),
                'end':   self._perf.index[-1].strftime('%Y-%m-%d'),
            },
            'disclaimer': '역사적 시뮬레이션 결과이며 미래 성과를 보장하지 않습니다.',
        }


# ─────────────────────────────────────────────
# 단독 실행 — 동작 확인용 예시
# ─────────────────────────────────────────────
if __name__ == '__main__':
    import json

    engine = PortfolioEngine()

    print("▶ 포트폴리오 엔진 초기화 완료")
    print(f"  리밸런싱 이력: {len(engine.list_rebalancing_dates())}개")
    print()

    result = engine.get_portfolio(
        risk_score=7.2,
        query_date='2024-10-01',
        user_info={
            'current_balance':  100_000_000,
            'annual_salary':     48_000_000,
            'retirement_years':  25,
            'sub_scores': {
                '나이': 8, '은퇴기간': 8, '직업': 6,
                '자금여력': 7, '가족': 5, '라이프스타일': 7,
            },
        }
    )

    print(f"기준 리밸런싱: {result['rebal_date']}")
    print(f"위험군: {result['risk_group']} (w_risky={result['w_risky']*100:.0f}%)")
    print()
    print("【 최종 포트폴리오 비중 】")
    for etf, w in sorted(result['portfolio'].items(), key=lambda x: -x[1]):
        print(f"  {etf:<50} {w*100:.1f}%")

    print()
    a1 = result['xai']['layer_a'].get('a1_cal_flow', {})
    print(f"【 A1 CAL 흐름 】\n  {a1.get('explanation', '')}")

    a5 = result['xai']['layer_a'].get('a5_implied_lambda', {})
    if a5:
        print(f"\n【 A5 내재 λ 】\n  {a5.get('explanation', '')}")

    b1 = result['xai']['layer_b'].get('b1_mcdr', {})
    if b1 and b1.get('comparison'):
        print("\n【 B1 MCDR — 상위 3 슬롯 】")
        for row in b1['comparison'][:3]:
            print(f"  {row['slot']:<25} 비중:{row['weight']*100:.1f}% MCDR:{row['mcdr']*100:.1f}% ({row['label']})")

    perf = engine.performance_summary()
    print(f"\n【 전체 성과 요약 】")
    print(f"  누적수익률: {perf['cumulative_return_pct']:.1f}%  MDD: {perf['mdd_pct']:.1f}%  "
          f"평균 소르티노: {perf['avg_sortino']:.3f}")
    print(f"\n  {perf['disclaimer']}")
