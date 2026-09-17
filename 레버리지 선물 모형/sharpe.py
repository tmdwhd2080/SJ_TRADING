"""
KOSPI200 선물 장마감 시간대 분석 (샤프 지수 기준)
- 샤프 지수 = 수익률 / 변동성
- Phase1 (15:20~15:30): 15:20까지의 지수 샤프 사용
- Phase2 (15:30~15:45): 15:30까지의 지수 샤프 사용
- Look-ahead bias 제거
"""

import pandas as pd
import numpy as np
import datetime
import matplotlib.pyplot as plt
import seaborn as sns
import warnings
warnings.filterwarnings('ignore')

# 한글 폰트 설정 (Windows: 'Malgun Gothic', Mac: 'AppleGothic')
plt.rcParams['font.family'] = 'Malgun Gothic'
# plt.rcParams['font.family'] = 'DejaVu Sans'
plt.rcParams['axes.unicode_minus'] = False
plt.rcParams['figure.facecolor'] = 'white'


# ============================================================
# 파라미터 설정 (여기서 수정)
# ============================================================
QUANTILE = 0.20  # 상위/하위 N% (0.20 = 20%, 0.30 = 30%)
# ============================================================


def load_data(fut_path, idx_path):
    """데이터 로드 및 전처리"""
    
    # 선물 데이터
    df_fut = pd.read_csv(fut_path)
    df_fut['Datetime'] = pd.to_datetime(df_fut['Datetime'])
    df_fut['Date'] = df_fut['Datetime'].dt.date
    df_fut['Time'] = df_fut['Datetime'].dt.time
    df_fut = df_fut.rename(columns={'Close': 'Fut_Close'})
    
    # 지수 데이터 (Bloomberg 형식: 4행 skip)
    df_idx = pd.read_excel(idx_path, skiprows=4, header=None)
    df_idx.columns = ['Datetime', 'Idx_Close']
    df_idx['Datetime'] = pd.to_datetime(df_idx['Datetime'])
    df_idx['Time'] = df_idx['Datetime'].dt.time
    
    # 정규장 필터링
    day_start = datetime.time(9, 0, 0)
    day_end = datetime.time(15, 45, 0)
    df_idx = df_idx[(df_idx['Time'] >= day_start) & (df_idx['Time'] <= day_end)].copy()
    df_idx['Date'] = df_idx['Datetime'].dt.date
    
    return df_fut, df_idx


def calculate_daily_stats(df_fut, df_idx):
    """
    일별 샤프 지수 및 Phase 수익률 계산
    - 샤프 = 수익률 / 변동성
    - Phase1용: 15:20까지 샤프
    - Phase2용: 15:30까지 샤프
    """
    
    t_0900 = datetime.time(9, 0)
    t_1520 = datetime.time(15, 20)
    t_1530 = datetime.time(15, 30)
    t_1544 = datetime.time(15, 44)
    
    # 지수: 일별 샤프 지수
    daily_stats = []
    for date, grp in df_idx.groupby('Date'):
        grp = grp.sort_values('Time')
        
        # 시가 (09:00)
        open_row = grp[grp['Time'] == t_0900]
        if len(open_row) == 0:
            continue
        open_price = open_row.iloc[0]['Idx_Close']
        
        # ============================================================
        # 15:20 기준 샤프 (Phase1용)
        # ============================================================
        close_row_1520 = grp[grp['Time'] == t_1520]
        if len(close_row_1520) == 0:
            continue
        close_price_1520 = close_row_1520.iloc[0]['Idx_Close']
        
        # 수익률 (%)
        daily_ret_1520 = (close_price_1520 - open_price) / open_price * 100
        
        # Realized Volatility (09:00 ~ 15:20)
        grp_1520 = grp[grp['Time'] <= t_1520].copy()
        grp_1520['return'] = grp_1520['Idx_Close'].pct_change()
        grp_1520['return_sq'] = grp_1520['return'] ** 2
        daily_rv_1520 = np.sqrt(grp_1520['return_sq'].sum()) * 100
        
        # 샤프 지수 = 수익률 / 변동성
        sharpe_1520 = daily_ret_1520 / daily_rv_1520 if daily_rv_1520 != 0 else 0
        
        # ============================================================
        # 15:30 기준 샤프 (Phase2용)
        # ============================================================
        close_row_1530 = grp[grp['Time'] == t_1530]
        if len(close_row_1530) == 0:
            continue
        close_price_1530 = close_row_1530.iloc[0]['Idx_Close']
        
        daily_ret_1530 = (close_price_1530 - open_price) / open_price * 100
        
        grp_1530 = grp[grp['Time'] <= t_1530].copy()
        grp_1530['return'] = grp_1530['Idx_Close'].pct_change()
        grp_1530['return_sq'] = grp_1530['return'] ** 2
        daily_rv_1530 = np.sqrt(grp_1530['return_sq'].sum()) * 100
        
        sharpe_1530 = daily_ret_1530 / daily_rv_1530 if daily_rv_1530 != 0 else 0
        
        daily_stats.append({
            'Date': date,
            'Daily_Ret_1520': daily_ret_1520,
            'Daily_RV_1520': daily_rv_1520,
            'Sharpe_1520': sharpe_1520,
            'Daily_Ret_1530': daily_ret_1530,
            'Daily_RV_1530': daily_rv_1530,
            'Sharpe_1530': sharpe_1530,
        })
    
    df_daily = pd.DataFrame(daily_stats)
    
    # 선물: Phase 수익률
    fut_phases = []
    for date, grp in df_fut.groupby('Date'):
        grp = grp.sort_values('Time')
        
        row_1520 = grp[grp['Time'] == t_1520]
        row_1530 = grp[grp['Time'] == t_1530]
        if len(row_1520) == 0 or len(row_1530) == 0:
            continue
        
        price_1520 = row_1520.iloc[0]['Fut_Close']
        price_1530 = row_1530.iloc[0]['Fut_Close']
        row_1544 = grp[grp['Time'] >= t_1544]
        price_1545 = row_1544.iloc[0]['Fut_Close'] if len(row_1544) > 0 else grp.iloc[-1]['Fut_Close']
        
        ret_phase1 = (price_1530 - price_1520) / price_1520 * 10000  # bp
        ret_phase2 = (price_1545 - price_1530) / price_1530 * 10000  # bp
        
        fut_phases.append({'Date': date, 'Ret_Phase1': ret_phase1, 'Ret_Phase2': ret_phase2})
    
    df_fut_daily = pd.DataFrame(fut_phases)
    
    # 병합
    df = pd.merge(df_daily, df_fut_daily, on='Date', how='inner')
    
    return df


def classify_regime(df, quantile=0.30):
    """
    샤프 지수 기준 마켓 레짐 분류 (상위/하위 N%)
    - Phase1용: 15:20 기준 샤프
    - Phase2용: 15:30 기준 샤프
    """
    
    # Phase1용 분류 (15:20 기준)
    sharpe_upper_1520 = df['Sharpe_1520'].quantile(1 - quantile)
    sharpe_lower_1520 = df['Sharpe_1520'].quantile(quantile)
    
    df['Sharpe_Type_P1'] = df['Sharpe_1520'].apply(
        lambda x: 'High Sharpe' if x >= sharpe_upper_1520 else ('Low Sharpe' if x <= sharpe_lower_1520 else 'Neutral'))
    
    # Phase2용 분류 (15:30 기준)
    sharpe_upper_1530 = df['Sharpe_1530'].quantile(1 - quantile)
    sharpe_lower_1530 = df['Sharpe_1530'].quantile(quantile)
    
    df['Sharpe_Type_P2'] = df['Sharpe_1530'].apply(
        lambda x: 'High Sharpe' if x >= sharpe_upper_1530 else ('Low Sharpe' if x <= sharpe_lower_1530 else 'Neutral'))
    
    print(f"\n분류 기준 (상위/하위 {quantile*100:.0f}%)")
    print(f"\n  [Phase1용 - 15:20 기준 샤프]")
    print(f"    High Sharpe: >= {sharpe_upper_1520:.3f}")
    print(f"    Low Sharpe:  <= {sharpe_lower_1520:.3f}")
    print(f"\n  [Phase2용 - 15:30 기준 샤프]")
    print(f"    High Sharpe: >= {sharpe_upper_1530:.3f}")
    print(f"    Low Sharpe:  <= {sharpe_lower_1530:.3f}")
    
    return df


def analyze_sharpe_regime(df, quantile):
    """샤프 레짐별 수익률 분석"""
    
    results = []
    
    # Phase1 분석 (15:20 기준 샤프)
    for regime in ['High Sharpe', 'Low Sharpe']:
        subset = df[df['Sharpe_Type_P1'] == regime]
        n = len(subset)
        if n == 0:
            continue
        
        win_rate = (subset['Ret_Phase1'] > 0).mean() * 100
        mean_all = subset['Ret_Phase1'].mean()
        
        if win_rate > 50:
            direction = 'Long'
            filtered = subset[subset['Ret_Phase1'] > 0]
            filtered_mean = filtered['Ret_Phase1'].mean() if len(filtered) > 0 else 0
        else:
            direction = 'Short'
            filtered = subset[subset['Ret_Phase1'] < 0]
            filtered_mean = abs(filtered['Ret_Phase1'].mean()) if len(filtered) > 0 else 0
        
        results.append({
            'Regime': regime,
            'Phase': 'Phase1 (15:20~15:30)',
            'Basis': '15:20 샤프',
            'N': n,
            'Win Rate': win_rate,
            'Mean (bp)': mean_all,
            'Direction': direction,
            'Filtered N': len(filtered),
            'Filtered Mean (bp)': filtered_mean,
        })
    
    # Phase2 분석 (15:30 기준 샤프)
    for regime in ['High Sharpe', 'Low Sharpe']:
        subset = df[df['Sharpe_Type_P2'] == regime]
        n = len(subset)
        if n == 0:
            continue
        
        win_rate = (subset['Ret_Phase2'] > 0).mean() * 100
        mean_all = subset['Ret_Phase2'].mean()
        
        if win_rate > 50:
            direction = 'Long'
            filtered = subset[subset['Ret_Phase2'] > 0]
            filtered_mean = filtered['Ret_Phase2'].mean() if len(filtered) > 0 else 0
        else:
            direction = 'Short'
            filtered = subset[subset['Ret_Phase2'] < 0]
            filtered_mean = abs(filtered['Ret_Phase2'].mean()) if len(filtered) > 0 else 0
        
        results.append({
            'Regime': regime,
            'Phase': 'Phase2 (15:30~15:45)',
            'Basis': '15:30 샤프',
            'N': n,
            'Win Rate': win_rate,
            'Mean (bp)': mean_all,
            'Direction': direction,
            'Filtered N': len(filtered),
            'Filtered Mean (bp)': filtered_mean,
        })
    
    return pd.DataFrame(results)


def print_analysis(df, quantile):
    """분석 결과 출력"""
    
    pct = int(quantile * 100)
    
    print("\n" + "="*100)
    print(f"샤프 지수 기반 분석 결과 (상위/하위 {pct}%)")
    print("="*100)
    
    # 샤프 통계
    print("\n[샤프 지수 통계]")
    print(df[['Sharpe_1520', 'Sharpe_1530']].describe())
    
    # Phase1 분석
    print("\n" + "-"*100)
    print("Phase1 분석 (15:20 샤프 기준 → 15:20~15:30 선물 수익률)")
    print("-"*100)
    print(f"{'Regime':<15} {'N':>4} {'승률':>8} {'평균':>10} {'방향':>8} {'방향N':>7} {'방향평균':>12}")
    print("-"*80)
    
    for regime in ['High Sharpe', 'Low Sharpe']:
        subset = df[df['Sharpe_Type_P1'] == regime]
        n = len(subset)
        wr = (subset['Ret_Phase1'] > 0).mean() * 100
        mean = subset['Ret_Phase1'].mean()
        
        if wr > 50:
            direction = 'Long'
            filtered = subset[subset['Ret_Phase1'] > 0]
        else:
            direction = 'Short'
            filtered = subset[subset['Ret_Phase1'] < 0]
        
        dir_n = len(filtered)
        dir_mean = filtered['Ret_Phase1'].mean() if direction == 'Long' else abs(filtered['Ret_Phase1'].mean())
        
        print(f"{regime:<15} {n:>4} {wr:>7.1f}% {mean:>+9.2f}bp {direction:>8} {dir_n:>7} {dir_mean:>+11.2f}bp")
    
    # Phase2 분석
    print("\n" + "-"*100)
    print("Phase2 분석 (15:30 샤프 기준 → 15:30~15:45 선물 수익률)")
    print("-"*100)
    print(f"{'Regime':<15} {'N':>4} {'승률':>8} {'평균':>10} {'방향':>8} {'방향N':>7} {'방향평균':>12}")
    print("-"*80)
    
    for regime in ['High Sharpe', 'Low Sharpe']:
        subset = df[df['Sharpe_Type_P2'] == regime]
        n = len(subset)
        wr = (subset['Ret_Phase2'] > 0).mean() * 100
        mean = subset['Ret_Phase2'].mean()
        
        if wr > 50:
            direction = 'Long'
            filtered = subset[subset['Ret_Phase2'] > 0]
        else:
            direction = 'Short'
            filtered = subset[subset['Ret_Phase2'] < 0]
        
        dir_n = len(filtered)
        dir_mean = filtered['Ret_Phase2'].mean() if direction == 'Long' else abs(filtered['Ret_Phase2'].mean())
        
        print(f"{regime:<15} {n:>4} {wr:>7.1f}% {mean:>+9.2f}bp {direction:>8} {dir_n:>7} {dir_mean:>+11.2f}bp")
    
    # 상관관계
    print("\n" + "="*100)
    print("상관관계")
    print("="*100)
    print(f"\n[Phase1]")
    print(f"  Sharpe (15:20) vs Phase1 Return: r = {df['Sharpe_1520'].corr(df['Ret_Phase1']):.4f}")
    print(f"  Return (15:20) vs Phase1 Return: r = {df['Daily_Ret_1520'].corr(df['Ret_Phase1']):.4f}")
    print(f"  RV (15:20) vs Phase1 Return:     r = {df['Daily_RV_1520'].corr(df['Ret_Phase1']):.4f}")
    print(f"\n[Phase2]")
    print(f"  Sharpe (15:30) vs Phase2 Return: r = {df['Sharpe_1530'].corr(df['Ret_Phase2']):.4f}")
    print(f"  Return (15:30) vs Phase2 Return: r = {df['Daily_Ret_1530'].corr(df['Ret_Phase2']):.4f}")
    print(f"  RV (15:30) vs Phase2 Return:     r = {df['Daily_RV_1530'].corr(df['Ret_Phase2']):.4f}")
    
    df_results = analyze_sharpe_regime(df, quantile)
    return df_results


def plot_sharpe_analysis(df, quantile):
    """샤프 지수 기반 시각화"""
    
    pct = int(quantile * 100)
    
    fig, axes = plt.subplots(2, 3, figsize=(15, 10))
    fig.suptitle(f'Sharpe-based Analysis (Top/Bottom {pct}%)', fontsize=14, fontweight='bold')
    
    # ============================================================
    # Phase1 (15:20 샤프 → 15:20~15:30 선물)
    # ============================================================
    
    # 1. Scatter: Sharpe vs Phase1
    ax1 = axes[0, 0]
    sns.regplot(data=df, x='Sharpe_1520', y='Ret_Phase1', ax=ax1,
                scatter_kws={'alpha': 0.6, 'color': 'steelblue'},
                line_kws={'color': 'red'})
    ax1.axhline(0, ls='--', color='gray', alpha=0.5)
    ax1.axvline(0, ls='--', color='gray', alpha=0.5)
    corr = df['Sharpe_1520'].corr(df['Ret_Phase1'])
    ax1.set_title(f'Phase1: Sharpe (15:20) vs Return\nr = {corr:.4f}')
    ax1.set_xlabel('Sharpe (09:00~15:20)')
    ax1.set_ylabel('Phase1 Return (bp)')
    
    # 2. Win Rate by Sharpe Regime
    ax2 = axes[0, 1]
    df_p1 = df[df['Sharpe_Type_P1'] != 'Neutral'].copy()
    df_p1['Direction'] = df_p1['Ret_Phase1'].apply(lambda x: 'Up' if x > 0 else 'Down')
    sns.countplot(data=df_p1, x='Sharpe_Type_P1', hue='Direction', ax=ax2,
                  palette={'Up': '#2ecc71', 'Down': '#e74c3c'})
    ax2.set_title('Phase1: Win/Loss by Sharpe Regime')
    ax2.set_xlabel('')
    ax2.legend(title='')
    
    for i, regime in enumerate(df_p1['Sharpe_Type_P1'].unique()):
        subset = df_p1[df_p1['Sharpe_Type_P1'] == regime]
        wr = (subset['Ret_Phase1'] > 0).mean() * 100
        ax2.text(i, ax2.get_ylim()[1] * 0.9, f'{wr:.0f}%', ha='center', fontsize=12, fontweight='bold')
    
    # 3. Summary Table
    ax3 = axes[0, 2]
    ax3.axis('off')
    table_data = []
    for regime in ['High Sharpe', 'Low Sharpe']:
        subset = df[df['Sharpe_Type_P1'] == regime]
        n = len(subset)
        wr = (subset['Ret_Phase1'] > 0).mean() * 100
        mean = subset['Ret_Phase1'].mean()
        direction = 'Long' if wr > 50 else 'Short'
        table_data.append([regime, n, f'{mean:+.2f}', f'{wr:.1f}%', direction])
    
    table = ax3.table(cellText=table_data,
                      colLabels=['Regime', 'N', 'Mean(bp)', 'WinRate', 'Dir'],
                      cellLoc='center', loc='center',
                      colWidths=[0.3, 0.15, 0.2, 0.2, 0.15])
    table.auto_set_font_size(False)
    table.set_fontsize(10)
    table.scale(1.2, 1.8)
    for j in range(5):
        table[(0, j)].set_facecolor('#3498db')
        table[(0, j)].set_text_props(color='white', fontweight='bold')
    ax3.set_title('Phase1 Summary', pad=20)
    
    # ============================================================
    # Phase2 (15:30 샤프 → 15:30~15:45 선물)
    # ============================================================
    
    # 1. Scatter: Sharpe vs Phase2
    ax4 = axes[1, 0]
    sns.regplot(data=df, x='Sharpe_1530', y='Ret_Phase2', ax=ax4,
                scatter_kws={'alpha': 0.6, 'color': 'steelblue'},
                line_kws={'color': 'red'})
    ax4.axhline(0, ls='--', color='gray', alpha=0.5)
    ax4.axvline(0, ls='--', color='gray', alpha=0.5)
    corr = df['Sharpe_1530'].corr(df['Ret_Phase2'])
    ax4.set_title(f'Phase2: Sharpe (15:30) vs Return\nr = {corr:.4f}')
    ax4.set_xlabel('Sharpe (09:00~15:30)')
    ax4.set_ylabel('Phase2 Return (bp)')
    
    # 2. Win Rate by Sharpe Regime
    ax5 = axes[1, 1]
    df_p2 = df[df['Sharpe_Type_P2'] != 'Neutral'].copy()
    df_p2['Direction'] = df_p2['Ret_Phase2'].apply(lambda x: 'Up' if x > 0 else 'Down')
    sns.countplot(data=df_p2, x='Sharpe_Type_P2', hue='Direction', ax=ax5,
                  palette={'Up': '#2ecc71', 'Down': '#e74c3c'})
    ax5.set_title('Phase2: Win/Loss by Sharpe Regime')
    ax5.set_xlabel('')
    ax5.legend(title='')
    
    for i, regime in enumerate(df_p2['Sharpe_Type_P2'].unique()):
        subset = df_p2[df_p2['Sharpe_Type_P2'] == regime]
        wr = (subset['Ret_Phase2'] > 0).mean() * 100
        ax5.text(i, ax5.get_ylim()[1] * 0.9, f'{wr:.0f}%', ha='center', fontsize=12, fontweight='bold')
    
    # 3. Summary Table
    ax6 = axes[1, 2]
    ax6.axis('off')
    table_data = []
    for regime in ['High Sharpe', 'Low Sharpe']:
        subset = df[df['Sharpe_Type_P2'] == regime]
        n = len(subset)
        wr = (subset['Ret_Phase2'] > 0).mean() * 100
        mean = subset['Ret_Phase2'].mean()
        direction = 'Long' if wr > 50 else 'Short'
        table_data.append([regime, n, f'{mean:+.2f}', f'{wr:.1f}%', direction])
    
    table = ax6.table(cellText=table_data,
                      colLabels=['Regime', 'N', 'Mean(bp)', 'WinRate', 'Dir'],
                      cellLoc='center', loc='center',
                      colWidths=[0.3, 0.15, 0.2, 0.2, 0.15])
    table.auto_set_font_size(False)
    table.set_fontsize(10)
    table.scale(1.2, 1.8)
    for j in range(5):
        table[(0, j)].set_facecolor('#e74c3c')
        table[(0, j)].set_text_props(color='white', fontweight='bold')
    ax6.set_title('Phase2 Summary', pad=20)
    
    plt.tight_layout()
    plt.savefig(f'sharpe_analysis_{pct}pct.png', dpi=150, bbox_inches='tight')
    plt.close()
    print(f"Saved: sharpe_analysis_{pct}pct.png")


def main():
    # ============================================================
    # 파일 경로 설정
    # ============================================================
    fut_path = r'C:\Users\intern9\truston_quant_dev\K2_K2F\K2_선물_분봉_정규장.csv'
    idx_path = r'C:\Users\intern9\truston_quant_dev\K2_K2F\K2_분봉.xlsx'
    
    # ============================================================
    # 상위/하위 N% 설정 (여기서 수정 가능)
    # ============================================================
    quantile = QUANTILE
    # ============================================================
    
    pct = int(quantile * 100)
    
    # 1. 데이터 로드
    print("="*100)
    print(f"KOSPI200 선물 장마감 분석 - 샤프 지수 기준 (상위/하위 {pct}%)")
    print("="*100)
    print("\n1. 데이터 로드")
    df_fut, df_idx = load_data(fut_path, idx_path)
    print(f"   선물: {len(df_fut):,}건, 지수: {len(df_idx):,}건")
    
    # 2. 일별 통계 계산
    print("\n2. 일별 샤프 지수 계산")
    df = calculate_daily_stats(df_fut, df_idx)
    print(f"   분석 대상: {len(df)}일")
    print(f"   - Phase1용: 09:00~15:20 샤프")
    print(f"   - Phase2용: 09:00~15:30 샤프")
    
    # 3. 레짐 분류
    print("\n3. 샤프 레짐 분류")
    df = classify_regime(df, quantile=quantile)
    
    print(f"\n   [Phase1 레짐 분포]")
    print(f"     {df['Sharpe_Type_P1'].value_counts().to_dict()}")
    print(f"\n   [Phase2 레짐 분포]")
    print(f"     {df['Sharpe_Type_P2'].value_counts().to_dict()}")
    
    # 4. 시각화
    print("\n4. 시각화")
    plot_sharpe_analysis(df, quantile)
    
    # 5. 분석 결과 출력
    df_results = print_analysis(df, quantile)
    
    # 6. 데이터 저장
    df.to_csv(f'sharpe_analysis_data_{pct}pct.csv', index=False, encoding='utf-8-sig')
    df_results.to_csv(f'sharpe_analysis_results_{pct}pct.csv', index=False, encoding='utf-8-sig')
    print(f"\n데이터 저장 완료:")
    print(f"  - sharpe_analysis_data_{pct}pct.csv")
    print(f"  - sharpe_analysis_results_{pct}pct.csv")
    
    return df, df_results


if __name__ == "__main__":
    df, df_results = main()

# python K2_K2F/sharpe.py