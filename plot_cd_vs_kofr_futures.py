from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib
import matplotlib.dates as mdates
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt


DEFAULT_EXCEL = r"C:\Users\tmdwhd2080\Desktop\한국투자증권 _FICC\kofr.xlsm"


def load_excel_rates(path: str) -> pd.DataFrame:
    raw = pd.read_excel(path, header=None)
    header_rows = raw.index[raw.iloc[:, 0].astype(str).eq("Date")].tolist()
    if not header_rows:
        raise ValueError("Could not find the header row whose first cell is 'Date'.")
    header_idx = header_rows[0]

    columns = raw.iloc[header_idx].tolist()
    df = raw.iloc[header_idx + 1 :, : len(columns)].copy()
    df.columns = columns
    df = df[df["Date"].notna()].copy()
    df["date"] = pd.to_datetime(df["Date"])
    df["CD91 rate"] = pd.to_numeric(df["CD91 rate"], errors="coerce")
    df["KOFR rate"] = pd.to_numeric(df["KOFR rate"], errors="coerce")
    return df[["date", "CD91 rate", "KOFR rate"]].dropna(subset=["date", "CD91 rate"])


def third_wednesday(year: int, month: int) -> pd.Timestamp:
    first = pd.Timestamp(year=year, month=month, day=1)
    days = pd.date_range(first, first + pd.offsets.MonthEnd(0), freq="D")
    return days[days.weekday == 2][2]


def contract_reference_period(contract_month: int) -> tuple[pd.Timestamp, pd.Timestamp]:
    year = int(contract_month) // 100
    month = int(contract_month) % 100
    end = third_wednesday(year, month)
    start_month = pd.Timestamp(year=year, month=month, day=1) - pd.DateOffset(months=3)
    start = third_wednesday(start_month.year, start_month.month)
    return start, end


def load_futures(path: str) -> pd.DataFrame:
    futures = pd.read_csv(path, encoding="utf-8-sig")
    futures["date"] = pd.to_datetime(futures["date"])
    futures["contract_month"] = pd.to_numeric(futures["contract_month"], errors="coerce")
    futures["is_spread"] = futures["is_spread"].astype(str).str.lower().eq("true")
    for col in ["종가", "현물가", "거래량", "close_implied_rate", "spot_implied_rate"]:
        if col in futures.columns:
            futures[col] = pd.to_numeric(futures[col], errors="coerce")

    outright = futures[
        (~futures["is_spread"])
        & futures["contract_month"].notna()
        & futures["spot_implied_rate"].between(-5, 20)
    ].copy()
    outright = outright.sort_values(["date", "contract_month"])
    refs = outright["contract_month"].astype(int).map(contract_reference_period)
    outright["reference_start"] = refs.map(lambda x: x[0])
    outright["reference_end"] = refs.map(lambda x: x[1])
    outright = outright.rename(
        columns={
            "종목명": "futures_name",
            "종가": "futures_close_price",
            "현물가": "futures_settlement_price",
            "거래량": "futures_volume",
            "spot_implied_rate": "futures_implied_rate",
            "close_implied_rate": "traded_close_implied_rate",
        }
    )
    outright.loc[outright["futures_volume"].fillna(0) <= 0, "traded_close_implied_rate"] = pd.NA
    return outright[
        [
            "date",
            "ticker",
            "futures_name",
            "contract_month",
            "reference_start",
            "reference_end",
            "futures_settlement_price",
            "futures_close_price",
            "futures_volume",
            "futures_implied_rate",
            "traded_close_implied_rate",
        ]
    ]


def select_front_contracts(futures: pd.DataFrame) -> pd.DataFrame:
    return futures.sort_values(["date", "contract_month"]).groupby("date", as_index=False).first()


def select_horizon_matched_contracts(rates: pd.DataFrame, futures: pd.DataFrame) -> pd.DataFrame:
    selected_rows = []
    futures_by_date = dict(tuple(futures.groupby("date")))
    for rate_row in rates.itertuples(index=False):
        date = rate_row.date
        candidates = futures_by_date.get(date)
        if candidates is None or candidates.empty:
            continue
        target_start = date
        target_end = date + pd.Timedelta(days=91)
        candidates = candidates.copy()
        overlap_start = candidates["reference_start"].where(
            candidates["reference_start"] > target_start, target_start
        )
        overlap_end = candidates["reference_end"].where(candidates["reference_end"] < target_end, target_end)
        candidates["overlap_days"] = (overlap_end - overlap_start).dt.days.clip(lower=0)
        candidates["start_gap_days"] = (candidates["reference_start"] - target_start).abs().dt.days
        selected = candidates.sort_values(
            ["overlap_days", "start_gap_days", "contract_month"],
            ascending=[False, True, True],
        ).iloc[0]
        selected_rows.append(selected)
    return pd.DataFrame(selected_rows).reset_index(drop=True)


def build_comparison(excel_path: str, futures_path: str, selection: str) -> pd.DataFrame:
    rates = load_excel_rates(excel_path)
    futures = load_futures(futures_path)
    if selection == "front":
        selected_futures = select_front_contracts(futures)
    elif selection == "horizon":
        selected_futures = select_horizon_matched_contracts(rates, futures)
    else:
        raise ValueError(f"Unsupported selection: {selection}")
    merged = rates.merge(selected_futures, on="date", how="inner")
    merged["basis_bp"] = (merged["CD91 rate"] - merged["futures_implied_rate"]) * 100.0
    merged["target_end"] = merged["date"] + pd.Timedelta(days=91)
    return merged


def add_event_shading(ax, ymin: float, ymax: float) -> None:
    events = [
        ("2025-11-03", "2026-01-15", "#f1d6b8", "CD repricing / funding"),
        ("2026-03-02", "2026-05-15", "#dcefd2", "cut hopes + short-term supply"),
        ("2026-06-20", "2026-07-15", "#e4dbf4", "CD to KOFR transition"),
    ]
    text_y = ymin + (ymax - ymin) * 0.88
    for start, end, color, label in events:
        ax.axvspan(pd.Timestamp(start), pd.Timestamp(end), color=color, alpha=0.45, lw=0)
        mid = pd.Timestamp(start) + (pd.Timestamp(end) - pd.Timestamp(start)) / 2
        ax.text(mid, text_y, label, ha="center", va="top", fontsize=8, color="#6b604f")


def plot_comparison(df: pd.DataFrame, output: str, selection: str) -> None:
    plt.style.use("seaborn-v0_8-whitegrid")
    fig, (ax1, ax2) = plt.subplots(
        2,
        1,
        figsize=(12.8, 7.2),
        sharex=True,
        gridspec_kw={"height_ratios": [2.2, 1.0], "hspace": 0.05},
    )

    y_min = min(df["CD91 rate"].min(), df["futures_implied_rate"].min()) - 0.05
    y_max = max(df["CD91 rate"].max(), df["futures_implied_rate"].max()) + 0.06
    add_event_shading(ax1, y_min, y_max)

    ax1.plot(df["date"], df["CD91 rate"], color="#355c9a", lw=1.8, label="CD91 rate")
    ax1.plot(
        df["date"],
        df["futures_implied_rate"],
        color="#d66a1f",
        lw=1.8,
        label="KRX 3M KOFR futures implied rate",
    )
    traded = df[df["traded_close_implied_rate"].notna()]
    if not traded.empty:
        ax1.scatter(
            traded["date"],
            traded["traded_close_implied_rate"],
            s=18,
            color="#111827",
            alpha=0.55,
            label="traded close implied rate",
            zorder=4,
        )

    selection_label = "horizon-matched" if selection == "horizon" else "nearest/front"
    ax1.set_title(f"CD91 vs KRX 3M KOFR Futures-Implied Rate ({selection_label})", fontsize=13, pad=10)
    ax1.set_ylabel("Rate (%)")
    ax1.set_ylim(y_min, y_max)
    ax1.legend(loc="upper left", ncol=3, frameon=False, fontsize=9)

    colors = df["basis_bp"].map(lambda x: "#79a744" if x >= 0 else "#c4554d")
    ax2.bar(df["date"], df["basis_bp"], width=1.8, color=colors, edgecolor=colors, alpha=0.9)
    ax2.axhline(0, color="#777777", lw=0.8)
    ax2.set_ylabel("Basis (bp)")
    ax2.set_xlabel("CD91 start date / selected KRX KOFR futures contract date")

    ax2.xaxis.set_major_locator(mdates.MonthLocator(interval=1))
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    for label in ax2.get_xticklabels():
        label.set_rotation(40)
        label.set_ha("right")

    for ax in (ax1, ax2):
        ax.grid(True, color="#e5e7eb", linewidth=0.8)
        ax.spines["top"].set_color("#999999")
        ax.spines["right"].set_visible(False)

    fig.text(
        0.01,
        0.01,
        "Note: futures implied rate = 100 - KRX SETL_PRC field returned by pykrx; "
        "horizon-matched selection maximizes overlap with date to date+91D. "
        "Close markers only appear on dates with reported trading volume.",
        fontsize=8,
        color="#555555",
    )
    fig.tight_layout(rect=(0, 0.04, 1, 1))

    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=180)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description="Plot CD91 against KRX 3M KOFR futures implied rate.")
    parser.add_argument("--excel", default=DEFAULT_EXCEL)
    parser.add_argument("--futures", default="out/kofr_futures_krx_20250602_20260727.csv")
    parser.add_argument("--selection", choices=["horizon", "front"], default="horizon")
    parser.add_argument("--comparison-output", default="out/cd91_vs_krx_kofr_futures_comparison.csv")
    parser.add_argument("--plot-output", default="out/cd91_vs_krx_kofr_futures.png")
    args = parser.parse_args()

    comparison = build_comparison(args.excel, args.futures, selection=args.selection)
    out_csv = Path(args.comparison_output)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    comparison.to_csv(out_csv, index=False, encoding="utf-8-sig")
    plot_comparison(comparison, args.plot_output, selection=args.selection)

    print(f"comparison={out_csv}")
    print(f"plot={args.plot_output}")
    print(f"rows={len(comparison)}")
    print(
        comparison[
            [
                "date",
                "CD91 rate",
                "futures_implied_rate",
                "contract_month",
                "reference_start",
                "reference_end",
                "basis_bp",
                "futures_volume",
                "traded_close_implied_rate",
            ]
        ]
        .describe(include="all")
        .to_string()
    )


if __name__ == "__main__":
    main()
