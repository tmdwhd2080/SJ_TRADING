"""Build a simple NFP initial-release regression panel and model.

Target:
    PAYEMS initial monthly change, target month January 2023 onward.

Features:
    1. ADP initial monthly change for the same target month.
    2. Latest Government Job Openings available before the PAYEMS release date.
    3. Monthly average of weekly initial claims, using final/latest value for all
       weeks except the last week in the target month, which uses its initial value.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import math
from pathlib import Path
from typing import Any


ADP = "ADP_monthly_change_thousands"
PAYEMS = "PAYEMS_monthly_change_thousands"
ICSA = "ICSA_weekly_level_count"
GOV_OPENINGS = "JTS9000JOL"


def load_fetch_module(script_dir: Path) -> Any:
    module_path = script_dir / "fetch_alfred_employment_data.py"
    spec = importlib.util.spec_from_file_location("fetch_alfred_employment_data", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def month_start(date_text: str) -> str:
    return f"{date_text[:7]}-01"


def fetch_government_openings(fetch_module: Any, start_date: str, end_date: str) -> list[dict[str, Any]]:
    vintage_rows = fetch_module.fetch_vintage_dates(GOV_OPENINGS, start_date, "9999-12-31")
    vintage_dates = [row["vintage_date"] for row in vintage_rows]
    if not vintage_dates:
        return []

    rows = fetch_module.normalize_observations(
        GOV_OPENINGS,
        fetch_module.paged_observations(
            {
                "series_id": GOV_OPENINGS,
                "observation_start": start_date,
                "observation_end": end_date,
                "sort_order": "asc",
                "output_type": 2,
                "vintage_dates": ",".join(vintage_dates),
            }
        ),
    )
    return rows


def latest_gov_openings_before_release(
    gov_rows: list[dict[str, Any]],
    release_date: str,
) -> tuple[float | None, str | None, str | None]:
    candidates = [
        row
        for row in gov_rows
        if str(row["realtime_start"]) < release_date and str(row["date"]) <= release_date
    ]
    if not candidates:
        return None, None, None

    candidates.sort(key=lambda row: (str(row["date"]), str(row["realtime_start"])))
    selected = candidates[-1]
    return float(selected["value_float"]), str(selected["date"]), str(selected["realtime_start"])


def initial_values(rows: list[dict[str, str]]) -> dict[tuple[str, str], dict[str, str]]:
    out: dict[tuple[str, str], dict[str, str]] = {}
    for row in rows:
        out[(row["indicator"], row["target_date"])] = row
    return out


def latest_revised_claims(initial_rows: list[dict[str, str]], revision_rows: list[dict[str, str]]) -> dict[str, float]:
    latest: dict[str, tuple[str, float]] = {}
    for row in initial_rows:
        if row["indicator"] != ICSA:
            continue
        latest[row["target_date"]] = (row["release_date"], float(row["published_value"]))

    revisions = [row for row in revision_rows if row["indicator"] == ICSA]
    revisions.sort(key=lambda row: (row["target_date"], row["release_date"]))
    for row in revisions:
        target = row["target_date"]
        if target not in latest or row["release_date"] >= latest[target][0]:
            latest[target] = (row["release_date"], float(row["revised_value"]))

    return {target: value for target, (_, value) in latest.items()}


def claims_average_feature(
    month: str,
    initial_rows: list[dict[str, str]],
    latest_claims: dict[str, float],
) -> tuple[float | None, int, str | None]:
    claims_initial = {
        row["target_date"]: float(row["published_value"])
        for row in initial_rows
        if row["indicator"] == ICSA and month_start(row["target_date"]) == month
    }
    weeks = sorted(claims_initial)
    if not weeks:
        return None, 0, None

    last_week = weeks[-1]
    values: list[float] = []
    for week in weeks:
        if week == last_week:
            values.append(claims_initial[week])
        else:
            values.append(latest_claims.get(week, claims_initial[week]))
    return sum(values) / len(values), len(values), last_week


def build_panel(
    initial_rows: list[dict[str, str]],
    revision_rows: list[dict[str, str]],
    gov_rows: list[dict[str, Any]],
    start_month: str,
    end_month: str,
) -> list[dict[str, Any]]:
    initial = initial_values(initial_rows)
    latest_claims = latest_revised_claims(initial_rows, revision_rows)
    months = sorted(
        target
        for indicator, target in initial
        if indicator == PAYEMS and start_month <= target <= end_month
    )

    panel: list[dict[str, Any]] = []
    for month in months:
        payems_row = initial.get((PAYEMS, month))
        adp_row = initial.get((ADP, month))
        if payems_row is None or adp_row is None:
            continue

        claims_avg, claims_week_count, claims_last_week = claims_average_feature(month, initial_rows, latest_claims)
        gov_openings, gov_ref_month, gov_vintage = latest_gov_openings_before_release(
            gov_rows,
            payems_row["release_date"],
        )
        if claims_avg is None or gov_openings is None:
            continue

        panel.append(
            {
                "target_month": month,
                "payems_release_date": payems_row["release_date"],
                "payems_initial_change_thousands": float(payems_row["published_value"]),
                "adp_release_date": adp_row["release_date"],
                "adp_initial_change_thousands": float(adp_row["published_value"]),
                "gov_job_openings_available_thousands": gov_openings,
                "gov_job_openings_reference_month": gov_ref_month,
                "gov_job_openings_vintage_date": gov_vintage,
                "claims_avg_mixed_count": claims_avg,
                "claims_week_count": claims_week_count,
                "claims_last_week_initial_target": claims_last_week,
            }
        )
    return panel


def transpose(matrix: list[list[float]]) -> list[list[float]]:
    return [list(column) for column in zip(*matrix)]


def matmul(a: list[list[float]], b: list[list[float]]) -> list[list[float]]:
    return [[sum(x * y for x, y in zip(row, col)) for col in transpose(b)] for row in a]


def matvec(a: list[list[float]], x: list[float]) -> list[float]:
    return [sum(value * coef for value, coef in zip(row, x)) for row in a]


def invert(matrix: list[list[float]]) -> list[list[float]]:
    n = len(matrix)
    aug = [row[:] + [1.0 if i == j else 0.0 for j in range(n)] for i, row in enumerate(matrix)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda row: abs(aug[row][col]))
        if abs(aug[pivot][col]) < 1e-12:
            raise RuntimeError("Matrix is singular")
        aug[col], aug[pivot] = aug[pivot], aug[col]
        divisor = aug[col][col]
        aug[col] = [value / divisor for value in aug[col]]
        for row in range(n):
            if row == col:
                continue
            factor = aug[row][col]
            aug[row] = [value - factor * pivot_value for value, pivot_value in zip(aug[row], aug[col])]
    return [row[n:] for row in aug]


def ols_fit(rows: list[dict[str, Any]], feature_names: list[str], target_name: str) -> dict[str, Any]:
    x = [[1.0] + [float(row[name]) for name in feature_names] for row in rows]
    y = [float(row[target_name]) for row in rows]
    xt = transpose(x)
    xtx = matmul(xt, x)
    xtx_inv = invert(xtx)
    xty = [sum(row[i] * y_value for row, y_value in zip(x, y)) for i in range(len(x[0]))]
    beta = matvec(xtx_inv, xty)
    fitted = matvec(x, beta)
    residuals = [actual - pred for actual, pred in zip(y, fitted)]
    y_mean = sum(y) / len(y)
    sse = sum(resid * resid for resid in residuals)
    sst = sum((actual - y_mean) ** 2 for actual in y)
    df = len(y) - len(beta)
    mse = sse / df
    std_errors = [math.sqrt(mse * xtx_inv[i][i]) for i in range(len(beta))]
    return {
        "coef_names": ["intercept"] + feature_names,
        "coefs": beta,
        "std_errors": std_errors,
        "t_stats": [coef / se for coef, se in zip(beta, std_errors)],
        "r2": 1 - sse / sst,
        "adj_r2": 1 - (1 - (1 - sse / sst)) * (len(y) - 1) / df,
        "rmse": math.sqrt(sse / len(y)),
        "residual_std_error": math.sqrt(mse),
        "n": len(y),
        "fitted": fitted,
        "residuals": residuals,
    }


def predict(rows: list[dict[str, Any]], feature_names: list[str], coefs: list[float]) -> list[float]:
    x = [[1.0] + [float(row[name]) for name in feature_names] for row in rows]
    return matvec(x, coefs)


def metrics(rows: list[dict[str, Any]], predictions: list[float], target_name: str) -> dict[str, float]:
    actuals = [float(row[target_name]) for row in rows]
    errors = [actual - pred for actual, pred in zip(actuals, predictions)]
    mean_actual = sum(actuals) / len(actuals)
    sse = sum(error * error for error in errors)
    sst = sum((actual - mean_actual) ** 2 for actual in actuals)
    return {
        "n": float(len(rows)),
        "rmse": math.sqrt(sse / len(rows)),
        "mae": sum(abs(error) for error in errors) / len(rows),
        "r2": 1 - sse / sst if sst != 0 else float("nan"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    script_dir = Path(__file__).resolve().parent
    default_input_dir = script_dir / "data" / "employment_events_2022_2026"
    default_output_dir = script_dir / "data" / "nfp_multivariate_model_2023-01_2026-06"
    parser.add_argument("--initial-file", default=str(default_input_dir / "initial_releases.csv"))
    parser.add_argument("--revision-file", default=str(default_input_dir / "revision_events.csv"))
    parser.add_argument("--start-month", default="2023-01-01")
    parser.add_argument("--end-month", default="2026-06-01")
    parser.add_argument("--train-end", default="2025-12-01")
    parser.add_argument("--output-dir", default=str(default_output_dir))
    args = parser.parse_args()

    initial_rows = read_csv(Path(args.initial_file))
    revision_rows = read_csv(Path(args.revision_file))
    fetch_module = load_fetch_module(script_dir)
    gov_rows = fetch_government_openings(fetch_module, "2022-01-01", args.end_month)
    panel = build_panel(initial_rows, revision_rows, gov_rows, args.start_month, args.end_month)

    train = [row for row in panel if row["target_month"] <= args.train_end]
    test = [row for row in panel if row["target_month"] > args.train_end]

    target = "payems_initial_change_thousands"
    features = [
        "adp_initial_change_thousands",
        "gov_job_openings_available_thousands",
        "claims_avg_mixed_count",
    ]
    model = ols_fit(train, features, target)
    train_predictions = predict(train, features, model["coefs"])
    test_predictions = predict(test, features, model["coefs"])

    prediction_rows: list[dict[str, Any]] = []
    for split, split_rows, predictions in (("train", train, train_predictions), ("test", test, test_predictions)):
        for row, pred in zip(split_rows, predictions):
            actual = float(row[target])
            prediction_rows.append(
                {
                    "split": split,
                    "target_month": row["target_month"],
                    "actual_payems_initial_change_thousands": actual,
                    "predicted_payems_initial_change_thousands": pred,
                    "error_actual_minus_pred": actual - pred,
                }
            )

    train_metrics = metrics(train, train_predictions, target)
    test_metrics = metrics(test, test_predictions, target)
    coefficient_rows = [
        {
            "term": name,
            "coefficient": coef,
            "std_error": se,
            "t_stat": t_stat,
            "train_n": model["n"],
            "train_r2": model["r2"],
            "train_adj_r2": model["adj_r2"],
            "train_rmse": model["rmse"],
            "test_n": test_metrics["n"],
            "test_r2": test_metrics["r2"],
            "test_rmse": test_metrics["rmse"],
            "test_mae": test_metrics["mae"],
        }
        for name, coef, se, t_stat in zip(
            model["coef_names"],
            model["coefs"],
            model["std_errors"],
            model["t_stats"],
        )
    ]

    output_dir = Path(args.output_dir)
    write_csv(
        output_dir / "model_panel.csv",
        panel,
        [
            "target_month",
            "payems_release_date",
            "payems_initial_change_thousands",
            "adp_release_date",
            "adp_initial_change_thousands",
            "gov_job_openings_available_thousands",
            "gov_job_openings_reference_month",
            "gov_job_openings_vintage_date",
            "claims_avg_mixed_count",
            "claims_week_count",
            "claims_last_week_initial_target",
        ],
    )
    write_csv(
        output_dir / "regression_coefficients.csv",
        coefficient_rows,
        [
            "term",
            "coefficient",
            "std_error",
            "t_stat",
            "train_n",
            "train_r2",
            "train_adj_r2",
            "train_rmse",
            "test_n",
            "test_r2",
            "test_rmse",
            "test_mae",
        ],
    )
    write_csv(
        output_dir / "predictions.csv",
        prediction_rows,
        [
            "split",
            "target_month",
            "actual_payems_initial_change_thousands",
            "predicted_payems_initial_change_thousands",
            "error_actual_minus_pred",
        ],
    )

    print(f"Wrote panel to {output_dir / 'model_panel.csv'}")
    print(f"Wrote coefficients to {output_dir / 'regression_coefficients.csv'}")
    print(f"Wrote predictions to {output_dir / 'predictions.csv'}")
    print(f"train_n={len(train)} test_n={len(test)}")
    print(f"train_r2={model['r2']:.6f} train_rmse={model['rmse']:.3f}")
    print(f"test_r2={test_metrics['r2']:.6f} test_rmse={test_metrics['rmse']:.3f} test_mae={test_metrics['mae']:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
