from __future__ import annotations

from pathlib import Path

import matplotlib
import matplotlib.dates as mdates
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt


CD_EXCEL_PATH = r"C:\Users\tmdwhd2080\Desktop\한국투자증권 _FICC\kofr.xlsm"
OIS_EXCEL_PATH = r"C:\Users\tmdwhd2080\Desktop\한국투자증권 _FICC\KOFR OIS.xlsx"


def load_cd91(path: str) -> pd.DataFrame:
    raw = pd.read_excel(path, header=None)
    header_idx = raw.index[raw.iloc[:, 0].astype(str).eq("Date")][0]
    cols = raw.iloc[header_idx].tolist()
    df = raw.iloc[header_idx + 1 :, : len(cols)].copy()
    df.columns = cols
    df = df[df["Date"].notna()].copy()
    df["date"] = pd.to_datetime(df["Date"])
    df["CD91 rate"] = pd.to_numeric(df["CD91 rate"], errors="coerce")
    return df[["date", "CD91 rate"]].dropna()


def load_kofr_ois_3m(path: str) -> pd.DataFrame:
    raw = pd.read_excel(path, sheet_name=0, header=None)
    header_idx = raw.index[raw.iloc[:, 0].astype(str).eq("시작")][0]
    cols = raw.iloc[header_idx].tolist()
    df = raw.iloc[header_idx + 3 :, : len(cols)].copy()
    df.columns = cols
    ois_col = "KOFR OIS(자중) 3개월"
    if ois_col not in df.columns:
        raise ValueError(f"Could not find expected column: {ois_col}")
    df = df[df["시작"].notna()].copy()
    df["date"] = pd.to_datetime(df["시작"])
    df[ois_col] = pd.to_numeric(df[ois_col], errors="coerce")
    return df[["date", ois_col]].rename(columns={ois_col: "KOFR OIS 3M"}).dropna()


def build_comparison(cd_path: str, ois_path: str) -> pd.DataFrame:
    cd = load_cd91(cd_path)
    ois = load_kofr_ois_3m(ois_path)
    merged = cd.merge(ois, on="date", how="inner").sort_values("date").reset_index(drop=True)
    merged["CD - KOFR OIS 3M (bp)"] = (merged["CD91 rate"] - merged["KOFR OIS 3M"]) * 100.0
    return merged


def plot(df: pd.DataFrame, output: str) -> None:
    plt.style.use("seaborn-v0_8-whitegrid")
    fig, ax = plt.subplots(figsize=(12.8, 5.6))

    ax.plot(df["date"], df["CD91 rate"], label="CD91 rate", color="#355c9a", linewidth=1.8)
    ax.plot(df["date"], df["KOFR OIS 3M"], label="KOFR OIS 3M", color="#d66a1f", linewidth=1.8)

    ax.set_title("CD91 vs Same-Day KOFR OIS 3M", fontsize=13, pad=10)
    ax.set_ylabel("Rate (%)")
    ax.set_xlabel("Date")
    ax.legend(loc="upper left", frameon=False, ncol=2)
    ax.grid(True, color="#e5e7eb", linewidth=0.8)
    ax.spines["top"].set_color("#999999")
    ax.spines["right"].set_visible(False)

    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=1))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    for label in ax.get_xticklabels():
        label.set_rotation(40)
        label.set_ha("right")

    fig.tight_layout()
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=180)
    plt.close(fig)


def main() -> None:
    output_csv = Path("out/cd91_vs_kofr_ois_3m_comparison.csv")
    output_png = "out/cd91_vs_kofr_ois_3m.png"
    comparison = build_comparison(CD_EXCEL_PATH, OIS_EXCEL_PATH)
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    comparison.to_csv(output_csv, index=False, encoding="utf-8-sig")
    plot(comparison, output_png)
    print(f"rows={len(comparison)}")
    print(f"start={comparison['date'].min().date()}")
    print(f"end={comparison['date'].max().date()}")
    print(f"basis_mean_bp={comparison['CD - KOFR OIS 3M (bp)'].mean():.2f}")
    print(f"saved={output_png}")
    print(f"saved={output_csv}")


if __name__ == "__main__":
    main()
