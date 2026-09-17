"""
국가별 수익률 뷰어 생성
========================
전략 × 유니버스 × 날짜 선택 → 국가별 비중 + 월간수익률 + 비중기여도
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
price_returns = df_price.pct_change().iloc[1:].replace([np.inf,-np.inf], np.nan)

df_mom = df_price.shift(1) / df_price.shift(12) - 1
df_mom = df_mom.replace([np.inf,-np.inf], np.nan)
df_epsg = (df_eps - df_eps.shift(12)) / df_eps.shift(12).abs()
df_epsg = df_epsg.replace([np.inf,-np.inf], np.nan).clip(-5,5)
df_pbr = df_per * df_roe / 100

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

# ── 국가별 수익률 데이터 ──
print("Country return data...")
# Monthly returns: dates + {country: [ret%]}
ret_dates = [d.strftime('%Y-%m-%d') for d in price_returns.index]
country_monthly = {}
for c in price_returns.columns:
    vals = price_returns[c].values
    country_monthly[c] = [round(float(v)*100, 3) if pd.notna(v) else None for v in vals]

# ── 비중 데이터 (sparse: 전략 × 날짜 → {국가: 비중%}) ──
# 매월 저장하면 너무 크므로, 날짜 목록만 저장하고 JS에서 매칭
print("Weight data (sampled)...")
# 비중은 매 3개월 샘플링으로 크기 축소
def sample_weights(w_dict, sample_every=3):
    result = {}
    for sn, wdf in w_dict.items():
        sd = {}
        for i, d in enumerate(wdf.index):
            if i % sample_every != 0 and i != len(wdf.index)-1:
                continue
            row = wdf.loc[d].dropna()
            if row.sum() == 0: continue
            rn = row / row.sum()
            rn = rn[rn > 0.0001]
            sd[d.strftime('%Y-%m-%d')] = {str(k): round(float(v)*100, 2) for k, v in rn.items()}
        result[sn] = sd
    return result

raw_w_sampled = sample_weights(raw_w, sample_every=3)
fif_w_sampled = sample_weights(fif_w, sample_every=3)

# EW
ew_d = {c: round(100.0/47, 2) for c in ALL_47}
raw_w_sampled['Equal Weight'] = {'all': ew_d}
fif_w_sampled['Equal Weight'] = {'all': ew_d}

data_json = json.dumps({
    'd': ret_dates,
    'r': country_monthly,
    'w': {'raw': raw_w_sampled, 'fif': fif_w_sampled},
}, separators=(',',':'))

print(f"JSON size: {len(data_json)/1024:.0f} KB")

# ══════════════════════════════════════════════════════════════
# ▶ HTML 생성
# ══════════════════════════════════════════════════════════════
html = '''<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Segoe UI',system-ui,sans-serif;background:#0f1117;color:#e0e0e0;padding:20px;max-width:1100px;margin:0 auto}
h1{font-size:20px;font-weight:600;color:#fff;margin-bottom:4px}
.sub{font-size:11px;color:#777;margin-bottom:16px}
.card{background:#1a1d27;border-radius:10px;padding:16px;border:1px solid #2a2d3a;margin-bottom:14px}
.card h2{font-size:13px;font-weight:600;margin-bottom:10px;color:#a0a8c0}
.row{display:flex;align-items:center;gap:16px;margin-bottom:10px}
.row-label{font-size:11px;color:#555;font-weight:600;min-width:70px}
.tabs{display:flex;gap:4px;flex-wrap:wrap}
.tab{padding:5px 10px;border-radius:6px;font-size:10px;cursor:pointer;background:#252836;color:#888;border:none}
.tab.active{background:#4f46e5;color:#fff}.tab:hover:not(.active){background:#303348}
.ftab{padding:5px 10px;border-radius:5px;font-size:10px;cursor:pointer;background:#252836;color:#888;border:none}
.ftab.active{background:#b45309;color:#fff}.ftab:hover:not(.active){background:#303348}
.utab{padding:5px 10px;border-radius:5px;font-size:10px;cursor:pointer;background:#252836;color:#888;border:none}
.utab.active{background:#065f46;color:#34d399}.utab:hover:not(.active){background:#303348}
.vtab{padding:5px 10px;border-radius:5px;font-size:10px;cursor:pointer;background:#252836;color:#888;border:none}
.vtab.active{background:#7c3aed;color:#fff}.vtab:hover:not(.active){background:#303348}
select{background:#252836;color:#e0e0e0;border:1px solid #2a2d3a;padding:6px 10px;border-radius:6px;font-size:12px;min-width:200px}
table{width:100%;border-collapse:collapse;font-size:11px;margin-top:10px}
th{text-align:left;padding:6px 8px;border-bottom:2px solid #2a2d3a;color:#7a8098;font-weight:500;cursor:pointer}
th:hover{color:#a0a8c0}
td{padding:5px 8px;border-bottom:1px solid #1e2130;white-space:nowrap}
tr:hover td{background:#1e2130}
.pos{color:#4ade80}.neg{color:#f87171}
.bar-cell{position:relative;min-width:120px}
.bar-bg{position:absolute;top:2px;height:16px;border-radius:3px;opacity:0.3}
.bar-pos{background:#4ade80}.bar-neg{background:#f87171}
.info{font-size:11px;color:#666;margin-top:10px}
a{color:#818cf8}
.dm-tag{color:#60a5fa;font-size:9px;font-weight:600}
.em-tag{color:#f87171;font-size:9px;font-weight:600}
</style></head><body>
<h1>국가별 수익률 뷰어</h1>
<div class="sub"><a href="factor_anal.html">&larr; 대시보드</a> | 전략별 국가 비중 + 월간수익률 + 기여도</div>

<div class="card">
<div class="row"><div class="row-label">전략</div><div class="tabs" id="sT"></div></div>
<div class="row"><div class="row-label">FIF</div><div class="tabs" id="fT"></div></div>
<div class="row"><div class="row-label">유니버스</div><div class="tabs" id="uT"></div></div>
<div class="row"><div class="row-label">보기</div><div class="tabs" id="vT"></div></div>
<div class="row"><div class="row-label">날짜</div><select id="dS"></select></div>
</div>

<div class="card">
<h2 id="title">국가별 상세</h2>
<div style="overflow-x:auto"><table id="tbl"><thead id="tHead"></thead><tbody id="tBody"></tbody></table></div>
<div class="info" id="iB"></div>
</div>

<script>
const DATA=''' + data_json + ''';
const DM=''' + json.dumps(DM) + ''';
const EM=''' + json.dumps(EM) + ''';
const DMS=new Set(DM);
const ALL_EX=[...DM,...EM].filter(c=>c!=='USA');
const DM_EX=DM.filter(c=>c!=='USA');
const UF={'All 47':null,'All ex USA':new Set(ALL_EX),'DM Only':new Set(DM),'DM ex USA':new Set(DM_EX),'EM Only':new Set(EM)};
const VIEWS={'월간상세':'monthly','누적수익률':'cumulative'};

let cS, cF='raw', cUn='All 47', cV='monthly', sortCol=null, sortAsc=false;

function init(){
  const strats=Object.keys(DATA.w.raw);
  cS=strats[0];
  mkT('sT','tab',strats,null,v=>{cS=v;pD();rn()},cS);
  mkT('fT','ftab',['raw','fif'],{'raw':'FIF OFF','fif':'FIF ON'},v=>{cF=v;pD();rn()},cF);
  mkT('uT','utab',Object.keys(UF),null,v=>{cUn=v;rn()},cUn);
  mkT('vT','vtab',Object.keys(VIEWS),null,v=>{cV=VIEWS[v];pD();rn()},Object.keys(VIEWS)[0]);
  pD(); rn();
}

function mkT(id,cls,keys,labels,cb,cur){
  const el=document.getElementById(id);
  keys.forEach(k=>{
    const b=document.createElement('button');
    b.className=cls+(k===cur?' active':'');
    b.textContent=(labels&&labels[k])||k;
    b.dataset.key=k;
    b.onclick=()=>{cb(k);el.querySelectorAll('.'+cls).forEach(t=>t.className=cls+(t.dataset.key===k?' active':''))};
    el.appendChild(b);
  });
}

function pD(){
  const sel=document.getElementById('dS');
  sel.innerHTML='';
  if(cV==='cumulative'){
    ['전체기간','최근5년','최근3년','최근1년'].forEach(t=>{
      const o=document.createElement('option');o.value=t;o.textContent=t;sel.appendChild(o);
    });
  } else {
    DATA.d.slice().reverse().forEach(d=>{
      const o=document.createElement('option');o.value=d;o.textContent=d;sel.appendChild(o);
    });
  }
  sel.onchange=rn;
}

function getFilter(){
  const f=UF[cUn];
  return c => f===null || f.has(c);
}

function rn(){
  sortCol=null;
  if(cV==='monthly') renderMonthly();
  else renderCumulative();
}

function renderMonthly(){
  const sel=document.getElementById('dS');
  const date=sel.value;
  const di=DATA.d.indexOf(date);
  if(di<0) return;

  // Get weights: strictly before selected date (= actual applied weight)
  // 12-31 선택 → 11-30 이전 비중 = 12월에 실제 적용된 비중
  const wData=DATA.w[cF]?.[cS];
  let weights={};
  if(wData){
    if(wData.all) weights=wData.all;
    else {
      const wDates=Object.keys(wData).sort();
      let wd=null;
      for(let i=wDates.length-1;i>=0;i--){if(wDates[i]<date){wd=wDates[i];break}}
      if(wd) weights=wData[wd];
    }
  }

  const filter=getFilter();
  const rows=[];
  let totalW=0;
  Object.keys(DATA.r).filter(filter).forEach(c=>{
    const w=weights[c]||0;
    totalW+=w;
  });

  Object.keys(DATA.r).filter(filter).forEach(c=>{
    const ret=DATA.r[c][di];
    const rawW=weights[c]||0;
    const w=totalW>0?rawW/totalW*100:0;
    const contrib=ret!==null?w*ret/100:0;
    rows.push({country:c, weight:w, ret:ret, contrib:contrib, isDM:DMS.has(c)});
  });

  // Sort by contribution desc by default
  rows.sort((a,b)=>(b.contrib||0)-(a.contrib||0));

  const thead=document.getElementById('tHead');
  const tbody=document.getElementById('tBody');
  thead.innerHTML='<tr><th onclick="sortBy(0)">국가</th><th onclick="sortBy(1)">DM/EM</th><th onclick="sortBy(2)" style="text-align:right">비중(%)</th><th onclick="sortBy(3)" style="text-align:right">월간수익률(%)</th><th onclick="sortBy(4)" style="text-align:right">기여도(%p)</th></tr>';

  let html='';
  let portRet=0;
  rows.forEach(r=>{
    const rc=r.ret!==null?(r.ret>=0?'pos':'neg'):'';
    const cc=r.contrib>=0?'pos':'neg';
    portRet+=r.contrib;
    html+='<tr><td><b>'+r.country+'</b></td>'
      +'<td><span class="'+(r.isDM?'dm-tag':'em-tag')+'">'+(r.isDM?'DM':'EM')+'</span></td>'
      +'<td style="text-align:right">'+r.weight.toFixed(2)+'</td>'
      +'<td style="text-align:right" class="'+rc+'">'+(r.ret!==null?r.ret.toFixed(2):'N/A')+'</td>'
      +'<td style="text-align:right" class="'+cc+'">'+r.contrib.toFixed(3)+'</td></tr>';
  });
  tbody.innerHTML=html;

  document.getElementById('title').textContent=cS+' — '+cUn+' ('+date+' 수익률, 전월 비중 적용)';
  document.getElementById('iB').textContent='포트 월간수익률: '+portRet.toFixed(3)+'%p | 국가 수: '+rows.length;
}

function renderCumulative(){
  const sel=document.getElementById('dS');
  const period=sel.value;
  const filter=getFilter();

  // Determine date range
  let startIdx=0, endIdx=DATA.d.length-1;
  const lastDate=new Date(DATA.d[endIdx]);
  if(period==='최근1년') startIdx=Math.max(0,endIdx-12);
  else if(period==='최근3년') startIdx=Math.max(0,endIdx-36);
  else if(period==='최근5년') startIdx=Math.max(0,endIdx-60);

  const rows=[];
  Object.keys(DATA.r).filter(filter).forEach(c=>{
    let cum=1;
    let count=0;
    for(let i=startIdx;i<=endIdx;i++){
      const v=DATA.r[c][i];
      if(v!==null){cum*=(1+v/100);count++}
    }
    const totalRet=(cum-1)*100;
    const ann=count>=12?((Math.pow(cum,12/count))-1)*100:totalRet;
    rows.push({country:c, cumRet:totalRet, annRet:ann, months:count, isDM:DMS.has(c)});
  });

  rows.sort((a,b)=>b.cumRet-a.cumRet);

  const thead=document.getElementById('tHead');
  const tbody=document.getElementById('tBody');
  thead.innerHTML='<tr><th onclick="sortBy(0)">국가</th><th onclick="sortBy(1)">DM/EM</th><th onclick="sortBy(2)" style="text-align:right">누적수익률(%)</th><th onclick="sortBy(3)" style="text-align:right">연환산(%)</th><th onclick="sortBy(4)" style="text-align:right">기간(월)</th></tr>';

  const maxAbs=Math.max(...rows.map(r=>Math.abs(r.cumRet)),1);
  let html='';
  rows.forEach(r=>{
    const rc=r.cumRet>=0?'pos':'neg';
    const barW=Math.abs(r.cumRet)/maxAbs*80;
    const barCls=r.cumRet>=0?'bar-pos':'bar-neg';
    html+='<tr><td><b>'+r.country+'</b></td>'
      +'<td><span class="'+(r.isDM?'dm-tag':'em-tag')+'">'+(r.isDM?'DM':'EM')+'</span></td>'
      +'<td style="text-align:right" class="'+rc+'">'+r.cumRet.toFixed(1)+'</td>'
      +'<td style="text-align:right" class="'+rc+'">'+r.annRet.toFixed(1)+'</td>'
      +'<td style="text-align:right">'+r.months+'</td></tr>';
  });
  tbody.innerHTML=html;

  document.getElementById('title').textContent='국가별 누적수익률 — '+cUn+' ('+period+')';
  const avg=rows.reduce((a,r)=>a+r.cumRet,0)/rows.length;
  document.getElementById('iB').textContent='평균: '+avg.toFixed(1)+'% | 국가 수: '+rows.length+'  ('+DATA.d[startIdx]+' ~ '+DATA.d[endIdx]+')';
}

function sortBy(col){
  const tbody=document.getElementById('tBody');
  const rows=[...tbody.querySelectorAll('tr')];
  if(sortCol===col) sortAsc=!sortAsc;
  else{sortCol=col;sortAsc=col<=1}
  rows.sort((a,b)=>{
    let va=a.cells[col].textContent, vb=b.cells[col].textContent;
    const na=parseFloat(va), nb=parseFloat(vb);
    if(!isNaN(na)&&!isNaN(nb)) return sortAsc?na-nb:nb-na;
    return sortAsc?va.localeCompare(vb):vb.localeCompare(va);
  });
  rows.forEach(r=>tbody.appendChild(r));
}

init();
</script></body></html>'''

os.makedirs(OUT_DIR, exist_ok=True)
out_path = os.path.join(OUT_DIR, 'factor_country_viewer.html')
with open(out_path, 'w', encoding='utf-8') as f:
    f.write(html)
print(f"\n저장 → {out_path}")
print("Done!")