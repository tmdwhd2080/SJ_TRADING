"""
KOSPI200 선물 장마감 시간대 국면별 분석 (롤링 방식)

국면 분류 (전일 종가 대비 수익률 기준):
  - 강세장: >= +1.5%
  - 약상승장: 0% ~ +1.5%
  - 약하락장: -1.5% ~ 0%
  - 강하락장: <= -1.5%

롤링 방식:
  - t 시점의 선물 수익률 분석 시, t-1 시점까지의 지수 수익률로 국면 판단
  - 예: 15:05분 선물 수익률 계산 시 → 15:04분까지의 코스피 지수 수익률(전일 종가 대비)로 국면 판단
  - ★ 15:44분 예외: 
    - 국면 판단: 15:30분 코스피200 지수 (전일 종가 대비)
    - 선물 수익률: 15:30분 선물 대비 15:44분 선물 수익률

분석 대상:
  - 15:00 ~ 15:34 분봉별 + 15:44 분봉 (총 36개)

수익률 계산:
  - 국면 판단용: (t-1 시점 지수 - 전일 종가) / 전일 종가 * 100 (%)
  - 선물 수익률 (일반): (현재분 종가 - 1분전 종가) / 1분전 종가 * 10000 (bp)
  - 선물 수익률 (15:44): (15:44 종가 - 15:30 종가) / 15:30 종가 * 10000 (bp)
"""

import pandas as pd
import numpy as np
import datetime
import matplotlib.pyplot as plt
import warnings
warnings.filterwarnings('ignore')

# 한글 폰트 설정
plt.rcParams['font.family'] = 'Malgun Gothic'
# plt.rcParams['font.family'] = 'DejaVu Sans'
plt.rcParams['axes.unicode_minus'] = False
plt.rcParams['figure.facecolor'] = 'white'


def load_data(fut_path, idx_path):
    """데이터 로드"""
    
    # 선물 데이터
    df_fut = pd.read_excel(fut_path)
    df_fut['Datetime'] = pd.to_datetime(df_fut['Datetime'])
    df_fut['Date'] = df_fut['Datetime'].dt.date
    df_fut['Time'] = df_fut['Datetime'].dt.time
    
    # 지수 데이터 (Bloomberg 형식: 4행 skip)
    df_idx = pd.read_excel(idx_path, skiprows=4, header=None)
    df_idx.columns = ['Datetime', 'Idx_Close']
    df_idx['Datetime'] = pd.to_datetime(df_idx['Datetime'])
    df_idx['Date'] = df_idx['Datetime'].dt.date
    df_idx['Time'] = df_idx['Datetime'].dt.time
    
    return df_fut, df_idx


def get_prev_day_close(df_idx, current_date, all_dates):
    """
    전일 종가 가져오기
    - 전일의 마지막 분봉 종가를 반환
    """
    # 현재 날짜의 인덱스 찾기
    try:
        current_idx = all_dates.index(current_date)
    except ValueError:
        return None
    
    # 전일이 없으면 None
    if current_idx == 0:
        return None
    
    prev_date = all_dates[current_idx - 1]
    prev_day_data = df_idx[df_idx['Date'] == prev_date].sort_values('Time')
    
    if len(prev_day_data) == 0:
        return None
    
    # 전일의 마지막 분봉 종가
    return prev_day_data.iloc[-1]['Idx_Close']


def classify_regime(ret_pct):
    """
    수익률 기준 국면 분류 (전일 종가 대비)
    - 강세장: >= +1.5%
    - 약상승장: 0% ~ +1.5%
    - 약하락장: -1.5% ~ 0%
    - 강하락장: <= -1.5%
    """
    if pd.isna(ret_pct):
        return None
    if ret_pct >= 1.5:
        return '강세장'
    elif ret_pct >= 0:
        return '약상승장'
    elif ret_pct >= -1.5:
        return '약하락장'
    else:
        return '강하락장'


def get_analysis_times():
    """
    분석 대상 시간 리스트 생성
    - 15:00 ~ 15:34 (35개) + 15:44 (1개) = 총 36개
    """
    times = [datetime.time(15, m) for m in range(0, 35)]  # 15:00 ~ 15:34
    times.append(datetime.time(15, 44))  # 15:44 추가
    return times


def analyze_rolling_regime(df_fut, df_idx):
    """
    롤링 방식 국면별 분석
    - t 시점 선물 수익률 분석 시, t-1 시점까지의 지수 수익률(전일 종가 대비)로 국면 판단
    - ★ 15:44분 예외: 
      - 국면 판단: 15:30분 코스피200 지수 (전일 종가 대비)
      - 선물 수익률: 15:30분 선물 대비 15:44분 선물 수익률
    """
    
    # 15:00~15:34 + 15:44 (총 36개)
    times_analysis = get_analysis_times()
    
    # 15:44분 특별 처리용 시간
    t_1530 = datetime.time(15, 30)
    t_1544 = datetime.time(15, 44)
    
    results = []
    
    # 공통 날짜 및 정렬된 날짜 리스트
    common_dates = sorted(set(df_fut['Date'].unique()) & set(df_idx['Date'].unique()))
    all_idx_dates = sorted(df_idx['Date'].unique())
    
    # ============================================================
    # 데이터 기간 확인 (디버깅용)
    # ============================================================
    print(f"\n   [데이터 기간 확인]")
    print(f"   선물 데이터 기간: {min(df_fut['Date'])} ~ {max(df_fut['Date'])} ({df_fut['Date'].nunique()}일)")
    print(f"   지수 데이터 기간: {min(df_idx['Date'])} ~ {max(df_idx['Date'])} ({df_idx['Date'].nunique()}일)")
    print(f"   공통 날짜 수: {len(common_dates)}일")
    
    # 전일 종가 있는 날짜 수 확인
    dates_with_prev_close = 0
    for date in common_dates:
        prev_close = get_prev_day_close(df_idx, date, all_idx_dates)
        if prev_close is not None:
            dates_with_prev_close += 1
    print(f"   전일 종가 데이터 있는 날짜: {dates_with_prev_close}일")
    print(f"   분석 대상 시간: {len(times_analysis)}개 (15:00~15:34 + 15:44)")
    print(f"   ★ 국면 판단 기준: 전일 종가 대비 수익률")
    print(f"   ★ 15:44분: 국면=15:30 지수 기준, 수익률=15:30 선물 대비")
    
    for date in common_dates:
        fut_day = df_fut[df_fut['Date'] == date].sort_values('Time')
        idx_day = df_idx[df_idx['Date'] == date].sort_values('Time')
        
        # ============================================================
        # ★ 전일 종가 가져오기
        # ============================================================
        prev_close = get_prev_day_close(df_idx, date, all_idx_dates)
        if prev_close is None:
            continue  # 전일 종가 없으면 해당 날짜 스킵
        
        for t in times_analysis:
            # 선물 데이터 (현재 시점 t)
            fut_row = fut_day[fut_day['Time'] == t]
            if len(fut_row) == 0:
                continue
            
            fut_close = fut_row.iloc[0]['Close']
            fut_volume = fut_row.iloc[0]['Volume']
            
            # ============================================================
            # ★ 15:44분 특별 처리
            # ============================================================
            if t == t_1544:
                # ★ 15:44분 선물 수익률: 15:30분 선물 대비
                fut_1530_row = fut_day[fut_day['Time'] == t_1530]
                if len(fut_1530_row) == 0:
                    fut_ret = np.nan  # 15:30 선물 데이터 없으면 NaN
                else:
                    fut_1530_close = fut_1530_row.iloc[0]['Close']
                    fut_ret = (fut_close - fut_1530_close) / fut_1530_close * 10000  # bp
                
                # ★ 15:44분 국면 판단: 15:30분 코스피200 지수
                idx_ref_row = idx_day[idx_day['Time'] == t_1530]
                if len(idx_ref_row) == 0:
                    # 15:30 데이터 없으면 그 이전 마지막 데이터 사용
                    idx_ref_row = idx_day[idx_day['Time'] <= t_1530]
                    if len(idx_ref_row) == 0:
                        idx_ret_pct = np.nan
                    else:
                        idx_ref_close = idx_ref_row.iloc[-1]['Idx_Close']
                        idx_ret_pct = (idx_ref_close - prev_close) / prev_close * 100
                else:
                    idx_ref_close = idx_ref_row.iloc[0]['Idx_Close']
                    idx_ret_pct = (idx_ref_close - prev_close) / prev_close * 100
            
            else:
                # ============================================================
                # 일반적인 롤링 방식 (15:00 ~ 15:34)
                # ============================================================
                # 선물 수익률: 직전 분봉 대비
                t_prev_dt = datetime.datetime.combine(datetime.date.today(), t) - datetime.timedelta(minutes=1)
                t_prev = t_prev_dt.time()
                
                fut_prev_row = fut_day[fut_day['Time'] == t_prev]
                
                if len(fut_prev_row) == 0:
                    fut_ret = np.nan
                else:
                    fut_prev_close = fut_prev_row.iloc[0]['Close']
                    fut_ret = (fut_close - fut_prev_close) / fut_prev_close * 10000  # bp
                
                # 국면 판단: t-1 시점 지수 사용
                idx_prev_row = idx_day[idx_day['Time'] == t_prev]
                if len(idx_prev_row) == 0:
                    # 15:20 이후에는 지수 데이터가 없을 수 있음 → 마지막 가용 데이터 사용
                    idx_prev_row = idx_day[idx_day['Time'] <= t_prev]
                    if len(idx_prev_row) == 0:
                        idx_ret_pct = np.nan
                    else:
                        idx_prev_close = idx_prev_row.iloc[-1]['Idx_Close']
                        idx_ret_pct = (idx_prev_close - prev_close) / prev_close * 100
                else:
                    idx_prev_close = idx_prev_row.iloc[0]['Idx_Close']
                    idx_ret_pct = (idx_prev_close - prev_close) / prev_close * 100
            
            # 국면 분류
            regime = classify_regime(idx_ret_pct)
            
            results.append({
                'Date': date,
                'Time': t,
                'Prev_Close': prev_close,
                'Idx_Ret_Pct': idx_ret_pct,
                'Regime': regime,
                'Fut_Ret_bp': fut_ret,
                'Fut_Volume': fut_volume,
            })
    
    return pd.DataFrame(results)


def print_analysis(df_results):
    """분석 결과 출력"""
    
    regime_order = ['강세장', '약상승장', '약하락장', '강하락장']
    
    # 15:00~15:34 + 15:44 시간 인덱스
    all_times = get_analysis_times()
    
    print("\n" + "="*80)
    print("국면별 전체 통계 (전일 종가 대비 국면 분류)")
    print("="*80)
    print(f"\n{'국면':<10} {'N':>6} {'평균수익률':>12} {'표준편차':>10} {'평균거래량':>12}")
    print("-"*60)
    
    for regime in regime_order:
        subset = df_results[df_results['Regime'] == regime]
        n = len(subset)
        mean_ret = subset['Fut_Ret_bp'].mean()
        std_ret = subset['Fut_Ret_bp'].std()
        mean_vol = subset['Fut_Volume'].mean()
        print(f"{regime:<10} {n:>6} {mean_ret:>+11.2f}bp {std_ret:>9.2f} {mean_vol:>12,.0f}")
    
    # 시간대별 국면별 평균 수익률
    print("\n" + "="*80)
    print("시간대별 국면별 평균 선물 수익률 (bp)")
    print("="*80)
    
    pivot_ret = df_results.pivot_table(
        index='Time', 
        columns='Regime', 
        values='Fut_Ret_bp', 
        aggfunc='mean'
    )
    pivot_ret = pivot_ret.reindex(all_times)[regime_order].round(2)
    print(pivot_ret)
    
    # 시간대별 국면별 평균 거래량
    print("\n" + "="*80)
    print("시간대별 국면별 평균 거래량")
    print("="*80)
    
    pivot_vol = df_results.pivot_table(
        index='Time', 
        columns='Regime', 
        values='Fut_Volume', 
        aggfunc='mean'
    )
    pivot_vol = pivot_vol.reindex(all_times)[regime_order].round(0)
    print(pivot_vol)
    
    # 시간대별 국면별 샘플 수
    print("\n" + "="*80)
    print("시간대별 국면별 샘플 수")
    print("="*80)
    
    pivot_count = df_results.pivot_table(
        index='Time', 
        columns='Regime', 
        values='Fut_Ret_bp', 
        aggfunc='count'
    )
    pivot_count = pivot_count.reindex(all_times)[regime_order]
    print(pivot_count)
    
    # ★ 15:44분 국면별 통계 별도 출력
    t_1544 = datetime.time(15, 44)
    df_1544 = df_results[df_results['Time'] == t_1544]
    print("\n" + "="*80)
    print("★ 15:44분 국면별 통계 (15:30 기준)")
    print("="*80)
    print(f"\n{'국면':<10} {'N':>6} {'평균수익률':>12} {'평균거래량':>12}")
    print("-"*50)
    for regime in regime_order:
        subset = df_1544[df_1544['Regime'] == regime]
        n = len(subset)
        mean_ret = subset['Fut_Ret_bp'].mean()
        mean_vol = subset['Fut_Volume'].mean()
        if n > 0:
            print(f"{regime:<10} {n:>6} {mean_ret:>+11.2f}bp {mean_vol:>12,.0f}")
        else:
            print(f"{regime:<10} {n:>6} {'N/A':>12} {'N/A':>12}")
    
    return pivot_ret, pivot_vol, pivot_count


def plot_analysis(df_results, pivot_ret, pivot_vol):
    """
    시각화: 국면별 개별 그래프 (수익률 + 거래량 동시 표시)
    - 2x2 subplot, 각 국면별 하나의 그래프
    - X축: 00~34 + 44 (분만 표시, 총 36개)
    - 왼쪽 Y축: 평균 수익률 (bp) - Bar chart
    - 오른쪽 Y축: 평균 거래량 - Line chart
    - ★ 15:44분도 국면별로 수익률/거래량 표시
    """
    
    regime_order = ['강세장', '약상승장', '약하락장', '강하락장']
    regime_colors = {'강세장': '#e74c3c', '약상승장': '#f39c12', '약하락장': '#3498db', '강하락장': '#2c3e50'}
    regime_names = {'강세장': '강세장 (>=1.5%)', '약상승장': '약상승장 (0~1.5%)', 
                    '약하락장': '약하락장 (-1.5~0%)', '강하락장': '강하락장 (<=-1.5%)'}
    
    # 15:00~15:34 + 15:44 시간 인덱스
    all_times = get_analysis_times()
    
    # Pivot table for count
    pivot_count = df_results.pivot_table(index='Time', columns='Regime', values='Fut_Ret_bp', aggfunc='count')
    pivot_count = pivot_count.reindex(all_times)[regime_order]
    
    # X축 라벨: 00~34 + 44 (총 36개)
    time_labels = [f'{m:02d}' for m in range(0, 35)] + ['44']
    x = np.arange(len(time_labels))
    
    # 2x2 subplot
    fig, axes = plt.subplots(2, 2, figsize=(20, 12))
    axes = axes.flatten()
    
    for i, regime in enumerate(regime_order):
        ax1 = axes[i]
        color = regime_colors[regime]
        
        # ★ 수익률/거래량 데이터 (15:44분도 국면별로 표시, NaN만 0으로)
        ret_data = pivot_ret[regime].fillna(0).values
        vol_data = pivot_vol[regime].fillna(0).values
        
        # 수익률 (왼쪽 Y축) - Bar chart
        bars = ax1.bar(x, ret_data, color=color, alpha=0.7, label='수익률 (bp)')
        ax1.axhline(0, color='gray', linestyle='--', alpha=0.5)
        ax1.set_ylabel('평균 수익률 (bp)', color=color, fontsize=11)
        ax1.tick_params(axis='y', labelcolor=color)
        
        # 15:20 수직선 (인덱스 20)
        ax1.axvline(20, color='red', linestyle='--', alpha=0.7, linewidth=1.5)
        
        # 거래량 (오른쪽 Y축) - Line chart
        ax2 = ax1.twinx()
        ax2.plot(x, vol_data, color='black', linewidth=2, marker='o', markersize=3, label='거래량')
        ax2.set_ylabel('평균 거래량', color='black', fontsize=11)
        ax2.tick_params(axis='y', labelcolor='black')
        
        # 제목
        avg_ret = pivot_ret[regime].mean()
        avg_vol = pivot_vol[regime].mean()
        ax1.set_title(f'{regime_names[regime]}\n(평균수익률: {avg_ret:+.2f}bp, 평균거래량: {avg_vol:.0f})', 
                      fontsize=12, fontweight='bold', color=color)
        
        # X축 설정 - 전체 분 표시 (00~34 + 44)
        ax1.set_xlabel('분 (15시 기준)', fontsize=11)
        ax1.set_xticks(x)
        ax1.set_xticklabels(time_labels, rotation=90, fontsize=8)
        
        # 범례
        lines1, labels1 = ax1.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper right', fontsize=9)
        
        # 그리드
        ax1.grid(True, alpha=0.3, axis='y')
    
    # 전체 제목
    fig.suptitle('국면별 선물 수익률 및 거래량 (15:00~15:34 + 15:44)\n국면 기준: 전일 종가 대비 | 빨간선: 20분 (동시호가 시작) | 15:44: 15:30 기준 국면/수익률', 
                 fontsize=14, fontweight='bold', y=1.02)
    
    plt.tight_layout()
    plt.savefig('regime_analysis.png', dpi=150, bbox_inches='tight')
    plt.close()
    print("Saved: regime_analysis.png")


def main():
    # ============================================================
    # 파일 경로 설정
    # ============================================================
    fut_path = r'C:\Users\intern9\truston_quant_dev\K2_K2F\K2_선물_분봉_정규장2.xlsx'
    idx_path = r'C:\Users\intern9\truston_quant_dev\K2_K2F\KOSPI_분봉.xlsx'
    
    # 1. 데이터 로드
    print("="*80)
    print("KOSPI200 선물 장마감 시간대 국면별 분석 (롤링 방식)")
    print("="*80)
    print("\n1. 데이터 로드")
    df_fut, df_idx = load_data(fut_path, idx_path)
    print(f"   선물: {len(df_fut):,}건, {df_fut['Date'].nunique()}일")
    print(f"   지수: {len(df_idx):,}건, {df_idx['Date'].nunique()}일")
    
    # 2. 롤링 국면별 분석
    print("\n2. 롤링 국면별 분석")
    print("   - 국면 분류: 강세장(>=1.5%), 약상승장(0~1.5%), 약하락장(-1.5~0%), 강하락장(<=-1.5%)")
    print("   - ★ 국면 기준: 전일 종가 대비 수익률")
    print("   - 롤링 방식: t 시점 분석 시, t-1 시점까지의 지수 수익률로 국면 판단")
    print("   - ★ 15:44분: 국면=15:30 지수 기준, 수익률=15:30 선물 대비")
    df_results = analyze_rolling_regime(df_fut, df_idx)
    print(f"   분석 결과: {len(df_results):,}건")
    
    # 3. 결과 출력
    print("\n3. 결과 출력")
    pivot_ret, pivot_vol, pivot_count = print_analysis(df_results)
    
    # 4. 시각화
    print("\n4. 시각화")
    plot_analysis(df_results, pivot_ret, pivot_vol)
    
    # 5. 데이터 저장
    df_results.to_csv('regime_analysis_data.csv', index=False, encoding='utf-8-sig')
    pivot_ret.to_csv('regime_return_by_time.csv', encoding='utf-8-sig')
    pivot_vol.to_csv('regime_volume_by_time.csv', encoding='utf-8-sig')
    print(f"\n데이터 저장 완료:")
    print(f"  - regime_analysis_data.csv")
    print(f"  - regime_return_by_time.csv")
    print(f"  - regime_volume_by_time.csv")
    
    return df_results, pivot_ret, pivot_vol


if __name__ == "__main__":
    df_results, pivot_ret, pivot_vol = main()

# python K2_K2F/ETF.py