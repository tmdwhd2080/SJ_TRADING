"""
KOSPI200 선물 장마감 시간대 국면별 분석 (10초 데이터, 롤링 방식)

국면 분류 (전일 종가 대비 수익률 기준):
  - 강세장: >= +1.5%
  - 약상승장: 0% ~ +1.5%
  - 약하락장: -1.5% ~ 0%
  - 강하락장: <= -1.5%

롤링 방식:
  - t 시점의 선물 수익률 분석 시, t-10초 시점까지의 지수 수익률로 국면 판단
  - 지수 데이터는 분봉이므로, 해당 10초가 속한 분의 지수 데이터 사용

분석 대상:
  - 15:26:00 ~ 15:34:50 (10초 단위, 총 54개 시점)

수익률 계산:
  - 국면 판단용: (해당 분 지수 - 전일 종가) / 전일 종가 * 100 (%)
  - 선물 수익률: (현재 종가 - 10초전 종가) / 10초전 종가 * 10000 (bp)
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


def load_data(fut_10s_path, idx_path):
    """데이터 로드"""
    
    # 선물 10초 데이터 (Bloomberg 형식)
    df_fut = pd.read_excel(fut_10s_path, skiprows=11, header=None)
    df_fut.columns = ['Datetime', 'Close', 'Volume']
    
    # Volume 컬럼 처리 (엑셀 날짜 형식 변환)
    def convert_volume(v):
        if pd.isna(v):
            return 0
        if isinstance(v, (int, float)):
            return v
        if isinstance(v, str):
            try:
                return int(v)
            except:
                return 0
        if hasattr(v, 'toordinal'):
            return (v - datetime.datetime(1899, 12, 30)).days
        return 0
    
    df_fut['Volume'] = df_fut['Volume'].apply(convert_volume)
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


def filter_time_range(df_fut, start_time, end_time):
    """
    시간 범위로 데이터 필터링
    - start_time: 시작 시간 (datetime.time)
    - end_time: 종료 시간 (datetime.time)
    """
    return df_fut[(df_fut['Time'] >= start_time) & (df_fut['Time'] <= end_time)].copy()


def get_prev_day_close(df_idx, current_date, all_dates):
    """
    전일 종가 가져오기
    - 전일의 마지막 분봉 종가를 반환
    """
    try:
        current_idx = all_dates.index(current_date)
    except ValueError:
        return None
    
    if current_idx == 0:
        return None
    
    prev_date = all_dates[current_idx - 1]
    prev_day_data = df_idx[df_idx['Date'] == prev_date].sort_values('Time')
    
    if len(prev_day_data) == 0:
        return None
    
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


def get_analysis_times_10s():
    """
    분석 대상 시간 리스트 생성 (10초 단위)
    - 15:26:00 ~ 15:34:50 (54개)
    """
    times = []
    for minute in range(26, 35):  # 15:26 ~ 15:34
        for second in range(0, 60, 10):  # 00, 10, 20, 30, 40, 50
            times.append(datetime.time(15, minute, second))
    return times


def get_minute_time(t):
    """
    10초 시간을 분 단위로 변환 (지수 데이터 매칭용)
    예: 15:26:30 → 15:26:00
    """
    return datetime.time(t.hour, t.minute, 0)


def analyze_rolling_regime_10s(df_fut, df_idx):
    """
    롤링 방식 국면별 분석 (10초 데이터)
    - t 시점 선물 수익률 분석 시, 해당 분의 지수 수익률(전일 종가 대비)로 국면 판단
    - 선물 수익률: 10초 전 대비 수익률
    """
    
    times_analysis = get_analysis_times_10s()
    
    results = []
    
    # 공통 날짜 및 정렬된 날짜 리스트
    common_dates = sorted(set(df_fut['Date'].unique()) & set(df_idx['Date'].unique()))
    all_idx_dates = sorted(df_idx['Date'].unique())
    
    # ============================================================
    # 데이터 기간 확인
    # ============================================================
    print(f"\n   [데이터 기간 확인]")
    print(f"   선물 10초 데이터 기간: {min(df_fut['Date'])} ~ {max(df_fut['Date'])} ({df_fut['Date'].nunique()}일)")
    print(f"   지수 분봉 데이터 기간: {min(df_idx['Date'])} ~ {max(df_idx['Date'])} ({df_idx['Date'].nunique()}일)")
    print(f"   공통 날짜 수: {len(common_dates)}일")
    
    # 전일 종가 있는 날짜 수 확인
    dates_with_prev_close = 0
    for date in common_dates:
        prev_close = get_prev_day_close(df_idx, date, all_idx_dates)
        if prev_close is not None:
            dates_with_prev_close += 1
    print(f"   전일 종가 데이터 있는 날짜: {dates_with_prev_close}일")
    print(f"   분석 대상 시간: {len(times_analysis)}개 (15:26:00~15:34:50, 10초 단위)")
    print(f"   ★ 국면 판단 기준: 전일 종가 대비 수익률")
    
    for date in common_dates:
        fut_day = df_fut[df_fut['Date'] == date].sort_values('Time')
        idx_day = df_idx[df_idx['Date'] == date].sort_values('Time')
        
        # 전일 종가 가져오기
        prev_close = get_prev_day_close(df_idx, date, all_idx_dates)
        if prev_close is None:
            continue
        
        for t in times_analysis:
            # 선물 데이터 (현재 시점 t)
            fut_row = fut_day[fut_day['Time'] == t]
            if len(fut_row) == 0:
                continue
            
            fut_close = fut_row.iloc[0]['Close']
            fut_volume = fut_row.iloc[0]['Volume']
            
            # 선물 수익률: 10초 전 대비
            t_prev_dt = datetime.datetime.combine(datetime.date.today(), t) - datetime.timedelta(seconds=10)
            t_prev = t_prev_dt.time()
            
            fut_prev_row = fut_day[fut_day['Time'] == t_prev]
            
            if len(fut_prev_row) == 0:
                fut_ret = np.nan
            else:
                fut_prev_close = fut_prev_row.iloc[0]['Close']
                fut_ret = (fut_close - fut_prev_close) / fut_prev_close * 10000  # bp
            
            # ============================================================
            # 국면 판단: 해당 분의 지수 데이터 사용 (전일 종가 대비)
            # 10초 데이터의 경우, t-10초가 속한 분의 지수 사용
            # ============================================================
            t_prev_minute = get_minute_time(t_prev)
            
            idx_row = idx_day[idx_day['Time'] == t_prev_minute]
            if len(idx_row) == 0:
                # 해당 분 데이터 없으면 이전 마지막 데이터 사용
                idx_row = idx_day[idx_day['Time'] <= t_prev_minute]
                if len(idx_row) == 0:
                    idx_ret_pct = np.nan
                else:
                    idx_close = idx_row.iloc[-1]['Idx_Close']
                    idx_ret_pct = (idx_close - prev_close) / prev_close * 100
            else:
                idx_close = idx_row.iloc[0]['Idx_Close']
                idx_ret_pct = (idx_close - prev_close) / prev_close * 100
            
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
    all_times = get_analysis_times_10s()
    
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
    
    return pivot_ret, pivot_vol, pivot_count


def plot_analysis(df_results, pivot_ret, pivot_vol):
    """
    시각화: 국면별 개별 그래프 (수익률 + 거래량 동시 표시)
    - 2x2 subplot, 각 국면별 하나의 그래프
    - X축: 초만 표시 (00, 10, 20, 30, 40, 50 반복), 전체 54개
    - 왼쪽 Y축: 평균 수익률 (bp) - Bar chart
    - 오른쪽 Y축: 평균 거래량 - Line chart
    """
    
    regime_order = ['강세장', '약상승장', '약하락장', '강하락장']
    regime_colors = {'강세장': '#e74c3c', '약상승장': '#f39c12', '약하락장': '#3498db', '강하락장': '#2c3e50'}
    regime_names = {'강세장': '강세장 (>=1.5%)', '약상승장': '약상승장 (0~1.5%)', 
                    '약하락장': '약하락장 (-1.5~0%)', '강하락장': '강하락장 (<=-1.5%)'}
    
    all_times = get_analysis_times_10s()
    
    # Pivot table for count
    pivot_count = df_results.pivot_table(index='Time', columns='Regime', values='Fut_Ret_bp', aggfunc='count')
    pivot_count = pivot_count.reindex(all_times)[regime_order]
    
    # ★ X축 라벨: 초만 표시 (00, 10, 20, 30, 40, 50 반복)
    time_labels = [f'{t.second:02d}' for t in all_times]
    x = np.arange(len(time_labels))
    
    # 분이 바뀌는 위치 (00초 위치) - 수직선용
    minute_change_positions = [i for i, t in enumerate(all_times) if t.second == 0]
    
    # 2x2 subplot
    fig, axes = plt.subplots(2, 2, figsize=(24, 12))
    axes = axes.flatten()
    
    for i, regime in enumerate(regime_order):
        ax1 = axes[i]
        color = regime_colors[regime]
        
        # 수익률/거래량 데이터
        ret_data = pivot_ret[regime].fillna(0).values
        vol_data = pivot_vol[regime].fillna(0).values
        
        # 수익률 (왼쪽 Y축) - Bar chart
        bars = ax1.bar(x, ret_data, color=color, alpha=0.7, label='수익률 (bp)')
        ax1.axhline(0, color='gray', linestyle='--', alpha=0.5)
        ax1.set_ylabel('평균 수익률 (bp)', color=color, fontsize=11)
        ax1.tick_params(axis='y', labelcolor=color)
        
        # 분 구분 수직선 (각 분의 시작 위치)
        for pos in minute_change_positions:
            ax1.axvline(pos, color='gray', linestyle='-', alpha=0.3, linewidth=0.5)
        
        # 15:30 수직선 (인덱스 24: 15:30:00) - 빨간색 굵게
        ax1.axvline(24, color='red', linestyle='--', alpha=0.7, linewidth=1.5)
        
        # 거래량 (오른쪽 Y축) - Line chart
        ax2 = ax1.twinx()
        ax2.plot(x, vol_data, color='black', linewidth=2, marker='o', markersize=2, label='거래량')
        ax2.set_ylabel('평균 거래량', color='black', fontsize=11)
        ax2.tick_params(axis='y', labelcolor='black')
        
        # 제목
        avg_ret = pivot_ret[regime].mean()
        avg_vol = pivot_vol[regime].mean()
        ax1.set_title(f'{regime_names[regime]}\n(평균수익률: {avg_ret:+.2f}bp, 평균거래량: {avg_vol:.0f})', 
                      fontsize=12, fontweight='bold', color=color)
        
        # ★ X축 설정 - 모든 10초 간격 표시 (초만)
        ax1.set_xlabel('초 (15:26~15:34)', fontsize=11)
        ax1.set_xticks(x)
        ax1.set_xticklabels(time_labels, rotation=90, fontsize=7)
        
        # 범례
        lines1, labels1 = ax1.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper right', fontsize=9)
        
        # 그리드
        ax1.grid(True, alpha=0.3, axis='y')
    
    # 전체 제목
    fig.suptitle('국면별 선물 수익률 및 거래량 (15:26~15:34, 10초 단위)\n국면 기준: 전일 종가 대비 | 빨간선: 15:30 (동시호가 시작) | 회색선: 분 구분', 
                 fontsize=14, fontweight='bold', y=1.02)
    
    plt.tight_layout()
    plt.savefig('regime_analysis_10s.png', dpi=150, bbox_inches='tight')
    plt.close()
    print("Saved: regime_analysis_10s.png")


def main():
    # ============================================================
    # 파일 경로 설정
    # ============================================================
    fut_10s_path = r'C:\Users\intern9\truston_quant_dev\K2_K2F\10초 데이터.xlsx'
    idx_path = r'C:\Users\intern9\truston_quant_dev\K2_K2F\KOSPI_분봉.xlsx'
    
    # 1. 데이터 로드
    print("="*80)
    print("KOSPI200 선물 장마감 시간대 국면별 분석 (10초 데이터, 롤링 방식)")
    print("="*80)
    print("\n1. 데이터 로드")
    df_fut, df_idx = load_data(fut_10s_path, idx_path)
    print(f"   선물 10초: {len(df_fut):,}건, {df_fut['Date'].nunique()}일")
    print(f"   지수 분봉: {len(df_idx):,}건, {df_idx['Date'].nunique()}일")
    
    # 2. 15:26 ~ 15:34:50 시간 필터링
    print("\n2. 시간 필터링")
    t_start = datetime.time(15, 26, 0)
    t_end = datetime.time(15, 34, 50)
    df_fut_filtered = filter_time_range(df_fut, t_start, t_end)
    print(f"   필터링 범위: {t_start} ~ {t_end}")
    print(f"   필터링 후: {len(df_fut_filtered):,}건, {df_fut_filtered['Date'].nunique()}일")
    
    # 3. 롤링 국면별 분석
    print("\n3. 롤링 국면별 분석")
    print("   - 국면 분류: 강세장(>=1.5%), 약상승장(0~1.5%), 약하락장(-1.5~0%), 강하락장(<=-1.5%)")
    print("   - ★ 국면 기준: 전일 종가 대비 수익률")
    print("   - 롤링 방식: t 시점 분석 시, t-10초가 속한 분의 지수 수익률로 국면 판단")
    df_results = analyze_rolling_regime_10s(df_fut_filtered, df_idx)
    print(f"   분석 결과: {len(df_results):,}건")
    
    # 4. 결과 출력
    print("\n4. 결과 출력")
    pivot_ret, pivot_vol, pivot_count = print_analysis(df_results)
    
    # 5. 시각화
    print("\n5. 시각화")
    plot_analysis(df_results, pivot_ret, pivot_vol)
    
    # 6. 데이터 저장
    df_results.to_csv('regime_analysis_10s_data.csv', index=False, encoding='utf-8-sig')
    pivot_ret.to_csv('regime_return_10s_by_time.csv', encoding='utf-8-sig')
    pivot_vol.to_csv('regime_volume_10s_by_time.csv', encoding='utf-8-sig')
    print(f"\n데이터 저장 완료:")
    print(f"  - regime_analysis_10s_data.csv")
    print(f"  - regime_return_10s_by_time.csv")
    print(f"  - regime_volume_10s_by_time.csv")
    
    return df_results, pivot_ret, pivot_vol


if __name__ == "__main__":
    df_results, pivot_ret, pivot_vol = main()

# python K2_K2F/ETF_sec.py