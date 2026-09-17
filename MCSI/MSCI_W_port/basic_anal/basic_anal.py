"""
국가 팩터 가중 전략 백테스트 (v8 — FIF 투자가능비율)
=====================================================
전략: GDP/EY/DY/MC 비례 + GDP/PER/DY/Composite ZS + EW (FIF ON/OFF)
FIF = MSCI시총(Sheet5) / 국가전체시총(cty_mkt_cap.xlsx)
  - GDP/PER/DY/Composite/EW: 비중 산출 후 FIF 곱해서 재정규화
  - MC (Prop): FIF 이미 반영 → 추가 적용 안 함

출력: summary_raw.csv, summary_fif.csv, fif_values.csv, chart_*.png
"""
import pandas as pd, numpy as np, matplotlib, os, warnings
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import matplotlib.dates as mdates
import matplotlib.font_manager as fm
from datetime import datetime, timedelta
warnings.filterwarnings('ignore')

# ══════════════════════════════════════════════════════════════
# ▶ 설정
# ══════════════════════════════════════════════════════════════
BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
DATA_DIR  = os.path.join(BASE_DIR, '..', 'data')
OUT_DIR   = os.path.join(BASE_DIR, '..', 'output')
FILE_MAIN = os.path.join(DATA_DIR, 'hk_msci_world_2006.xlsx')
FILE_BM   = os.path.join(DATA_DIR, 'bm_price.xlsx')
FILE_CTY  = os.path.join(DATA_DIR, 'cty_mkt_cap.xlsx')   # 국가 전체 시총

TEMPERATURE = 1.0

DM = ['USA','Japan','UK','France','Canada','Switzerland','Germany','Australia',
      'Netherlands','Sweden','Denmark','Spain','Italy','Hong Kong','Singapore',
      'Belgium','Finland','Israel','Norway','Ireland','New Zealand','Austria','Portugal']
EM = ['China','India','Taiwan','Korea','Brazil','Saudi Arabia','South Africa','Mexico',
      'Indonesia','Malaysia','UAE','Thailand','Kuwait','Qatar','Poland','Chile',
      'Turkey','Greece','Philippines','Hungary','Egypt','Czech Republic','Colombia','Peru']
ALL_47 = DM + EM

UNIVERSES = {
    'All 47':      {'countries': None,                              'bm': 'MSCI ACWI'},
    'All ex USA':  {'countries': [c for c in ALL_47 if c!='USA'],   'bm': 'MSCI ACWI ex USA'},
    'DM Only':     {'countries': DM,                                'bm': 'MSCI World'},
    'DM ex USA':   {'countries': [c for c in DM if c!='USA'],       'bm': 'MSCI World ex USA'},
    'EM Only':     {'countries': EM,                                'bm': 'MSCI EM'},
}

# ══════════════════════════════════════════════════════════════
# ▶ 폰트
# ══════════════════════════════════════════════════════════════
def set_korean_font():
    for c in [r'C:/Windows/Fonts/malgun.ttf','/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
              '/usr/share/fonts/truetype/nanum/NanumGothic.ttf']:
        if os.path.exists(c):
            fm.fontManager.addfont(c)
            plt.rcParams['font.family'] = fm.FontProperties(fname=c).get_name()
            break
    plt.rcParams['axes.unicode_minus'] = False
set_korean_font()

# ══════════════════════════════════════════════════════════════
# ▶ 데이터 로딩
# ══════════════════════════════════════════════════════════════
def parse_date(d):
    if isinstance(d, (datetime, pd.Timestamp)): return pd.Timestamp(d)
    if isinstance(d, str):
        for fmt in ['%m/%d/%Y','%m-%d-%y','%Y-%m-%d']:
            try: return pd.Timestamp(datetime.strptime(d, fmt))
            except: pass
    if isinstance(d, (int, float)) and not np.isnan(d):
        return pd.Timestamp(datetime(1899,12,30) + timedelta(days=int(d)))
    return pd.NaT

def load_sheet(xls, sheet, name_row=1, data_start=3):
    """엑셀 시트 → DataFrame (날짜=인덱스, 국가=컬럼)"""
    df = pd.read_excel(xls, sheet_name=sheet, header=None)
    cols = df.iloc[name_row, 1:].values
    dates = pd.DatetimeIndex([parse_date(d) for d in df.iloc[data_start:, 0].values])
    vals = pd.to_numeric(df.iloc[data_start:, 1:].values.flatten(), errors='coerce')
    vals = vals.reshape(df.iloc[data_start:, 1:].shape)
    r = pd.DataFrame(vals, index=dates, columns=cols)
    return r[r.index.notna()].pipe(lambda x: x[~x.index.duplicated(keep='first')]).sort_index()

def load_benchmarks(fp):
    """bm_price.xlsx → 벤치마크 월간 수익률 dict"""
    df = pd.read_excel(fp, sheet_name='Sheet2', header=None)
    dates = pd.DatetimeIndex([parse_date(d) for d in df.iloc[1:, 0].values])
    bm = pd.DataFrame({
        'MSCI World':        pd.to_numeric(df.iloc[1:, 1], errors='coerce').values,
        'MSCI World ex USA': pd.to_numeric(df.iloc[1:, 2], errors='coerce').values,
        'MSCI ACWI':         pd.to_numeric(df.iloc[1:, 3], errors='coerce').values,
        'MSCI EM':           pd.to_numeric(df.iloc[1:, 4], errors='coerce').values,
        'MSCI ACWI ex USA':  pd.to_numeric(df.iloc[1:, 5], errors='coerce').values,
    }, index=dates)
    bm = bm[bm.index.notna()].sort_index().dropna(how='all')
    bm = bm[~bm.index.duplicated(keep='first')]
    return {col: bm[col].pct_change().dropna() for col in bm.columns}

# ══════════════════════════════════════════════════════════════
# ▶ FIF 계산 (투자가능비율)
# ══════════════════════════════════════════════════════════════
def calc_fif(df_msci_mc, file_cty):
    """
    FIF = MSCI 시총 / 국가 전체 시총
    - MSCI 시총: Sheet5 (이미 유동시총×FIF 반영)
    - 국가 전체 시총: cty_mkt_cap.xlsx (FC0000XX 코드)
    
    Returns: DataFrame (날짜 × 국가), 값 = 0~1 사이의 투자가능비율
    """
    # 국가 전체 시총 로드
    try:
        xls_cty = pd.ExcelFile(file_cty)
        # Sheet1 또는 첫번째 데이터 시트 찾기
        for sn in xls_cty.sheet_names:
            if sn.startswith('__'): continue
            df_cty = pd.read_excel(xls_cty, sheet_name=sn, header=None)
            if df_cty.shape[0] > 5: break
        
        cols_cty = df_cty.iloc[1, 1:].values
        dates_cty = pd.DatetimeIndex([parse_date(d) for d in df_cty.iloc[3:, 0].values])
        vals_cty = pd.to_numeric(df_cty.iloc[3:, 1:].values.flatten(), errors='coerce')
        vals_cty = vals_cty.reshape(df_cty.iloc[3:, 1:].shape)
        df_total = pd.DataFrame(vals_cty, index=dates_cty, columns=cols_cty)
        df_total = df_total[df_total.index.notna()].pipe(
            lambda x: x[~x.index.duplicated(keep='first')]).sort_index()
        
        print(f"  국가전체 시총: {df_total.shape}, {df_total.index[0]:%Y-%m} ~ {df_total.index[-1]:%Y-%m}")
    except Exception as e:
        print(f"  WARNING: 국가 전체 시총 로드 실패 ({e}). FIF=1.0 사용.")
        return pd.DataFrame(1.0, index=df_msci_mc.index, columns=df_msci_mc.columns)
    
    # FIF 계산: 공통 날짜/국가에 대해
    common_dates = df_msci_mc.index.intersection(df_total.index)
    common_cols = df_msci_mc.columns.intersection(df_total.columns)
    
    fif = (df_msci_mc.loc[common_dates, common_cols] / 
           df_total.loc[common_dates, common_cols].replace(0, np.nan))
    fif = fif.clip(0, 1.5)  # 이상치 제한
    
    # FIF가 없는 날짜/국가는 ffill → bfill
    all_dates = df_msci_mc.index
    fif = fif.reindex(all_dates).ffill().bfill()
    
    # 커버되지 않는 국가는 1.0
    for c in df_msci_mc.columns:
        if c not in fif.columns:
            fif[c] = 1.0
    
    return fif

def apply_fif_to_weights(weights, fif_df):
    """비중에 FIF를 곱한 뒤 재정규화. MC(Prop)에는 사용하지 말 것!"""
    cd = weights.index.intersection(fif_df.index)
    cc = weights.columns.intersection(fif_df.columns)
    adj = weights.loc[cd, cc] * fif_df.loc[cd, cc]
    return adj.div(adj.sum(axis=1), axis=0)

# ══════════════════════════════════════════════════════════════
# ▶ 비중 계산
# ══════════════════════════════════════════════════════════════
def softmax(z, T=1.0):
    zs = z/T; zs = zs - np.nanmax(zs)
    e = np.exp(zs); e = np.where(np.isnan(z), 0, e)
    s = np.nansum(e)
    return e/s if s > 0 else np.full_like(z, np.nan)

def calc_prop(df, inverse=False):
    if inverse: t = (1.0/df.replace(0, np.nan)).clip(lower=0)
    else: t = df.clip(lower=0)
    return t.div(t.sum(axis=1), axis=0)

def calc_zs(df, inverse=False, use_log=False, T=1.0):
    result = pd.DataFrame(index=df.index, columns=df.columns, dtype=float)
    for d in df.index:
        row = df.loc[d].astype(float); valid = row.notna() & (row > 0)
        if valid.sum() < 5: continue
        vals = row[valid].copy()
        if use_log: vals = np.log(vals)
        if inverse: vals = -vals
        mu, sig = vals.mean(), vals.std()
        if sig == 0 or np.isnan(sig): continue
        result.loc[d, valid] = softmax(((vals-mu)/sig).values, T)
    return result

def calc_comp(dfs, inverses, use_logs, T=1.0):
    cd = dfs[0].index
    for df in dfs[1:]: cd = cd.intersection(df.index)
    cd = cd.sort_values()
    cc = dfs[0].columns
    for df in dfs[1:]: cc = cc.intersection(df.columns)
    result = pd.DataFrame(index=cd, columns=cc, dtype=float)
    for d in cd:
        zl = []
        for df, inv, ul in zip(dfs, inverses, use_logs):
            if d not in df.index: continue
            row = df.loc[d][cc].astype(float); v = row.notna() & (row > 0)
            if v.sum() < 5: continue
            vals = row[v].copy()
            if ul: vals = np.log(vals)
            if inv: vals = -vals
            mu, sig = vals.mean(), vals.std()
            if sig == 0 or np.isnan(sig): continue
            zl.append((vals-mu)/sig)
        if not zl: continue
        az = pd.concat(zl, axis=1).mean(axis=1); va = az.notna()
        if va.sum() < 5: continue
        sm = softmax(az[va].values, T)
        for c, v in zip(list(va[va].index), sm): result.at[d, c] = v
    return result

# ══════════════════════════════════════════════════════════════
# ▶ 포트폴리오 + 성과
# ══════════════════════════════════════════════════════════════
def build_portfolio(weights, returns, country_filter=None):
    cc = weights.columns.intersection(returns.columns)
    if country_filter is not None: cc = cc.intersection(country_filter)
    w_df = weights[cc]; r_df = returns[cc]; w_dates = w_df.index.sort_values()
    records = []
    for ret_date in r_df.index:
        vw = w_dates[w_dates < ret_date]
        if len(vw) == 0: continue
        w = w_df.loc[vw[-1]]; r = r_df.loc[ret_date]
        if isinstance(w, pd.DataFrame): w = w.iloc[0]
        if isinstance(r, pd.DataFrame): r = r.iloc[0]
        ok = w.notna() & r.notna() & (w > 0)
        if ok.sum() < 3: continue
        wn = w[ok] / w[ok].sum()
        records.append({'date': ret_date, 'ret': float((wn * r[ok]).sum())})
    if not records: return pd.DataFrame()
    return pd.DataFrame(records).set_index('date').sort_index()

def evaluate(port_df, bm_ret, sn, un, bn):
    ci = port_df.index.intersection(bm_ret.index)
    if len(ci) < 12: return None, None
    p = port_df['ret'].reindex(ci).dropna(); b = bm_ret.reindex(ci).dropna()
    ci2 = p.index.intersection(b.index); p, b = p.loc[ci2], b.loc[ci2]
    monthly = pd.DataFrame({'Port_Return':p,'BM_Return':b,'Excess':p-b})
    monthly['Cum_Port'] = (1+p).cumprod()-1
    monthly['Cum_BM'] = (1+b).cumprod()-1
    monthly['Cum_Excess'] = (1+(p-b)).cumprod()-1
    ar=(1+p.mean())**12-1; av=p.std()*np.sqrt(12); sh=ar/av if av>0 else 0
    cr=(1+p).prod()-1; md=((1+p).cumprod()/(1+p).cumprod().cummax()-1).min()
    bar=(1+b.mean())**12-1; ex=p-b
    summary = {'Strategy':sn,'Universe':un,'Benchmark':bn,
        'Period':f"{ci2[0]:%Y-%m} ~ {ci2[-1]:%Y-%m}",'Months':len(ci2),
        'Ann_Return(%)':round(ar*100,2),'Ann_Vol(%)':round(av*100,2),'Sharpe':round(sh,3),
        'Cum_Return(%)':round(cr*100,2),'MDD(%)':round(md*100,2),
        'Ann_Excess(%)':round((ar-bar)*100,2),'Win_Rate(%)':round((ex>0).mean()*100,1),
        'Cum_Excess(%)':round(((1+ex).cumprod()-1).iloc[-1]*100,2)}
    return monthly, summary

# ══════════════════════════════════════════════════════════════
# ▶ 차트
# ══════════════════════════════════════════════════════════════
COLORS = {
    'GDP (Prop)': '#2563EB', 'EY (Prop)': '#DB2777', 'DY (Prop)': '#D97706',
    'MC (Prop)': '#0891B2',
    'GDP (ZS)': '#4F46E5', 'PER (ZS)': '#A855F7', 'DY (ZS)': '#EA580C',
    'Composite (ZS)': '#65A30D', 'Equal Weight': '#6B7280',
}
BM_COLOR = '#059669'


def draw_chart(metric_name, results_by_univ, out_path):
    """하나의 전략 × 5개 유니버스 비교 차트"""
    fig, axes = plt.subplots(3, 2, figsize=(20, 16))
    fig.patch.set_facecolor('#F8FAFC')
    univ_list = list(UNIVERSES.items())

    for idx in range(6):
        ax = axes[idx // 2][idx % 2]
        ax.set_facecolor('#FFFFFF')

        if idx >= len(univ_list):
            ax.axis('off')
            continue

        univ_name, univ_cfg = univ_list[idx]
        key = f"{metric_name}|{univ_name}"
        data = results_by_univ.get(key)

        if data is None:
            ax.text(0.5, 0.5, 'No Data', ha='center', va='center',
                    transform=ax.transAxes, fontsize=14)
            continue

        monthly, summary = data
        x = monthly.index.to_pydatetime()

        # 포트 vs 벤치마크 누적수익률
        ax.plot(x, monthly['Cum_Port'] * 100,
                color=COLORS.get(metric_name, '#2563EB'), lw=2, label=f'{metric_name}')
        ax.plot(x, monthly['Cum_BM'] * 100,
                color=BM_COLOR, lw=1.5, ls='--', label=f'{univ_cfg["bm"]}')
        ax.axhline(0, color='#D1D5DB', lw=0.8)

        # 초과수익 영역 (양수=파란, 음수=빨강)
        exc = monthly['Cum_Excess'] * 100
        ax.fill_between(x, 0, exc, where=(exc >= 0),
                        alpha=0.12, color=COLORS.get(metric_name, '#2563EB'), interpolate=True)
        ax.fill_between(x, 0, exc, where=(exc < 0),
                        alpha=0.12, color='red', interpolate=True)

        # 정보 박스
        info = (f"승률: {summary['Win_Rate(%)']:.1f}%\n"
                f"누적초과: {summary['Cum_Excess(%)']:+.1f}%\n"
                f"Sharpe: {summary['Sharpe']:.3f}\n"
                f"포트 누적: {summary['Cum_Return(%)']:.1f}%\n"
                f"벤치 누적: {monthly['Cum_BM'].iloc[-1]*100:.1f}%")
        ax.text(0.02, 0.97, info, transform=ax.transAxes, fontsize=8, va='top',
                bbox=dict(boxstyle='round,pad=0.4', facecolor='white',
                          edgecolor='#CBD5E1', alpha=0.9))

        ax.xaxis.set_major_locator(mdates.YearLocator(2))
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
        ax.tick_params(axis='x', labelsize=8)
        ax.yaxis.set_major_formatter(
            mticker.FuncFormatter(lambda v, _: f'{v:.0f}%'))
        ax.tick_params(axis='y', labelsize=8)
        ax.grid(axis='y', ls=':', lw=0.5, color='#E2E8F0')
        ax.spines[['top', 'right']].set_visible(False)
        ax.set_title(f"{univ_name} vs {univ_cfg['bm']}", fontsize=10, fontweight='bold')
        ax.legend(fontsize=8, loc='upper left', framealpha=0.8)

    fig.suptitle(f'{metric_name} — 누적수익률 (T={TEMPERATURE})',
                 fontsize=13, fontweight='bold', y=1.01)
    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches='tight', facecolor=fig.get_facecolor())
    plt.close()
    print(f"  차트 저장 → {out_path}")

# ══════════════════════════════════════════════════════════════
# ▶ 메인
# ══════════════════════════════════════════════════════════════
if __name__ == '__main__':
    os.makedirs(OUT_DIR, exist_ok=True)

    # ── 1. 데이터 로드 ──
    print("데이터 로드 중...")
    xls = pd.ExcelFile(FILE_MAIN)
    df_gdp   = load_sheet(xls, 'Sheet4', 1, 3)
    df_per   = load_sheet(xls, 'Sheet7', 1, 3)
    df_div   = load_sheet(xls, 'Sheet8', 1, 3)
    df_mc    = load_sheet(xls, 'Sheet5', 1, 3)   # MSCI 유동시총 (FIF 이미 반영)
    df_price = load_sheet(xls, 'Sheet10', 1, 5)
    bm_returns = load_benchmarks(FILE_BM)
    price_returns = df_price.pct_change().iloc[1:].replace([np.inf,-np.inf], np.nan)

    print(f"  GDP:{df_gdp.shape} PER:{df_per.shape} DY:{df_div.shape} MC:{df_mc.shape} Price:{df_price.shape}")

    # ── 2. FIF 계산 ──
    print("\nFIF 계산 중...")
    fif_df = calc_fif(df_mc, FILE_CTY)

    # FIF 저장 (data 폴더에)
    fif_save = fif_df.copy()
    fif_save.index = fif_save.index.strftime('%Y-%m-%d')
    fif_save.to_csv(os.path.join(DATA_DIR, 'fif_values.csv'), encoding='utf-8-sig')
    print(f"  FIF 저장 → {os.path.join(DATA_DIR, 'fif_values.csv')}")

    # FIF 요약 출력
    fif_latest = fif_df.iloc[-1].dropna().sort_values()
    print(f"\n  FIF 최신값 (낮은순):")
    for c, v in fif_latest.head(10).items():
        print(f"    {c:<15} {v:.3f}")
    print(f"  ...")
    for c, v in fif_latest.tail(5).items():
        print(f"    {c:<15} {v:.3f}")

    # ── 3. 비중 계산 ──
    print("\n비중 계산 중...")
    raw_strategies = {
        'GDP (Prop)': calc_prop(df_gdp),
        'EY (Prop)':  calc_prop(df_per, inverse=True),
        'DY (Prop)':  calc_prop(df_div),
        'MC (Prop)':  calc_prop(df_mc),
        'GDP (ZS)':   calc_zs(df_gdp, use_log=True, T=TEMPERATURE),
        'PER (ZS)':   calc_zs(df_per, T=TEMPERATURE),
        'DY (ZS)':    calc_zs(df_div, T=TEMPERATURE),
        'Composite (ZS)': calc_comp([df_gdp,df_per,df_div],[False,False,False],[True,False,False],T=TEMPERATURE),
        'Equal Weight': pd.DataFrame(1.0, index=price_returns.index, columns=price_returns.columns),
    }

    # FIF 적용 버전: MC(Prop)는 이미 FIF 반영이므로 그대로 유지
    fif_strategies = {}
    for name, w in raw_strategies.items():
        if name == 'MC (Prop)':
            fif_strategies[name] = w  # MC는 FIF 추가 적용 안 함
        else:
            fif_strategies[name] = apply_fif_to_weights(w, fif_df)

    # ── 4. 백테스트 (Raw + FIF) ──
    for label, strategies in [('Raw', raw_strategies), ('FIF', fif_strategies)]:
        print(f"\n{'='*90}")
        print(f"백테스트 ({label})")
        print(f"{'='*90}")
        all_summary = []
        chart_results = {}

        for sn, w in strategies.items():
            for un, uc in UNIVERSES.items():
                port = build_portfolio(w, price_returns, uc['countries'])
                if port.empty: continue
                monthly, summary = evaluate(port, bm_returns[uc['bm']], sn, un, uc['bm'])
                if monthly is None: continue
                chart_results[f"{sn}|{un}"] = (monthly, summary)
                all_summary.append(summary)
                print(f"  {sn:23s} | {un:12s} | SR={summary['Sharpe']:.3f} | CumEx={summary['Cum_Excess(%)']:+7.1f}%")

        sdf = pd.DataFrame(all_summary)
        sdf.to_csv(os.path.join(OUT_DIR, f'summary_{label.lower()}.csv'), index=False, encoding='utf-8-sig')

        for sn in strategies:
            safe = sn.replace(' ','_').replace('(','').replace(')','')
            draw_chart(sn, chart_results, os.path.join(OUT_DIR, f'chart_{label.lower()}_{safe}.png'))

    print(f"\n완료!")
    print(f"  FIF 데이터  → {DATA_DIR}/fif_values.csv")
    print(f"  Raw 요약    → {OUT_DIR}/summary_raw.csv")
    print(f"  FIF 요약    → {OUT_DIR}/summary_fif.csv")"""
국가 팩터 가중 전략 백테스트 (v8 — FIF 투자가능비율)
=====================================================
전략: GDP/EY/DY/MC 비례 + GDP/PER/DY/Composite ZS + EW (FIF ON/OFF)
FIF = MSCI시총(Sheet5) / 국가전체시총(cty_mkt_cap.xlsx)
  - GDP/PER/DY/Composite/EW: 비중 산출 후 FIF 곱해서 재정규화
  - MC (Prop): FIF 이미 반영 → 추가 적용 안 함

출력: summary_raw.csv, summary_fif.csv, fif_values.csv, chart_*.png
"""
import pandas as pd, numpy as np, matplotlib, os, warnings
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import matplotlib.dates as mdates
import matplotlib.font_manager as fm
from datetime import datetime, timedelta
warnings.filterwarnings('ignore')

# ══════════════════════════════════════════════════════════════
# ▶ 설정
# ══════════════════════════════════════════════════════════════
BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
DATA_DIR  = os.path.join(BASE_DIR, '..', 'data')
OUT_DIR   = os.path.join(BASE_DIR, '..', 'output')
FILE_MAIN = os.path.join(DATA_DIR, 'hk_msci_world_2006.xlsx')
FILE_BM   = os.path.join(DATA_DIR, 'bm_price.xlsx')
FILE_CTY  = os.path.join(DATA_DIR, 'cty_mkt_cap.xlsx')   # 국가 전체 시총

TEMPERATURE = 1.0

DM = ['USA','Japan','UK','France','Canada','Switzerland','Germany','Australia',
      'Netherlands','Sweden','Denmark','Spain','Italy','Hong Kong','Singapore',
      'Belgium','Finland','Israel','Norway','Ireland','New Zealand','Austria','Portugal']
EM = ['China','India','Taiwan','Korea','Brazil','Saudi Arabia','South Africa','Mexico',
      'Indonesia','Malaysia','UAE','Thailand','Kuwait','Qatar','Poland','Chile',
      'Turkey','Greece','Philippines','Hungary','Egypt','Czech Republic','Colombia','Peru']
ALL_47 = DM + EM

UNIVERSES = {
    'All 47':      {'countries': None,                              'bm': 'MSCI ACWI'},
    'All ex USA':  {'countries': [c for c in ALL_47 if c!='USA'],   'bm': 'MSCI ACWI ex USA'},
    'DM Only':     {'countries': DM,                                'bm': 'MSCI World'},
    'DM ex USA':   {'countries': [c for c in DM if c!='USA'],       'bm': 'MSCI World ex USA'},
    'EM Only':     {'countries': EM,                                'bm': 'MSCI EM'},
}

# ══════════════════════════════════════════════════════════════
# ▶ 폰트
# ══════════════════════════════════════════════════════════════
def set_korean_font():
    for c in [r'C:/Windows/Fonts/malgun.ttf','/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
              '/usr/share/fonts/truetype/nanum/NanumGothic.ttf']:
        if os.path.exists(c):
            fm.fontManager.addfont(c)
            plt.rcParams['font.family'] = fm.FontProperties(fname=c).get_name()
            break
    plt.rcParams['axes.unicode_minus'] = False
set_korean_font()

# ══════════════════════════════════════════════════════════════
# ▶ 데이터 로딩
# ══════════════════════════════════════════════════════════════
def parse_date(d):
    if isinstance(d, (datetime, pd.Timestamp)): return pd.Timestamp(d)
    if isinstance(d, str):
        for fmt in ['%m/%d/%Y','%m-%d-%y','%Y-%m-%d']:
            try: return pd.Timestamp(datetime.strptime(d, fmt))
            except: pass
    if isinstance(d, (int, float)) and not np.isnan(d):
        return pd.Timestamp(datetime(1899,12,30) + timedelta(days=int(d)))
    return pd.NaT

def load_sheet(xls, sheet, name_row=1, data_start=3):
    """엑셀 시트 → DataFrame (날짜=인덱스, 국가=컬럼)"""
    df = pd.read_excel(xls, sheet_name=sheet, header=None)
    cols = df.iloc[name_row, 1:].values
    dates = pd.DatetimeIndex([parse_date(d) for d in df.iloc[data_start:, 0].values])
    vals = pd.to_numeric(df.iloc[data_start:, 1:].values.flatten(), errors='coerce')
    vals = vals.reshape(df.iloc[data_start:, 1:].shape)
    r = pd.DataFrame(vals, index=dates, columns=cols)
    return r[r.index.notna()].pipe(lambda x: x[~x.index.duplicated(keep='first')]).sort_index()

def load_benchmarks(fp):
    """bm_price.xlsx → 벤치마크 월간 수익률 dict"""
    df = pd.read_excel(fp, sheet_name='Sheet2', header=None)
    dates = pd.DatetimeIndex([parse_date(d) for d in df.iloc[1:, 0].values])
    bm = pd.DataFrame({
        'MSCI World':        pd.to_numeric(df.iloc[1:, 1], errors='coerce').values,
        'MSCI World ex USA': pd.to_numeric(df.iloc[1:, 2], errors='coerce').values,
        'MSCI ACWI':         pd.to_numeric(df.iloc[1:, 3], errors='coerce').values,
        'MSCI EM':           pd.to_numeric(df.iloc[1:, 4], errors='coerce').values,
        'MSCI ACWI ex USA':  pd.to_numeric(df.iloc[1:, 5], errors='coerce').values,
    }, index=dates)
    bm = bm[bm.index.notna()].sort_index().dropna(how='all')
    bm = bm[~bm.index.duplicated(keep='first')]
    return {col: bm[col].pct_change().dropna() for col in bm.columns}

# ══════════════════════════════════════════════════════════════
# ▶ FIF 계산 (투자가능비율)
# ══════════════════════════════════════════════════════════════
def calc_fif(df_msci_mc, file_cty):
    """
    FIF = MSCI 시총 / 국가 전체 시총
    - MSCI 시총: Sheet5 (이미 유동시총×FIF 반영)
    - 국가 전체 시총: cty_mkt_cap.xlsx (FC0000XX 코드)
    
    Returns: DataFrame (날짜 × 국가), 값 = 0~1 사이의 투자가능비율
    """
    # 국가 전체 시총 로드
    try:
        xls_cty = pd.ExcelFile(file_cty)
        # Sheet1 또는 첫번째 데이터 시트 찾기
        for sn in xls_cty.sheet_names:
            if sn.startswith('__'): continue
            df_cty = pd.read_excel(xls_cty, sheet_name=sn, header=None)
            if df_cty.shape[0] > 5: break
        
        cols_cty = df_cty.iloc[1, 1:].values
        dates_cty = pd.DatetimeIndex([parse_date(d) for d in df_cty.iloc[3:, 0].values])
        vals_cty = pd.to_numeric(df_cty.iloc[3:, 1:].values.flatten(), errors='coerce')
        vals_cty = vals_cty.reshape(df_cty.iloc[3:, 1:].shape)
        df_total = pd.DataFrame(vals_cty, index=dates_cty, columns=cols_cty)
        df_total = df_total[df_total.index.notna()].pipe(
            lambda x: x[~x.index.duplicated(keep='first')]).sort_index()
        
        print(f"  국가전체 시총: {df_total.shape}, {df_total.index[0]:%Y-%m} ~ {df_total.index[-1]:%Y-%m}")
    except Exception as e:
        print(f"  WARNING: 국가 전체 시총 로드 실패 ({e}). FIF=1.0 사용.")
        return pd.DataFrame(1.0, index=df_msci_mc.index, columns=df_msci_mc.columns)
    
    # FIF 계산: 공통 날짜/국가에 대해
    common_dates = df_msci_mc.index.intersection(df_total.index)
    common_cols = df_msci_mc.columns.intersection(df_total.columns)
    
    fif = (df_msci_mc.loc[common_dates, common_cols] / 
           df_total.loc[common_dates, common_cols].replace(0, np.nan))
    fif = fif.clip(0, 1.5)  # 이상치 제한
    
    # FIF가 없는 날짜/국가는 ffill → bfill
    all_dates = df_msci_mc.index
    fif = fif.reindex(all_dates).ffill().bfill()
    
    # 커버되지 않는 국가는 1.0
    for c in df_msci_mc.columns:
        if c not in fif.columns:
            fif[c] = 1.0
    
    return fif

def apply_fif_to_weights(weights, fif_df):
    """비중에 FIF를 곱한 뒤 재정규화. MC(Prop)에는 사용하지 말 것!"""
    cd = weights.index.intersection(fif_df.index)
    cc = weights.columns.intersection(fif_df.columns)
    adj = weights.loc[cd, cc] * fif_df.loc[cd, cc]
    return adj.div(adj.sum(axis=1), axis=0)

# ══════════════════════════════════════════════════════════════
# ▶ 비중 계산
# ══════════════════════════════════════════════════════════════
def softmax(z, T=1.0):
    zs = z/T; zs = zs - np.nanmax(zs)
    e = np.exp(zs); e = np.where(np.isnan(z), 0, e)
    s = np.nansum(e)
    return e/s if s > 0 else np.full_like(z, np.nan)

def calc_prop(df, inverse=False):
    if inverse: t = (1.0/df.replace(0, np.nan)).clip(lower=0)
    else: t = df.clip(lower=0)
    return t.div(t.sum(axis=1), axis=0)

def calc_zs(df, inverse=False, use_log=False, T=1.0):
    result = pd.DataFrame(index=df.index, columns=df.columns, dtype=float)
    for d in df.index:
        row = df.loc[d].astype(float); valid = row.notna() & (row > 0)
        if valid.sum() < 5: continue
        vals = row[valid].copy()
        if use_log: vals = np.log(vals)
        if inverse: vals = -vals
        mu, sig = vals.mean(), vals.std()
        if sig == 0 or np.isnan(sig): continue
        result.loc[d, valid] = softmax(((vals-mu)/sig).values, T)
    return result

def calc_comp(dfs, inverses, use_logs, T=1.0):
    cd = dfs[0].index
    for df in dfs[1:]: cd = cd.intersection(df.index)
    cd = cd.sort_values()
    cc = dfs[0].columns
    for df in dfs[1:]: cc = cc.intersection(df.columns)
    result = pd.DataFrame(index=cd, columns=cc, dtype=float)
    for d in cd:
        zl = []
        for df, inv, ul in zip(dfs, inverses, use_logs):
            if d not in df.index: continue
            row = df.loc[d][cc].astype(float); v = row.notna() & (row > 0)
            if v.sum() < 5: continue
            vals = row[v].copy()
            if ul: vals = np.log(vals)
            if inv: vals = -vals
            mu, sig = vals.mean(), vals.std()
            if sig == 0 or np.isnan(sig): continue
            zl.append((vals-mu)/sig)
        if not zl: continue
        az = pd.concat(zl, axis=1).mean(axis=1); va = az.notna()
        if va.sum() < 5: continue
        sm = softmax(az[va].values, T)
        for c, v in zip(list(va[va].index), sm): result.at[d, c] = v
    return result

# ══════════════════════════════════════════════════════════════
# ▶ 포트폴리오 + 성과
# ══════════════════════════════════════════════════════════════
def build_portfolio(weights, returns, country_filter=None):
    cc = weights.columns.intersection(returns.columns)
    if country_filter is not None: cc = cc.intersection(country_filter)
    w_df = weights[cc]; r_df = returns[cc]; w_dates = w_df.index.sort_values()
    records = []
    for ret_date in r_df.index:
        vw = w_dates[w_dates < ret_date]
        if len(vw) == 0: continue
        w = w_df.loc[vw[-1]]; r = r_df.loc[ret_date]
        if isinstance(w, pd.DataFrame): w = w.iloc[0]
        if isinstance(r, pd.DataFrame): r = r.iloc[0]
        ok = w.notna() & r.notna() & (w > 0)
        if ok.sum() < 3: continue
        wn = w[ok] / w[ok].sum()
        records.append({'date': ret_date, 'ret': float((wn * r[ok]).sum())})
    if not records: return pd.DataFrame()
    return pd.DataFrame(records).set_index('date').sort_index()

def evaluate(port_df, bm_ret, sn, un, bn):
    ci = port_df.index.intersection(bm_ret.index)
    if len(ci) < 12: return None, None
    p = port_df['ret'].reindex(ci).dropna(); b = bm_ret.reindex(ci).dropna()
    ci2 = p.index.intersection(b.index); p, b = p.loc[ci2], b.loc[ci2]
    monthly = pd.DataFrame({'Port_Return':p,'BM_Return':b,'Excess':p-b})
    monthly['Cum_Port'] = (1+p).cumprod()-1
    monthly['Cum_BM'] = (1+b).cumprod()-1
    monthly['Cum_Excess'] = (1+(p-b)).cumprod()-1
    ar=(1+p.mean())**12-1; av=p.std()*np.sqrt(12); sh=ar/av if av>0 else 0
    cr=(1+p).prod()-1; md=((1+p).cumprod()/(1+p).cumprod().cummax()-1).min()
    bar=(1+b.mean())**12-1; ex=p-b
    summary = {'Strategy':sn,'Universe':un,'Benchmark':bn,
        'Period':f"{ci2[0]:%Y-%m} ~ {ci2[-1]:%Y-%m}",'Months':len(ci2),
        'Ann_Return(%)':round(ar*100,2),'Ann_Vol(%)':round(av*100,2),'Sharpe':round(sh,3),
        'Cum_Return(%)':round(cr*100,2),'MDD(%)':round(md*100,2),
        'Ann_Excess(%)':round((ar-bar)*100,2),'Win_Rate(%)':round((ex>0).mean()*100,1),
        'Cum_Excess(%)':round(((1+ex).cumprod()-1).iloc[-1]*100,2)}
    return monthly, summary

# ══════════════════════════════════════════════════════════════
# ▶ 차트
# ══════════════════════════════════════════════════════════════
COLORS = {
    'GDP (Prop)': '#2563EB', 'EY (Prop)': '#DB2777', 'DY (Prop)': '#D97706',
    'MC (Prop)': '#0891B2',
    'GDP (ZS)': '#4F46E5', 'PER (ZS)': '#A855F7', 'DY (ZS)': '#EA580C',
    'Composite (ZS)': '#65A30D', 'Equal Weight': '#6B7280',
}
BM_COLOR = '#059669'


def draw_chart(metric_name, results_by_univ, out_path):
    """하나의 전략 × 5개 유니버스 비교 차트"""
    fig, axes = plt.subplots(3, 2, figsize=(20, 16))
    fig.patch.set_facecolor('#F8FAFC')
    univ_list = list(UNIVERSES.items())

    for idx in range(6):
        ax = axes[idx // 2][idx % 2]
        ax.set_facecolor('#FFFFFF')

        if idx >= len(univ_list):
            ax.axis('off')
            continue

        univ_name, univ_cfg = univ_list[idx]
        key = f"{metric_name}|{univ_name}"
        data = results_by_univ.get(key)

        if data is None:
            ax.text(0.5, 0.5, 'No Data', ha='center', va='center',
                    transform=ax.transAxes, fontsize=14)
            continue

        monthly, summary = data
        x = monthly.index.to_pydatetime()

        # 포트 vs 벤치마크 누적수익률
        ax.plot(x, monthly['Cum_Port'] * 100,
                color=COLORS.get(metric_name, '#2563EB'), lw=2, label=f'{metric_name}')
        ax.plot(x, monthly['Cum_BM'] * 100,
                color=BM_COLOR, lw=1.5, ls='--', label=f'{univ_cfg["bm"]}')
        ax.axhline(0, color='#D1D5DB', lw=0.8)

        # 초과수익 영역 (양수=파란, 음수=빨강)
        exc = monthly['Cum_Excess'] * 100
        ax.fill_between(x, 0, exc, where=(exc >= 0),
                        alpha=0.12, color=COLORS.get(metric_name, '#2563EB'), interpolate=True)
        ax.fill_between(x, 0, exc, where=(exc < 0),
                        alpha=0.12, color='red', interpolate=True)

        # 정보 박스
        info = (f"승률: {summary['Win_Rate(%)']:.1f}%\n"
                f"누적초과: {summary['Cum_Excess(%)']:+.1f}%\n"
                f"Sharpe: {summary['Sharpe']:.3f}\n"
                f"포트 누적: {summary['Cum_Return(%)']:.1f}%\n"
                f"벤치 누적: {monthly['Cum_BM'].iloc[-1]*100:.1f}%")
        ax.text(0.02, 0.97, info, transform=ax.transAxes, fontsize=8, va='top',
                bbox=dict(boxstyle='round,pad=0.4', facecolor='white',
                          edgecolor='#CBD5E1', alpha=0.9))

        ax.xaxis.set_major_locator(mdates.YearLocator(2))
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
        ax.tick_params(axis='x', labelsize=8)
        ax.yaxis.set_major_formatter(
            mticker.FuncFormatter(lambda v, _: f'{v:.0f}%'))
        ax.tick_params(axis='y', labelsize=8)
        ax.grid(axis='y', ls=':', lw=0.5, color='#E2E8F0')
        ax.spines[['top', 'right']].set_visible(False)
        ax.set_title(f"{univ_name} vs {univ_cfg['bm']}", fontsize=10, fontweight='bold')
        ax.legend(fontsize=8, loc='upper left', framealpha=0.8)

    fig.suptitle(f'{metric_name} — 누적수익률 (T={TEMPERATURE})',
                 fontsize=13, fontweight='bold', y=1.01)
    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches='tight', facecolor=fig.get_facecolor())
    plt.close()
    print(f"  차트 저장 → {out_path}")

# ══════════════════════════════════════════════════════════════
# ▶ 메인
# ══════════════════════════════════════════════════════════════
if __name__ == '__main__':
    os.makedirs(OUT_DIR, exist_ok=True)

    # ── 1. 데이터 로드 ──
    print("데이터 로드 중...")
    xls = pd.ExcelFile(FILE_MAIN)
    df_gdp   = load_sheet(xls, 'Sheet4', 1, 3)
    df_per   = load_sheet(xls, 'Sheet7', 1, 3)
    df_div   = load_sheet(xls, 'Sheet8', 1, 3)
    df_mc    = load_sheet(xls, 'Sheet5', 1, 3)   # MSCI 유동시총 (FIF 이미 반영)
    df_price = load_sheet(xls, 'Sheet10', 1, 5)
    bm_returns = load_benchmarks(FILE_BM)
    price_returns = df_price.pct_change().iloc[1:].replace([np.inf,-np.inf], np.nan)

    print(f"  GDP:{df_gdp.shape} PER:{df_per.shape} DY:{df_div.shape} MC:{df_mc.shape} Price:{df_price.shape}")

    # ── 2. FIF 계산 ──
    print("\nFIF 계산 중...")
    fif_df = calc_fif(df_mc, FILE_CTY)

    # FIF 저장 (data 폴더에)
    fif_save = fif_df.copy()
    fif_save.index = fif_save.index.strftime('%Y-%m-%d')
    fif_save.to_csv(os.path.join(DATA_DIR, 'fif_values.csv'), encoding='utf-8-sig')
    print(f"  FIF 저장 → {os.path.join(DATA_DIR, 'fif_values.csv')}")

    # FIF 요약 출력
    fif_latest = fif_df.iloc[-1].dropna().sort_values()
    print(f"\n  FIF 최신값 (낮은순):")
    for c, v in fif_latest.head(10).items():
        print(f"    {c:<15} {v:.3f}")
    print(f"  ...")
    for c, v in fif_latest.tail(5).items():
        print(f"    {c:<15} {v:.3f}")

    # ── 3. 비중 계산 ──
    print("\n비중 계산 중...")
    raw_strategies = {
        'GDP (Prop)': calc_prop(df_gdp),
        'EY (Prop)':  calc_prop(df_per, inverse=True),
        'DY (Prop)':  calc_prop(df_div),
        'MC (Prop)':  calc_prop(df_mc),
        'GDP (ZS)':   calc_zs(df_gdp, use_log=True, T=TEMPERATURE),
        'PER (ZS)':   calc_zs(df_per, inverse=True, T=TEMPERATURE),  # 반전 (밸류)
        'DY (ZS)':    calc_zs(df_div, T=TEMPERATURE),
        'Composite (ZS)': calc_comp([df_gdp,df_per,df_div],[False,True,False],[True,False,False],T=TEMPERATURE),
        'Equal Weight': pd.DataFrame(1.0, index=price_returns.index, columns=price_returns.columns),
    }

    # FIF 적용 버전: MC(Prop)는 이미 FIF 반영이므로 그대로 유지
    fif_strategies = {}
    for name, w in raw_strategies.items():
        if name == 'MC (Prop)':
            fif_strategies[name] = w  # MC는 FIF 추가 적용 안 함
        else:
            fif_strategies[name] = apply_fif_to_weights(w, fif_df)

    # ── 4. 백테스트 (Raw + FIF) ──
    for label, strategies in [('Raw', raw_strategies), ('FIF', fif_strategies)]:
        print(f"\n{'='*90}")
        print(f"백테스트 ({label})")
        print(f"{'='*90}")
        all_summary = []
        chart_results = {}

        for sn, w in strategies.items():
            for un, uc in UNIVERSES.items():
                port = build_portfolio(w, price_returns, uc['countries'])
                if port.empty: continue
                monthly, summary = evaluate(port, bm_returns[uc['bm']], sn, un, uc['bm'])
                if monthly is None: continue
                chart_results[f"{sn}|{un}"] = (monthly, summary)
                all_summary.append(summary)
                print(f"  {sn:23s} | {un:12s} | SR={summary['Sharpe']:.3f} | CumEx={summary['Cum_Excess(%)']:+7.1f}%")

        sdf = pd.DataFrame(all_summary)
        sdf.to_csv(os.path.join(OUT_DIR, f'summary_{label.lower()}.csv'), index=False, encoding='utf-8-sig')

        for sn in strategies:
            safe = sn.replace(' ','_').replace('(','').replace(')','')
            draw_chart(sn, chart_results, os.path.join(OUT_DIR, f'chart_{label.lower()}_{safe}.png'))

    print(f"\n완료!")
    print(f"  FIF 데이터  → {DATA_DIR}/fif_values.csv")
    print(f"  Raw 요약    → {OUT_DIR}/summary_raw.csv")
    print(f"  FIF 요약    → {OUT_DIR}/summary_fif.csv")