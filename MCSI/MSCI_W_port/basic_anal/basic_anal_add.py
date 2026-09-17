"""
국가 팩터 가중 전략 — 확장 팩터 분석 (v1)
==========================================
기존: GDP / EY / DY / MC / PER(ZS) / Composite
추가: ROE / ROA / PBR(=PER×ROE) / Momentum(12-1M) / EPS Growth(YoY)

파일: hk_msci_world_f.xlsx (data 폴더에 저장)
     cty_mkt_cap.xlsx (FIF용)
     bm_price.xlsx

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
FILE_MAIN = os.path.join(DATA_DIR, 'hk_msci_world_f.xlsx')
FILE_BM   = os.path.join(DATA_DIR, 'bm_price.xlsx')
FILE_CTY  = os.path.join(DATA_DIR, 'cty_mkt_cap.xlsx')

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
for c in [r'C:/Windows/Fonts/malgun.ttf','/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
          '/usr/share/fonts/truetype/nanum/NanumGothic.ttf']:
    if os.path.exists(c):
        fm.fontManager.addfont(c)
        plt.rcParams['font.family'] = fm.FontProperties(fname=c).get_name(); break
plt.rcParams['axes.unicode_minus'] = False

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
    df = pd.read_excel(xls, sheet_name=sheet, header=None)
    cols = df.iloc[name_row, 1:].values
    dates = pd.DatetimeIndex([parse_date(d) for d in df.iloc[data_start:, 0].values])
    vals = pd.to_numeric(df.iloc[data_start:, 1:].values.flatten(), errors='coerce')
    vals = vals.reshape(df.iloc[data_start:, 1:].shape)
    r = pd.DataFrame(vals, index=dates, columns=cols)
    return r[r.index.notna()].pipe(lambda x: x[~x.index.duplicated(keep='first')]).sort_index()

def load_benchmarks(fp):
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
# ▶ 파생 팩터 계산
# ══════════════════════════════════════════════════════════════
def calc_momentum(df_price, lookback=12, skip=1):
    """
    Momentum (12-1M): 12개월 수익률에서 최근 1개월 제외
    MOM_i,t = Price_i,t-skip / Price_i,t-lookback - 1
    """
    mom = df_price.shift(skip) / df_price.shift(lookback) - 1
    return mom.replace([np.inf, -np.inf], np.nan)

def calc_eps_growth(df_eps, periods=12):
    """EPS YoY 변화율: (EPS_t - EPS_t-12) / |EPS_t-12|"""
    eps_prev = df_eps.shift(periods)
    growth = (df_eps - eps_prev) / eps_prev.abs()
    return growth.replace([np.inf, -np.inf], np.nan).clip(-5, 5)  # 극단값 제한

def calc_pbr(df_per, df_roe):
    """PBR = PER × ROE / 100"""
    common_dates = df_per.index.intersection(df_roe.index)
    common_cols = df_per.columns.intersection(df_roe.columns)
    pbr = df_per.loc[common_dates, common_cols] * df_roe.loc[common_dates, common_cols] / 100
    return pbr.replace([np.inf, -np.inf], np.nan)

# ══════════════════════════════════════════════════════════════
# ▶ FIF
# ══════════════════════════════════════════════════════════════
def calc_fif(df_msci_mc, file_cty):
    try:
        xls_c = pd.ExcelFile(file_cty)
        for sn in xls_c.sheet_names:
            if sn.startswith('__'): continue
            df_c = pd.read_excel(xls_c, sheet_name=sn, header=None)
            if df_c.shape[0] > 5: break
        cols_c = df_c.iloc[1, 1:].values
        dates_c = pd.DatetimeIndex([parse_date(d) for d in df_c.iloc[3:, 0].values])
        vals_c = pd.to_numeric(df_c.iloc[3:, 1:].values.flatten(), errors='coerce').reshape(df_c.iloc[3:, 1:].shape)
        df_total = pd.DataFrame(vals_c, index=dates_c, columns=cols_c)
        df_total = df_total[df_total.index.notna()].pipe(lambda x: x[~x.index.duplicated(keep='first')]).sort_index()
        print(f"  국가전체 시총: {df_total.shape}, {df_total.index[0]:%Y-%m} ~ {df_total.index[-1]:%Y-%m}")
    except Exception as e:
        print(f"  WARNING: 국가전체 시총 로드 실패 ({e}). FIF=1.0")
        return pd.DataFrame(1.0, index=df_msci_mc.index, columns=df_msci_mc.columns)
    cd = df_msci_mc.index.intersection(df_total.index)
    cc = df_msci_mc.columns.intersection(df_total.columns)
    fif = (df_msci_mc.loc[cd, cc] / df_total.loc[cd, cc].replace(0, np.nan)).clip(0, 1.5)
    fif = fif.reindex(df_msci_mc.index).ffill().bfill()
    for c in df_msci_mc.columns:
        if c not in fif.columns: fif[c] = 1.0
    return fif

def apply_fif(w, fif):
    cd = w.index.intersection(fif.index); cc = w.columns.intersection(fif.columns)
    adj = w.loc[cd, cc] * fif.loc[cd, cc]
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
    """단순 비례 가중. inverse=True: 1/x 비례 (PER→EY, PBR→1/PBR)"""
    if inverse:
        t = (1.0/df.replace(0, np.nan)).clip(lower=0)
    else:
        t = df.clip(lower=0)
    return t.div(t.sum(axis=1), axis=0)

def calc_prop_positive(df):
    """양수만 비례 가중 (모멘텀, EPS Growth용). 음수 국가는 비중 0."""
    t = df.clip(lower=0)
    row_sum = t.sum(axis=1)
    return t.div(row_sum.replace(0, np.nan), axis=0)

def calc_zs(df, inverse=False, use_log=False, T=1.0):
    """Z-score + Softmax 가중"""
    result = pd.DataFrame(index=df.index, columns=df.columns, dtype=float)
    for d in df.index:
        row = df.loc[d].astype(float); valid = row.notna() & (row > 0) if not inverse else row.notna()
        if use_log:
            valid = valid & (row > 0)
        if valid.sum() < 5: continue
        vals = row[valid].copy()
        if use_log: vals = np.log(vals)
        if inverse: vals = -vals
        mu, sig = vals.mean(), vals.std()
        if sig == 0 or np.isnan(sig): continue
        result.loc[d, valid] = softmax(((vals-mu)/sig).values, T)
    return result

def calc_zs_any(df, inverse=False, T=1.0):
    """음수 값도 허용하는 ZS (모멘텀, EPS Growth용)"""
    result = pd.DataFrame(index=df.index, columns=df.columns, dtype=float)
    for d in df.index:
        row = df.loc[d].astype(float); valid = row.notna()
        if valid.sum() < 5: continue
        vals = row[valid].copy()
        if inverse: vals = -vals
        mu, sig = vals.mean(), vals.std()
        if sig == 0 or np.isnan(sig): continue
        result.loc[d, valid] = softmax(((vals-mu)/sig).values, T)
    return result

def calc_comp(dfs, inverses, use_logs, T=1.0):
    """여러 팩터 z-score 평균 → softmax"""
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
            row = df.loc[d][cc].astype(float)
            valid = row.notna() & (row > 0) if ul else row.notna() & (row > 0)
            if valid.sum() < 5: continue
            vals = row[valid].copy()
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
    'GDP (Prop)':'#2563EB','EY (Prop)':'#DB2777','DY (Prop)':'#D97706','MC (Prop)':'#0891B2',
    'ROE (Prop)':'#7C3AED','ROA (Prop)':'#2DD4BF','1/PBR (Prop)':'#F97316',
    'Mom (Prop)':'#EC4899','EPSg (Prop)':'#8B5CF6',
    'GDP (ZS)':'#4F46E5','PER (ZS)':'#A855F7','DY (ZS)':'#EA580C',
    'ROE (ZS)':'#7C3AED','ROA (ZS)':'#2DD4BF','PBR (ZS)':'#F97316',
    'Mom (ZS)':'#EC4899','EPSg (ZS)':'#8B5CF6',
    'Composite (ZS)':'#65A30D','Comp+ (ZS)':'#16A34A',
    'Equal Weight':'#6B7280',
}
BM_COLOR = '#059669'

def draw_chart(metric_name, results_by_univ, out_path):
    fig, axes = plt.subplots(3, 2, figsize=(20, 16)); fig.patch.set_facecolor('#F8FAFC')
    univ_list = list(UNIVERSES.items())
    for idx in range(6):
        ax = axes[idx//2][idx%2]; ax.set_facecolor('#FFFFFF')
        if idx >= len(univ_list): ax.axis('off'); continue
        univ_name, univ_cfg = univ_list[idx]
        data = results_by_univ.get(f"{metric_name}|{univ_name}")
        if data is None: ax.text(0.5,0.5,'No Data',ha='center',va='center',transform=ax.transAxes); continue
        monthly, summary = data; x = monthly.index.to_pydatetime()
        ax.plot(x, monthly['Cum_Port']*100, color=COLORS.get(metric_name,'#2563EB'), lw=2, label=metric_name)
        ax.plot(x, monthly['Cum_BM']*100, color=BM_COLOR, lw=1.5, ls='--', label=univ_cfg['bm'])
        ax.axhline(0, color='#D1D5DB', lw=0.8)
        exc = monthly['Cum_Excess']*100
        ax.fill_between(x,0,exc,where=(exc>=0),alpha=0.12,color=COLORS.get(metric_name,'#2563EB'),interpolate=True)
        ax.fill_between(x,0,exc,where=(exc<0),alpha=0.12,color='red',interpolate=True)
        info = (f"승률: {summary['Win_Rate(%)']:.1f}%\n누적초과: {summary['Cum_Excess(%)']:+.1f}%\n"
                f"Sharpe: {summary['Sharpe']:.3f}\n포트 누적: {summary['Cum_Return(%)']:.1f}%\n"
                f"벤치 누적: {monthly['Cum_BM'].iloc[-1]*100:.1f}%")
        ax.text(0.02,0.97,info,transform=ax.transAxes,fontsize=8,va='top',
                bbox=dict(boxstyle='round,pad=0.4',facecolor='white',edgecolor='#CBD5E1',alpha=0.9))
        ax.xaxis.set_major_locator(mdates.YearLocator(2)); ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
        ax.tick_params(axis='x',labelsize=8)
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v,_:f'{v:.0f}%'))
        ax.tick_params(axis='y',labelsize=8)
        ax.grid(axis='y',ls=':',lw=0.5,color='#E2E8F0'); ax.spines[['top','right']].set_visible(False)
        ax.set_title(f"{univ_name} vs {univ_cfg['bm']}", fontsize=10, fontweight='bold')
        ax.legend(fontsize=8, loc='upper left', framealpha=0.8)
    fig.suptitle(f'{metric_name} — 누적수익률', fontsize=13, fontweight='bold', y=1.01)
    plt.tight_layout(); plt.savefig(out_path,dpi=150,bbox_inches='tight',facecolor=fig.get_facecolor()); plt.close()
    print(f"  차트 → {out_path}")

# ══════════════════════════════════════════════════════════════
# ▶ 메인
# ══════════════════════════════════════════════════════════════
if __name__ == '__main__':
    os.makedirs(OUT_DIR, exist_ok=True)

    # ── 1. 데이터 로드 ──
    print("데이터 로드 중...")
    xls = pd.ExcelFile(FILE_MAIN)
    df_gdp   = load_sheet(xls, 'Sheet4',   name_row=1, data_start=3)   # GDP
    df_per   = load_sheet(xls, 'Sheet7',    name_row=1, data_start=3)   # PER
    df_div   = load_sheet(xls, 'Sheet8',    name_row=1, data_start=3)   # DY
    df_mc    = load_sheet(xls, 'Sheet5',    name_row=1, data_start=3)   # Market Cap
    df_price = load_sheet(xls, 'Sheet10',   name_row=1, data_start=5)   # Price
    df_roe   = load_sheet(xls, 'Sheet2',    name_row=1, data_start=3)   # ROE
    df_roa   = load_sheet(xls, 'Sheet11',   name_row=1, data_start=3)   # ROA
    df_eps   = load_sheet(xls, 'Sheet15',   name_row=1, data_start=3)   # EPS
    bm_returns = load_benchmarks(FILE_BM)
    price_returns = df_price.pct_change().iloc[1:].replace([np.inf,-np.inf], np.nan)

    print(f"  GDP:{df_gdp.shape} PER:{df_per.shape} DY:{df_div.shape} MC:{df_mc.shape}")
    print(f"  ROE:{df_roe.shape} ROA:{df_roa.shape} EPS:{df_eps.shape} Price:{df_price.shape}")

    # ── 2. 파생 팩터 ──
    print("\n파생 팩터 계산 중...")
    df_pbr   = calc_pbr(df_per, df_roe)
            df_mom   = calc_momentum(df_price, lookback=12, skip=1)
    df_epsg  = calc_eps_growth(df_eps, periods=12)
    print(f"  PBR:{df_pbr.shape} Mom:{df_mom.shape} EPSg:{df_epsg.shape}")

    # ── 3. FIF ──
    print("\nFIF 계산 중...")
    fif_df = calc_fif(df_mc, FILE_CTY)
    fif_save = fif_df.copy(); fif_save.index = fif_save.index.strftime('%Y-%m-%d')
    fif_save.to_csv(os.path.join(DATA_DIR, 'fif_values.csv'), encoding='utf-8-sig')

    # ── 4. 전략 비중 계산 ──
    print("\n비중 계산 중...")
    raw_strategies = {
        # ── 단순 비례 ──
        'GDP (Prop)':   calc_prop(df_gdp),
        'EY (Prop)':    calc_prop(df_per, inverse=True),
        'DY (Prop)':    calc_prop(df_div),
        'MC (Prop)':    calc_prop(df_mc),
        'ROE (Prop)':   calc_prop(df_roe),
        'ROA (Prop)':   calc_prop(df_roa),
        '1/PBR (Prop)': calc_prop(df_pbr, inverse=True),
        'Mom (Prop)':   calc_prop_positive(df_mom),
        'EPSg (Prop)':  calc_prop_positive(df_epsg),
        # ── Z-score + Softmax ──
        'GDP (ZS)':     calc_zs(df_gdp, use_log=True, T=TEMPERATURE),
        'PER (ZS)':     calc_zs(df_per, inverse=True, T=TEMPERATURE),  # 반전 (밸류)
        'DY (ZS)':      calc_zs(df_div, T=TEMPERATURE),
        'ROE (ZS)':     calc_zs(df_roe, T=TEMPERATURE),
        'ROA (ZS)':     calc_zs(df_roa, T=TEMPERATURE),
        'PBR (ZS)':     calc_zs(df_pbr, inverse=True, T=TEMPERATURE),  # 낮을수록 좋음
        'Mom (ZS)':     calc_zs_any(df_mom, T=TEMPERATURE),
        'EPSg (ZS)':    calc_zs_any(df_epsg, T=TEMPERATURE),
        # ── 복합 ──
        'Composite (ZS)': calc_comp(
            [df_gdp, df_per, df_div],
            [False, True, False], [True, False, False], T=TEMPERATURE),
        'Comp+ (ZS)': calc_comp(
            [df_gdp, df_per, df_div, df_roe, df_mom],
            [False, True, False, False, False],
            [True, False, False, False, False], T=TEMPERATURE),
        # ── Equal Weight ──
        'Equal Weight': pd.DataFrame(1.0, index=price_returns.index, columns=price_returns.columns),
    }

    # FIF 적용
    fif_strategies = {}
    for name, w in raw_strategies.items():
        if name == 'MC (Prop)':   # MC는 이미 FIF 반영
            fif_strategies[name] = w
        else:
            fif_strategies[name] = apply_fif(w, fif_df)

    # ── 5. 백테스트 ──
    for label, strategies in [('Raw', raw_strategies), ('FIF', fif_strategies)]:
        print(f"\n{'='*90}\n백테스트 ({label})\n{'='*90}")
        all_summary = []; chart_results = {}
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
        sdf.to_csv(os.path.join(OUT_DIR, f'factor_summary_{label.lower()}.csv'), index=False, encoding='utf-8-sig')

        for sn in strategies:
            safe = sn.replace(' ','_').replace('(','').replace(')','').replace('/','').replace('+','p')
            draw_chart(sn, chart_results, os.path.join(OUT_DIR, f'factor_{label.lower()}_{safe}.png'))

    print(f"\n완료!")