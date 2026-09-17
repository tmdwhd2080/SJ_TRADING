import pandas as pd
import numpy as np

# ══════════════════════════════════════════════════════════════
# ★ SETTING
# ══════════════════════════════════════════════════════════════
REMOVE_OUTLIERS = True
# True  : x·y < 0 인 이상치 표본 제거 후 회귀 (implied AUM < 0 제거)
# False : 이상치 제거 없이 전체 표본으로 회귀
# ══════════════════════════════════════════════════════════════

REBAL_DATES = pd.to_datetime([
    '2023-03-09',
    '2023-09-14',
    '2024-03-14',
    '2024-09-12',
    '2025-03-13',
    '2025-09-11',
    '2026-03-12',
])

ITEM_MAP = {
    'S100100': '종가',
    'S102100': '시가총액',
    'U111320': '금투순매수',
    'U117320': '연기금순매수',
    'S102301': '지수산정시가총액',
}

SECTORS = ['대형주', '중형주', '소형주']


# ═══════════════════════════════════════════════════════════════
# 1. 데이터 로딩
# ═══════════════════════════════════════════════════════════════
def load_data(filepath: str):
    print("데이터 로딩 중...")
    df_raw = pd.read_excel(filepath, sheet_name='Sheet1', header=None)

    codes_row      = df_raw.iloc[7, 1:].values
    names_row      = df_raw.iloc[8, 1:].values
    item_codes_row = df_raw.iloc[9, 1:].values

    raw_dates = df_raw.iloc[14:, 0].reset_index(drop=True)
    dates_idx = pd.to_datetime(raw_dates.astype(str).str[:10], errors='coerce')
    data_vals = df_raw.iloc[14:, 1:].reset_index(drop=True)
    data_vals.columns = range(len(data_vals.columns))
    data_np = data_vals.values.astype(float)

    n_cols    = len(codes_row)
    col_items = [ITEM_MAP.get(str(item_codes_row[i]), str(item_codes_row[i]))
                 for i in range(n_cols)]
    col_codes = list(codes_row)
    col_names = list(names_row)

    item_dfs = {}
    for item in list(ITEM_MAP.values()):
        cidx = [i for i in range(n_cols) if col_items[i] == item]
        cods = [col_codes[i] for i in cidx]
        item_dfs[item] = pd.DataFrame(
            data_np[:, cidx], index=dates_idx, columns=cods
        )

    code_to_name = {}
    for i in range(n_cols):
        code_to_name.setdefault(col_codes[i], col_names[i])

    all_dates_sorted = sorted(
        item_dfs['지수산정시가총액'].index.dropna().unique()
    )
    print(f"  고유 종목 수: {len(set(col_codes))}, 날짜 수: {len(dates_idx)}")
    return item_dfs, all_dates_sorted, code_to_name


# ═══════════════════════════════════════════════════════════════
# 2. 유틸
# ═══════════════════════════════════════════════════════════════
def get_prev_biz_day(target_date, all_dates_sorted):
    cands = [d for d in all_dates_sorted if d < pd.Timestamp(target_date)]
    return cands[-1] if cands else None


def classify_sectors(cap_series: pd.Series) -> pd.Series:
    valid  = cap_series.dropna()
    valid  = valid[valid > 0]
    ranked = valid.rank(method='first', ascending=False)
    sector = pd.Series(index=valid.index, dtype=str)
    sector[ranked <= 100]                    = '대형주'
    sector[(ranked > 100) & (ranked <= 300)] = '중형주'
    sector[ranked > 300]                     = '소형주'
    return sector


def calc_sector_weights(cap_series: pd.Series, sector_map: pd.Series) -> dict:
    result = {}
    for sector in SECTORS:
        stocks    = sector_map[sector_map == sector].index
        cap       = cap_series.reindex(stocks).dropna()
        total_cap = cap.sum()
        if total_cap > 0:
            for code, w in (cap / total_cap).items():
                result[code] = {'sector': sector, 'weight': float(w)}
    return result


# ═══════════════════════════════════════════════════════════════
# 3. 회귀 (AUM 추정)
# ═══════════════════════════════════════════════════════════════
def _filter_outliers(reg_df: pd.DataFrame) -> pd.DataFrame:
    return reg_df[(reg_df['delta_w'] * reg_df['net_inflow']) > 0].copy()


def _ols_no_intercept(x: np.ndarray, y: np.ndarray):
    sum_xx = np.sum(x ** 2)
    if sum_xx == 0:
        return np.nan, np.nan, np.nan

    beta   = np.sum(x * y) / sum_xx
    y_pred = beta * x
    ss_res = np.sum((y - y_pred) ** 2)
    ss_tot = np.sum((y - np.mean(y)) ** 2)
    r2     = 1 - ss_res / ss_tot if ss_tot > 0 else np.nan

    n      = len(x)
    mse    = ss_res / (n - 1) if n > 1 else np.nan
    se     = (np.sqrt(mse / sum_xx)
              if (mse is not None and mse >= 0 and sum_xx > 0)
              else np.nan)
    t_stat = beta / se if (se and se > 0) else np.nan
    return beta, r2, t_stat


def run_regression(item_dfs: dict, all_dates_sorted: list):
    """
    섹터별 AUM 추정 회귀 수행.
    표본 구성: 교집합(섹터 유지 종목)만 사용
        - 신규 편입 종목 (new_mbr에만 존재) 제외
        - 편출 종목     (old_mbr에만 존재) 제외
    """
    outlier_label = "이상치제거" if REMOVE_OUTLIERS else "전체표본"
    print(f"  회귀 설정: REMOVE_OUTLIERS={REMOVE_OUTLIERS} ({outlier_label}), "
          f"표본=섹터유지종목(교집합)")

    results     = []
    aum_dict    = {}
    sector_info = {}

    for idx in range(1, len(REBAL_DATES)):
        cur_date            = REBAL_DATES[idx]
        prev_rebal_date     = REBAL_DATES[idx - 1]
        prev_biz_day        = get_prev_biz_day(cur_date, all_dates_sorted)

        if prev_biz_day is None:
            continue

        date_str            = cur_date.strftime('%Y-%m-%d')
        prev_rebal_date_str = prev_rebal_date.strftime('%Y-%m-%d')
        prev_biz_day_str    = prev_biz_day.strftime('%Y-%m-%d')

        cap_cur        = item_dfs['지수산정시가총액'].loc[cur_date]
        cap_prev_rebal = item_dfs['지수산정시가총액'].loc[prev_rebal_date]
        cap_prev_biz   = item_dfs['지수산정시가총액'].loc[prev_biz_day]

        sector_new = classify_sectors(cap_cur)
        sector_old = classify_sectors(cap_prev_rebal)

        weights_new       = calc_sector_weights(cap_cur,        sector_new)
        weights_old       = calc_sector_weights(cap_prev_biz,   sector_old)
        weights_old_rebal = calc_sector_weights(cap_prev_rebal, sector_old)

        finv       = item_dfs['금투순매수'].loc[cur_date].fillna(0)
        pension    = item_dfs['연기금순매수'].loc[cur_date].fillna(0)
        net_inflow = finv + pension

        for sector in SECTORS:
            new_mbr = {k for k, v in weights_new.items() if v['sector'] == sector}
            old_mbr = {k for k, v in weights_old.items() if v['sector'] == sector}
            all_mbr = new_mbr & old_mbr   # 교집합: 섹터 유지 종목만

            rows = []
            for code in all_mbr:
                nw = weights_new[code]['weight']
                ow = weights_old[code]['weight']
                rows.append({
                    'code':       code,
                    'delta_w':    nw - ow,
                    'net_inflow': float(net_inflow.get(code, 0.0)),
                })

            reg_df  = pd.DataFrame(rows)
            reg_df  = reg_df[reg_df['delta_w'].abs() > 1e-12].copy()
            n_raw   = len(reg_df)

            if REMOVE_OUTLIERS:
                reg_fit = _filter_outliers(reg_df)
            else:
                reg_fit = reg_df.copy()

            n_fit = len(reg_fit)
            if n_fit < 2:
                continue

            x = reg_fit['delta_w'].values
            y = reg_fit['net_inflow'].values
            beta, r2, t_stat = _ols_no_intercept(x, y)

            aum_dict[(date_str, sector)] = beta

            results.append({
                '정기변경일':    date_str,
                '섹터':        sector,
                '전체표본수':    n_raw,
                '회귀사용표본수': n_fit,
                '제거된표본수':   n_raw - n_fit,
                'AUM(백만원)':  round(beta)                if not np.isnan(beta)   else np.nan,
                'AUM(억원)':   round(beta / 100, 1)        if not np.isnan(beta)   else np.nan,
                'AUM(조원)':   round(beta / 1_000_000, 4)  if not np.isnan(beta)   else np.nan,
                'R²':         round(r2, 4)                 if not np.isnan(r2)     else np.nan,
                't통계량':     round(t_stat, 3)             if not np.isnan(t_stat) else np.nan,
            })

        sector_info[date_str] = {
            'sector_new':          sector_new,
            'sector_old':          sector_old,
            'weights_new':         weights_new,
            'weights_old':         weights_old,
            'weights_old_rebal':   weights_old_rebal,
            'prev_rebal_date_str': prev_rebal_date_str,
            'prev_biz_day_str':    prev_biz_day_str,
        }

    results_df = pd.DataFrame(results)
    return results_df, aum_dict, sector_info


if __name__ == '__main__':
    # ★ 코스닥 데이터 파일 경로
    DATA_PATH = r'C:\Users\intern9\truston_quant_dev\util\코스닥_최종.xlsx'

    item_dfs, all_dates_sorted, code_to_name = load_data(DATA_PATH)
    results_df, aum_dict, sector_info = run_regression(item_dfs, all_dates_sorted)

    print("\n" + "=" * 80)
    print(f"▶ [코스닥] 회귀 결과 (REMOVE_OUTLIERS={REMOVE_OUTLIERS}, 표본=섹터유지종목)")
    print("=" * 80)
    print(results_df.to_string(index=False))

#python kospi_정기변경/flow__kosdaq_calculate.py