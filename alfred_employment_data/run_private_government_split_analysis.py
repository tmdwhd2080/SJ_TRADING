"""Fetch BLS private/government payroll vintages and analyze ADP/private fit.

Outputs are written under:
    data/private_government_split_2020_present

The main modeling panel uses first-available monthly changes for each target
month, which is the closest API-based point-in-time setup for a release-time
forecast exercise.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

import pandas as pd
import statsmodels.api as sm
from statsmodels.stats.diagnostic import acorr_ljungbox


API_BASE = "https://api.stlouisfed.org/fred"

SERIES = {
    "PAYEMS": {
        "label": "BLS total nonfarm payrolls",
        "scale_to_thousands": 1.0,
    },
    "USPRIV": {
        "label": "BLS total private payrolls",
        "scale_to_thousands": 1.0,
    },
    "USGOVT": {
        "label": "BLS government payrolls",
        "scale_to_thousands": 1.0,
    },
    "CES9091000001": {
        "label": "BLS federal government payrolls",
        "scale_to_thousands": 1.0,
    },
    "CES9092000001": {
        "label": "BLS state government payrolls",
        "scale_to_thousands": 1.0,
    },
    "CES9093000001": {
        "label": "BLS local government payrolls",
        "scale_to_thousands": 1.0,
    },
    "ADPMNUSNERSA": {
        "label": "ADP total nonfarm private payroll employment",
        "scale_to_thousands": 0.001,
    },
}

OUTPUT_NAME = "private_government_split_2020_present"


def read_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    raw = path.read_bytes()
    text: str | None = None
    for encoding in ("utf-8-sig", "cp949", "latin-1"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        return {}

    values: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def find_env_file() -> Path | None:
    candidates: list[Path] = []
    for start in (Path.cwd(), Path(__file__).resolve().parent):
        candidates.extend(parent / ".env" for parent in (start, *start.parents))

    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if resolved.exists():
            return resolved
    return None


def get_api_key() -> str:
    key = os.environ.get("FRED_API_KEY")
    if key:
        return key

    env_file = find_env_file()
    if env_file is not None:
        key = read_env_file(env_file).get("FRED_API_KEY")
        if key:
            return key

    raise RuntimeError("FRED_API_KEY was not found in environment or .env")


def fred_get(endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
    query = {
        **params,
        "api_key": get_api_key(),
        "file_type": "json",
    }
    url = f"{API_BASE}/{endpoint}?{urlencode(query)}"
    try:
        with urlopen(url, timeout=60) as response:
            payload = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"FRED API HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"FRED API request failed: {exc}") from exc

    data = json.loads(payload)
    if "error_code" in data:
        raise RuntimeError(f"FRED API error {data['error_code']}: {data.get('error_message')}")
    return data


def chunked(items: list[str], size: int) -> list[list[str]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def fetch_vintage_dates(series_id: str, realtime_start: str, realtime_end: str) -> list[str]:
    data = fred_get(
        "series/vintagedates",
        {
            "series_id": series_id,
            "realtime_start": realtime_start,
            "realtime_end": realtime_end,
            "limit": 10000,
        },
    )
    return list(data.get("vintage_dates", []))


def fetch_series_metadata(series_id: str) -> dict[str, Any]:
    data = fred_get("series", {"series_id": series_id})
    rows = data.get("seriess") or []
    return rows[0] if rows else {"id": series_id}


def clean_value(value: Any) -> float | None:
    if value in ("", ".") or value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def vintage_column_to_date(series_id: str, column_name: str) -> str | None:
    prefix = f"{series_id}_"
    if not column_name.startswith(prefix):
        return None
    raw = column_name.removeprefix(prefix)
    if len(raw) != 8 or not raw.isdigit():
        return None
    return f"{raw[0:4]}-{raw[4:6]}-{raw[6:8]}"


def paged_observations(params: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    limit = 100000
    offset = 0
    while True:
        data = fred_get("series/observations", {**params, "limit": limit, "offset": offset})
        batch = list(data.get("observations", []))
        rows.extend(batch)
        count = int(data.get("count", len(rows)))
        offset += len(batch)
        if not batch or offset >= count:
            break
        time.sleep(0.2)
    return rows


def normalize_observation_rows(series_id: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        if "value" in row:
            value_float = clean_value(row.get("value"))
            if value_float is None:
                continue
            out.append(
                {
                    "series_id": series_id,
                    "date": row.get("date"),
                    "realtime_start": row.get("realtime_start"),
                    "realtime_end": row.get("realtime_end"),
                    "value": value_float,
                }
            )
            continue

        for column, raw_value in row.items():
            vintage_date = vintage_column_to_date(series_id, column)
            if vintage_date is None:
                continue
            value_float = clean_value(raw_value)
            if value_float is None:
                continue
            out.append(
                {
                    "series_id": series_id,
                    "date": row.get("date"),
                    "realtime_start": vintage_date,
                    "realtime_end": "",
                    "value": value_float,
                }
            )
    return out


def fetch_all_vintage_observations(start_date: str, end_date: str, realtime_end: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    all_rows: list[dict[str, Any]] = []
    metadata_rows: list[dict[str, Any]] = []
    fetch_start = f"{int(start_date[:4]) - 1}-12-01"

    for series_id, config in SERIES.items():
        metadata = fetch_series_metadata(series_id)
        metadata_rows.append(
            {
                "series_id": series_id,
                "label": config["label"],
                "title": metadata.get("title"),
                "observation_start": metadata.get("observation_start"),
                "observation_end": metadata.get("observation_end"),
                "frequency": metadata.get("frequency"),
                "units": metadata.get("units"),
                "seasonal_adjustment": metadata.get("seasonal_adjustment"),
                "last_updated": metadata.get("last_updated"),
            }
        )

        vintages = fetch_vintage_dates(series_id, start_date, realtime_end)
        if not vintages:
            continue

        params_base = {
            "series_id": series_id,
            "observation_start": fetch_start,
            "observation_end": end_date,
            "sort_order": "asc",
            "output_type": 2,
        }
        for vintage_chunk in chunked(vintages, 50):
            rows = paged_observations({**params_base, "vintage_dates": ",".join(vintage_chunk)})
            all_rows.extend(normalize_observation_rows(series_id, rows))
            time.sleep(0.2)

    obs = pd.DataFrame(all_rows)
    if not obs.empty:
        obs["date"] = pd.to_datetime(obs["date"])
        obs["realtime_start"] = pd.to_datetime(obs["realtime_start"])
        obs = obs.sort_values(["series_id", "realtime_start", "date"])
    return obs, pd.DataFrame(metadata_rows)


def monthly_changes_from_vintages(obs: pd.DataFrame, start_date: str, end_date: str) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)

    for (series_id, vintage), group in obs.groupby(["series_id", "realtime_start"], sort=True):
        sorted_group = group.sort_values("date").copy()
        sorted_group["monthly_change"] = sorted_group["value"].diff()
        sorted_group = sorted_group[(sorted_group["date"] >= start) & (sorted_group["date"] <= end)]
        scale = SERIES[series_id]["scale_to_thousands"]
        for item in sorted_group.dropna(subset=["monthly_change"]).itertuples(index=False):
            rows.append(
                {
                    "series_id": series_id,
                    "target_date": item.date,
                    "vintage_date": item.realtime_start,
                    "level": item.value,
                    "monthly_change_thousands": item.monthly_change * scale,
                }
            )
    changes = pd.DataFrame(rows)
    if not changes.empty:
        changes = changes.sort_values(["series_id", "target_date", "vintage_date"])
    return changes


def first_available_changes(changes: pd.DataFrame) -> pd.DataFrame:
    if changes.empty:
        return changes.copy()
    return (
        changes.sort_values(["series_id", "target_date", "vintage_date"])
        .drop_duplicates(["series_id", "target_date"], keep="first")
        .reset_index(drop=True)
    )


def latest_available_changes(changes: pd.DataFrame) -> pd.DataFrame:
    if changes.empty:
        return changes.copy()
    return (
        changes.sort_values(["series_id", "target_date", "vintage_date"])
        .drop_duplicates(["series_id", "target_date"], keep="last")
        .reset_index(drop=True)
    )


def pivot_changes(changes: pd.DataFrame, suffix: str) -> pd.DataFrame:
    values = changes.pivot(index="target_date", columns="series_id", values="monthly_change_thousands")
    vintages = changes.pivot(index="target_date", columns="series_id", values="vintage_date")
    values.columns = [f"{column}_{suffix}_change_k" for column in values.columns]
    vintages.columns = [f"{column}_{suffix}_vintage_date" for column in vintages.columns]
    panel = values.join(vintages).reset_index()
    return panel.sort_values("target_date")


def add_identity_checks(panel: pd.DataFrame, suffix: str) -> pd.DataFrame:
    out = panel.copy()
    payems = f"PAYEMS_{suffix}_change_k"
    private = f"USPRIV_{suffix}_change_k"
    govt = f"USGOVT_{suffix}_change_k"
    if {payems, private, govt}.issubset(out.columns):
        out[f"private_plus_government_{suffix}_change_k"] = out[private] + out[govt]
        out[f"payems_minus_components_{suffix}_k"] = out[payems] - out[f"private_plus_government_{suffix}_change_k"]
    return out


def fit_ols(y: pd.Series, x: pd.DataFrame):
    return sm.OLS(y, sm.add_constant(x, has_constant="add")).fit()


def regression_rows(model, model_name: str, equation: str, start: str, end: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    rmse = float((model.resid.pow(2).mean()) ** 0.5)
    mae = float(model.resid.abs().mean())
    for term in model.params.index:
        rows.append(
            {
                "model": model_name,
                "equation": equation,
                "term": "intercept" if term == "const" else term,
                "coefficient": model.params[term],
                "std_error": model.bse[term],
                "t_stat": model.tvalues[term],
                "p_value": model.pvalues[term],
                "n": int(model.nobs),
                "r2": model.rsquared,
                "adj_r2": model.rsquared_adj,
                "rmse": rmse,
                "mae": mae,
                "start_target_date": start,
                "end_target_date": end,
            }
        )
    return rows


def analyze_adp_private(panel: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    needed = ["target_date", "ADPMNUSNERSA_initial_change_k", "USPRIV_initial_change_k"]
    data = panel.dropna(subset=needed).copy()
    data = data.sort_values("target_date")
    model = fit_ols(data["USPRIV_initial_change_k"], data[["ADPMNUSNERSA_initial_change_k"]])
    data["predicted_uspriv_initial_change_k"] = model.predict(
        sm.add_constant(data[["ADPMNUSNERSA_initial_change_k"]], has_constant="add")
    )
    data["error_actual_minus_predicted_k"] = data["USPRIV_initial_change_k"] - data["predicted_uspriv_initial_change_k"]
    corr = data[["ADPMNUSNERSA_initial_change_k", "USPRIV_initial_change_k"]].corr().iloc[0, 1]
    summary = pd.DataFrame(
        regression_rows(
            model,
            "adp_to_bls_private_initial",
            "USPRIV_initial_change_k = alpha + beta * ADP_initial_change_k",
            data["target_date"].iloc[0].strftime("%Y-%m-%d"),
            data["target_date"].iloc[-1].strftime("%Y-%m-%d"),
        )
    )
    summary["correlation"] = corr
    return data, summary


def analyze_government_inertia(panel: pd.DataFrame, suffix: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    source_col = f"USGOVT_{suffix}_change_k"
    component_cols = [
        f"CES9091000001_{suffix}_change_k",
        f"CES9092000001_{suffix}_change_k",
        f"CES9093000001_{suffix}_change_k",
    ]
    data = panel[["target_date", source_col, *[col for col in component_cols if col in panel.columns]]].copy()
    data = data.dropna(subset=["target_date", source_col]).sort_values("target_date")
    data["govt_lag1_k"] = data[source_col].shift(1)
    data["govt_lag2_k"] = data[source_col].shift(2)
    data["govt_lag3_k"] = data[source_col].shift(3)
    data["govt_lag3_avg_k"] = data[source_col].shift(1).rolling(3).mean()

    rows: list[dict[str, Any]] = []
    for lag in [1, 2, 3]:
        lag_col = f"govt_lag{lag}_k"
        corr_data = data[[source_col, lag_col]].dropna()
        rows.append(
            {
                "series": "USGOVT",
                "vintage_type": suffix,
                "test": f"autocorrelation_lag_{lag}",
                "value": corr_data[source_col].corr(corr_data[lag_col]),
                "n": len(corr_data),
            }
        )

    for model_name, feature_cols in [
        ("ar1", ["govt_lag1_k"]),
        ("ar3", ["govt_lag1_k", "govt_lag2_k", "govt_lag3_k"]),
        ("lag1_plus_lag3_avg", ["govt_lag1_k", "govt_lag3_avg_k"]),
    ]:
        model_data = data.dropna(subset=[source_col, *feature_cols]).copy()
        if len(model_data) < len(feature_cols) + 4:
            continue
        model = fit_ols(model_data[source_col], model_data[feature_cols])
        rows.extend(
            regression_rows(
                model,
                f"government_{suffix}_{model_name}",
                f"{source_col} = alpha + " + " + ".join(feature_cols),
                model_data["target_date"].iloc[0].strftime("%Y-%m-%d"),
                model_data["target_date"].iloc[-1].strftime("%Y-%m-%d"),
            )
        )

    lb_data = data[source_col].dropna()
    if len(lb_data) >= 12:
        lb = acorr_ljungbox(lb_data, lags=[3, 6, 12], return_df=True)
        for lag, item in lb.iterrows():
            rows.append(
                {
                    "series": "USGOVT",
                    "vintage_type": suffix,
                    "test": f"ljung_box_lag_{lag}",
                    "value": item["lb_stat"],
                    "p_value": item["lb_pvalue"],
                    "n": len(lb_data),
                }
            )

    return data, pd.DataFrame(rows)


def write_csv(path: Path, rows: list[dict[str, Any]] | pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(rows, pd.DataFrame):
        rows.to_csv(path, index=False, encoding="utf-8-sig")
        return
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def format_dates(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for column in out.columns:
        if "date" in column:
            out[column] = pd.to_datetime(out[column], errors="coerce").dt.strftime("%Y-%m-%d")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-date", default="2020-01-01")
    parser.add_argument("--end-date", default=f"{date.today().year}-12-31")
    parser.add_argument("--realtime-end", default="9999-12-31")
    parser.add_argument(
        "--output-dir",
        default=str(Path(__file__).resolve().parent / "data" / OUTPUT_NAME),
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    obs, metadata = fetch_all_vintage_observations(args.start_date, args.end_date, args.realtime_end)
    changes = monthly_changes_from_vintages(obs, args.start_date, args.end_date)
    initial_changes = first_available_changes(changes)
    latest_changes = latest_available_changes(changes)

    initial_panel = add_identity_checks(pivot_changes(initial_changes, "initial"), "initial")
    latest_panel = add_identity_checks(pivot_changes(latest_changes, "latest"), "latest")
    model_panel = initial_panel.merge(latest_panel, on="target_date", how="outer").sort_values("target_date")

    private_panel, private_summary = analyze_adp_private(model_panel)
    govt_initial_panel, govt_initial_summary = analyze_government_inertia(model_panel, "initial")
    govt_latest_panel, govt_latest_summary = analyze_government_inertia(model_panel, "latest")
    govt_summary = pd.concat([govt_initial_summary, govt_latest_summary], ignore_index=True)

    write_csv(output_dir / "series_metadata.csv", metadata)
    write_csv(output_dir / "all_vintage_monthly_changes.csv", format_dates(changes))
    write_csv(output_dir / "initial_monthly_changes.csv", format_dates(initial_changes))
    write_csv(output_dir / "latest_monthly_changes.csv", format_dates(latest_changes))
    write_csv(output_dir / "monthly_split_model_panel.csv", format_dates(model_panel))
    write_csv(output_dir / "adp_to_private_regression_panel.csv", format_dates(private_panel))
    write_csv(output_dir / "adp_to_private_regression_summary.csv", private_summary)
    write_csv(output_dir / "government_inertia_panel_initial.csv", format_dates(govt_initial_panel))
    write_csv(output_dir / "government_inertia_panel_latest.csv", format_dates(govt_latest_panel))
    write_csv(output_dir / "government_inertia_summary.csv", govt_summary)

    model_row = private_summary[private_summary["term"] == "ADPMNUSNERSA_initial_change_k"].iloc[0]
    intercept = private_summary[private_summary["term"] == "intercept"].iloc[0]["coefficient"]
    print(f"Wrote outputs to {output_dir}")
    print(f"ADP/private sample n={int(model_row['n'])}, corr={model_row['correlation']:.6f}")
    print(
        "USPRIV_initial_change_k = "
        f"{intercept:.6f} + {model_row['coefficient']:.6f} * ADP_initial_change_k; "
        f"r2={model_row['r2']:.6f}, adj_r2={model_row['adj_r2']:.6f}, "
        f"rmse={model_row['rmse']:.3f}"
    )

    for suffix in ["initial", "latest"]:
        ar1 = govt_summary[
            (govt_summary["vintage_type"] == suffix)
            & (govt_summary["model"] == f"government_{suffix}_ar1")
            & (govt_summary["term"] == "govt_lag1_k")
        ]
        ac1 = govt_summary[
            (govt_summary["vintage_type"] == suffix)
            & (govt_summary["test"] == "autocorrelation_lag_1")
        ]
        if not ar1.empty and not ac1.empty:
            print(
                f"government {suffix}: lag1_corr={ac1.iloc[0]['value']:.6f}, "
                f"AR1_beta={ar1.iloc[0]['coefficient']:.6f}, "
                f"p={ar1.iloc[0]['p_value']:.6f}, r2={ar1.iloc[0]['r2']:.6f}"
            )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
