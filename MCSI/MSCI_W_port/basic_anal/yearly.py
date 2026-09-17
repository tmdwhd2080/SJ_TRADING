"""
연도별 팩터 분석 + Deep Dive HTML
==================================
출력: yearly_analysis.html
  - 연도별 히트맵 (전략 × 연도 → 초과수익률/승률)
  - Deep Dive: 연도 클릭 → 국가별 기여도 분해
"""
import pandas as pd, numpy as np, json, os, warnings
from datetime import datetime, timedelta
warnings.filterwarnings('ignore')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, '..', 'data')
OUT_DIR  = os.path.join(BASE_DIR, '..', 'output')
FILE_MAIN = os.path.join(DATA_DIR, 'hk_msci_world_f.xlsx')
FILE_BM   = os.path.join(DATA_DIR, 'bm_price.xlsx')
FILE_CTY  = os.path.join(DATA_DIR, 'cty_mkt_cap.xlsx')

DM = ['USA','Japan','UK','France','Canada','Switzerland','Germany','Australia',
      'Netherlands','Sweden','Denmark','Spain','Italy','Hong Kong','Singapore',
      'Belgium','Finland','Israel','Norway','Ireland','New Zealand','Austria','Portugal']
EM = ['China','India','Taiwan','Korea','Brazil','Saudi Arabia','South Africa','Mexico',
      'Indonesia','Malaysia','UAE','Thailand','Kuwait','Qatar','Poland','Chile',
      'Turkey','Greece','Philippines','Hungary','Egypt','Czech Republic','Colombia','Peru']
ALL_47 = DM + EM
univs = {
    'All 47':     {'c':None,'bm':'MSCI ACWI'},
    'All ex USA': {'c':[c for c in ALL_47 if c!='USA'],'bm':'MSCI ACWI ex USA'},
    'DM Only':    {'c':DM,'bm':'MSCI World'},
    'DM ex USA':  {'c':[c for c in DM if c!='USA'],'bm':'MSCI World ex USA'},
    'EM Only':    {'c':EM,'bm':'MSCI EM'},
}

def parse_date(d):
    if isinstance(d, datetime): return d
    if isinstance(d, pd.Timestamp): return d.to_pydatetime()
    if isinstance(d, str):
        for fmt in ['%m/%d/%Y','%m-%d-%y','%Y-%m-%d']:
            try: return datetime.strptime(d, fmt)
            except: pass
    if isinstance(d, (int, float)) and not np.isnan(d):
        return datetime(1899,12,30) + timedelta(days=int(d))
    return None

def load_data(xls, sheet, nr=1, ds=3):
    df = pd.read_excel(xls, sheet_name=sheet, header=None)
    cols = df.iloc[nr, 1:].values
    dates = [parse_date(d) for d in df.iloc[ds:, 0].values]
    vals = pd.to_numeric(df.iloc[ds:, 1:].values.flatten(), errors='coerce').reshape(df.iloc[ds:, 1:].shape)
    r = pd.DataFrame(vals, index=pd.DatetimeIndex(dates), columns=cols)
    return r[r.index.notna()].pipe(lambda x: x[~x.index.duplicated(keep='first')]).sort_index()

def load_bm(fp, sheet):
    df = pd.read_excel(fp, sheet_name=sheet, header=None)
    result = {}
    names = ['MSCI World','MSCI World ex USA','MSCI ACWI','MSCI EM','MSCI ACWI ex USA']
    for ci, cn in enumerate(names):
        dates, vals = [], []
        for r in range(1, len(df)):
            d, v = df.iloc[r, 0], df.iloc[r, ci+1]
            if pd.notna(d) and pd.notna(v):
                dates.append(pd.Timestamp(d)); vals.append(float(v))
        s = pd.Series(vals, index=pd.DatetimeIndex(dates)).sort_index()
        s = s[~s.index.duplicated(keep='first')]
        result[cn] = s.pct_change().dropna()
    return result

def softmax(z, T=1.0):
    zs=z/T; zs=zs-np.nanmax(zs); e=np.exp(zs); e=np.where(np.isnan(z),0,e)
    s=np.nansum(e); return e/s if s>0 else np.full_like(z,np.nan)
def calc_prop(df, inv=False):
    if inv: t=(1.0/df.replace(0,np.nan)).clip(lower=0)
    else: t=df.clip(lower=0)
    return t.div(t.sum(axis=1),axis=0)
def calc_prop_pos(df):
    t=df.clip(lower=0); s=t.sum(axis=1); return t.div(s.replace(0,np.nan),axis=0)
def calc_zs(df, inv=False, log=False, T=1.0):
    r=pd.DataFrame(index=df.index,columns=df.columns,dtype=float)
    for d in df.index:
        row=df.loc[d].astype(float); v=row.notna()&(row>0)
        if v.sum()<5: continue
        vals=row[v].copy()
        if log: vals=np.log(vals)
        if inv: vals=-vals
        mu,sig=vals.mean(),vals.std()
        if sig==0 or np.isnan(sig): continue
        r.loc[d,v]=softmax(((vals-mu)/sig).values,T)
    return r
def calc_zs_any(df, T=1.0):
    r=pd.DataFrame(index=df.index,columns=df.columns,dtype=float)
    for d in df.index:
        row=df.loc[d].astype(float); v=row.notna()
        if v.sum()<5: continue
        vals=row[v].copy(); mu,sig=vals.mean(),vals.std()
        if sig==0 or np.isnan(sig): continue
        r.loc[d,v]=softmax(((vals-mu)/sig).values,T)
    return r
def calc_comp(dfs,invs,logs,T=1.0):
    cd=dfs[0].index
    for df in dfs[1:]: cd=cd.intersection(df.index)
    cd=cd.sort_values(); cc=dfs[0].columns
    for df in dfs[1:]: cc=cc.intersection(df.columns)
    r=pd.DataFrame(index=cd,columns=cc,dtype=float)
    for d in cd:
        zl=[]
        for df,inv,ul in zip(dfs,invs,logs):
            if d not in df.index: continue
            row=df.loc[d][cc].astype(float); v=row.notna()&(row>0)
            if v.sum()<5: continue
            vals=row[v].copy()
            if ul: vals=np.log(vals)
            if inv: vals=-vals
            mu,sig=vals.mean(),vals.std()
            if sig==0 or np.isnan(sig): continue
            zl.append((vals-mu)/sig)
        if not zl: continue
        az=pd.concat(zl,axis=1).mean(axis=1); va=az.notna()
        if va.sum()<5: continue
        sm=softmax(az[va].values,T)
        for c2,sv in zip(list(va[va].index),sm): r.at[d,c2]=sv
    return r

def build_port_detailed(weights, returns, country_filter=None):
    """포트 수익률 + 국가별 기여도 반환"""
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
        contribs = (wn * r[ok])
        rec = {'date': ret_date, 'ret': float(contribs.sum())}
        # 상위 5 + 하위 5 기여도
        for c_name, c_val in contribs.items():
            rec[f'w_{c_name}'] = float(wn.get(c_name, 0))
            rec[f'c_{c_name}'] = float(c_val)
            rec[f'r_{c_name}'] = float(r[c_name]) if pd.notna(r[c_name]) else 0
        records.append(rec)
    if not records: return pd.DataFrame()
    return pd.DataFrame(records).set_index('date').sort_index()

# ══════════════════════════════════════════════════════════════
print("Loading...")
xls = pd.ExcelFile(FILE_MAIN)
df_gdp=load_data(xls,'Sheet4',1,3); df_per=load_data(xls,'Sheet7',1,3)
df_div=load_data(xls,'Sheet8',1,3); df_mc=load_data(xls,'Sheet5',1,3)
df_price=load_data(xls,'Sheet10',1,5)
df_roe=load_data(xls,'Sheet2',1,3); df_roa=load_data(xls,'Sheet11',1,3)
df_eps=load_data(xls,'Sheet15',1,3)
bm_returns = load_bm(os.path.join(DATA_DIR,'bm_price.xlsx'), 'Sheet2')
price_returns = df_price.pct_change().iloc[1:].replace([np.inf,-np.inf], np.nan)
df_mom = (df_price.shift(1)/df_price.shift(12)-1).replace([np.inf,-np.inf],np.nan)
df_pbr = (df_per * df_roe / 100).replace([np.inf,-np.inf], np.nan)
df_epsg = ((df_eps - df_eps.shift(12)) / df_eps.shift(12).abs()).replace([np.inf,-np.inf], np.nan).clip(-5, 5)

print("Weights...")
strats = {
    # 비례
    'GDP (Prop)': calc_prop(df_gdp),
    'EY (Prop)': calc_prop(df_per, inv=True),
    'DY (Prop)': calc_prop(df_div),
    'MC (Prop)': calc_prop(df_mc),
    'ROE (Prop)': calc_prop(df_roe),
    'ROA (Prop)': calc_prop(df_roa),
    '1/PBR (Prop)': calc_prop(df_pbr, inv=True),
    'Mom (Prop)': calc_prop_pos(df_mom),
    'EPSg (Prop)': calc_prop_pos(df_epsg),
    # ZS
    'ROE (ZS)': calc_zs(df_roe),
    'ROA (ZS)': calc_zs(df_roa),
    'PBR (ZS)': calc_zs(df_pbr, inv=True),
    'Mom (ZS)': calc_zs_any(df_mom),
    'EPSg (ZS)': calc_zs_any(df_epsg),
    'Comp+ (ZS)': calc_comp([df_gdp,df_per,df_div,df_roe,df_mom],[0,1,0,0,0],[1,0,0,0,0]),
}
ew = pd.DataFrame(1.0, index=price_returns.index, columns=price_returns.columns)
strats['Equal Weight'] = ew

print("Yearly analysis...")
# 연도별 분석 데이터 수집
yearly_data = {}  # {univ: {strat: {year: {ret, bm_ret, excess, win_months, lose_months, contribs}}}}

for un, uc in univs.items():
    bmn = uc['bm']; bmr = bm_returns[bmn]
    yearly_data[un] = {}
    
    for sn, w in strats.items():
        port = build_port_detailed(w, price_returns, uc['c'])
        if port.empty: continue
        
        # 월별 포트 수익률 vs BM
        ci = port.index.intersection(bmr.index)
        if len(ci) < 12: continue
        p_ret = port['ret'].reindex(ci)
        b_ret = bmr.reindex(ci)
        ci2 = p_ret.dropna().index.intersection(b_ret.dropna().index)
        p_ret, b_ret = p_ret.loc[ci2], b_ret.loc[ci2]
        
        strat_yearly = {}
        years = sorted(set(ci2.year))
        
        for yr in years:
            mask = ci2.year == yr
            yr_p = p_ret[mask]
            yr_b = b_ret[mask]
            if len(yr_p) < 3: continue
            
            yr_excess = yr_p - yr_b
            ann_p = (1+yr_p).prod() - 1
            ann_b = (1+yr_b).prod() - 1
            ann_ex = (1+yr_excess).prod() - 1
            win = (yr_excess > 0).sum()
            lose = (yr_excess <= 0).sum()
            
            # 국가별 기여도 (해당 연도 합계)
            country_cols_w = [c for c in port.columns if c.startswith('w_')]
            country_cols_c = [c for c in port.columns if c.startswith('c_')]
            country_cols_r = [c for c in port.columns if c.startswith('r_')]
            
            yr_port = port.loc[mask]
            contribs = {}
            for wc, cc, rc in zip(country_cols_w, country_cols_c, country_cols_r):
                cname = wc[2:]  # remove 'w_' prefix
                avg_w = yr_port[wc].mean() * 100  # 평균 비중 (%)
                tot_c = yr_port[cc].sum() * 100    # 총 기여도 (%p)
                avg_r = ((1+yr_port[rc]).prod()-1) * 100  # 연간 수익률 (%)
                if abs(avg_w) > 0.01:
                    contribs[cname] = {
                        'w': round(avg_w, 2),
                        'c': round(tot_c, 3),
                        'r': round(avg_r, 1),
                    }
            
            # 기여도 상위/하위 정렬
            sorted_c = sorted(contribs.items(), key=lambda x: x[1]['c'], reverse=True)
            top5 = sorted_c[:5]
            bot5 = sorted_c[-5:]
            
            strat_yearly[yr] = {
                'ret': round(ann_p*100, 1),
                'bm': round(ann_b*100, 1),
                'ex': round(ann_ex*100, 1),
                'win': int(win),
                'lose': int(lose),
                'months': int(len(yr_p)),
                'top5': [[c, d] for c, d in top5],
                'bot5': [[c, d] for c, d in bot5],
            }
        
        yearly_data[un][sn] = strat_yearly
        print(f"  {sn:20s} | {un:12s} | {len(strat_yearly)} years")

# JSON
js = f"const Y={json.dumps(yearly_data, separators=(',',':'))};"

# ══════════════════════════════════════════════════════════════
# HTML
# ══════════════════════════════════════════════════════════════
html = '''<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Segoe UI',system-ui,sans-serif;background:#0f1117;color:#e0e0e0;padding:20px;max-width:1300px;margin:0 auto}
h1{font-size:20px;font-weight:600;color:#fff;margin-bottom:4px}
.sub{font-size:11px;color:#777;margin-bottom:16px}
.card{background:#1a1d27;border-radius:10px;padding:16px;border:1px solid #2a2d3a;margin-bottom:14px}
.card h2{font-size:13px;font-weight:600;margin-bottom:10px;color:#a0a8c0}
.row{display:flex;align-items:center;gap:16px;margin-bottom:10px}
.row-label{font-size:11px;color:#555;font-weight:600;min-width:70px}
.tabs{display:flex;gap:4px;flex-wrap:wrap}
.tab{padding:5px 10px;border-radius:6px;font-size:10px;cursor:pointer;background:#252836;color:#888;border:none}
.tab.active{background:#4f46e5;color:#fff}.tab:hover:not(.active){background:#303348}
.utab{padding:5px 10px;border-radius:5px;font-size:10px;cursor:pointer;background:#252836;color:#888;border:none}
.utab.active{background:#065f46;color:#34d399}.utab:hover:not(.active){background:#303348}

/* 히트맵 테이블 */
.hm{width:100%;border-collapse:collapse;font-size:10px;margin-top:10px}
.hm th{padding:4px 6px;text-align:center;color:#7a8098;font-weight:500;border-bottom:2px solid #2a2d3a;position:sticky;top:0;background:#1a1d27}
.hm td{padding:4px 6px;text-align:center;border-bottom:1px solid #1e2130;cursor:pointer;transition:opacity .15s}
.hm td:hover{opacity:0.7}
.hm .strat-name{text-align:left;font-weight:600;color:#a0a8c0;min-width:100px}

/* Deep dive */
.dd{background:#151822;border-radius:8px;padding:14px;margin-top:12px;border:1px solid #2a2d3a;display:none}
.dd.show{display:block}
.dd h3{font-size:12px;font-weight:600;color:#818cf8;margin-bottom:8px}
.dd-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.dd-section{background:#1a1d27;border-radius:6px;padding:10px}
.dd-section h4{font-size:11px;color:#a0a8c0;margin-bottom:6px}
.bar-row{display:flex;align-items:center;gap:4px;margin-bottom:3px;font-size:10px}
.bar-label{width:85px;text-align:right;color:#999;flex-shrink:0;overflow:hidden;text-overflow:ellipsis}
.bar-track{flex:1;height:14px;background:#1e2130;border-radius:3px;overflow:hidden;position:relative}
.bar-fill{height:100%;border-radius:3px;position:absolute;top:0}
.bar-pos{background:#4ade80}.bar-neg{background:#f87171}
.bar-val{width:50px;text-align:right;color:#ccc;flex-shrink:0;font-size:9px}
.pos{color:#4ade80}.neg{color:#f87171}
.sum-row{display:flex;gap:20px;margin-bottom:8px;font-size:11px}
.sum-item{display:flex;gap:4px}
.sum-label{color:#666}.sum-val{font-weight:600}
a{color:#818cf8}
</style></head><body>
<h1>연도별 팩터 분석</h1>
<div class="sub"><a href="factor_anal.html">&larr; 대시보드</a> | 셀 클릭 → Deep Dive</div>

<div class="card">
<div class="row"><div class="row-label">유니버스</div><div class="tabs" id="uT"></div></div>
<div class="row"><div class="row-label">지표</div><div class="tabs" id="mT"></div></div>
</div>

<div class="card"><h2 id="hmTitle">연도별 초과수익률 (%)</h2>
<div style="overflow-x:auto"><table class="hm" id="hmTable"><thead id="hmHead"></thead><tbody id="hmBody"></tbody></table></div>
</div>

<div class="dd" id="ddPanel">
<h3 id="ddTitle">Deep Dive</h3>
<div class="sum-row" id="ddSum"></div>
<div class="dd-grid">
<div class="dd-section"><h4>🟢 기여도 상위 5</h4><div id="ddTop"></div></div>
<div class="dd-section"><h4>🔴 기여도 하위 5</h4><div id="ddBot"></div></div>
</div>
</div>

<script>
'''+js+'''
const uK=Object.keys(Y);
const metrics=['excess','winrate'];
const metricLabels={'excess':'초과수익률 (%)','winrate':'월간 승률'};
let cU=uK[0],cM='excess';

function init(){
  mkT('uT','utab',uK,null,v=>{cU=v;render()},cU);
  mkT('mT','tab',Object.keys(metricLabels),metricLabels,v=>{cM=v;render()},cM);
  render();
}
function mkT(id,cls,keys,labels,cb,cur){
  const el=document.getElementById(id);
  keys.forEach(k=>{const b=document.createElement('button');
    b.className=cls+(k===cur?' active':'');b.textContent=(labels&&labels[k])||k;b.dataset.key=k;
    b.onclick=()=>{cb(k);el.querySelectorAll('.'+cls).forEach(t=>t.className=cls+(t.dataset.key===k?' active':''))};
    el.appendChild(b)});
}

function render(){
  const data=Y[cU]; if(!data) return;
  document.getElementById('hmTitle').textContent=metricLabels[cM]+' — '+cU;
  
  // Collect all years
  const allYears=new Set();
  Object.values(data).forEach(sd=>Object.keys(sd).forEach(y=>allYears.add(y)));
  const years=[...allYears].sort();
  
  // Header
  const thead=document.getElementById('hmHead');
  thead.innerHTML='<tr><th class="strat-name">전략</th>'+years.map(y=>'<th>'+y+'</th>').join('')+'<th>평균</th></tr>';
  
  // Body
  const tbody=document.getElementById('hmBody');
  tbody.innerHTML='';
  const stratNames=Object.keys(data);
  
  stratNames.forEach(sn=>{
    const sd=data[sn];
    let tr='<tr><td class="strat-name">'+sn+'</td>';
    let vals=[];
    
    years.forEach(yr=>{
      const yd=sd[yr];
      if(!yd){tr+='<td style="color:#333">—</td>';return}
      
      let val, display;
      if(cM==='excess'){
        val=yd.ex; display=val.toFixed(1);
      } else {
        val=yd.months>0?yd.win/yd.months*100:0;
        display=val.toFixed(0)+'%';
      }
      vals.push(val);
      
      // Color
      let bg;
      if(cM==='excess'){
        if(val>15) bg='rgba(74,222,128,0.35)';
        else if(val>5) bg='rgba(74,222,128,0.2)';
        else if(val>0) bg='rgba(74,222,128,0.08)';
        else if(val>-5) bg='rgba(248,113,113,0.08)';
        else if(val>-15) bg='rgba(248,113,113,0.2)';
        else bg='rgba(248,113,113,0.35)';
      } else {
        if(val>=70) bg='rgba(74,222,128,0.35)';
        else if(val>=55) bg='rgba(74,222,128,0.15)';
        else if(val>=45) bg='transparent';
        else if(val>=30) bg='rgba(248,113,113,0.15)';
        else bg='rgba(248,113,113,0.35)';
      }
      
      const cls=val>=0?'pos':'neg';
      tr+='<td style="background:'+bg+'" class="'+cls+'" data-sn="'+sn+'" data-yr="'+yr+'">'
        +display+'</td>';
    });
    
    // Average
    const avg=vals.length>0?vals.reduce((a,b)=>a+b,0)/vals.length:0;
    const avgCls=avg>=0?'pos':'neg';
    if(cM==='excess') tr+='<td style="font-weight:700" class="'+avgCls+'">'+avg.toFixed(1)+'</td>';
    else tr+='<td style="font-weight:700">'+avg.toFixed(0)+'%</td>';
    
    tr+='</tr>';
    tbody.innerHTML+=tr;
  });
  
  // Event delegation for deep dive
  tbody.querySelectorAll('td[data-sn]').forEach(td=>{
    td.style.cursor='pointer';
    td.addEventListener('click',function(){
      deepDive(this.dataset.sn, this.dataset.yr);
    });
  });
}

function deepDive(strat, year){
  const data=Y[cU]?.[strat]?.[''+year];
  if(!data) return;
  
  const panel=document.getElementById('ddPanel');
  panel.classList.add('show');
  
  document.getElementById('ddTitle').textContent=strat+' — '+cU+' — '+year+'년 Deep Dive';
  
  // Summary
  const sumEl=document.getElementById('ddSum');
  sumEl.innerHTML=
    '<div class="sum-item"><span class="sum-label">포트:</span><span class="sum-val '+(data.ret>=0?'pos':'neg')+'">'+data.ret.toFixed(1)+'%</span></div>'+
    '<div class="sum-item"><span class="sum-label">벤치:</span><span class="sum-val">'+data.bm.toFixed(1)+'%</span></div>'+
    '<div class="sum-item"><span class="sum-label">초과:</span><span class="sum-val '+(data.ex>=0?'pos':'neg')+'">'+data.ex.toFixed(1)+'%</span></div>'+
    '<div class="sum-item"><span class="sum-label">승/패:</span><span class="sum-val">'+data.win+'/'+data.lose+'</span></div>';
  
  // Top 5
  renderContribs('ddTop', data.top5, true);
  renderContribs('ddBot', data.bot5, false);
  
  // Scroll to panel
  panel.scrollIntoView({behavior:'smooth', block:'start'});
}

function renderContribs(id, items, isTop){
  const el=document.getElementById(id);
  if(!items||items.length===0){el.innerHTML='<div style="color:#555">데이터 없음</div>';return}
  
  const maxAbs=Math.max(...items.map(([_,d])=>Math.abs(d.c)),0.01);
  let html='';
  items.forEach(([country, d])=>{
    const barW=Math.abs(d.c)/maxAbs*80;
    const cls=d.c>=0?'bar-pos':'bar-neg';
    const valCls=d.c>=0?'pos':'neg';
    html+='<div class="bar-row">'
      +'<div class="bar-label">'+country+'</div>'
      +'<div class="bar-track"><div class="bar-fill '+cls+'" style="width:'+barW+'%;'+(d.c<0?'right:0':'')+'"></div></div>'
      +'<div class="bar-val"><span class="'+valCls+'">'+d.c.toFixed(2)+'%p</span></div>'
      +'</div>'
      +'<div style="font-size:9px;color:#555;margin-left:89px;margin-bottom:4px">비중:'+d.w.toFixed(1)+'% | 수익률:'+d.r.toFixed(1)+'%</div>';
  });
  el.innerHTML=html;
}

init();
</script></body></html>'''

os.makedirs(OUT_DIR, exist_ok=True)
with open(os.path.join(OUT_DIR, 'yearly_analysis.html'), 'w', encoding='utf-8') as f:
    f.write(html)
print(f"\n저장 → {os.path.join(OUT_DIR, 'yearly_analysis.html')}")
print("Done!")