"""
KOSPI200 선물 장마감 시간대 분석
- 승률, 상관관계, 평균 수익률 분석
- 승률 > 50%: 롱 수익률 (상승일 평균)
- 승률 <= 50%: 숏 수익률 (하락일 평균)
- Look-ahead bias 제거:
  - Phase1 (15:20~15:30): 15:20까지의 지수 수익률/변동성 사용
  - Phase2 (15:30~15:45): 15:30까지의 지수 수익률/변동성 사용
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
QUANTILE = 0.10  # 상위/하위 N% (0.20 = 20%, 0.30 = 30%)
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
    df_idx.columns = ['Datetime', 'Close']
    df_idx['Datetime'] = pd.to_datetime(df_idx['Datetime'])
    df_idx['Time'] = df_idx['Datetime'].dt.time
    
    # 정규장 필터링
    day_start = datetime.time(9, 0, 0)
    day_end = datetime.time(15, 45, 0)
    df_idx = df_idx[(df_idx['Time'] >= day_start) & (df_idx['Time'] <= day_end)].copy()
    df_idx['Date'] = df_idx['Datetime'].dt.date
    df_idx = df_idx.rename(columns={'Close': 'Idx_Close'})
    
    return df_fut, df_idx


def calculate_daily_stats(df_fut, df_idx):
    """
    일별 수익률, 변동성, Phase 수익률 계산
    - Phase1용: 15:20까지 수익률/변동성
    - Phase2용: 15:30까지 수익률/변동성
    """
    
    t_0900 = datetime.time(9, 0)
    t_1520 = datetime.time(15, 20)
    t_1530 = datetime.time(15, 30)
    t_1545 = datetime.time(15, 44)
    
    # 지수: 일별 수익률/변동성 (15:20 기준, 15:30 기준 각각 계산)
    daily_stats = []
    for date, grp in df_idx.groupby('Date'):
        grp = grp.sort_values('Time')
        
        # 시가 (09:00)
        open_row = grp[grp['Time'] == t_0900]
        open_price = open_row.iloc[0]['Idx_Close'] if len(open_row) > 0 else grp.iloc[0]['Idx_Close']
        
        # ============================================================
        # 15:20 기준 (Phase1용)
        # ============================================================
        close_row_1520 = grp[grp['Time'] == t_1520]
        close_price_1520 = close_row_1520.iloc[0]['Idx_Close'] if len(close_row_1520) > 0 else grp[grp['Time'] <= t_1520].iloc[-1]['Idx_Close']
        
        daily_ret_1520 = (close_price_1520 - open_price) / open_price * 100
        
        # Realized Volatility (09:00 ~ 15:20)
        grp_1520 = grp[grp['Time'] <= t_1520].copy()
        grp_1520['return'] = grp_1520['Idx_Close'].pct_change()
        grp_1520['return_sq'] = grp_1520['return'] ** 2
        daily_rv_1520 = np.sqrt(grp_1520['return_sq'].sum()) * 100
        
        # ============================================================
        # 15:30 기준 (Phase2용)
        # ============================================================
        close_row_1530 = grp[grp['Time'] == t_1530]
        close_price_1530 = close_row_1530.iloc[0]['Idx_Close'] if len(close_row_1530) > 0 else grp[grp['Time'] <= t_1530].iloc[-1]['Idx_Close']
        
        daily_ret_1530 = (close_price_1530 - open_price) / open_price * 100
        
        # Realized Volatility (09:00 ~ 15:30)
        grp_1530 = grp[grp['Time'] <= t_1530].copy()
        grp_1530['return'] = grp_1530['Idx_Close'].pct_change()
        grp_1530['return_sq'] = grp_1530['return'] ** 2
        daily_rv_1530 = np.sqrt(grp_1530['return_sq'].sum()) * 100
        
        daily_stats.append({
            'Date': date,
            'Daily_Ret_1520': daily_ret_1520,  # Phase1용
            'Daily_RV_1520': daily_rv_1520,    # Phase1용
            'Daily_Ret_1530': daily_ret_1530,  # Phase2용
            'Daily_RV_1530': daily_rv_1530,    # Phase2용
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
        row_1545 = grp[grp['Time'] >= t_1545]
        price_1545 = row_1545.iloc[0]['Fut_Close'] if len(row_1545) > 0 else grp.iloc[-1]['Fut_Close']
        
        ret_phase1 = (price_1530 - price_1520) / price_1520 * 10000  # bp
        ret_phase2 = (price_1545 - price_1530) / price_1530 * 10000  # bp
        
        fut_phases.append({'Date': date, 'Ret_Phase1': ret_phase1, 'Ret_Phase2': ret_phase2})
    
    df_fut_daily = pd.DataFrame(fut_phases)
    
    # 병합
    df = pd.merge(df_daily, df_fut_daily, on='Date', how='inner')
    
    return df


def classify_regime(df, quantile=0.20):
    """
    마켓 레짐 분류 (상위/하위 N%)
    - Phase1용: 15:20 기준 수익률/변동성
    - Phase2용: 15:30 기준 수익률/변동성
    """
    
    # Phase1용 분류 (15:20 기준)
    ret_upper_1520 = df['Daily_Ret_1520'].quantile(1 - quantile)
    ret_lower_1520 = df['Daily_Ret_1520'].quantile(quantile)
    rv_upper_1520 = df['Daily_RV_1520'].quantile(1 - quantile)
    rv_lower_1520 = df['Daily_RV_1520'].quantile(quantile)
    
    df['Return_Type_P1'] = df['Daily_Ret_1520'].apply(
        lambda x: 'Bull' if x >= ret_upper_1520 else ('Bear' if x <= ret_lower_1520 else 'Neutral'))
    df['Vol_Type_P1'] = df['Daily_RV_1520'].apply(
        lambda x: 'High Vol' if x >= rv_upper_1520 else ('Low Vol' if x <= rv_lower_1520 else 'Neutral'))
    
    # Phase2용 분류 (15:30 기준)
    ret_upper_1530 = df['Daily_Ret_1530'].quantile(1 - quantile)
    ret_lower_1530 = df['Daily_Ret_1530'].quantile(quantile)
    rv_upper_1530 = df['Daily_RV_1530'].quantile(1 - quantile)
    rv_lower_1530 = df['Daily_RV_1530'].quantile(quantile)
    
    df['Return_Type_P2'] = df['Daily_Ret_1530'].apply(
        lambda x: 'Bull' if x >= ret_upper_1530 else ('Bear' if x <= ret_lower_1530 else 'Neutral'))
    df['Vol_Type_P2'] = df['Daily_RV_1530'].apply(
        lambda x: 'High Vol' if x >= rv_upper_1530 else ('Low Vol' if x <= rv_lower_1530 else 'Neutral'))
    
    print(f"\n분류 기준 (상위/하위 {quantile*100:.0f}%)")
    print(f"\n  [Phase1용 - 15:20 기준]")
    print(f"    수익률 상위: >= {ret_upper_1520:.2f}%")
    print(f"    수익률 하위: <= {ret_lower_1520:.2f}%")
    print(f"    변동성 상위: >= {rv_upper_1520:.2f}%")
    print(f"    변동성 하위: <= {rv_lower_1520:.2f}%")
    print(f"\n  [Phase2용 - 15:30 기준]")
    print(f"    수익률 상위: >= {ret_upper_1530:.2f}%")
    print(f"    수익률 하위: <= {ret_lower_1530:.2f}%")
    print(f"    변동성 상위: >= {rv_upper_1530:.2f}%")
    print(f"    변동성 하위: <= {rv_lower_1530:.2f}%")
    
    return df


def analyze_win_rate_filtered(df, quantile):
    """
    승률 기준 롱/숏 수익률 분석 (Look-ahead bias 제거)
    - Phase1: 15:20 기준 레짐 사용
    - Phase2: 15:30 기준 레짐 사용
    """
    
    results = []
    
    # Phase1 분석 (15:20 기준 레짐)
    regimes_p1 = [
        ('Bull', 'Return_Type_P1', '수익률 상위'),
        ('Bear', 'Return_Type_P1', '수익률 하위'),
        ('High Vol', 'Vol_Type_P1', '변동성 상위'),
        ('Low Vol', 'Vol_Type_P1', '변동성 하위'),
    ]
    
    for regime_key, regime_col, regime_name in regimes_p1:
        subset = df[df[regime_col] == regime_key]
        n = len(subset)
        
        phase_col = 'Ret_Phase1'
        phase_name = 'Phase1 (15:20~15:30)'
        
        win_rate = (subset[phase_col] > 0).mean() * 100
        mean_all = subset[phase_col].mean()
        
        if win_rate > 50:
            direction = 'Long'
            filtered = subset[subset[phase_col] > 0]
            filtered_mean = filtered[phase_col].mean() if len(filtered) > 0 else 0
            filtered_n = len(filtered)
        else:
            direction = 'Short'
            filtered = subset[subset[phase_col] < 0]
            filtered_mean = abs(filtered[phase_col].mean()) if len(filtered) > 0 else 0
            filtered_n = len(filtered)
        
        results.append({
            'Regime': f'{regime_name} ({regime_key})',
            'Phase': phase_name,
            'Basis': '15:20 기준',
            'N': n,
            'Win Rate': win_rate,
            'Mean (bp)': mean_all,
            'Direction': direction,
            'Filtered N': filtered_n,
            'Filtered Mean (bp)': filtered_mean,
        })
    
    # Phase2 분석 (15:30 기준 레짐)
    regimes_p2 = [
        ('Bull', 'Return_Type_P2', '수익률 상위'),
        ('Bear', 'Return_Type_P2', '수익률 하위'),
        ('High Vol', 'Vol_Type_P2', '변동성 상위'),
        ('Low Vol', 'Vol_Type_P2', '변동성 하위'),
    ]
    
    for regime_key, regime_col, regime_name in regimes_p2:
        subset = df[df[regime_col] == regime_key]
        n = len(subset)
        
        phase_col = 'Ret_Phase2'
        phase_name = 'Phase2 (15:30~15:45)'
        
        win_rate = (subset[phase_col] > 0).mean() * 100
        mean_all = subset[phase_col].mean()
        
        if win_rate > 50:
            direction = 'Long'
            filtered = subset[subset[phase_col] > 0]
            filtered_mean = filtered[phase_col].mean() if len(filtered) > 0 else 0
            filtered_n = len(filtered)
        else:
            direction = 'Short'
            filtered = subset[subset[phase_col] < 0]
            filtered_mean = abs(filtered[phase_col].mean()) if len(filtered) > 0 else 0
            filtered_n = len(filtered)
        
        results.append({
            'Regime': f'{regime_name} ({regime_key})',
            'Phase': phase_name,
            'Basis': '15:30 기준',
            'N': n,
            'Win Rate': win_rate,
            'Mean (bp)': mean_all,
            'Direction': direction,
            'Filtered N': filtered_n,
            'Filtered Mean (bp)': filtered_mean,
        })
    
    df_results = pd.DataFrame(results)
    return df_results


def print_analysis(df, quantile):
    """분석 결과 출력"""
    
    pct = int(quantile * 100)
    
    print("\n" + "="*100)
    print(f"전체 분석 결과 (상위/하위 {pct}%) - Look-ahead Bias 제거")
    print("="*100)
    
    # Phase1 기본 통계 (15:20 기준)
    print(f"\n[Phase1 분석 - 15:20 기준 레짐]")
    print(f"{'Regime':<15} {'Phase':<22} {'N':>4} {'승률':>8} {'평균':>10}")
    print("-"*70)
    
    for regime_key, regime_col in [('Bull', 'Return_Type_P1'), ('Bear', 'Return_Type_P1'),
                                    ('High Vol', 'Vol_Type_P1'), ('Low Vol', 'Vol_Type_P1')]:
        subset = df[df[regime_col] == regime_key]
        n = len(subset)
        wr = (subset['Ret_Phase1'] > 0).mean() * 100
        mean = subset['Ret_Phase1'].mean()
        print(f"{regime_key:<15} {'Phase1 (15:20~15:30)':<22} {n:>4} {wr:>7.1f}% {mean:>+9.2f}bp")
    
    # Phase2 기본 통계 (15:30 기준)
    print(f"\n[Phase2 분석 - 15:30 기준 레짐]")
    print(f"{'Regime':<15} {'Phase':<22} {'N':>4} {'승률':>8} {'평균':>10}")
    print("-"*70)
    
    for regime_key, regime_col in [('Bull', 'Return_Type_P2'), ('Bear', 'Return_Type_P2'),
                                    ('High Vol', 'Vol_Type_P2'), ('Low Vol', 'Vol_Type_P2')]:
        subset = df[df[regime_col] == regime_key]
        n = len(subset)
        wr = (subset['Ret_Phase2'] > 0).mean() * 100
        mean = subset['Ret_Phase2'].mean()
        print(f"{regime_key:<15} {'Phase2 (15:30~15:45)':<22} {n:>4} {wr:>7.1f}% {mean:>+9.2f}bp")
    
    # 방향성 수익률 분석
    print("\n" + "="*100)
    print("방향성 수익률 분석 (승률 > 50%: Long, 승률 <= 50%: Short)")
    print("="*100)
    
    df_results = analyze_win_rate_filtered(df, quantile)
    
    print(f"\n{'Regime':<20} {'Phase':<22} {'기준':>10} {'N':>4} {'승률':>8} {'방향':>6} {'해당N':>7} {'방향평균':>12}")
    print("-"*100)
    
    for _, row in df_results.iterrows():
        print(f"{row['Regime']:<20} {row['Phase']:<22} {row['Basis']:>10} {row['N']:>4} "
              f"{row['Win Rate']:>7.1f}% {row['Direction']:>6} "
              f"{row['Filtered N']:>7} {row['Filtered Mean (bp)']:>+11.2f}bp")
    
    # 상관관계
    print("\n" + "="*100)
    print("상관관계")
    print("="*100)
    print(f"\n[Phase1 - 15:20 기준]")
    print(f"  Daily Return (15:20) vs Phase1:     r = {df['Daily_Ret_1520'].corr(df['Ret_Phase1']):.4f}")
    print(f"  Daily Volatility (15:20) vs Phase1: r = {df['Daily_RV_1520'].corr(df['Ret_Phase1']):.4f}")
    print(f"\n[Phase2 - 15:30 기준]")
    print(f"  Daily Return (15:30) vs Phase2:     r = {df['Daily_Ret_1530'].corr(df['Ret_Phase2']):.4f}")
    print(f"  Daily Volatility (15:30) vs Phase2: r = {df['Daily_RV_1530'].corr(df['Ret_Phase2']):.4f}")
    
    return df_results


def plot_simple_analysis(df, quantile):
    """간소화된 시각화: Phase별 분리"""
    
    pct = int(quantile * 100)
    
    # ============================================================
    # Phase1 시각화 (15:20 기준)
    # ============================================================
    fig, axes = plt.subplots(2, 3, figsize=(15, 10))
    fig.suptitle(f'Phase1 (15:20~15:30) Analysis - Based on 15:20 Data (Top/Bottom {pct}%)', 
                 fontsize=14, fontweight='bold')
    
    for row, (group_col, title) in enumerate([('Return_Type_P1', 'Return Regime'), 
                                               ('Vol_Type_P1', 'Volatility Regime')]):
        df_filtered = df[df[group_col] != 'Neutral'].copy()
        phase = 'Ret_Phase1'
        
        # 1. 승률 (Countplot)
        ax1 = axes[row, 0]
        df_filtered['Direction'] = df_filtered[phase].apply(lambda x: 'Up' if x > 0 else 'Down')
        sns.countplot(data=df_filtered, x=group_col, hue='Direction', ax=ax1, 
                     palette={'Up': '#2ecc71', 'Down': '#e74c3c'})
        ax1.set_title(f'{title}\nWin/Loss Count')
        ax1.set_ylabel('Count')
        ax1.set_xlabel('')
        ax1.legend(title='')
        
        for i, grp_name in enumerate(df_filtered[group_col].unique()):
            subset = df_filtered[df_filtered[group_col] == grp_name]
            win_rate = (subset[phase] > 0).mean() * 100
            ax1.text(i, ax1.get_ylim()[1] * 0.9, f'{win_rate:.0f}%', 
                    ha='center', fontsize=12, fontweight='bold')
        
        # 2. 상관관계 (Scatterplot)
        ax2 = axes[row, 1]
        x_col = 'Daily_Ret_1520' if 'Return' in group_col else 'Daily_RV_1520'
        x_label = 'Daily Return 15:20 (%)' if 'Return' in group_col else 'Daily Volatility 15:20 (%)'
        
        sns.regplot(data=df, x=x_col, y=phase, ax=ax2, 
                   scatter_kws={'alpha':0.6, 'color':'steelblue'}, 
                   line_kws={'color':'red'})
        ax2.set_title(f'{title}\nCorrelation')
        ax2.set_xlabel(x_label)
        ax2.set_ylabel('Return (bp)')
        ax2.axhline(0, color='gray', linestyle='--', alpha=0.3)
        ax2.axvline(0, color='gray', linestyle='--', alpha=0.3)
        
        corr = df[x_col].corr(df[phase])
        ax2.text(0.05, 0.95, f'r = {corr:.3f}', transform=ax2.transAxes, 
                fontsize=12, fontweight='bold', verticalalignment='top',
                bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))
        
        # 3. 테이블
        ax3 = axes[row, 2]
        ax3.axis('off')
        
        table_data = []
        for grp_name in df_filtered[group_col].unique():
            subset = df_filtered[df_filtered[group_col] == grp_name]
            mean_ret = subset[phase].mean()
            win_rate = (subset[phase] > 0).mean() * 100
            n = len(subset)
            
            if win_rate > 50:
                direction = 'Long'
                dir_mean = subset[subset[phase] > 0][phase].mean()
            else:
                direction = 'Short'
                dir_mean = abs(subset[subset[phase] < 0][phase].mean())
            
            table_data.append([grp_name, n, f'{mean_ret:.2f}', f'{win_rate:.1f}%', direction, f'{dir_mean:.2f}'])
        
        table = ax3.table(cellText=table_data,
                         colLabels=['Regime', 'N', 'Mean', 'WinRate', 'Dir', 'Dir Mean'],
                         cellLoc='center', loc='center',
                         colWidths=[0.22, 0.1, 0.15, 0.17, 0.13, 0.18])
        table.auto_set_font_size(False)
        table.set_fontsize(9)
        table.scale(1.2, 1.8)
        
        for j in range(6):
            table[(0, j)].set_facecolor('#3498db')
            table[(0, j)].set_text_props(color='white', fontweight='bold')
        
        ax3.set_title(f'{title}\nSummary Statistics', pad=20)
    
    plt.tight_layout()
    plt.savefig(f'analysis_phase1_{pct}pct.png', dpi=150, bbox_inches='tight')
    plt.close()
    print(f"Saved: analysis_phase1_{pct}pct.png")
    
    # ============================================================
    # Phase2 시각화 (15:30 기준)
    # ============================================================
    fig, axes = plt.subplots(2, 3, figsize=(15, 10))
    fig.suptitle(f'Phase2 (15:30~15:45) Analysis - Based on 15:30 Data (Top/Bottom {pct}%)', 
                 fontsize=14, fontweight='bold')
    
    for row, (group_col, title) in enumerate([('Return_Type_P2', 'Return Regime'), 
                                               ('Vol_Type_P2', 'Volatility Regime')]):
        df_filtered = df[df[group_col] != 'Neutral'].copy()
        phase = 'Ret_Phase2'
        
        # 1. 승률 (Countplot)
        ax1 = axes[row, 0]
        df_filtered['Direction'] = df_filtered[phase].apply(lambda x: 'Up' if x > 0 else 'Down')
        sns.countplot(data=df_filtered, x=group_col, hue='Direction', ax=ax1, 
                     palette={'Up': '#2ecc71', 'Down': '#e74c3c'})
        ax1.set_title(f'{title}\nWin/Loss Count')
        ax1.set_ylabel('Count')
        ax1.set_xlabel('')
        ax1.legend(title='')
        
        for i, grp_name in enumerate(df_filtered[group_col].unique()):
            subset = df_filtered[df_filtered[group_col] == grp_name]
            win_rate = (subset[phase] > 0).mean() * 100
            ax1.text(i, ax1.get_ylim()[1] * 0.9, f'{win_rate:.0f}%', 
                    ha='center', fontsize=12, fontweight='bold')
        
        # 2. 상관관계 (Scatterplot)
        ax2 = axes[row, 1]
        x_col = 'Daily_Ret_1530' if 'Return' in group_col else 'Daily_RV_1530'
        x_label = 'Daily Return 15:30 (%)' if 'Return' in group_col else 'Daily Volatility 15:30 (%)'
        
        sns.regplot(data=df, x=x_col, y=phase, ax=ax2, 
                   scatter_kws={'alpha':0.6, 'color':'steelblue'}, 
                   line_kws={'color':'red'})
        ax2.set_title(f'{title}\nCorrelation')
        ax2.set_xlabel(x_label)
        ax2.set_ylabel('Return (bp)')
        ax2.axhline(0, color='gray', linestyle='--', alpha=0.3)
        ax2.axvline(0, color='gray', linestyle='--', alpha=0.3)
        
        corr = df[x_col].corr(df[phase])
        ax2.text(0.05, 0.95, f'r = {corr:.3f}', transform=ax2.transAxes, 
                fontsize=12, fontweight='bold', verticalalignment='top',
                bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))
        
        # 3. 테이블
        ax3 = axes[row, 2]
        ax3.axis('off')
        
        table_data = []
        for grp_name in df_filtered[group_col].unique():
            subset = df_filtered[df_filtered[group_col] == grp_name]
            mean_ret = subset[phase].mean()
            win_rate = (subset[phase] > 0).mean() * 100
            n = len(subset)
            
            if win_rate > 50:
                direction = 'Long'
                dir_mean = subset[subset[phase] > 0][phase].mean()
            else:
                direction = 'Short'
                dir_mean = abs(subset[subset[phase] < 0][phase].mean())
            
            table_data.append([grp_name, n, f'{mean_ret:.2f}', f'{win_rate:.1f}%', direction, f'{dir_mean:.2f}'])
        
        table = ax3.table(cellText=table_data,
                         colLabels=['Regime', 'N', 'Mean', 'WinRate', 'Dir', 'Dir Mean'],
                         cellLoc='center', loc='center',
                         colWidths=[0.22, 0.1, 0.15, 0.17, 0.13, 0.18])
        table.auto_set_font_size(False)
        table.set_fontsize(9)
        table.scale(1.2, 1.8)
        
        for j in range(6):
            table[(0, j)].set_facecolor('#e74c3c')
            table[(0, j)].set_text_props(color='white', fontweight='bold')
        
        ax3.set_title(f'{title}\nSummary Statistics', pad=20)
    
    plt.tight_layout()
    plt.savefig(f'analysis_phase2_{pct}pct.png', dpi=150, bbox_inches='tight')
    plt.close()
    print(f"Saved: analysis_phase2_{pct}pct.png")


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
    print(f"KOSPI200 선물 장마감 분석 (상위/하위 {pct}%) - Look-ahead Bias 제거")
    print("="*100)
    print("\n1. 데이터 로드")
    df_fut, df_idx = load_data(fut_path, idx_path)
    print(f"   선물: {len(df_fut):,}건, 지수: {len(df_idx):,}건")
    
    # 2. 일별 통계 계산
    print("\n2. 일별 통계 계산")
    df = calculate_daily_stats(df_fut, df_idx)
    print(f"   분석 대상: {len(df)}일")
    print(f"   - Phase1용: 15:20 기준 수익률/변동성")
    print(f"   - Phase2용: 15:30 기준 수익률/변동성")
    
    # 3. 레짐 분류
    print("\n3. 레짐 분류")
    df = classify_regime(df, quantile=quantile)
    
    print(f"\n   [Phase1 레짐 분포]")
    print(f"     Return Type: {df['Return_Type_P1'].value_counts().to_dict()}")
    print(f"     Vol Type: {df['Vol_Type_P1'].value_counts().to_dict()}")
    print(f"\n   [Phase2 레짐 분포]")
    print(f"     Return Type: {df['Return_Type_P2'].value_counts().to_dict()}")
    print(f"     Vol Type: {df['Vol_Type_P2'].value_counts().to_dict()}")
    
    # 4. 시각화
    print("\n4. 시각화")
    plot_simple_analysis(df, quantile)
    
    # 5. 분석 결과 출력
    df_results = print_analysis(df, quantile)
    
    # 6. 데이터 저장
    df.to_csv(f'futures_analysis_data_{pct}pct.csv', index=False, encoding='utf-8-sig')
    df_results.to_csv(f'futures_analysis_results_{pct}pct.csv', index=False, encoding='utf-8-sig')
    print(f"\n데이터 저장 완료:")
    print(f"  - futures_analysis_data_{pct}pct.csv")
    print(f"  - futures_analysis_results_{pct}pct.csv")
    
    return df, df_results


if __name__ == "__main__":
    df, df_results = main()

#python K2_K2F/ret_vol.py