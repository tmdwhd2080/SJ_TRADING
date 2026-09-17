"""Analyze initial-release correlations for PAYEMS, ADP, and initial claims."""

from __future__ import annotations

import argparse
import csv
import math
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any


PAYEMS = "PAYEMS_monthly_change_thousands"
ADP = "ADP_monthly_change_thousands"
ICSA = "ICSA_weekly_level_count"

PANEL_FIELDS = [
    "target_month",
    "year",
    "payems_initial_change_thousands",
    "adp_initial_change_thousands",
    "icsa_initial_avg_count",
    "icsa_week_count",
]

CORR_FIELDS = [
    "period",
    "n_months",
    "payems_adp_corr",
    "payems_icsa_corr",
    "adp_icsa_corr",
]


def parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def month_start(value: str) -> str:
    parsed = parse_date(value)
    return f"{parsed.year:04d}-{parsed.month:02d}-01"


def read_initial_releases(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def as_float(value: str) -> float:
    return float(value)


def build_monthly_panel(rows: list[dict[str, str]], start_month: str, end_month: str) -> list[dict[str, Any]]:
    monthly_values: dict[tuple[str, str], float] = {}
    icsa_values: dict[str, list[float]] = defaultdict(list)

    for row in rows:
        indicator = row["indicator"]
        target_month = month_start(row["target_date"])
        if target_month < start_month or target_month > end_month:
            continue

        if indicator in (PAYEMS, ADP):
            monthly_values[(indicator, target_month)] = as_float(row["published_value"])
        elif indicator == ICSA:
            icsa_values[target_month].append(as_float(row["published_value"]))

    months = sorted(
        {
            month
            for _, month in monthly_values
            if (PAYEMS, month) in monthly_values and (ADP, month) in monthly_values and month in icsa_values
        }
    )

    panel: list[dict[str, Any]] = []
    for month in months:
        claims = icsa_values[month]
        panel.append(
            {
                "target_month": month,
                "year": month[:4],
                "payems_initial_change_thousands": monthly_values[(PAYEMS, month)],
                "adp_initial_change_thousands": monthly_values[(ADP, month)],
                "icsa_initial_avg_count": sum(claims) / len(claims),
                "icsa_week_count": len(claims),
            }
        )
    return panel


def pearson(xs: list[float], ys: list[float]) -> float | str:
    if len(xs) != len(ys) or len(xs) < 2:
        return ""

    x_mean = sum(xs) / len(xs)
    y_mean = sum(ys) / len(ys)
    x_diffs = [item - x_mean for item in xs]
    y_diffs = [item - y_mean for item in ys]
    numerator = sum(x * y for x, y in zip(x_diffs, y_diffs))
    x_denominator = math.sqrt(sum(x * x for x in x_diffs))
    y_denominator = math.sqrt(sum(y * y for y in y_diffs))
    denominator = x_denominator * y_denominator
    if denominator == 0:
        return ""
    return numerator / denominator


def corr_row(period: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    payems = [float(row["payems_initial_change_thousands"]) for row in rows]
    adp = [float(row["adp_initial_change_thousands"]) for row in rows]
    icsa = [float(row["icsa_initial_avg_count"]) for row in rows]
    return {
        "period": period,
        "n_months": len(rows),
        "payems_adp_corr": pearson(payems, adp),
        "payems_icsa_corr": pearson(payems, icsa),
        "adp_icsa_corr": pearson(adp, icsa),
    }


def correlation_summary(panel: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = [corr_row("overall", panel)]
    years = sorted({row["year"] for row in panel})
    for year in years:
        year_rows = [row for row in panel if row["year"] == year]
        out.append(corr_row(year, year_rows))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    script_dir = Path(__file__).resolve().parent
    default_input = script_dir / "data" / "employment_events_2022_2026" / "initial_releases.csv"
    default_output_dir = script_dir / "data" / "initial_correlation_analysis_2022-09_2026-06"
    parser.add_argument("--input-file", default=str(default_input))
    parser.add_argument("--start-month", default="2022-09-01")
    parser.add_argument("--end-month", default="2026-06-01")
    parser.add_argument("--output-dir", default=str(default_output_dir))
    args = parser.parse_args()

    rows = read_initial_releases(Path(args.input_file))
    panel = build_monthly_panel(rows, args.start_month, args.end_month)
    summary = correlation_summary(panel)

    output_dir = Path(args.output_dir)
    panel_file = output_dir / "initial_monthly_panel.csv"
    summary_file = output_dir / "initial_correlations.csv"
    write_csv(panel_file, panel, PANEL_FIELDS)
    write_csv(summary_file, summary, CORR_FIELDS)

    print(f"Wrote monthly panel to {panel_file}")
    print(f"Wrote correlations to {summary_file}")
    print(f"months: {len(panel)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
