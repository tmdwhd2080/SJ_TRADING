import pandas as pd
import numpy as np
from scipy import stats
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker

# 한글 폰트 설정
plt.rcParams['font.family'] = 'Malgun Gothic'
plt.rcParams['axes.unicode_minus'] = False

# 가격 데이터 → Sheet4 (Total Return), 날짜 컬럼 rename
df_price = pd.read_excel(r'C:\Users\intern9\truston_quant_dev\util\bm_price 2.xlsx', sheet_name='Sheet4')
df_price = df_price.rename(columns={'Unnamed: 0': 'Date'})
df_price['Date'] = pd.to_datetime(df_price['Date'])
df_price = df_price.sort_values('Date').set_index('Date')
df_price = df_price[['MSCI EM (Emerging Markets)', 'MSCI AC World ex USA']].copy()
df_price.columns = ['EM', 'WORLD_EX_USA']
df_price_m = df_price.resample('ME').last()
df_price_m['EM_ret']  = df_price_m['EM'].pct_change()
df_price_m['DM_ret']  = df_price_m['WORLD_EX_USA'].pct_change()
df_price_m['EM_avg6'] = df_price_m['EM_ret'].rolling(6).mean().shift(1)
df_price_m['DM_avg6'] = df_price_m['DM_ret'].rolling(6).mean().shift(1)

# 벤치마크 → Sheet4 (Total Return), 날짜 컬럼 rename
df_bm_raw = pd.read_excel(r'C:\Users\intern9\truston_quant_dev\util\bm_price 2.xlsx', sheet_name='Sheet4')
df_bm_raw = df_bm_raw.rename(columns={'Unnamed: 0': 'Date'})
df_bm_raw['Date'] = pd.to_datetime(df_bm_raw['Date'])
df_bm_raw = df_bm_raw.sort_values('Date').set_index('Date')
acwi_m = df_bm_raw[['MSCI AC World ex USA']].resample('ME').last()
acwi_m['BM_ret'] = acwi_m['MSCI AC World ex USA'].pct_change()

# 펀드플로우 데이터 (변경 없음)
df_ff_raw = pd.read_excel(r'C:\Users\intern9\truston_quant_dev\util\노승종 (12).xlsx', sheet_name='Sheet1', header=0)
df_ff = df_ff_raw.iloc[1:].copy()
df_ff.columns = ['Date', 'EEM', 'EFA']
df_ff['Date'] = pd.to_datetime(df_ff['Date'], errors='coerce')
df_ff = df_ff.dropna(subset=['Date'])
df_ff['EEM'] = pd.to_numeric(df_ff['EEM'], errors='coerce').fillna(0)
df_ff['EFA'] = pd.to_numeric(df_ff['EFA'], errors='coerce').fillna(0)
df_ff = df_ff.set_index('Date')
df_ff_m = df_ff.resample('ME').sum()

# ROE 데이터 → (EM_ROE − DM_ROE) YoY 변화량으로 변환 (변경 없음)
df_qual = pd.read_excel(r'C:\Users\intern9\truston_quant_dev\util\em_dm_quality.xlsx', sheet_name='월별_EM_DM_지표')
df_qual['Date'] = pd.to_datetime(df_qual['YM']) + pd.offsets.MonthEnd(0)
df_qual = df_qual.set_index('Date')[['EM_ROE', 'DM_exUSA_ROE']]
df_qual['ROE_diff']     = df_qual['EM_ROE'] - df_qual['DM_exUSA_ROE']
df_qual['ROE_diff_YoY'] = df_qual['ROE_diff'] - df_qual['ROE_diff'].shift(12)

# USA PRICE에서 T-1월 수익률 팩터 생성
df_hk = pd.read_excel(r'C:\Users\intern9\truston_quant_dev\util\hk_msci_world_최종.xlsx',
                      sheet_name=None)
ko_en = {}
for _, row in df_hk['CONFIG'].iterrows():
    if pd.notna(row.get('한국어명')) and pd.notna(row.get('영문명')):
        ko_en[row['한국어명']] = row['영문명']

price_raw = df_hk['PRICE']
usa_price_data = price_raw.iloc[4:].copy()
usa_price_data.columns = price_raw.columns
usa_price_data = usa_price_data.rename(columns={'Price': 'Date'})
usa_price_data['Date'] = pd.to_datetime(usa_price_data['Date'], errors='coerce')
usa_price_data = usa_price_data.dropna(subset=['Date']).set_index('Date')
usa_price_data = usa_price_data.apply(pd.to_numeric, errors='coerce').sort_index()
usa_price_data.columns = [ko_en.get(c, c) for c in usa_price_data.columns]

usa_price_m  = usa_price_data['USA'].resample('ME').last()
usa_ret_m    = usa_price_m.pct_change()
usa_ret_lag1 = usa_ret_m.shift(1)
usa_ret_lag1.name = 'USA_ret_lag1'

# 병합 및 T-1 래그
df = df_price_m[['EM_ret', 'DM_ret', 'EM_avg6', 'DM_avg6']].join(df_ff_m[['EEM', 'EFA']], how='inner')
df = df.join(df_qual[['ROE_diff_YoY']], how='left')
df = df.join(usa_ret_lag1, how='left')
df['EEM_FF_lag']      = df['EEM'].shift(1)
df['EFA_FF_lag']      = df['EFA'].shift(1)
df['ROE_diffYoY_lag'] = df['ROE_diff_YoY'].shift(1)
df = df.dropna(subset=['EM_ret', 'DM_ret', 'EEM_FF_lag', 'EFA_FF_lag',
                        'ROE_diffYoY_lag', 'EM_avg6', 'DM_avg6',
                        'USA_ret_lag1'])

def ewma_ols(y, X_data, halflife=12):
    n, k  = X_data.shape
    lam   = 0.5 ** (1.0 / halflife)
    w     = lam ** (n - 1 - np.arange(n))
    w     = w / w.sum()
    W     = np.diag(w)
    X     = np.column_stack([np.ones(n), X_data])
    XtW   = X.T @ W
    beta  = np.linalg.solve(XtW @ X, XtW @ y)
    resid = y - X @ beta
    n_eff = 1.0 / np.sum(w ** 2)
    sse   = float(resid @ W @ resid)
    mse   = sse / max(n_eff - k - 1, 1)
    se    = np.sqrt(np.diag(mse * np.linalg.inv(XtW @ X)))
    t_stats = beta / se
    df_t  = max(int(n_eff) - k - 1, 1)
    p_vals = 2 * (1 - stats.t.cdf(np.abs(t_stats), df=df_t))
    y_wm  = np.sum(w * y)
    ss_tot = float((y - y_wm) @ W @ (y - y_wm))
    r2    = 1 - sse / ss_tot if ss_tot > 0 else 0.0
    adj_r2 = 1 - (1 - r2) * (n_eff - 1) / max(n_eff - k - 1, 1)
    return beta, t_stats, p_vals, r2, adj_r2

MIN_WINDOW = 36; halflife = 12
records = []

for i in range(MIN_WINDOW - 1, len(df)):
    w        = df.iloc[0: i + 1]
    end_date = df.index[i]

    b_em, t_em, p_em, r2_em, ar2_em = ewma_ols(
        w['EM_ret'].values,
        w[['EEM_FF_lag', 'ROE_diffYoY_lag', 'EM_avg6', 'USA_ret_lag1']].values, halflife)
    pred_em = np.array([1,
                        df['EEM_FF_lag'].iloc[i],
                        df['ROE_diffYoY_lag'].iloc[i],
                        df['EM_avg6'].iloc[i],
                        df['USA_ret_lag1'].iloc[i]]) @ b_em

    b_dm, t_dm, p_dm, r2_dm, ar2_dm = ewma_ols(
        w['DM_ret'].values,
        w[['EFA_FF_lag', 'ROE_diffYoY_lag', 'DM_avg6', 'USA_ret_lag1']].values, halflife)
    pred_dm = np.array([1,
                        df['EFA_FF_lag'].iloc[i],
                        df['ROE_diffYoY_lag'].iloc[i],
                        df['DM_avg6'].iloc[i],
                        df['USA_ret_lag1'].iloc[i]]) @ b_dm

    actual_em     = df['EM_ret'].iloc[i]
    actual_dm     = df['DM_ret'].iloc[i]
    model_pick    = 'EM' if pred_em >= pred_dm else 'DM'
    actual_better = 'EM' if actual_em >= actual_dm else 'DM'

    records.append({
        'Date'          : end_date,
        'EM_alpha'      : b_em[0],
        'EM_b_FF'       : b_em[1], 'EM_t_FF'    : t_em[1], 'EM_p_FF'    : p_em[1],
        'EM_b_ROE'      : b_em[2], 'EM_t_ROE'   : t_em[2], 'EM_p_ROE'   : p_em[2],
        'EM_b_avg6'     : b_em[3], 'EM_t_avg6'  : t_em[3], 'EM_p_avg6'  : p_em[3],
        'EM_b_USA'      : b_em[4], 'EM_t_USA'   : t_em[4], 'EM_p_USA'   : p_em[4],
        'EM_R2'         : r2_em,   'EM_adjR2'   : ar2_em,
        'EM_Pred'       : pred_em, 'EM_Actual'  : actual_em,
        'DM_alpha'      : b_dm[0],
        'DM_b_FF'       : b_dm[1], 'DM_t_FF'    : t_dm[1], 'DM_p_FF'    : p_dm[1],
        'DM_b_ROE'      : b_dm[2], 'DM_t_ROE'   : t_dm[2], 'DM_p_ROE'   : p_dm[2],
        'DM_b_avg6'     : b_dm[3], 'DM_t_avg6'  : t_dm[3], 'DM_p_avg6'  : p_dm[3],
        'DM_b_USA'      : b_dm[4], 'DM_t_USA'   : t_dm[4], 'DM_p_USA'   : p_dm[4],
        'DM_R2'         : r2_dm,   'DM_adjR2'   : ar2_dm,
        'DM_Pred'       : pred_dm, 'DM_Actual'  : actual_dm,
        'Model_Pick'    : model_pick,
        'Actual_Better' : actual_better,
        'Hit'           : model_pick == actual_better,
    })

df_res = pd.DataFrame(records).set_index('Date')
df_res['Cumul_HR']     = df_res['Hit'].expanding().mean()
df_res['Rolling12_HR'] = df_res['Hit'].rolling(12).mean()

# 추가 1: 선택 변경 횟수
df_res['Pick_Changed'] = df_res['Model_Pick'] != df_res['Model_Pick'].shift(1)
df_res.iloc[0, df_res.columns.get_loc('Pick_Changed')] = False
n_changes = int(df_res['Pick_Changed'].sum())
n_total   = len(df_res)

# 추가 2: 연도별 평균 적중률
df_res['Year'] = df_res.index.year
yearly = df_res.groupby('Year')['Hit'].agg(
    Hit_Count='sum', Total='count', Hit_Rate='mean').reset_index()

# ===== 추가 3: 성과 분석 (거래비용 20bp 왕복) =====
TC = 0.0020

df_res['Strategy_ret'] = np.where(
    df_res['Model_Pick'] == 'EM', df_res['EM_Actual'], df_res['DM_Actual'])

strategy_ret_tc = df_res['Strategy_ret'].copy()
strategy_ret_tc[df_res['Pick_Changed']] -= TC
df_res['Strategy_ret_tc'] = strategy_ret_tc

df_perf = df_res[['Strategy_ret_tc', 'EM_Actual', 'DM_Actual', 'Model_Pick']].join(
    acwi_m[['BM_ret']], how='left').dropna(subset=['BM_ret'])

def calc_mdd(ret_series):
    cum = (1 + ret_series).cumprod()
    return ((cum - cum.cummax()) / cum.cummax()).min()

def calc_ann_ret(ret_series):
    n = len(ret_series)
    return (1 + ret_series).prod() ** (12 / n) - 1

def calc_calmar(ret_series):
    mdd = abs(calc_mdd(ret_series))
    return calc_ann_ret(ret_series) / mdd if mdd != 0 else np.nan

def calc_sharpe(ret_series):
    return ret_series.mean() / ret_series.std() * np.sqrt(12) if ret_series.std() > 0 else np.nan

strat_ann = calc_ann_ret(df_perf['Strategy_ret_tc'])
strat_mdd = calc_mdd(df_perf['Strategy_ret_tc'])
strat_cal = calc_calmar(df_perf['Strategy_ret_tc'])
strat_shr = calc_sharpe(df_perf['Strategy_ret_tc'])
bm_ann    = calc_ann_ret(df_perf['BM_ret'])
bm_mdd    = calc_mdd(df_perf['BM_ret'])
bm_cal    = calc_calmar(df_perf['BM_ret'])
bm_shr    = calc_sharpe(df_perf['BM_ret'])

print(f"\n===== 전체 기간 성과 (거래비용 20bp 왕복 반영) =====")
print(f"{'항목':<22} {'전략':>14} {'BM (ACWI ex USA)':>18}")
print("-" * 56)
print(f"{'분석 기간':<22} {df_perf.index[0].strftime('%Y-%m')+'~'+df_perf.index[-1].strftime('%Y-%m'):>14}")
print(f"{'연환산 수익률':<22} {strat_ann:>14.2%} {bm_ann:>18.2%}")
print(f"{'MDD':<22} {strat_mdd:>14.2%} {bm_mdd:>18.2%}")
print(f"{'Sharpe 비율':<22} {strat_shr:>14.3f} {bm_shr:>18.3f}")
print(f"{'Calmar 비율':<22} {strat_cal:>14.3f} {bm_cal:>18.3f}")
print(f"{'전환 횟수':<22} {n_changes:>14}회")
print(f"{'연간 비용 영향':<22} {'약 ' + f'{n_changes * TC / n_total * 12 * 100:.1f}bp/년':>14}")

df_perf['Year'] = df_perf.index.year
yr = df_perf.groupby('Year').apply(lambda x: pd.Series({
    'Strategy' : (1 + x['Strategy_ret_tc']).prod() - 1,
    'BM'       : (1 + x['BM_ret']).prod() - 1,
    'Excess'   : (1 + x['Strategy_ret_tc']).prod() - (1 + x['BM_ret']).prod(),
    'N'        : len(x),
})).reset_index()

# 연도별 누적 초과수익 (출력용)
yr['Cum_Excess'] = yr['Excess'].cumsum() * 100

print(f"\n===== 연도별 수익률 비교 (거래비용 20bp 왕복 반영) =====")
print(f"{'연도':<6} {'전략':>10} {'BM':>9} {'초과수익':>10} {'누적초과':>10} {'N':>4}")
print("-" * 52)
for _, row in yr.iterrows():
    print(f"{int(row['Year']):<6} {row['Strategy']:>10.2%} {row['BM']:>9.2%} "
          f"{row['Excess']:>+10.2%} {row['Cum_Excess']:>+10.2f}% {int(row['N']):>4}")

# 기존 결과 출력
total_n   = len(df_res)
total_hit = int(df_res['Hit'].sum())
em_n = int((df_res['Model_Pick'] == 'EM').sum())
dm_n = int((df_res['Model_Pick'] == 'DM').sum())
em_h = int(((df_res['Model_Pick'] == 'EM') & df_res['Hit']).sum())
dm_h = int(((df_res['Model_Pick'] == 'DM') & df_res['Hit']).sum())

print(f"\n분석 기간   : {df_res.index[0].strftime('%Y-%m')} ~ {df_res.index[-1].strftime('%Y-%m')}")
print(f"총 N        : {total_n}개월")
print(f"전체 적중률 : {total_hit/total_n:.2%}  ({total_hit}/{total_n})")
print(f"EM 선택 적중: {em_h/em_n:.2%}  ({em_h}/{em_n}회)")
print(f"DM 선택 적중: {dm_h/dm_n:.2%}  ({dm_h}/{dm_n}회)")
print(f"\n선택 변경 횟수: {n_changes}회 / {n_total}개월  ({n_changes/(n_total-1):.2%})")

print(f"\n{'연도':<6} {'적중':>5} {'전체':>5} {'적중률':>8}")
print("-" * 26)
for _, row in yearly.iterrows():
    print(f"{int(row['Year']):<6} {int(row['Hit_Count']):>5} {int(row['Total']):>5} {row['Hit_Rate']:>8.2%}")

print(f"\n--- EM 모델 (롤링 평균) ---")
print(f"  α={df_res['EM_alpha'].mean():.4f}  "
      f"β_FF={df_res['EM_b_FF'].mean():.3e}(t={df_res['EM_t_FF'].mean():.3f})  "
      f"β_ROEdYoY={df_res['EM_b_ROE'].mean():.4f}(t={df_res['EM_t_ROE'].mean():.3f})  "
      f"β_avg6={df_res['EM_b_avg6'].mean():.4f}(t={df_res['EM_t_avg6'].mean():.3f})  "
      f"β_USA={df_res['EM_b_USA'].mean():.4f}(t={df_res['EM_t_USA'].mean():.3f})")
print(f"  R²={df_res['EM_R2'].mean():.4f}  Adj-R²={df_res['EM_adjR2'].mean():.4f}")

print(f"\n--- DM 모델 (롤링 평균) ---")
print(f"  α={df_res['DM_alpha'].mean():.4f}  "
      f"β_FF={df_res['DM_b_FF'].mean():.3e}(t={df_res['DM_t_FF'].mean():.3f})  "
      f"β_ROEdYoY={df_res['DM_b_ROE'].mean():.4f}(t={df_res['DM_t_ROE'].mean():.3f})  "
      f"β_avg6={df_res['DM_b_avg6'].mean():.4f}(t={df_res['DM_t_avg6'].mean():.3f})  "
      f"β_USA={df_res['DM_b_USA'].mean():.4f}(t={df_res['DM_t_USA'].mean():.3f})")
print(f"  R²={df_res['DM_R2'].mean():.4f}  Adj-R²={df_res['DM_adjR2'].mean():.4f}")

# ===== [추가] CSV 저장: 월별 선택·실제 결과 =====
df_csv = df_perf[['Strategy_ret_tc', 'BM_ret']].copy()
df_csv = df_csv.join(df_res[['Model_Pick', 'Actual_Better',
                               'EM_Actual', 'DM_Actual', 'Hit']])
df_csv['Ret_Diff_EM_minus_DM'] = df_csv['EM_Actual'] - df_csv['DM_Actual']  # EM−DM 수익률 차이
df_csv['Excess_ret']           = df_csv['Strategy_ret_tc'] - df_csv['BM_ret']  # 전략−BM 초과
df_csv = df_csv[[
    'Model_Pick', 'Actual_Better', 'Hit',
    'EM_Actual', 'DM_Actual', 'Ret_Diff_EM_minus_DM',
    'Strategy_ret_tc', 'BM_ret', 'Excess_ret',
]]
df_csv.index.name = 'Date'
df_csv.to_csv('monthly_pick_result.csv', encoding='utf-8-sig')
print(f"\nCSV 저장 완료: monthly_pick_result.csv  ({len(df_csv)}행)")

# ===== [추가] 3Y Rolling Sharpe / Calmar 계산 =====
ROLL = 36

df_roll = df_perf[['Strategy_ret_tc', 'BM_ret']].copy()
df_roll['strat_roll_sharpe'] = (df_roll['Strategy_ret_tc'].rolling(ROLL).mean() /
                                 df_roll['Strategy_ret_tc'].rolling(ROLL).std() * np.sqrt(12))
df_roll['bm_roll_sharpe']    = (df_roll['BM_ret'].rolling(ROLL).mean() /
                                 df_roll['BM_ret'].rolling(ROLL).std() * np.sqrt(12))

def roll_calmar(r_series, window):
    vals = []
    for i in range(len(r_series)):
        if i < window - 1:
            vals.append(np.nan)
        else:
            sub = r_series.iloc[i - window + 1 : i + 1]
            ann = (1 + sub).prod() ** (12 / window) - 1
            cum = (1 + sub).cumprod()
            mdd = abs(((cum - cum.cummax()) / cum.cummax()).min())
            vals.append(ann / mdd if mdd > 0 else np.nan)
    return pd.Series(vals, index=r_series.index)

df_roll['strat_roll_calmar'] = roll_calmar(df_roll['Strategy_ret_tc'], ROLL)
df_roll['bm_roll_calmar']    = roll_calmar(df_roll['BM_ret'], ROLL)

# ===== 추가 4: 시각화 — 한 페이지에 하나씩 4개 figure =====
C_STRAT = '#27500A'; C_NEG = '#791F1F'; C_BM = '#4A6FA5'; C_LINE = '#2C7B2C'
GRID_C  = '#888780'

years   = [int(r['Year']) for _, r in yr.iterrows()]
excess  = [r['Excess'] * 100 for _, r in yr.iterrows()]
xlabels = [str(y) if y != 2026 else '2026*' for y in years]
colors  = [C_STRAT if v >= 0 else C_NEG for v in excess]

# ── Figure 1: 연도별 초과수익 막대 ───────────────────────────
fig1, ax1 = plt.subplots(figsize=(14, 6))
bars = ax1.bar(xlabels, excess, color=colors, width=0.6, zorder=3)
for bar, val in zip(bars, excess):
    offset = 0.2 if val >= 0 else -0.2
    va     = 'bottom' if val >= 0 else 'top'
    ax1.text(bar.get_x() + bar.get_width() / 2, val + offset,
             f'{val:+.1f}%', ha='center', va=va, fontsize=8,
             color=C_STRAT if val >= 0 else C_NEG, fontweight='bold')
ax1.axhline(0, color=GRID_C, linewidth=1.2, linestyle='--', alpha=0.6)
ax1.yaxis.set_major_locator(ticker.MultipleLocator(1))
ax1.yaxis.set_major_formatter(ticker.FuncFormatter(
    lambda v, _: f'+{v:.0f}%' if v > 0 else f'{v:.0f}%'))
ax1.set_ylim(-9, 18)
ax1.grid(axis='y', color=GRID_C, alpha=0.15, linewidth=0.5, zorder=0)
ax1.set_ylabel('초과수익 (%p)', fontsize=11)
ax1.set_title('연도별 초과수익', fontsize=13, pad=14)
plt.xticks(rotation=0, fontsize=10)
plt.tight_layout()
plt.savefig('excess_return_tc20bp.png', dpi=150, bbox_inches='tight')
plt.show()

# ── Figure 2: 월별 누적 초과수익 선그래프 ────────────────────  [수정]
fig2, ax2 = plt.subplots(figsize=(14, 6))
# 월별 초과수익 누적합 (Strategy - BM, %p 단위)
monthly_excess     = df_perf['Strategy_ret_tc'] - df_perf['BM_ret']
cum_excess_monthly = monthly_excess.cumsum() * 100   # %p 누적합

ax2.plot(cum_excess_monthly.index, cum_excess_monthly.values,
         color=C_LINE, linewidth=1.8, zorder=3)
ax2.fill_between(cum_excess_monthly.index, cum_excess_monthly.values, 0,
                 where=cum_excess_monthly.values >= 0,
                 alpha=0.15, color=C_LINE, interpolate=True)
ax2.fill_between(cum_excess_monthly.index, cum_excess_monthly.values, 0,
                 where=cum_excess_monthly.values < 0,
                 alpha=0.15, color=C_NEG, interpolate=True)
ax2.axhline(0, color=GRID_C, linewidth=1.0, linestyle='--', alpha=0.6)
ax2.yaxis.set_major_formatter(ticker.FuncFormatter(
    lambda v, _: f'+{v:.0f}%' if v > 0 else f'{v:.0f}%'))
ax2.grid(color=GRID_C, alpha=0.15, linewidth=0.5)
ax2.set_ylabel('누적 초과수익 (%p)', fontsize=11)
ax2.set_title('누적 초과 수익률', fontsize=13, pad=14)
plt.tight_layout()
plt.savefig('cum_excess_return.png', dpi=150, bbox_inches='tight')
plt.show()

# ── Figure 3: 3Y Rolling Sharpe ──────────────────────────────
fig3, ax3 = plt.subplots(figsize=(14, 6))
ax3.plot(df_roll.index, df_roll['strat_roll_sharpe'],
         color=C_STRAT, lw=1.8, label='전략', zorder=3)
ax3.plot(df_roll.index, df_roll['bm_roll_sharpe'],
         color=C_BM, lw=1.5, ls='--', label='BM (ACWI ex USA)', zorder=2)
ax3.axhline(0, color=GRID_C, lw=1.0, ls='--', alpha=0.6)
ax3.axhline(strat_shr, color=C_STRAT, lw=0.9, ls=':', alpha=0.7,
            label=f'전략 전체 Sharpe: {strat_shr:.2f}')
ax3.axhline(bm_shr, color=C_BM, lw=0.9, ls=':', alpha=0.7,
            label=f'BM 전체 Sharpe: {bm_shr:.2f}')
ax3.fill_between(df_roll.index,
                 df_roll['strat_roll_sharpe'], df_roll['bm_roll_sharpe'],
                 where=df_roll['strat_roll_sharpe'] >= df_roll['bm_roll_sharpe'],
                 alpha=0.10, color=C_STRAT, interpolate=True)
ax3.fill_between(df_roll.index,
                 df_roll['strat_roll_sharpe'], df_roll['bm_roll_sharpe'],
                 where=df_roll['strat_roll_sharpe'] < df_roll['bm_roll_sharpe'],
                 alpha=0.10, color=C_NEG, interpolate=True)
ax3.legend(fontsize=9, loc='upper left', framealpha=0.8)
ax3.grid(color=GRID_C, alpha=0.15, linewidth=0.5)
ax3.set_ylabel('Sharpe Ratio', fontsize=11)
ax3.set_title('3Y Rolling Sharpe Ratio', fontsize=13, pad=14)
plt.tight_layout()
plt.savefig('rolling_sharpe.png', dpi=150, bbox_inches='tight')
plt.show()

# ── Figure 4: 3Y Rolling Calmar ──────────────────────────────
fig4, ax4 = plt.subplots(figsize=(14, 6))
ax4.plot(df_roll.index, df_roll['strat_roll_calmar'],
         color=C_STRAT, lw=1.8, label='전략', zorder=3)
ax4.plot(df_roll.index, df_roll['bm_roll_calmar'],
         color=C_BM, lw=1.5, ls='--', label='BM (ACWI ex USA)', zorder=2)
ax4.axhline(0, color=GRID_C, lw=1.0, ls='--', alpha=0.6)
ax4.axhline(strat_cal, color=C_STRAT, lw=0.9, ls=':', alpha=0.7,
            label=f'전략 전체 Calmar: {strat_cal:.2f}')
ax4.axhline(bm_cal, color=C_BM, lw=0.9, ls=':', alpha=0.7,
            label=f'BM 전체 Calmar: {bm_cal:.2f}')
ax4.fill_between(df_roll.index,
                 df_roll['strat_roll_calmar'], df_roll['bm_roll_calmar'],
                 where=df_roll['strat_roll_calmar'] >= df_roll['bm_roll_calmar'],
                 alpha=0.10, color=C_STRAT, interpolate=True)
ax4.fill_between(df_roll.index,
                 df_roll['strat_roll_calmar'], df_roll['bm_roll_calmar'],
                 where=df_roll['strat_roll_calmar'] < df_roll['bm_roll_calmar'],
                 alpha=0.10, color=C_NEG, interpolate=True)
ax4.legend(fontsize=9, loc='upper left', framealpha=0.8)
ax4.grid(color=GRID_C, alpha=0.15, linewidth=0.5)
ax4.set_ylabel('Calmar Ratio', fontsize=11)
ax4.set_title('3Y Rolling Calmar Ratio', fontsize=13, pad=14)
plt.tight_layout()
plt.savefig('rolling_calmar.png', dpi=150, bbox_inches='tight')
plt.show()

# python world_rotation/DMvsEM.py

# python world_rotation/DMvsEM.py
