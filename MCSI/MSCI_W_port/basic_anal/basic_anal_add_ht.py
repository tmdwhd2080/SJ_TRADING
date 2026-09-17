"""
확장 팩터 분석 → HTML Dashboard + Weight Viewer (FIF 토글)
==========================================================
카테고리: Value / Quality / Macro / Momentum / Composite
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

# ── 카테고리별 전략 그룹 ──
CATEGORIES = {
    'Value':    ['EY (Prop)','DY (Prop)','1/PBR (Prop)','PER (ZS)','DY (ZS)','PBR (ZS)','Equal Weight'],
    'Quality':  ['ROE (Prop)','ROA (Prop)','ROE (ZS)','ROA (ZS)','Equal Weight'],
    'Macro':    ['GDP (Prop)','MC (Prop)','GDP (ZS)','Equal Weight'],
    'Momentum': ['Mom (Prop)','EPSg (Prop)','Mom (ZS)','EPSg (ZS)','Equal Weight'],
    'Composite':['Composite (ZS)','Comp+ (ZS)','Equal Weight'],
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

def calc_fif(df_mc, file_cty):
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
    except: return pd.DataFrame(1.0, index=df_mc.index, columns=df_mc.columns)
    cd = df_mc.index.intersection(df_total.index); cc = df_mc.columns.intersection(df_total.columns)
    fif = (df_mc.loc[cd, cc] / df_total.loc[cd, cc].replace(0, np.nan)).clip(0, 1.5)
    fif = fif.reindex(df_mc.index).ffill().bfill()
    for c in df_mc.columns:
        if c not in fif.columns: fif[c] = 1.0
    return fif

def apply_fif(w, fif):
    cd = w.index.intersection(fif.index); cc = w.columns.intersection(fif.columns)
    adj = w.loc[cd, cc] * fif.loc[cd, cc]
    return adj.div(adj.sum(axis=1), axis=0)

def softmax(z, T=1.0):
    zs=z/T; zs=zs-np.nanmax(zs); e=np.exp(zs); e=np.where(np.isnan(z),0,e)
    s=np.nansum(e); return e/s if s>0 else np.full_like(z,np.nan)

def calc_prop(df, inverse=False):
    if inverse: t=(1.0/df.replace(0,np.nan)).clip(lower=0)
    else: t=df.clip(lower=0)
    return t.div(t.sum(axis=1),axis=0)

def calc_prop_pos(df):
    t=df.clip(lower=0); s=t.sum(axis=1); return t.div(s.replace(0,np.nan),axis=0)

def calc_zs(df, inverse=False, use_log=False, T=1.0):
    r=pd.DataFrame(index=df.index,columns=df.columns,dtype=float)
    for d in df.index:
        row=df.loc[d].astype(float); v=row.notna()&(row>0)
        if use_log: v=v&(row>0)
        if v.sum()<5: continue
        vals=row[v].copy()
        if use_log: vals=np.log(vals)
        if inverse: vals=-vals
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

def calc_comp(dfs, inverses, use_logs, T=1.0):
    cd=dfs[0].index
    for df in dfs[1:]: cd=cd.intersection(df.index)
    cd=cd.sort_values(); cc=dfs[0].columns
    for df in dfs[1:]: cc=cc.intersection(df.columns)
    r=pd.DataFrame(index=cd,columns=cc,dtype=float)
    for d in cd:
        zl=[]
        for df,inv,ul in zip(dfs,inverses,use_logs):
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

def build_port(w, ret, cf=None):
    cc=w.columns.intersection(ret.columns)
    if cf: cc=cc.intersection(cf)
    wd=w[cc]; rd=ret[cc]; wdates=wd.index.sort_values(); res=[]
    for d in rd.index:
        vw=wdates[wdates<d]
        if len(vw)==0: continue
        wi=wd.loc[vw[-1]]; ri=rd.loc[d]
        if isinstance(wi,pd.DataFrame): wi=wi.iloc[0]
        if isinstance(ri,pd.DataFrame): ri=ri.iloc[0]
        ok=wi.notna()&ri.notna()&(wi>0)
        if ok.sum()<3: continue
        wn=wi[ok]/wi[ok].sum(); res.append({'date':d,'ret':float((wn*ri[ok]).sum())})
    if not res: return pd.Series(dtype=float)
    o=pd.DataFrame(res); return pd.Series(o['ret'].values,index=pd.DatetimeIndex(o['date'].values))

def calc_stats(pr, br, name):
    ci=pr.index.intersection(br.index)
    if len(ci)<12: return None
    p=pr.reindex(ci).dropna(); b=br.reindex(ci).dropna()
    ci2=p.index.intersection(b.index); p,b=p.loc[ci2],b.loc[ci2]
    ar=(1+p.mean())**12-1; av=p.std()*np.sqrt(12); sh=ar/av if av>0 else 0
    cr=(1+p).prod()-1; md=((1+p).cumprod()/(1+p).cumprod().cummax()-1).min()
    bar=(1+b.mean())**12-1; ex=p-b; wr=(ex>0).sum()/len(ex)
    ce=((1+ex).cumprod()-1).iloc[-1]
    return {'name':name,'ann_return':round(ar*100,2),'ann_vol':round(av*100,2),
            'sharpe':round(sh,3),'cum_return':round(cr*100,2),'max_drawdown':round(md*100,2),
            'excess_return':round((ar-bar)*100,2),'win_rate':round(wr*100,1),'cum_excess':round(ce*100,2)}

# ══════════════════════════════════════════════════════════════
# ▶ 메인
# ══════════════════════════════════════════════════════════════
print("Loading...")
xls = pd.ExcelFile(FILE_MAIN)
df_gdp=load_data(xls,'Sheet4',1,3); df_per=load_data(xls,'Sheet7',1,3)
df_div=load_data(xls,'Sheet8',1,3); df_mc=load_data(xls,'Sheet5',1,3)
df_price=load_data(xls,'Sheet10',1,5)
df_roe=load_data(xls,'Sheet2',1,3); df_roa=load_data(xls,'Sheet11',1,3)
df_eps=load_data(xls,'Sheet15',1,3)

bm_raw=pd.read_excel(FILE_BM,sheet_name='Sheet2',header=None)
bm_dates=[parse_date(d) for d in bm_raw.iloc[1:,0].values]
bm_df=pd.DataFrame({
    'MSCI World':pd.to_numeric(bm_raw.iloc[1:,1],errors='coerce').values,
    'MSCI World ex USA':pd.to_numeric(bm_raw.iloc[1:,2],errors='coerce').values,
    'MSCI ACWI':pd.to_numeric(bm_raw.iloc[1:,3],errors='coerce').values,
    'MSCI EM':pd.to_numeric(bm_raw.iloc[1:,4],errors='coerce').values,
    'MSCI ACWI ex USA':pd.to_numeric(bm_raw.iloc[1:,5],errors='coerce').values,
},index=pd.DatetimeIndex(bm_dates))
bm_df=bm_df[bm_df.index.notna()].sort_index().dropna(how='all')
bm_df=bm_df[~bm_df.index.duplicated(keep='first')]
bm_returns={col:bm_df[col].pct_change().dropna() for col in bm_df.columns}
price_returns=df_price.pct_change().iloc[1:].replace([np.inf,-np.inf],np.nan)

# Derived
df_pbr = df_per * df_roe / 100
df_mom = df_price.shift(1) / df_price.shift(12) - 1
df_mom = df_mom.replace([np.inf,-np.inf], np.nan)
df_epsg = (df_eps - df_eps.shift(12)) / df_eps.shift(12).abs()
df_epsg = df_epsg.replace([np.inf,-np.inf], np.nan).clip(-5,5)

print("FIF...")
fif_df = calc_fif(df_mc, FILE_CTY)

print("Weights...")
raw_w = {
    'GDP (Prop)':calc_prop(df_gdp),'EY (Prop)':calc_prop(df_per,inverse=True),
    'DY (Prop)':calc_prop(df_div),'MC (Prop)':calc_prop(df_mc),
    'ROE (Prop)':calc_prop(df_roe),'ROA (Prop)':calc_prop(df_roa),
    '1/PBR (Prop)':calc_prop(df_pbr,inverse=True),
    'Mom (Prop)':calc_prop_pos(df_mom),'EPSg (Prop)':calc_prop_pos(df_epsg),
    'GDP (ZS)':calc_zs(df_gdp,use_log=True),'PER (ZS)':calc_zs(df_per,inverse=True),
    'DY (ZS)':calc_zs(df_div),'ROE (ZS)':calc_zs(df_roe),'ROA (ZS)':calc_zs(df_roa),
    'PBR (ZS)':calc_zs(df_pbr,inverse=True),'Mom (ZS)':calc_zs_any(df_mom),
    'EPSg (ZS)':calc_zs_any(df_epsg),
    'Composite (ZS)':calc_comp([df_gdp,df_per,df_div],[0,1,0],[1,0,0]),
    'Comp+ (ZS)':calc_comp([df_gdp,df_per,df_div,df_roe,df_mom],[0,1,0,0,0],[1,0,0,0,0]),
}
fif_w = {k:(v if k=='MC (Prop)' else apply_fif(v,fif_df)) for k,v in raw_w.items()}

# Build chart data: {universe: {category_fif: {d,v,bm,st}}}
chart = {'u':{}}
for fl, strats in [('raw',raw_w),('fif',fif_w)]:
    print(f"\nPortfolios ({fl})...")
    ports = {}
    for un,uc in univs.items():
        ports[un] = {}
        for sn,w in strats.items(): ports[un][sn]=build_port(w,price_returns,uc['c'])
        ew=pd.DataFrame(1.0,index=price_returns.index,columns=price_returns.columns)
        if fl=='fif': ports[un]['Equal Weight']=build_port(apply_fif(ew,fif_df),price_returns,uc['c'])
        else: ports[un]['Equal Weight']=build_port(ew,price_returns,uc['c'])

    for un,uc in univs.items():
        bmn=uc['bm']; bmr=bm_returns[bmn]
        if un not in chart['u']: chart['u'][un]={}
        for cat_name, slist in CATEGORIES.items():
            key=f"{cat_name}_{fl}"
            all_s=[ports[un].get(sn) for sn in slist if sn in ports[un]]+[bmr]
            all_s=[s for s in all_s if s is not None and len(s)>0]
            if not all_s: continue
            cs=max(s.index[0] for s in all_s); ce=min(s.index[-1] for s in all_s)
            dout=None; vout={}; stout=[]
            for sn in slist:
                if sn not in ports[un] or len(ports[un][sn])==0: continue
                t=ports[un][sn][(ports[un][sn].index>=cs)&(ports[un][sn].index<=ce)]
                cum=(1+t).cumprod()
                if dout is None: dout=[d.strftime('%Y-%m-%d') for d in cum.index]
                vout[sn]=[round(float(v),4) for v in cum.values]
                st=calc_stats(ports[un][sn],bmr,sn)
                if st: stout.append(st)
                if st: print(f"  {fl:3s} {cat_name:10s} {sn:23s} | {un:12s} | CumEx={st['cum_excess']:+.1f}%")
            bmt=bmr[(bmr.index>=cs)&(bmr.index<=ce)]
            vout[bmn]=[round(float(v),4) for v in (1+bmt).cumprod().values]
            bms=calc_stats(bmr,bmr,f'{bmn} (BM)')
            if bms: bms['win_rate']=50.0;bms['cum_excess']=0.0;bms['excess_return']=0.0;stout.append(bms)
            chart['u'][un][key]={'d':dout,'v':vout,'bm':bmn,'st':sorted(stout,key=lambda x:-x['sharpe'])}

# Weight data
wj={'raw':{},'fif':{}}
for fl,strats in [('raw',raw_w),('fif',fif_w)]:
    for sn,wdf in strats.items():
        sd={}
        for d in wdf.index:
            row=wdf.loc[d].dropna()
            if row.sum()==0: continue
            rn=(row/row.sum()).sort_values(ascending=False); rn=rn[rn>0.0001]
            sd[d.strftime('%Y-%m-%d')]={str(k):round(float(v)*100,4) for k,v in rn.items()}
        wj[fl][sn]=sd
    wj[fl]['Equal Weight']={'all_dates':{c:round(100.0/47,4) for c in ALL_47}}

js1=f"const D={json.dumps(chart,separators=(',',':'))};"
js2=f"const W={json.dumps(wj,separators=(',',':'))};"

# ══════════════════════════════════════════════════════════════
# ▶ HTML
# ══════════════════════════════════════════════════════════════
colors_js = json.dumps({
    'EY (Prop)':'#f472b6','DY (Prop)':'#fbbf24','1/PBR (Prop)':'#fb923c',
    'PER (ZS)':'#e879f9','DY (ZS)':'#fb923c','PBR (ZS)':'#f97316',
    'ROE (Prop)':'#a78bfa','ROA (Prop)':'#2dd4bf','ROE (ZS)':'#a78bfa','ROA (ZS)':'#2dd4bf',
    'GDP (Prop)':'#22d3ee','MC (Prop)':'#0891B2','GDP (ZS)':'#818cf8',
    'Mom (Prop)':'#ec4899','EPSg (Prop)':'#8b5cf6','Mom (ZS)':'#ec4899','EPSg (ZS)':'#8b5cf6',
    'Composite (ZS)':'#a3e635','Comp+ (ZS)':'#16a34a','Equal Weight':'#94a3b8'
})

dashboard='''<!DOCTYPE html>
<html><head><meta charset="utf-8">
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
*{margin:0;padding:0;box-sizing:border-box}body{font-family:'Segoe UI',system-ui,sans-serif;background:#0f1117;color:#e0e0e0;padding:20px;max-width:1200px;margin:0 auto}
h1{font-size:20px;font-weight:600;color:#fff}.sub{font-size:11px;color:#777;margin:4px 0 16px}
.card{background:#1a1d27;border-radius:10px;padding:16px;border:1px solid #2a2d3a;margin-bottom:14px}.card h2{font-size:13px;font-weight:600;margin-bottom:10px;color:#a0a8c0}
.tabs{display:flex;gap:5px;flex-wrap:wrap}.tab{padding:6px 14px;border-radius:6px;font-size:11px;cursor:pointer;background:#252836;color:#888;border:none;font-weight:500}
.tab.active{color:#fff}.t-u.active{background:#4f46e5}.t-c.active{background:#0e7490}.t-f.active{background:#b45309}
.tab:hover:not(.active){background:#303348}.tab-row{display:flex;align-items:center;gap:16px;margin-bottom:10px}.tab-label{font-size:11px;color:#555;font-weight:600;min-width:60px}
table{width:100%;border-collapse:collapse;font-size:11px}th{text-align:left;padding:6px;border-bottom:2px solid #2a2d3a;color:#7a8098;font-weight:500;white-space:nowrap}
td{padding:5px 6px;border-bottom:1px solid #1e2130;white-space:nowrap}tr:hover td{background:#1e2130}.pos{color:#4ade80}.neg{color:#f87171}
.legend-row{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px}.legend-item{display:flex;align-items:center;gap:3px;font-size:10px;cursor:pointer;opacity:.9}.legend-item:hover{opacity:1}.legend-dot{width:7px;height:7px;border-radius:50%}
canvas{max-height:380px}
</style></head><body>
<h1>국가 팩터 가중 전략 — 확장 분석</h1>
<div class="sub">Value / Quality / Macro / Momentum / Composite | FIF 토글 | <a href="factor_weight_viewer.html" style="color:#818cf8">비중 뷰어</a> | <a href="factor_country_viewer.html" style="color:#818cf8">국가별 수익률 →</a></div>
<div class="card">
<div class="tab-row"><div class="tab-label">Universe</div><div class="tabs" id="uT"></div></div>
<div class="tab-row"><div class="tab-label">카테고리</div><div class="tabs" id="cT"></div></div>
<div class="tab-row"><div class="tab-label">FIF</div><div class="tabs" id="fT"></div></div>
</div>
<div class="card"><h2 id="chartTitle">누적 수익률</h2><div class="legend-row" id="lB"></div><canvas id="cC" height="380"></canvas></div>
<div class="card"><h2>성과 요약</h2><div style="overflow-x:auto"><table><thead><tr><th>전략</th><th style="text-align:right">연수익</th><th style="text-align:right">변동성</th><th style="text-align:right">Sharpe</th><th style="text-align:right">누적</th><th style="text-align:right">MDD</th><th style="text-align:right">연초과</th><th style="text-align:right">승률</th><th style="text-align:right">누적초과</th></tr></thead><tbody id="sB"></tbody></table></div></div>
<script>
'''+js1+'''
const CL='''+colors_js+''';
const bC='#34d399';
const uK=Object.keys(D.u),cK='''+json.dumps(list(CATEGORIES.keys()))+''',fK=['raw','fif'];
let cU=uK[0],cC=cK[0],cF='raw',ch=null;
function init(){
  const ul={'All 47':'All47','All ex USA':'ExUSA','DM Only':'DM','DM ex USA':'DMxUSA','EM Only':'EM'};
  mk('uT','t-u',uK,ul,v=>{cU=v});
  mk('cT','t-c',cK,null,v=>{cC=v});
  mk('fT','t-f',fK,{'raw':'FIF OFF','fif':'FIF ON'},v=>{cF=v});
  rA();
}
function mk(id,cls,keys,labels,cb){
  const el=document.getElementById(id);
  keys.forEach((k,i)=>{const b=document.createElement('button');
    b.className='tab '+cls+(i===0?' active':'');b.textContent=(labels&&labels[k])||k;b.dataset.key=k;
    b.onclick=()=>{cb(k);el.querySelectorAll('.tab').forEach(t=>t.className='tab '+cls+(t.dataset.key===k?' active':''));rA()};
    el.appendChild(b)});
}
function rA(){
  const key=cC+'_'+cF;const u=D.u[cU]?.[key];if(!u||!u.d)return;
  document.getElementById('chartTitle').textContent=cC+(cF==='fif'?' (FIF)':'');
  const labels=u.d.map(d=>d.substring(0,7));const ds=[];
  Object.keys(u.v).forEach(n=>{const iB=n.startsWith('MSCI');
    ds.push({label:n,data:u.v[n],borderColor:iB?bC:(CL[n]||'#888'),backgroundColor:'transparent',
      borderWidth:iB?2:2.5,pointRadius:0,tension:0.3,borderDash:iB?[5,3]:[]})});
  if(ch)ch.destroy();
  ch=new Chart(document.getElementById('cC').getContext('2d'),{type:'line',data:{labels,datasets:ds},
    options:{responsive:true,maintainAspectRatio:false,interaction:{mode:'index',intersect:false},
      scales:{x:{ticks:{maxTicksToLimit:15,color:'#555'},grid:{color:'#1e2130'}},
        y:{ticks:{callback:v=>((v-1)*100).toFixed(0)+'%',color:'#555'},grid:{color:'#1e2130'}}},
      plugins:{legend:{display:false},tooltip:{callbacks:{label:i=>i.dataset.label+': '+((i.raw-1)*100).toFixed(1)+'%'}}}}});
  const lb=document.getElementById('lB');lb.innerHTML='';
  ds.forEach((d,i)=>{const e=document.createElement('div');e.className='legend-item';
    e.innerHTML='<div class="legend-dot" style="background:'+d.borderColor+'"></div>'+d.label;
    e.onclick=()=>{const m=ch.getDatasetMeta(i);m.hidden=!m.hidden;ch.update();e.style.opacity=m.hidden?0.3:0.9};lb.appendChild(e)});
  const tb=document.getElementById('sB');tb.innerHTML='';
  u.st.forEach(s=>{const ec=s.cum_excess>0?'pos':s.cum_excess<0?'neg':'';const wc=s.win_rate>=50?'pos':'';
    tb.innerHTML+='<tr><td>'+s.name+'</td><td style="text-align:right">'+s.ann_return.toFixed(2)+'%</td><td style="text-align:right">'+s.ann_vol.toFixed(2)+'%</td><td style="text-align:right;font-weight:600">'+s.sharpe.toFixed(3)+'</td><td style="text-align:right">'+s.cum_return.toFixed(1)+'%</td><td style="text-align:right" class="neg">'+s.max_drawdown.toFixed(1)+'%</td><td style="text-align:right">'+(s.excess_return>=0?'+':'')+s.excess_return.toFixed(2)+'%</td><td style="text-align:right" class="'+wc+'">'+s.win_rate.toFixed(1)+'%</td><td style="text-align:right;font-weight:600" class="'+ec+'">'+(s.cum_excess>=0?'+':'')+s.cum_excess.toFixed(2)+'%</td></tr>'});
}
init();
</script></body></html>'''

# ── Weight Viewer ──
wv='''<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
*{margin:0;padding:0;box-sizing:border-box}body{font-family:'Segoe UI',system-ui,sans-serif;background:#0f1117;color:#e0e0e0;padding:20px;max-width:1000px;margin:0 auto}
h1{font-size:20px;font-weight:600;color:#fff;margin-bottom:4px}.sub{font-size:11px;color:#777;margin-bottom:16px}
.card{background:#1a1d27;border-radius:10px;padding:16px;border:1px solid #2a2d3a;margin-bottom:14px}.card h2{font-size:13px;font-weight:600;margin-bottom:10px;color:#a0a8c0}
.row{display:flex;align-items:center;gap:16px;margin-bottom:10px}.row-label{font-size:11px;color:#555;font-weight:600;min-width:70px}
.tabs{display:flex;gap:4px;flex-wrap:wrap}
.tab{padding:5px 10px;border-radius:6px;font-size:10px;cursor:pointer;background:#252836;color:#888;border:none}.tab.active{background:#4f46e5;color:#fff}.tab:hover:not(.active){background:#303348}
.ftab{padding:5px 10px;border-radius:5px;font-size:10px;cursor:pointer;background:#252836;color:#888;border:none}.ftab.active{background:#b45309;color:#fff}
.utab{padding:5px 10px;border-radius:5px;font-size:10px;cursor:pointer;background:#252836;color:#888;border:none}.utab.active{background:#065f46;color:#34d399}
select{background:#252836;color:#e0e0e0;border:1px solid #2a2d3a;padding:6px 10px;border-radius:6px;font-size:12px;min-width:200px}
.bar-row{display:flex;align-items:center;gap:6px;margin-bottom:4px;font-size:11px}
.bar-label{width:110px;text-align:right;color:#999;flex-shrink:0}.bar-track{flex:1;height:18px;background:#1e2130;border-radius:4px;overflow:hidden}
.bar-fill{height:100%;border-radius:4px;display:flex;align-items:center;padding-left:5px;font-size:9px;color:#fff;font-weight:600}
.bar-val{width:55px;text-align:right;color:#ccc;flex-shrink:0}
.dm{background:linear-gradient(90deg,#2563EB,#3b82f6)}.em{background:linear-gradient(90deg,#DC2626,#ef4444)}
.info{font-size:11px;color:#666;margin-top:10px}a{color:#818cf8}
</style></head><body>
<h1>확장 팩터 — 국가 비중 뷰어</h1>
<div class="sub"><a href="factor_anal.html">&larr; 대시보드</a></div>
<div class="card">
<div class="row"><div class="row-label">전략</div><div class="tabs" id="sT"></div></div>
<div class="row"><div class="row-label">FIF</div><div class="tabs" id="fT"></div></div>
<div class="row"><div class="row-label">유니버스</div><div class="tabs" id="uT"></div></div>
<div class="row"><div class="row-label">날짜</div><select id="dS"></select></div>
</div>
<div class="card"><h2 id="title">비중</h2><div id="wB"></div><div class="info" id="iB"></div></div>
<script>
'''+js2+'''
const DM='''+json.dumps(DM)+''';const EM='''+json.dumps(EM)+''';
const DMS=new Set(DM);const ALL_EX=[...DM,...EM].filter(c=>c!=='USA');const DM_EX=DM.filter(c=>c!=='USA');
const UF={'All 47':null,'All ex USA':new Set(ALL_EX),'DM Only':new Set(DM),'DM ex USA':new Set(DM_EX),'EM Only':new Set(EM)};
let cS,cF='raw',cUn='All 47';
function init(){
  cS=Object.keys(W.raw)[0];
  mkT('sT','tab',Object.keys(W.raw),null,v=>{cS=v;pD();rn()},cS);
  mkT('fT','ftab',['raw','fif'],{'raw':'FIF OFF','fif':'FIF ON'},v=>{cF=v;pD();rn()},cF);
  mkT('uT','utab',Object.keys(UF),null,v=>{cUn=v;rn()},cUn);
  pD();rn();
}
function mkT(id,cls,keys,labels,cb,cur){
  const el=document.getElementById(id);
  keys.forEach(k=>{const b=document.createElement('button');
    b.className=cls+(k===cur?' active':'');b.textContent=(labels&&labels[k])||k;b.dataset.key=k;
    b.onclick=()=>{cb(k);el.querySelectorAll('.'+cls).forEach(t=>t.className=cls+(t.dataset.key===k?' active':''))};
    el.appendChild(b)});
}
function pD(){
  const sel=document.getElementById('dS');sel.innerHTML='';
  const data=W[cF]?.[cS];
  if(!data){sel.innerHTML='<option>없음</option>';return}
  if(data.all_dates){sel.innerHTML='<option>전체</option>';return}
  Object.keys(data).sort().reverse().forEach(d=>{const o=document.createElement('option');o.value=d;o.textContent=d;sel.appendChild(o)});
  sel.onchange=rn;
}
function rn(){
  const box=document.getElementById('wB');const info=document.getElementById('iB');
  const data=W[cF]?.[cS]; if(!data){box.innerHTML='없음';return}
  let aw;if(data.all_dates)aw=data.all_dates;else aw=data[document.getElementById('dS').value]||{};
  if(!aw||!Object.keys(aw).length){box.innerHTML='없음';return}
  const filter=UF[cUn];let weights={};
  for(const[c,w] of Object.entries(aw)){if(filter===null||filter.has(c))weights[c]=w}
  const tot=Object.values(weights).reduce((a,b)=>a+b,0);
  if(tot===0){box.innerHTML='없음';return}
  const norm={};for(const[c,w] of Object.entries(weights))norm[c]=w/tot*100;
  const sorted=Object.entries(norm).sort((a,b)=>b[1]-a[1]);
  const mx=sorted[0][1];let dmS=0,emS=0,html='';
  sorted.forEach(([c,w])=>{const isDM=DMS.has(c);if(isDM)dmS+=w;else emS+=w;
    html+='<div class="bar-row"><div class="bar-label">'+c+'</div><div class="bar-track"><div class="bar-fill '+(isDM?'dm':'em')+'" style="width:'+(w/mx*100)+'%">'+(w>1.5?w.toFixed(1)+'%':'')+'</div></div><div class="bar-val">'+w.toFixed(2)+'%</div></div>'});
  document.getElementById('title').textContent=cS+' — '+cUn+(cF==='fif'?' (FIF)':'');
  box.innerHTML=html;
  info.innerHTML='<span style="color:#3b82f6">■</span> DM:'+dmS.toFixed(1)+'% | <span style="color:#ef4444">■</span> EM:'+emS.toFixed(1)+'% | '+sorted.length+'개국';
}
init();
</script></body></html>'''

os.makedirs(OUT_DIR, exist_ok=True)
with open(os.path.join(OUT_DIR,'factor_anal.html'),'w',encoding='utf-8') as f: f.write(dashboard)
with open(os.path.join(OUT_DIR,'factor_weight_viewer.html'),'w',encoding='utf-8') as f: f.write(wv)
print(f"\n저장: factor_anal.html, factor_weight_viewer.html → {OUT_DIR}")
print("Done!")