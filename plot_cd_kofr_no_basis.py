from __future__ import annotations

from pathlib import Path

import matplotlib
import matplotlib.dates as mdates
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt


EXCEL_PATH = r"C:\Users\tmdwhd2080\Desktop\한국투자증권 _FICC\kofr.xlsm"


def load_rates(path: str) -> pd.DataFrame:
    raw = pd.read_excel(path, header=None)
    header_idx = raw.index[raw.iloc[:, 0].astype(str).eq("Date")][0]
    cols = raw.iloc[header_idx].tolist()
    df = raw.iloc[header_idx + 1 :, : len(cols)].copy()
    df.columns = cols
    df = df[df["Date"].notna()].copy()
    df["Date"] = pd.to_datetime(df["Date"])
    for col in ["KOFR rate", "CD91 rate", "Compounded KOFR rate"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.dropna(subset=["Date", "CD91 rate"])


def plot_lines(
    df: pd.DataFrame,
    y_columns: list[str],
    labels: list[str],
    colors: list[str],
    title: str,
    output: str,
) -> None:
    plt.style.use("seaborn-v0_8-whitegrid")
    fig, ax = plt.subplots(figsize=(12.8, 5.6))

    for col, label, color in zip(y_columns, labels, colors):
        ax.plot(df["Date"], df[col], label=label, color=color, linewidth=1.8)

    ax.set_title(title, fontsize=13, pad=10)
    ax.set_ylabel("Rate (%)")
    ax.set_xlabel("Date")
    ax.legend(loc="upper left", frameon=False, ncol=len(y_columns))
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
    df = load_rates(EXCEL_PATH)
    plot_lines(
        df.dropna(subset=["KOFR rate"]),
        ["CD91 rate", "KOFR rate"],
        ["CD91 rate", "Same-day KOFR"],
        ["#355c9a", "#7e57c2"],
        "CD91 vs Same-Day KOFR",
        "out/cd91_vs_same_day_kofr_no_basis.png",
    )
    plot_lines(
        df.dropna(subset=["Compounded KOFR rate"]),
        ["CD91 rate", "Compounded KOFR rate"],
        ["CD91 rate", "Subsequent 91D compounded KOFR"],
        ["#355c9a", "#d66a1f"],
        "CD91 vs Subsequent 91-Day Compounded KOFR",
        "out/cd91_vs_forward91_compounded_kofr_no_basis.png",
    )
    print(f"rows={len(df)}")
    print(f"start={df['Date'].min().date()}")
    print(f"end={df['Date'].max().date()}")
    print("saved=out/cd91_vs_same_day_kofr_no_basis.png")
    print("saved=out/cd91_vs_forward91_compounded_kofr_no_basis.png")


if __name__ == "__main__":
    main()
