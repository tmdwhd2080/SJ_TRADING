"""Run single-factor regressions: PAYEMS initial on ADP initial."""

from __future__ import annotations

import argparse
import csv
import math
from datetime import datetime
from pathlib import Path
from typing import Any


ADP = "ADP_monthly_change_thousands"
PAYEMS = "PAYEMS_monthly_change_thousands"


def read_initial_values(path: Path, start_month: str, end_month: str) -> tuple[list[str], list[float], list[float]]:
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

    months = sorted(set(adp) & set(payems))
    return months, [adp[month] for month in months], [payems[month] for month in months]


def mean(values: list[float]) -> float:
    return sum(values) / len(values)


def sample_std(values: list[float]) -> float:
    avg = mean(values)
    return math.sqrt(sum((value - avg) ** 2 for value in values) / (len(values) - 1))


def ols(x: list[float], y: list[float]) -> dict[str, Any]:
    n = len(x)
    x_mean = mean(x)
    y_mean = mean(y)
    sxx = sum((value - x_mean) ** 2 for value in x)
    syy = sum((value - y_mean) ** 2 for value in y)
    sxy = sum((x_value - x_mean) * (y_value - y_mean) for x_value, y_value in zip(x, y))
    beta = sxy / sxx
    alpha = y_mean - beta * x_mean
    fitted = [alpha + beta * value for value in x]
    residuals = [actual - fit for actual, fit in zip(y, fitted)]
    sse = sum(value * value for value in residuals)
    r2 = 1 - sse / syy
    df = n - 2
    mse = sse / df
    se_beta = math.sqrt(mse / sxx)
    se_alpha = math.sqrt(mse * (1 / n + x_mean * x_mean / sxx))
    return {
        "n": n,
        "alpha": alpha,
        "beta": beta,
        "r2": r2,
        "adj_r2": 1 - (1 - r2) * (n - 1) / (n - 2),
        "corr": sxy / math.sqrt(sxx * syy),
        "se_alpha": se_alpha,
        "se_beta": se_beta,
        "t_alpha": alpha / se_alpha,
        "t_beta": beta / se_beta,
        "rmse": math.sqrt(sse / n),
        "residual_std_error": math.sqrt(mse),
        "x_mean": x_mean,
        "x_sample_std": sample_std(x),
        "y_mean": y_mean,
        "y_sample_std": sample_std(y),
    }


def zscore(values: list[float]) -> list[float]:
    avg = mean(values)
    std = sample_std(values)
    return [(value - avg) / std for value in values]


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "model",
        "start_month",
        "end_month",
        "n",
        "equation",
        "alpha",
        "beta",
        "r2",
        "adj_r2",
        "corr",
        "se_alpha",
        "se_beta",
        "t_alpha",
        "t_beta",
        "rmse",
        "residual_std_error",
        "x_mean",
        "x_sample_std",
        "y_mean",
        "y_sample_std",
    ]
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    script_dir = Path(__file__).resolve().parent
    parser.add_argument(
        "--input-file",
        default=str(script_dir / "data" / "employment_events_2022_2026" / "initial_releases.csv"),
    )
    parser.add_argument("--start-month", default="2022-09-01")
    parser.add_argument("--end-month", default="2026-06-01")
    parser.add_argument(
        "--output-file",
        default=str(script_dir / "data" / "adp_payems_initial_regression_2022-09_2026-06.csv"),
    )
    args = parser.parse_args()

    months, adp, payems = read_initial_values(Path(args.input_file), args.start_month, args.end_month)
    raw = ols(adp, payems)
    standardized = ols(zscore(adp), zscore(payems))

    rows = [
        {
            **raw,
            "model": "raw_initial",
            "start_month": months[0],
            "end_month": months[-1],
            "equation": "PAYEMS_initial = alpha + beta * ADP_initial",
        },
        {
            **standardized,
            "model": "zscore_initial",
            "start_month": months[0],
            "end_month": months[-1],
            "equation": "Z_PAYEMS_initial = alpha + beta * Z_ADP_initial",
        },
    ]
    write_csv(Path(args.output_file), rows)
    print(f"Wrote regression results to {args.output_file}")
    print(f"generated_at={datetime.now().isoformat(timespec='seconds')}")
    for row in rows:
        print(
            f"{row['model']}: alpha={row['alpha']:.6f}, beta={row['beta']:.6f}, "
            f"r2={row['r2']:.6f}, t_beta={row['t_beta']:.6f}, n={row['n']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
