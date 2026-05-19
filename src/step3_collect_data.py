"""
피드백 2: 롤링 윈도우 탐색용 기초자산 지수 데이터 수집
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
출력:
  raw/index_returns.parquet   ← 슬롯별 일간 수익률
  raw/mar_series.parquet      ← 월별 정기예금 금리 (MAR)

슬롯별 데이터 소스:
  국내주식_코스피      → ^KS11            (yfinance)
  국내주식_코스닥      → ^KQ11            (yfinance)
  미국주식_SP500       → ^GSPC            (yfinance)
  미국주식_나스닥      → ^NDX             (yfinance)
  신흥국_인도          → ^NSEI            (yfinance)
  신흥국_중국          → ^HSI             (yfinance)
  국내채권_국고채단중기 → 국고채3년        (ECOS 817Y002/010200000, MD=2.8)
  국내채권_국고채장기  → 국고채30년        (ECOS 817Y002/010230000, MD=18.0)
  국내채권_회사채      → 회사채AA- 3년     (ECOS 817Y002/010300000, MD=2.7)
  국내채권_종합        → 국고채3년(50%)+10년(50%) (ECOS, MD=5.5)
  해외채권_미국국채    → ^IRX (13w T-bill) (yfinance, MD≈0.25)
  원자재_금            → GC=F              (yfinance)
  무위험(현금성)       → CD91일            (ECOS 817Y002/010502000)
  MAR                  → 정기예금6개월미만  (ECOS 121Y002/BEABAA2111, 월별)
"""

import argparse
import warnings
import numpy as np
import pandas as pd
import requests
import yfinance as yf
from pathlib import Path

warnings.filterwarnings('ignore')

# ── 날짜 인수 파싱 ──
# 기본값: 오늘 날짜. 학술제 날짜로 고정하려면:
#   python step3_collect_data.py --end 2026-06-15
parser = argparse.ArgumentParser()
parser.add_argument('--end', default=pd.Timestamp.today().strftime('%Y-%m-%d'),
                    help='데이터 수집 종료일 (YYYY-MM-DD). 기본값: 오늘')
args = parser.parse_args()

DATA_DIR = Path(__file__).parent.parent / 'data'
ECOS_KEY = '1J5840GM10SEKX5HM748'
START_YF = '2000-01-01'
END_YF   = args.end

_end_ecos = pd.Timestamp(END_YF).strftime('%Y%m%d')   # ECOS용 YYYYMMDD
_end_ecos_m = pd.Timestamp(END_YF).strftime('%Y%m')   # ECOS 월별용 YYYYMM

print(f"▶ 데이터 수집 종료일: {END_YF}")

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


# ════════════════════════════════════════════════
# ECOS 유틸리티
# ════════════════════════════════════════════════
def ecos_fetch(stat_code, item_code, cycle='D', start='20000101', end=None):
    if end is None:
        end = _end_ecos
    """ECOS StatisticSearch → pandas Series (index=date, value=float)."""
    if cycle == 'M':
        start = start[:6]
        end   = end[:6]
    url = (f"https://ecos.bok.or.kr/api/StatisticSearch/"
           f"{ECOS_KEY}/json/kr/1/100000/"
           f"{stat_code}/{cycle}/{start}/{end}/{item_code}")
    try:
        r = requests.get(url, timeout=30)
        js = r.json()
    except Exception as e:
        print(f"    요청 오류: {e}")
        return None
    if 'StatisticSearch' not in js:
        print(f"    응답 없음: {js.get('RESULT', {}).get('MESSAGE','')}")
        return None
    rows = js['StatisticSearch'].get('row', [])
    if not rows:
        return None
    df = pd.DataFrame(rows)[['TIME', 'DATA_VALUE']].copy()
    fmt = '%Y%m%d' if cycle == 'D' else '%Y%m'
    df['date']  = pd.to_datetime(df['TIME'], format=fmt, errors='coerce')
    df['value'] = pd.to_numeric(df['DATA_VALUE'], errors='coerce')
    s = df.dropna(subset=['date','value']).set_index('date')['value'].sort_index()
    return s if len(s) > 0 else None


def yield_to_ret(yield_pct, modified_duration):
    """
    채권 수익률(%) → 일별 가격 수익률
      daily_ret ≈ YTM/252  −  MD × Δy
    """
    y = yield_pct / 100
    carry   = y / 252
    delta_y = y.diff()
    return (carry - modified_duration * delta_y).dropna()


def dl_yf(ticker, name):
    """yfinance 다운로드 → 일별 수익률 Series."""
    try:
        df = yf.download(ticker, start=START_YF, end=END_YF,
                         progress=False, auto_adjust=True)
        if df.empty:
            raise ValueError("빈 데이터")
        close = df['Close'].squeeze()
        close.index = pd.to_datetime(close.index)
        if close.index.tz is not None:
            close.index = close.index.tz_localize(None)
        ret = close.pct_change().dropna()
        print(f"  {name}: {ret.index.min().date()} ~ {ret.index.max().date()} "
              f"({len(ret):>5}거래일)")
        return ret
    except Exception as e:
        print(f"  ⚠ {name} ({ticker}) 실패: {e}")
        return None


# ════════════════════════════════════════════════
# 1. 주식·금 — yfinance
# ════════════════════════════════════════════════
print("▶ 1. 주식·금 지수 (yfinance)...")

yf_map = {
    '국내주식_코스피':  ('^KS11',  '코스피'),
    '국내주식_코스닥':  ('^KQ11',  '코스닥'),
    '미국주식_SP500':   ('^GSPC',  'S&P 500'),
    '미국주식_나스닥':  ('^NDX',   'NASDAQ 100'),
    '신흥국_인도':      ('^NSEI',  'Nifty 50'),
    '신흥국_중국':      ('^HSI',   '항셍지수'),
    '원자재_금':        ('GC=F',   '금 선물'),
}

rets = {}
for slot, (ticker, name) in yf_map.items():
    s = dl_yf(ticker, name)
    if s is not None:
        rets[slot] = s


# ════════════════════════════════════════════════
# 2. 해외채권 미국국채 — yfinance ^IRX
# ════════════════════════════════════════════════
print("\n▶ 2. 미국 단기국채 (yfinance ^IRX)...")

try:
    df_irx = yf.download('^IRX', start=START_YF, end=END_YF,
                          progress=False, auto_adjust=True)
    irx = df_irx['Close'].squeeze()
    irx.index = pd.to_datetime(irx.index)
    if irx.index.tz is not None:
        irx.index = irx.index.tz_localize(None)
    # ^IRX: 연율 할인율(%) → 근사 일별 수익률
    ret_irx = (irx.dropna() / 100) / 252
    rets['해외채권_미국국채'] = ret_irx
    print(f"  해외채권_미국국채: {ret_irx.index.min().date()} ~ "
          f"{ret_irx.index.max().date()} ({len(ret_irx)}거래일)")
except Exception as e:
    print(f"  ⚠ ^IRX 실패: {e}")


# ════════════════════════════════════════════════
# 3. 국내채권·무위험 — ECOS 817Y002
# ════════════════════════════════════════════════
print("\n▶ 3. 국내채권·CD금리 (ECOS 817Y002)...")

ecos_items = {
    'y3':  ('010200000', '국고채(3년)'),
    'y10': ('010210000', '국고채(10년)'),
    'y30': ('010230000', '국고채(30년)'),
    'ycc': ('010300000', '회사채(3년,AA-)'),
    'cd':  ('010502000', 'CD(91일)'),
}
raw_yields = {}
for key, (code, desc) in ecos_items.items():
    s = ecos_fetch('817Y002', code)
    if s is not None:
        raw_yields[key] = s
        print(f"  {desc}: {s.index.min().date()} ~ {s.index.max().date()} "
              f"({len(s)}일)")
    else:
        print(f"  ⚠ {desc} 수집 실패")

# 슬롯 변환
bond_cfg = [
    ('국내채권_국고채단중기', 'y3',  2.8),
    ('국내채권_국고채장기',   'y30', 18.0),  # 30년물
    ('국내채권_회사채',       'ycc', 2.7),
]
for slot, key, md in bond_cfg:
    if key in raw_yields:
        ret = yield_to_ret(raw_yields[key], md)
        rets[slot] = ret
        print(f"  {slot}: {ret.index.min().date()} ~ {ret.index.max().date()} "
              f"(MD={md}, {len(ret)}거래일)")
    else:
        print(f"  ⚠ {slot} 변환 불가 (원시 수익률 없음)")

# 국내채권_종합: 3년(50%) + 10년(50%), MD=5.5
if 'y3' in raw_yields and 'y10' in raw_yields:
    idx_c = raw_yields['y3'].index.intersection(raw_yields['y10'].index)
    y_agg = raw_yields['y3'][idx_c] * 0.5 + raw_yields['y10'][idx_c] * 0.5
    ret_agg = yield_to_ret(y_agg, 5.5)
    rets['국내채권_종합'] = ret_agg
    print(f"  국내채권_종합: {ret_agg.index.min().date()} ~ {ret_agg.index.max().date()} "
          f"(y3×0.5+y10×0.5, MD=5.5, {len(ret_agg)}거래일)")

# 무위험(현금성): CD91 일별 수익률
if 'cd' in raw_yields:
    ret_rf = raw_yields['cd'] / 100 / 252
    rets['무위험(현금성)'] = ret_rf
    print(f"  무위험(현금성): {ret_rf.index.min().date()} ~ {ret_rf.index.max().date()}")


# ════════════════════════════════════════════════
# 4. MAR — ECOS 121Y002 정기예금 6개월미만
# ════════════════════════════════════════════════
print("\n▶ 4. MAR 시계열 (ECOS 121Y002/BEABAA2111)...")

mar_series = ecos_fetch('121Y002', 'BEABAA2111', cycle='M',
                         start='200001', end=_end_ecos_m)
if mar_series is not None and len(mar_series) >= 12:
    print(f"  정기예금(6개월미만): {mar_series.index.min().date()} ~ "
          f"{mar_series.index.max().date()} ({len(mar_series)}개월)")
    print(f"  범위: {mar_series.min():.2f}% ~ {mar_series.max():.2f}%")
else:
    print("  ⚠ 정기예금 수집 실패 → CD91 일별→월별 변환으로 대체")
    if 'cd' in raw_yields:
        mar_series = raw_yields['cd'].resample('MS').last()
    else:
        idx = pd.date_range('2000-01-01', '2025-04-01', freq='MS')
        mar_series = pd.Series(2.5, index=idx)
        print("  ⚠ CD91도 없음 → 2.5% 고정 (임시)")


# ════════════════════════════════════════════════
# 5. 저장
# ════════════════════════════════════════════════
print("\n" + "="*65)
print("▶ 5. 결과 저장")
print("="*65)

all_s = {}
for slot in SLOTS:
    if slot in rets:
        s = rets[slot].copy()
        s.index = pd.to_datetime(s.index)
        if hasattr(s.index, 'tz') and s.index.tz is not None:
            s.index = s.index.tz_localize(None)
        all_s[slot] = s
    else:
        print(f"  ⚠ {slot}: 데이터 없음")

idx_df = pd.DataFrame(all_s).sort_index()
idx_df = idx_df[idx_df.notna().any(axis=1)]

print("\n[슬롯별 최종 현황]")
for slot in SLOTS:
    if slot in idx_df.columns:
        s = idx_df[slot].dropna()
        print(f"  {slot:<32} {s.index.min().date()} ~ {s.index.max().date()} "
              f"({len(s):>5}거래일)")
    else:
        print(f"  {slot:<32} ⚠ 없음")

idx_df.to_parquet(DATA_DIR / 'index_returns.parquet')
print(f"\n[저장] index_returns.parquet → {idx_df.shape[0]}일 × {idx_df.shape[1]}슬롯")

mar_df = mar_series.rename('mar_annual').to_frame()
mar_df.index = pd.to_datetime(mar_df.index)
mar_df.to_parquet(DATA_DIR / 'mar_series.parquet')
print(f"[저장] mar_series.parquet     → {len(mar_df)}개월")
