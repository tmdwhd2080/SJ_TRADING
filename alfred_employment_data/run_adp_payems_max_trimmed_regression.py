"""Fetch max ADP/PAYEMS initial-like data and run trimmed regressions."""

from __future__ import annotations

import argparse
import csv
import math
import statistics
from datetime import datetime
from pathlib import Path
from typing import Any

from fetch_alfred_employment_data import (
    fetch_vintage_dates,
    fred_get,
    monthly_changes as vintage_monthly_changes,
    normalize_observations,
    paged_observations,
)


ADP_SERIES = "ADPMNUSNERSA"
PAYEMS_SERIES = "PAYEMS"
ADP_LAUNCH_VINTAGE = "2022-08-31"


def parse_float(value: str) -> float | None:
    if value in ("", "."):
        return None
    return float(value)


def month_key(value: str) -> str:
    return value[:7]


def min_date(left: str, right: str) -> str:
    return left if left <= right else right


def series_metadata(series_id: str) -> dict[str, Any]:
    return fred_get("series", {"series_id": series_id})["seriess"][0]


def chunks(values: list[str], size: int) -> list[list[str]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def fetch_vintage_observations(
    series_id: str,
    realtime_start: str,
    realtime_end: str,
    observation_start: str,
    observation_end: str,
    chunk_size: int,
) -> list[dict[str, Any]]:
    vintage_dates = [
        row["vintage_date"]
        for row in fetch_vintage_dates(series_id, realtime_start, realtime_end)
        if realtime_start <= row["vintage_date"] <= realtime_end
    ]
    out: list[dict[str, Any]] = []
    for vintage_chunk in chunks(vintage_dates, chunk_size):
        observations = paged_observations(
            {
                "series_id": series_id,
                "observation_start": observation_start,
                "observation_end": observation_end,
                "output_type": 2,
                "vintage_dates": ",".join(vintage_chunk),
            }
        )
        out.extend(normalize_observations(series_id, observations))
    return out


def first_monthly_change_by_date(
    rows: list[dict[str, Any]],
    series_id: str,
    start: str,
    end: str,
) -> dict[str, dict[str, Any]]:
    changes = vintage_monthly_changes(rows, start, end)
    out: dict[str, dict[str, Any]] = {}
    for row in changes:
        if row["series_id"] != series_id:
            continue
        target_date = str(row["date"])
        if target_date not in out or str(row["realtime_start"]) < str(out[target_date]["realtime_start"]):
            out[target_date] = row
    return out


def median_abs_deviation(values: list[float]) -> float:
    median = statistics.median(values)
    return statistics.median([abs(value - median) for value in values])


def robust_z_scores(values: list[float]) -> list[float]:
    median = statistics.median(values)
    mad = median_abs_deviation(values)
    if mad == 0:
        return [0.0 for _ in values]
    return [0.6745 * (value - median) / mad for value in values]


def mean(values: list[float]) -> float:
    return sum(values) / len(values)


def ols(x: list[float], y: list[float]) -> dict[str, float]:
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
    corr = sxy / math.sqrt(sxx * syy)
    rmse = math.sqrt(sse / n)
    df = n - 2
    residual_std_error = math.sqrt(sse / df)
    se_beta = math.sqrt((sse / df) / sxx)
    se_alpha = math.sqrt((sse / df) * (1 / n + x_mean * x_mean / sxx))
    return {
        "alpha": alpha,
        "beta": beta,
        "corr": corr,
        "r2": r2,
        "adj_r2": 1 - (1 - r2) * (n - 1) / (n - 2),
        "rmse": rmse,
        "residual_std_error": residual_std_error,
        "se_alpha": se_alpha,
        "se_beta": se_beta,
        "t_alpha": alpha / se_alpha,
        "t_beta": beta / se_beta,
        "x_mean": x_mean,
        "y_mean": y_mean,
    }


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def build_panel(common_end: str, chunk_size: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    adp_meta = series_metadata(ADP_SERIES)
    payems_meta = series_metadata(PAYEMS_SERIES)

    adp_start = adp_meta["observation_start"]
    payems_start = payems_meta["observation_start"]
    observation_end = min_date(adp_meta["observation_end"], payems_meta["observation_end"],)
    common_end = min_date(common_end, observation_end)

    adp_rows = fetch_vintage_observations(
        ADP_SERIES,
        ADP_LAUNCH_VINTAGE,
        "9999-12-31",
        adp_start,
        common_end,
        chunk_size,
    )
    payems_rows = fetch_vintage_observations(
        PAYEMS_SERIES,
        "2010-01-01",
        "9999-12-31",
        "2009-12-01",
        common_end,
        chunk_size,
    )

    adp_changes = first_monthly_change_by_date(adp_rows, ADP_SERIES, "2010-02-01", common_end)
    payems_changes = first_monthly_change_by_date(payems_rows, PAYEMS_SERIES, "2010-02-01", common_end)

    months = sorted(set(adp_changes) & set(payems_changes))
    panel: list[dict[str, Any]] = []
    for target_date in months:
        adp = adp_changes[target_date]
        payems = payems_changes[target_date]
        panel.append(
            {
                "target_date": target_date,
                "adp_release_date": adp["realtime_start"],
                "payems_release_date": payems["realtime_start"],
                "adp_initial": adp["monthly_change_thousands"],
                "payems_initial": payems["monthly_change_thousands"],
                "adp_level": adp["level"],
                "payems_level": payems["level"],
                "adp_source_type": "launch_backfill" if adp["realtime_start"] == ADP_LAUNCH_VINTAGE else "initial_release",
            }
        )

    meta = {
        "adp_observation_start": adp_meta["observation_start"],
        "adp_observation_end": adp_meta["observation_end"],
        "payems_observation_start": payems_meta["observation_start"],
        "payems_observation_end": payems_meta["observation_end"],
        "common_level_end": observation_end,
        "common_change_start": panel[0]["target_date"],
        "common_change_end": panel[-1]["target_date"],
        "adp_launch_vintage": ADP_LAUNCH_VINTAGE,
    }
    return panel, meta


def add_outlier_flags(panel: list[dict[str, Any]], threshold: float) -> None:
    adp_z = robust_z_scores([row["adp_initial"] for row in panel])
    payems_z = robust_z_scores([row["payems_initial"] for row in panel])
    for row, adp_score, payems_score in zip(panel, adp_z, payems_z):
        row["adp_robust_z"] = adp_score
        row["payems_robust_z"] = payems_score
        row["is_outlier"] = abs(adp_score) > threshold or abs(payems_score) > threshold


def regression_row(sample: str, panel: list[dict[str, Any]]) -> dict[str, Any]:
    stats = ols([row["adp_initial"] for row in panel], [row["payems_initial"] for row in panel])
    return {
        "sample": sample,
        "start_month": panel[0]["target_date"],
        "end_month": panel[-1]["target_date"],
        "n": len(panel),
        "equation": "PAYEMS_initial = alpha + beta * ADP_initial",
        **stats,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    script_dir = Path(__file__).resolve().parent
    parser.add_argument("--end-month", default="9999-12-31")
    parser.add_argument("--outlier-threshold", type=float, default=3.5)
    parser.add_argument("--vintage-chunk-size", type=int, default=75)
    parser.add_argument(
        "--output-dir",
        default=str(script_dir / "data" / "adp_payems_max_trimmed_regression"),
    )
    args = parser.parse_args()

    panel, meta = build_panel(args.end_month, args.vintage_chunk_size)
    add_outlier_flags(panel, args.outlier_threshold)
    trimmed = [row for row in panel if not row["is_outlier"]]
    outliers = [row for row in panel if row["is_outlier"]]

    output_dir = Path(args.output_dir)
    panel_fields = [
        "target_date",
        "adp_release_date",
        "payems_release_date",
        "adp_initial",
        "payems_initial",
        "adp_level",
        "payems_level",
        "adp_source_type",
        "adp_robust_z",
        "payems_robust_z",
        "is_outlier",
    ]
    write_csv(output_dir / "monthly_panel_with_outlier_flags.csv", panel, panel_fields)
    write_csv(output_dir / "trimmed_panel.csv", trimmed, panel_fields)
    write_csv(output_dir / "outliers_removed.csv", outliers, panel_fields)

    summary = [regression_row("full_untrimmed", panel), regression_row("trimmed_mad_3p5", trimmed)]
    summary_fields = [
        "sample",
        "start_month",
        "end_month",
        "n",
        "equation",
        "alpha",
        "beta",
        "corr",
        "r2",
        "adj_r2",
        "rmse",
        "residual_std_error",
        "se_alpha",
        "se_beta",
        "t_alpha",
        "t_beta",
        "x_mean",
        "y_mean",
    ]
    write_csv(output_dir / "regression_summary.csv", summary, summary_fields)
    write_csv(output_dir / "metadata.csv", [meta], list(meta.keys()))

    print(f"Wrote outputs to {output_dir}")
    print(f"generated_at={datetime.now().isoformat(timespec='seconds')}")
    print(
        "metadata: "
        f"ADP level {meta['adp_observation_start']}~{meta['adp_observation_end']}; "
        f"PAYEMS level {meta['payems_observation_start']}~{meta['payems_observation_end']}; "
        f"common changes {meta['common_change_start']}~{meta['common_change_end']}"
    )
    print(f"outliers_removed={len(outliers)} threshold=robust_z_abs>{args.outlier_threshold}")
    for row in summary:
        print(
            f"{row['sample']}: n={row['n']}, corr={row['corr']:.6f}, "
            f"r2={row['r2']:.6f}, alpha={row['alpha']:.6f}, beta={row['beta']:.6f}, "
            f"rmse={row['rmse']:.3f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
