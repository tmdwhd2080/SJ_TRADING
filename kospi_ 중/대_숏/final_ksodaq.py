import pandas as pd
import numpy as np
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from flow_kosdaq_calculate import (          # ★ 코스닥 모듈 import
    load_data, run_regression,
    REBAL_DATES, SECTORS, REMOVE_OUTLIERS,
)

# ══════════════════════════════════════════════════════════════
# ★ SETTING
# ══════════════════════════════════════════════════════════════
DATA_PATH      = r'C:\Users\intern9\truston_quant_dev\util\코스닥_최종.xlsx'   # ★ 코스닥 데이터
OUTPUT_DIR     = r'C:\Users\intern9\truston_quant_dev\util\output'
BENCHMARK_PATH = r'C:\Users\intern9\truston_quant_dev\util\코스피_코스닥_종가.xlsx'
# BENCHMARK_PATH : 코스피·코스닥 지수 종가 파일
#   col 1 = 코스닥(IKQ001)  ← 코스닥 분석 벤치마크
#   col 2 = 코스피(IKS900)
# ══════════════════════════════════════════════════════════════

CASES = [
    ('대형주', '중형주'),
    ('중형주', '대형주'),
    ('중형주', '소형주'),
    ('소형주', '중형주'),
    ('대형주', '소형주'),
    ('소형주', '대형주'),
]
CASE_LABELS = {c: f"{c[0]}→{c[1]}" for c in CASES}

SEP  = "═" * 80
SEP2 = "─" * 80


# ════════════════════════════════════════════════════════════
# 벤치마크(코스닥 지수) 로딩
# ════════════════════════════════════════════════════════════
def load_benchmark(filepath: str) -> pd.Series:
    """
    코스피_코스닥_종가.xlsx 에서 코스닥 지수 종가를 로딩.
        col 1 (IKQ001) = 코스닥 종가지수  ← 코스닥 분석 벤치마크
        col 2 (IKS900) = 코스피 종가지수
        데이터 시작 14행

    Returns
    -------
    pd.Series  index=날짜(Timestamp), values=코스닥 종가지수
    """
    df        = pd.read_excel(filepath, header=None)
    raw_dates = df.iloc[14:, 0].reset_index(drop=True)
    dates_idx = pd.to_datetime(raw_dates.astype(str).str[:10], errors='coerce')
    # ★ col 1 = 코스닥 (코스피는 col 2)
    kosdaq_vals = df.iloc[14:, 1].values.astype(float)
    return pd.Series(kosdaq_vals, index=dates_idx, name='코스닥')


# ════════════════════════════════════════════════════════════
# 섹터 이동 종목 탐색 + gain + 초과 주가 수익률
# ════════════════════════════════════════════════════════════
def build_switch_table(sector_info: dict,
                       aum_dict: dict,
                       item_dfs: dict,
                       code_to_name: dict,
                       kosdaq_index: pd.Series):
    """
    섹터 이동 종목별 gain 및 코스닥 벤치마크 대비 초과 주가 수익률 계산.

    gain 계산 기준
    ──────────────
        val_old = AUM(현 정기변경일, s_old) × w_old_rebal
        val_new = AUM(현 정기변경일, s_new) × w_new
        gain    = val_new - val_old

    주가 수익률 (벤치마크 초과)
    ────────────────────────
        종목 수익률     = (price_T - price_T1) / price_T1
        벤치마크 수익률  = (kosdaq_T - kosdaq_T1) / kosdaq_T1  ← 코스닥 지수
        초과 수익률     = 종목 수익률 - 벤치마크 수익률
        초과 승률       = 초과 수익률 > 0 인 종목 수 / 전체 종목 수
    """
    records = []

    for date_str, info in sector_info.items():
        sector_new          = info['sector_new']
        sector_old          = info['sector_old']
        weights_new         = info['weights_new']
        weights_old         = info['weights_old']
        weights_old_rebal   = info['weights_old_rebal']
        prev_rebal_date_str = info['prev_rebal_date_str']
        prev_biz_day_str    = info['prev_biz_day_str']

        cur_date     = pd.Timestamp(date_str)
        prev_biz_day = pd.Timestamp(prev_biz_day_str)

        price_T  = item_dfs['종가'].loc[cur_date]
        price_T1 = item_dfs['종가'].loc[prev_biz_day]

        # ★ 벤치마크: 코스닥 지수
        bm_T  = float(kosdaq_index.get(cur_date,     np.nan))
        bm_T1 = float(kosdaq_index.get(prev_biz_day, np.nan))
        if not np.isnan(bm_T1) and bm_T1 > 0 and not np.isnan(bm_T):
            bm_ret = (bm_T - bm_T1) / bm_T1
        else:
            bm_ret = np.nan

        codes_new = set(sector_new.index)
        codes_old = set(sector_old.index)
        common    = codes_new & codes_old

        for code in common:
            s_new = sector_new.loc[code]
            s_old = sector_old.loc[code]

            if s_new == s_old:
                continue

            case = (s_old, s_new)
            if case not in CASES:
                continue

            w_old_t1 = weights_old.get(code, {}).get('weight', np.nan)
            w_new_t  = weights_new.get(code, {}).get('weight', np.nan)
            delta_w  = (w_new_t - w_old_t1
                        if not (np.isnan(w_new_t) or np.isnan(w_old_t1))
                        else np.nan)
            w_old_pr = weights_old_rebal.get(code, {}).get('weight', np.nan)

            aum_cur_old = aum_dict.get((date_str, s_old), np.nan)
            val_old = (aum_cur_old * w_old_pr
                       if not (np.isnan(aum_cur_old) or np.isnan(w_old_pr))
                       else np.nan)

            aum_cur_new = aum_dict.get((date_str, s_new), np.nan)
            val_new = (aum_cur_new * w_new_t
                       if not (np.isnan(aum_cur_new) or np.isnan(w_new_t))
                       else np.nan)

            if not (np.isnan(val_new) or np.isnan(val_old)):
                gain    = val_new - val_old
                is_gain = int(gain > 0)
            else:
                gain    = np.nan
                is_gain = np.nan

            p_t1 = float(price_T1.get(code, np.nan))
            p_t  = float(price_T.get(code, np.nan))

            if not np.isnan(p_t1) and p_t1 > 0 and not np.isnan(p_t):
                stock_ret = (p_t - p_t1) / p_t1
            else:
                stock_ret = np.nan

            if not np.isnan(stock_ret) and not np.isnan(bm_ret):
                excess_ret = stock_ret - bm_ret
                excess_win = int(excess_ret > 0)
            else:
                excess_ret = np.nan
                excess_win = np.nan

            records.append({
                '정기변경일':              date_str,
                '직전정기변경일':           prev_rebal_date_str,
                '종목코드':               code,
                '종목명':                 code_to_name.get(code, code),
                '케이스':                 CASE_LABELS[case],
                '이전섹터':               s_old,
                '신규섹터':               s_new,
                '이전비중_T1':            round(w_old_t1, 8) if not np.isnan(w_old_t1) else np.nan,
                '신규비중_T':             round(w_new_t,  8) if not np.isnan(w_new_t)  else np.nan,
                '비중변화량(Δw)_회귀기준': round(delta_w,  8) if not np.isnan(delta_w)  else np.nan,
                '이전비중_prevRebal':     round(w_old_pr, 8) if not np.isnan(w_old_pr) else np.nan,
                '이전AUM_cur(백만원)':    round(aum_cur_old) if not np.isnan(aum_cur_old) else np.nan,
                '신규AUM_cur(백만원)':    round(aum_cur_new) if not np.isnan(aum_cur_new) else np.nan,
                '이전금액(백만원)':         round(val_old, 1) if not np.isnan(val_old) else np.nan,
                '신규금액(백만원)':         round(val_new, 1) if not np.isnan(val_new) else np.nan,
                '차이(백만원)':            round(gain, 1)    if not np.isnan(gain)    else np.nan,
                '차이(억원)':             round(gain / 100, 2) if not np.isnan(gain)  else np.nan,
                '이득여부':               is_gain,
                '전날종가(T-1)':          p_t1,
                '당일종가(T)':            p_t,
                '종목수익률':              round(stock_ret,  6) if not np.isnan(stock_ret)  else np.nan,
                '코스닥수익률(벤치마크)':   round(bm_ret,    6) if not np.isnan(bm_ret)    else np.nan,  # ★
                '초과수익률':              round(excess_ret, 6) if not np.isnan(excess_ret) else np.nan,
                '초과승리여부':            excess_win,
            })

    switch_df = pd.DataFrame(records)
    gain_df   = switch_df.dropna(subset=['차이(백만원)', '이득여부']).copy()
    return switch_df, gain_df


# ════════════════════════════════════════════════════════════
# CSV 저장
# ════════════════════════════════════════════════════════════
def save_csvs(switch_df: pd.DataFrame,
              gain_df: pd.DataFrame,
              output_dir: str,
              remove_outliers: bool):
    os.makedirs(output_dir, exist_ok=True)
    suffix = "_outlier_removed" if remove_outliers else "_full_sample"
    saved  = []

    for date_str in sorted(switch_df['정기변경일'].unique()):
        sub  = switch_df[switch_df['정기변경일'] == date_str].copy()
        # ★ 파일명 prefix: kosdaq_
        path = os.path.join(output_dir,
                            f"kosdaq_sector_switch_{date_str.replace('-','')}{suffix}.csv")
        sub.to_csv(path, index=False, encoding='utf-8-sig')
        saved.append(path)

    path_all = os.path.join(output_dir, f"kosdaq_sector_switch_all{suffix}.csv")
    switch_df.to_csv(path_all, index=False, encoding='utf-8-sig')
    saved.append(path_all)

    path_gain = os.path.join(output_dir, f"kosdaq_gain_analysis{suffix}.csv")
    gain_df.to_csv(path_gain, index=False, encoding='utf-8-sig')
    saved.append(path_gain)

    print(f"\n  [CSV 저장 완료] → {output_dir}")
    for p in saved:
        print(f"    • {os.path.basename(p)}")


# ════════════════════════════════════════════════════════════
# 출력 헬퍼
# ════════════════════════════════════════════════════════════
def _fmt_aum(v):
    if np.isnan(v):
        return "     N/A   "
    return f"{v / 1_000_000:>9.2f}조"


def _print_section(title):
    print(f"\n{'═'*80}")
    print(f"  {title}")
    print('═'*80)


# ════════════════════════════════════════════════════════════
# 메인
# ════════════════════════════════════════════════════════════
def main():
    print(f"\n{'='*80}")
    print(f"  [SETTING]  REMOVE_OUTLIERS = {REMOVE_OUTLIERS}"
          f"  ({'이상치(x·y<0) 제거 후 회귀' if REMOVE_OUTLIERS else '전체 표본으로 회귀'})")
    print(f"  [SETTING]  OUTPUT_DIR      = {OUTPUT_DIR}")
    print(f"  [SETTING]  BENCHMARK_PATH  = {BENCHMARK_PATH}  (벤치마크: 코스닥 지수)")
    print(f"{'='*80}")

    item_dfs, all_dates_sorted, code_to_name = load_data(DATA_PATH)
    kosdaq_index = load_benchmark(BENCHMARK_PATH)
    print(f"  벤치마크(코스닥 지수) 로딩 완료: {len(kosdaq_index)}일")

    results_df, aum_dict, sector_info = run_regression(item_dfs, all_dates_sorted)

    dates_list = sorted(sector_info.keys())
    case_order = [CASE_LABELS[c] for c in CASES]

    switch_df, gain_df = build_switch_table(
        sector_info, aum_dict, item_dfs, code_to_name, kosdaq_index
    )

    # ────────────────────────────────────────────────────────
    # 출력 1: AUM
    # ────────────────────────────────────────────────────────
    _print_section("[코스닥] ① 리밸런싱별 섹터별 추정 AUM  (섹터유지종목 교집합 표본)")
    print(f"  {'날짜':<14}  {'대형주':>11}  {'중형주':>11}  {'소형주':>11}"
          f"  {'회귀표본_대':>11}  {'회귀표본_중':>11}  {'회귀표본_소':>11}")
    print('─'*80)
    for d in dates_list:
        aum_row  = [_fmt_aum(aum_dict.get((d, s), np.nan)) for s in SECTORS]
        sub      = results_df[results_df['정기변경일'] == d]
        fit_info = []
        for s in SECTORS:
            r = sub[sub['섹터'] == s]
            if len(r):
                n_fit = int(r['회귀사용표본수'].values[0])
                n_raw = int(r['전체표본수'].values[0])
                fit_info.append(f"  {n_fit:>3}/{n_raw:>3}개")
            else:
                fit_info.append("        N/A")
        print(f"  {d:<14}  {aum_row[0]}  {aum_row[1]}  {aum_row[2]}"
              f"  {fit_info[0]}  {fit_info[1]}  {fit_info[2]}")

    outlier_note = "※ 이상치: x·y<0 표본 제거" if REMOVE_OUTLIERS else "※ 이상치 제거 없음"
    print(f"\n  {outlier_note}")
    print(f"  ※ gain: val_old = AUM(당일, s_old) × 비중(직전 정기변경일)")
    print(f"           val_new = AUM(당일, s_new) × 비중(당일)")

    # ────────────────────────────────────────────────────────
    # 출력 2: 케이스별 분석
    # ────────────────────────────────────────────────────────
    _print_section("[코스닥] ② 리밸런싱별 케이스별 분석  (주가수익률 = 코스닥 대비 초과수익률)")

    print(f"  {'날짜':<14}  코스닥 당일 수익률")
    print('─'*40)
    for d in dates_list:
        t1  = sector_info[d]['prev_biz_day_str']
        bT  = float(kosdaq_index.get(pd.Timestamp(d),  np.nan))
        bT1 = float(kosdaq_index.get(pd.Timestamp(t1), np.nan))
        bm  = (bT - bT1) / bT1 if not np.isnan(bT1) and bT1 > 0 else np.nan
        bm_s = f"{bm*100:>+.3f}%" if not np.isnan(bm) else "N/A"
        print(f"  {d:<14}  {bm_s}")
    print()

    hdr = (f"  {'날짜':<14}  {'케이스':<10}  {'종목수':>5}"
           f"  {'이득확률':>8}  {'초과승률':>8}  {'평균초과수익률':>14}")
    print(hdr)
    print('─'*80)

    for d in dates_list:
        sub   = gain_df[gain_df['정기변경일'] == d]
        first = True
        for cl in case_order:
            csub = sub[sub['케이스'] == cl]
            n    = len(csub)
            if n == 0:
                gain_s, win_s, ret_s = "     N/A", "     N/A", "           N/A"
            else:
                gain_s = f"  {csub['이득여부'].mean():>6.1%}"
                ew = csub['초과승리여부'].dropna()
                win_s  = f"  {ew.mean():>6.1%}" if len(ew) else "     N/A"
                er = csub['초과수익률'].dropna()
                ret_s  = f"  {er.mean()*100:>+12.3f}%" if len(er) else "           N/A"
            date_col = d if first else " " * 14
            print(f"  {date_col:<14}  {cl:<10}  {n:>5}"
                  f"  {gain_s}  {win_s}  {ret_s}")
            first = False
        print('─'*80)

    # ────────────────────────────────────────────────────────
    # 출력 3: 전체 합산
    # ────────────────────────────────────────────────────────
    _print_section("[코스닥] ③ 전체 기간 합산 — 케이스별 분석  (코스닥 대비 초과수익률 기준)")
    print(f"  {'케이스':<10}  {'총종목수':>6}"
          f"  {'수급승률':>8}  {'초과수익률 승률':>8}  {'평균초과수익률':>14}")
    print('─'*80)
    for cl in case_order:
        csub = gain_df[gain_df['케이스'] == cl]
        n    = len(csub)
        if n == 0:
            print(f"  {cl:<10}  {n:>6}  {'N/A':>8}  {'N/A':>8}  {'N/A':>14}")
            continue
        gain_s = f"  {csub['이득여부'].mean():>6.1%}"
        ew = csub['초과승리여부'].dropna()
        win_s  = f"  {ew.mean():>6.1%}" if len(ew) else "     N/A"
        er = csub['초과수익률'].dropna()
        ret_s  = f"  {er.mean()*100:>+12.3f}%" if len(er) else "           N/A"
        print(f"  {cl:<10}  {n:>6}  {gain_s}  {win_s}  {ret_s}")

    # ────────────────────────────────────────────────────────
    # 출력 4: 종목 수
    # ────────────────────────────────────────────────────────
    _print_section("[코스닥] ④ 리밸런싱별 케이스별 종목 수")
    header = (f"  {'날짜':<14}"
              + "".join(f"  {cl:>10}" for cl in case_order)
              + f"  {'합계':>6}")
    print(header)
    print('─'*80)
    total_row = {cl: 0 for cl in case_order}
    for d in dates_list:
        sub   = switch_df[switch_df['정기변경일'] == d]
        cnts  = sub['케이스'].value_counts()
        row_s = f"  {d:<14}"
        total = 0
        for cl in case_order:
            cnt = int(cnts.get(cl, 0))
            total_row[cl] += cnt
            total += cnt
            row_s += f"  {cnt:>10}"
        row_s += f"  {total:>6}"
        print(row_s)
    print('─'*80)
    tot_s = (f"  {'합  계':<14}"
             + "".join(f"  {total_row[cl]:>10}" for cl in case_order)
             + f"  {sum(total_row.values()):>6}")
    print(tot_s)

    save_csvs(switch_df, gain_df, OUTPUT_DIR, REMOVE_OUTLIERS)

    print(f"\n{'═'*80}")
    print("  [코스닥] 분석 완료")
    print('═'*80)

    return switch_df, gain_df, results_df, aum_dict


if __name__ == '__main__':
    switch_df, gain_df, results_df, aum_dict = main()

#python kospi_정기변경/final_ksodaq.py