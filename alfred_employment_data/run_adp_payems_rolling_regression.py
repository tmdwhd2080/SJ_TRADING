"""Run rolling same-month ADP initial vs PAYEMS initial regressions."""

from __future__ import annotations

import argparse
import csv
import math
from datetime import datetime
from pathlib import Path
from typing import Any


ADP = "ADP_monthly_change_thousands"
PAYEMS = "PAYEMS_monthly_change_thousands"


def mean(values: list[float]) -> float:
    return sum(values) / len(values)


def ols(x: list[float], y: list[float]) -> dict[str, float]:
    n = len(x)
    x_mean = mean(x)
    y_mean = mean(y)
    sxx = sum((value - x_mean) ** 2 for value in x)
    syy = sum((value - y_mean) ** 2 for value in y)
    sxy = sum((x_value - x_mean) * (y_value - y_mean) for x_value, y_value in zip(x, y))
    beta = sxy / sxx if sxx else float("nan")
    alpha = y_mean - beta * x_mean if sxx else float("nan")
    fitted = [alpha + beta * value for value in x]
    residuals = [actual - fit for actual, fit in zip(y, fitted)]
    sse = sum(value * value for value in residuals)
    r2 = 1 - sse / syy if syy else float("nan")
    corr = sxy / math.sqrt(sxx * syy) if sxx and syy else float("nan")
    return {
        "alpha": alpha,
        "beta": beta,
        "corr": corr,
        "r2": r2,
        "rmse": math.sqrt(sse / n),
    }


def read_panel(path: Path, start_month: str, end_month: str) -> list[dict[str, Any]]:
    adp: dict[str, float] = {}
    payems: dict[str, float] = {}

    with path.open("r", newline="", encoding="utf-8") as file:
        for row in csv.DictReader(file):
            target = row["target_date"]
            if target < start_month or target > end_month:
                continue
            if row["indicator"] == ADP:
                adp[target] = float(row["published_value"])
            elif row["indicator"] == PAYEMS:
                payems[target] = float(row["published_value"])

    panel: list[dict[str, Any]] = []
    for target_date in sorted(set(adp) & set(payems)):
        panel.append(
            {
                "target_date": target_date,
                "adp_initial": adp[target_date],
                "payems_initial": payems[target_date],
            }
        )
    return panel


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def window_stats(panel: list[dict[str, Any]], window: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for end_idx in range(window - 1, len(panel)):
        sample = panel[end_idx - window + 1 : end_idx + 1]
        x = [row["adp_initial"] for row in sample]
        y = [row["payems_initial"] for row in sample]
        stats = ols(x, y)
        rows.append(
            {
                "window_months": window,
                "window_start": sample[0]["target_date"],
                "window_end": sample[-1]["target_date"],
                "n": len(sample),
                "alpha": stats["alpha"],
                "beta": stats["beta"],
                "corr": stats["corr"],
                "r2": stats["r2"],
                "rmse": stats["rmse"],
                "latest_adp_initial": sample[-1]["adp_initial"],
                "latest_payems_initial": sample[-1]["payems_initial"],
                "latest_fitted": stats["alpha"] + stats["beta"] * sample[-1]["adp_initial"],
                "latest_residual": sample[-1]["payems_initial"]
                - (stats["alpha"] + stats["beta"] * sample[-1]["adp_initial"]),
            }
        )
    return rows


def parse_windows(value: str) -> list[int]:
    windows = [int(item.strip()) for item in value.split(",") if item.strip()]
    if not windows or any(window < 3 for window in windows):
        raise argparse.ArgumentTypeError("window sizes must be comma-separated integers >= 3")
    return windows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    script_dir = Path(__file__).resolve().parent
    parser.add_argument(
        "--input-file",
        default=str(script_dir / "data" / "employment_events_2020_2026" / "initial_releases.csv"),
    )
    parser.add_argument("--start-month", default="2020-02-01")
    parser.add_argument("--end-month", default="2026-06-01")
    parser.add_argument("--windows", type=parse_windows, default=parse_windows("12,24,36"))
    parser.add_argument(
        "--output-dir",
        default=str(script_dir / "data" / "adp_payems_rolling_2020-02_2026-06"),
    )
    args = parser.parse_args()

    panel = read_panel(Path(args.input_file), args.start_month, args.end_month)
    if len(panel) < max(args.windows):
        raise RuntimeError(f"Need at least {max(args.windows)} paired observations; got {len(panel)}")

    output_dir = Path(args.output_dir)
    write_csv(
        output_dir / "monthly_panel.csv",
        panel,
        ["target_date", "adp_initial", "payems_initial"],
    )

    all_x = [row["adp_initial"] for row in panel]
    all_y = [row["payems_initial"] for row in panel]
    full = ols(all_x, all_y)
    summary_rows = [
        {
            "sample": "full",
            "start_month": panel[0]["target_date"],
            "end_month": panel[-1]["target_date"],
            "n": len(panel),
            "alpha": full["alpha"],
            "beta": full["beta"],
            "corr": full["corr"],
            "r2": full["r2"],
            "rmse": full["rmse"],
        }
    ]

    for start in ("2021-01-01", "2022-09-01", "2023-01-01"):
        sub = [row for row in panel if row["target_date"] >= start]
        stats = ols([row["adp_initial"] for row in sub], [row["payems_initial"] for row in sub])
        summary_rows.append(
            {
                "sample": f"from_{start[:7]}",
                "start_month": sub[0]["target_date"],
                "end_month": sub[-1]["target_date"],
                "n": len(sub),
                "alpha": stats["alpha"],
                "beta": stats["beta"],
                "corr": stats["corr"],
                "r2": stats["r2"],
                "rmse": stats["rmse"],
            }
        )

    summary_fields = ["sample", "start_month", "end_month", "n", "alpha", "beta", "corr", "r2", "rmse"]
    write_csv(output_dir / "summary_correlations.csv", summary_rows, summary_fields)

    rolling_rows: list[dict[str, Any]] = []
    for window in args.windows:
        rolling_rows.extend(window_stats(panel, window))

    rolling_fields = [
        "window_months",
        "window_start",
        "window_end",
        "n",
        "alpha",
        "beta",
        "corr",
        "r2",
        "rmse",
        "latest_adp_initial",
        "latest_payems_initial",
        "latest_fitted",
        "latest_residual",
    ]
    write_csv(output_dir / "rolling_regressions.csv", rolling_rows, rolling_fields)

    print(f"Wrote outputs to {output_dir}")
    print(f"generated_at={datetime.now().isoformat(timespec='seconds')}")
    for row in summary_rows:
        print(
            f"{row['sample']}: n={row['n']}, corr={row['corr']:.6f}, "
            f"r2={row['r2']:.6f}, beta={row['beta']:.6f}"
        )
    for window in args.windows:
        latest = [row for row in rolling_rows if row["window_months"] == window][-1]
        print(
            f"latest_{window}m: {latest['window_start']}~{latest['window_end']}, "
            f"corr={latest['corr']:.6f}, r2={latest['r2']:.6f}, beta={latest['beta']:.6f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
