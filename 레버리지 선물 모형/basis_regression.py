"""
KOSPI200 선물 베이시스 괴리 분석
- 09:00~15:20 평균 베이시스 (정상 베이시스)
- 15:20~15:30 베이시스 (15:20 현물 고정)
- 베이시스 괴리(Disparity) = 15:20~15:30 베이시스 - 정상 베이시스
- 베이시스 괴리로 15:30~15:45 선물 수익률 예측
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
    day_end = datetime.time(15, 44, 0)
    df_idx = df_idx[(df_idx['Time'] >= day_start) & (df_idx['Time'] <= day_end)].copy()
    df_idx['Date'] = df_idx['Datetime'].dt.date
    
    # 병합
    df = pd.merge(df_fut[['Datetime', 'Date', 'Time', 'Fut_Close']], 
                  df_idx[['Datetime', 'Idx_Close']], 
                  on='Datetime', how='outer')
    df['Date'] = df['Datetime'].dt.date
    df['Time'] = df['Datetime'].dt.time
    df = df.sort_values(['Date', 'Time'])
    
    # 베이시스 계산 (선물 - 현물)
    df['Basis'] = df['Fut_Close'] - df['Idx_Close']
    
    return df


def fix_index_after_1520(df):
    """15:20 이후에는 15:20 현물가를 고정해서 베이시스 재계산"""
    
    t_1520 = datetime.time(15, 20)
    
    def _fix_group(grp):
        grp = grp.copy()
        
        # 15:20 현물 가격 추출
        idx_1520_row = grp[grp['Time'] == t_1520]
        if len(idx_1520_row) == 0:
            return grp
        
        idx_1520 = idx_1520_row.iloc[0]['Idx_Close']
        
        # 15:20 이후 현물 가격을 15:20 값으로 고정
        grp.loc[grp['Time'] > t_1520, 'Idx_Close_Fixed'] = idx_1520
        grp.loc[grp['Time'] <= t_1520, 'Idx_Close_Fixed'] = grp.loc[grp['Time'] <= t_1520, 'Idx_Close']
        
        # 고정된 베이시스 재계산
        grp['Basis_Fixed'] = grp['Fut_Close'] - grp['Idx_Close_Fixed']
        
        return grp
    
    df = df.groupby('Date', group_keys=False).apply(_fix_group)
    return df


def calculate_daily_basis_stats(df):
    """일별 베이시스 통계 계산"""
    
    t_0900 = datetime.time(9, 0)
    t_1520 = datetime.time(15, 20)
    t_1530 = datetime.time(15, 30)
    t_1544 = datetime.time(15, 44)
    
    daily_analysis = []
    
    for date, grp in df.groupby('Date'):
        grp = grp.sort_values('Time')
        
        # 1. 09:00 ~ 15:20 평균 베이시스 (정상 베이시스)
        basis_normal_data = grp[(grp['Time'] >= t_0900) & (grp['Time'] <= t_1520)]['Basis']
        if len(basis_normal_data) == 0:
            continue
        basis_normal = basis_normal_data.mean()
        
        # 2. 15:20 ~ 15:30 베이시스 (15:20 현물 고정) - 평균
        basis_gap_data = grp[(grp['Time'] > t_1520) & (grp['Time'] <= t_1530)]['Basis_Fixed']
        if len(basis_gap_data) == 0:
            continue
        basis_gap = basis_gap_data.mean()
        
        # 3. 베이시스 괴리 (Disparity)
        basis_disparity = basis_gap - basis_normal
        
        # 4. 15:30 ~ 15:45 선물 수익률
        row_1530 = grp[grp['Time'] == t_1530]
        row_1544 = grp[grp['Time'] >= t_1544]
        
        if len(row_1530) == 0 or len(row_1544) == 0:
            continue
        
        price_1530 = row_1530.iloc[0]['Fut_Close']
        price_1545 = row_1544.iloc[0]['Fut_Close']
        ret_post = (price_1545 - price_1530) / price_1530 * 10000  # bp
        
        daily_analysis.append({
            'Date': date,
            'Basis_Normal': basis_normal,      # 09:00~15:20 평균 베이시스
            'Basis_Gap': basis_gap,            # 15:20~15:30 평균 베이시스 (15:20 현물 고정)
            'X_Disparity': basis_disparity,    # 베이시스 괴리
            'Y_Post_Return': ret_post,         # 15:30~15:45 선물 수익률 (bp)
        })
    
    return pd.DataFrame(daily_analysis)


def analyze_disparity_quartiles(df_daily):
    """Disparity Quartile별 분석"""
    
    df_daily = df_daily.copy()
    df_daily['Disparity_Quartile'] = pd.qcut(
        df_daily['X_Disparity'], q=4, 
        labels=['Q1 (Low)', 'Q2', 'Q3', 'Q4 (High)']
    )
    
    results = []
    
    for q in ['Q1 (Low)', 'Q2', 'Q3', 'Q4 (High)']:
        subset = df_daily[df_daily['Disparity_Quartile'] == q]
        n = len(subset)
        mean_disparity = subset['X_Disparity'].mean()
        win_rate = (subset['Y_Post_Return'] > 0).mean() * 100
        mean_ret = subset['Y_Post_Return'].mean()
        
        if win_rate > 50:
            direction = 'Long'
            dir_ret = subset[subset['Y_Post_Return'] > 0]['Y_Post_Return'].mean()
            dir_n = len(subset[subset['Y_Post_Return'] > 0])
        else:
            direction = 'Short'
            dir_ret = abs(subset[subset['Y_Post_Return'] < 0]['Y_Post_Return'].mean())
            dir_n = len(subset[subset['Y_Post_Return'] < 0])
        
        results.append({
            'Quartile': q,
            'N': n,
            'Avg_Disparity': mean_disparity,
            'Win_Rate': win_rate,
            'Mean_Return': mean_ret,
            'Direction': direction,
            'Dir_N': dir_n,
            'Dir_Mean': dir_ret,
        })
    
    return pd.DataFrame(results), df_daily


def plot_analysis(df_daily, corr, filename='basis_disparity_analysis.png'):
    """시각화"""
    
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))
    
    # 1. Scatter + Regression
    ax1 = axes[0]
    sns.regplot(x='X_Disparity', y='Y_Post_Return', data=df_daily, ax=ax1,
                scatter_kws={'alpha': 0.6, 'color': 'steelblue'},
                line_kws={'color': 'red'})
    ax1.axhline(0, ls='--', color='gray', alpha=0.5)
    ax1.axvline(0, ls='--', color='gray', alpha=0.5)
    ax1.set_title(f'Basis Disparity vs Post-Close Return\n(r = {corr:.4f})', fontsize=12, fontweight='bold')
    ax1.set_xlabel('Basis Disparity (15:20~15:30 Basis - Normal Basis)')
    ax1.set_ylabel('Post-Market Futures Return (bp)')
    ax1.grid(True, alpha=0.3)
    
    # 2. Quartile별 수익률
    ax2 = axes[1]
    quartile_stats = df_daily.groupby('Disparity_Quartile')['Y_Post_Return'].agg(['mean', 'count'])
    
    colors = ['#2ecc71', '#3498db', '#f39c12', '#e74c3c']
    bars = ax2.bar(quartile_stats.index, quartile_stats['mean'], color=colors, edgecolor='black')
    ax2.axhline(0, ls='--', color='gray', alpha=0.5)
    ax2.set_title('Post-Close Return by Disparity Quartile', fontsize=12, fontweight='bold')
    ax2.set_xlabel('Basis Disparity Quartile')
    ax2.set_ylabel('Avg Post-Market Return (bp)')
    
    for bar, (idx, row) in zip(bars, quartile_stats.iterrows()):
        ax2.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.5, 
                 f'{row["mean"]:.1f}bp\n(n={int(row["count"])})', 
                 ha='center', va='bottom', fontsize=10)
    
    plt.tight_layout()
    plt.savefig(filename, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"Saved: {filename}")


def print_analysis(df_daily, df_quartile):
    """분석 결과 출력"""
    
    corr = df_daily['X_Disparity'].corr(df_daily['Y_Post_Return'])
    
    print("\n" + "="*80)
    print("베이시스 괴리 분석 결과")
    print("="*80)
    
    print(f"\n분석 대상: {len(df_daily)}일")
    print(f"상관계수 (Disparity vs Phase2 Return): r = {corr:.4f}")
    
    print("\n" + "-"*80)
    print("통계 요약")
    print("-"*80)
    print(df_daily[['X_Disparity', 'Y_Post_Return']].describe())
    
    print("\n" + "-"*80)
    print("Disparity Quartile별 Phase2 수익률 분석")
    print("-"*80)
    print(f"\n{'Quartile':<12} {'N':>4} {'Avg Disp':>10} {'Win Rate':>10} {'Mean Ret':>12} {'Direction':>10} {'Dir Mean':>12}")
    print("-"*80)
    
    for _, row in df_quartile.iterrows():
        print(f"{row['Quartile']:<12} {row['N']:>4} {row['Avg_Disparity']:>+10.3f} "
              f"{row['Win_Rate']:>9.1f}% {row['Mean_Return']:>+11.2f}bp "
              f"{row['Direction']:>10} {row['Dir_Mean']:>+11.2f}bp")
    
    return corr


def main():
    # ============================================================
    # 파일 경로 설정
    # ============================================================
    fut_path = r'C:\Users\intern9\truston_quant_dev\K2_K2F\K2_선물_분봉_정규장.csv'
    idx_path = r'C:\Users\intern9\truston_quant_dev\K2_K2F\K2_분봉.xlsx'
    
    # 1. 데이터 로드
    print("="*80)
    print("KOSPI200 선물 베이시스 괴리 분석")
    print("="*80)
    print("\n1. 데이터 로드")
    df = load_data(fut_path, idx_path)
    print(f"   병합된 데이터: {len(df):,}건")
    
    # 2. 15:20 이후 현물 고정
    print("\n2. 15:20 이후 현물 가격 고정")
    df = fix_index_after_1520(df)
    
    # 3. 일별 베이시스 통계 계산
    print("\n3. 일별 베이시스 통계 계산")
    df_daily = calculate_daily_basis_stats(df)
    print(f"   분석 대상: {len(df_daily)}일")
    
    # 4. Quartile 분석
    print("\n4. Disparity Quartile 분석")
    df_quartile, df_daily = analyze_disparity_quartiles(df_daily)
    
    # 5. 시각화
    print("\n5. 시각화")
    corr = df_daily['X_Disparity'].corr(df_daily['Y_Post_Return'])
    plot_analysis(df_daily, corr)
    
    # 6. 결과 출력
    print_analysis(df_daily, df_quartile)
    
    # 7. 데이터 저장
    df_daily.to_csv('basis_disparity_analysis.csv', index=False, encoding='utf-8-sig')
    print(f"\n데이터 저장: basis_disparity_analysis.csv")
    
    return df_daily, df_quartile


if __name__ == "__main__":
    df_daily, df_quartile = main()
#python K2_K2F/basis_regression.py