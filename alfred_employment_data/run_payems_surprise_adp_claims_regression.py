"""Regress PAYEMS surprise on ADP actual and mixed initial-claims average.

Target:
    PAYEMS surprise = PAYEMS actual/initial value - PAYEMS consensus.

Features:
    1. ADP actual monthly change for the same target month.
    2. Average of weekly initial claims in the target month, using final/latest
       revised values for all weeks except the last week, which uses initial.

Rows are dropped if any model input is missing.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
import statsmodels.api as sm

from run_nfp_twofactor_regression import claims_average_feature, latest_revised_claims, read_csv


ICSA = "ICSA_weekly_level_count"


def default_desktop_path(filename: str) -> Path:
    return Path.home() / "Desktop" / filename


def read_adp_actual(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, encoding="utf-8-sig")
    required = {"target_date", "Real_value"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"{path} is missing required columns: {sorted(missing)}")

    out = df.copy()
    out["target_date"] = pd.to_datetime(out["target_date"], errors="coerce")
    out["Real_value"] = pd.to_numeric(out["Real_value"], errors="coerce")
    if "release_date" in out.columns:
        out["release_date"] = pd.to_datetime(out["release_date"], errors="coerce")

    keep = ["target_date", "Real_value"]
    if "release_date" in out.columns:
        keep.insert(1, "release_date")
    out = out[keep].dropna(subset=["target_date", "Real_value"])
    out = out.rename(columns={"release_date": "adp_release_date", "Real_value": "adp_actual"})
    out = out.sort_values("target_date").drop_duplicates("target_date", keep="last")
    return out


def read_payems_surprise(path: Path) -> pd.DataFrame:
    df = pd.read_excel(path) if path.suffix.lower() in {".xlsx", ".xls"} else pd.read_csv(path, encoding="utf-8-sig")
    required = {"target_date", "Real_value", "Consensus"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"{path} is missing required columns: {sorted(missing)}")

    out = df.copy()
    out["target_date"] = pd.to_datetime(out["target_date"], errors="coerce")
    out["Real_value"] = pd.to_numeric(out["Real_value"], errors="coerce")
    out["Consensus"] = pd.to_numeric(out["Consensus"], errors="coerce")
    if "release_date" in out.columns:
        out["release_date"] = pd.to_datetime(out["release_date"], errors="coerce")

    keep = ["target_date", "Real_value", "Consensus"]
    if "release_date" in out.columns:
        keep.insert(1, "release_date")
    out = out[keep].dropna(subset=["target_date", "Real_value", "Consensus"])
    out = out.rename(
        columns={
            "release_date": "payems_release_date",
            "Real_value": "payems_actual",
            "Consensus": "payems_consensus",
        }
    )
    out["payems_surprise"] = out["payems_actual"] - out["payems_consensus"]
    out = out.sort_values("target_date").drop_duplicates("target_date", keep="last")
    return out


def month_text(value: pd.Timestamp) -> str:
    return value.strftime("%Y-%m-01")


def build_claims_features(
    initial_file: Path,
    revision_file: Path,
    months: list[pd.Timestamp],
) -> pd.DataFrame:
    initial_rows = read_csv(initial_file)
    revision_rows = read_csv(revision_file)
    latest_claims = latest_revised_claims(initial_rows, revision_rows)

    rows: list[dict[str, object]] = []
    for month in months:
        month_str = month_text(month)
        claims_avg, week_count, last_week = claims_average_feature(month_str, initial_rows, latest_claims)
        if claims_avg is None:
            continue
        rows.append(
            {
                "target_date": month,
                "claims_avg_mixed_count": claims_avg,
                "claims_avg_mixed_thousands": claims_avg / 1000.0,
                "claims_week_count": week_count,
                "claims_last_week_initial_target": last_week,
            }
        )
    return pd.DataFrame(rows)


def format_dates(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for column in out.columns:
        if column.endswith("_date") or column == "target_date":
            out[column] = pd.to_datetime(out[column]).dt.strftime("%Y-%m-%d")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    script_dir = Path(__file__).resolve().parent
    default_events_dir = script_dir / "data" / "employment_events_2022_2026"
    parser.add_argument("--adp-file", default=str(default_desktop_path("ADP.csv")))
    parser.add_argument("--payems-file", default=str(default_desktop_path("PAYEMS.xlsx")))
    parser.add_argument("--initial-file", default=str(default_events_dir / "initial_releases.csv"))
    parser.add_argument("--revision-file", default=str(default_events_dir / "revision_events.csv"))
    parser.add_argument(
        "--output-dir",
        default=str(script_dir / "data" / "payems_surprise_adp_claims_regression"),
    )
    args = parser.parse_args()

    adp = read_adp_actual(Path(args.adp_file))
    payems = read_payems_surprise(Path(args.payems_file))
    base = payems.merge(adp, on="target_date", how="inner")
    claims = build_claims_features(Path(args.initial_file), Path(args.revision_file), list(base["target_date"]))
    panel = base.merge(claims, on="target_date", how="inner")
    panel = panel.dropna(
        subset=[
            "payems_surprise",
            "adp_actual",
            "claims_avg_mixed_thousands",
        ]
    ).sort_values("target_date")

    if len(panel) < 4:
        raise RuntimeError(f"Not enough complete rows to run regression: {len(panel)}")

    target = panel["payems_surprise"]
    features = panel[["adp_actual", "claims_avg_mixed_thousands"]]
    model = sm.OLS(target, sm.add_constant(features)).fit()
    predictions = model.predict(sm.add_constant(features))
    panel = panel.copy()
    panel["predicted_payems_surprise"] = predictions
    panel["error_actual_minus_predicted"] = panel["payems_surprise"] - panel["predicted_payems_surprise"]

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    panel_path = output_dir / "model_panel.csv"
    format_dates(panel).to_csv(panel_path, index=False, encoding="utf-8-sig")

    coefficient_rows = []
    for term in ["const", "adp_actual", "claims_avg_mixed_thousands"]:
        coefficient_rows.append(
            {
                "term": "intercept" if term == "const" else term,
                "coefficient": model.params[term],
                "std_error": model.bse[term],
                "t_stat": model.tvalues[term],
                "p_value": model.pvalues[term],
                "n": int(model.nobs),
                "r2": model.rsquared,
                "adj_r2": model.rsquared_adj,
                "rmse": float((model.resid.pow(2).mean()) ** 0.5),
                "mae": float(model.resid.abs().mean()),
                "start_target_date": panel["target_date"].iloc[0].strftime("%Y-%m-%d"),
                "end_target_date": panel["target_date"].iloc[-1].strftime("%Y-%m-%d"),
            }
        )
    coef_path = output_dir / "regression_coefficients.csv"
    pd.DataFrame(coefficient_rows).to_csv(coef_path, index=False, encoding="utf-8-sig")

    corr_path = output_dir / "correlation_matrix.csv"
    panel[["payems_surprise", "adp_actual", "claims_avg_mixed_thousands"]].corr().to_csv(
        corr_path, encoding="utf-8-sig"
    )

    print(f"Wrote panel to {panel_path}")
    print(f"Wrote coefficients to {coef_path}")
    print(f"Wrote correlations to {corr_path}")
    print(
        f"sample={panel['target_date'].iloc[0].strftime('%Y-%m-%d')}~"
        f"{panel['target_date'].iloc[-1].strftime('%Y-%m-%d')}, n={int(model.nobs)}"
    )
    print(
        "equation: PAYEMS_surprise = "
        f"{model.params['const']:.6f} "
        f"+ {model.params['adp_actual']:.6f} * ADP_actual "
        f"+ {model.params['claims_avg_mixed_thousands']:.6f} * ICSA_avg_mixed_1000"
    )
    print(f"r2={model.rsquared:.6f}, adj_r2={model.rsquared_adj:.6f}, rmse={((model.resid.pow(2).mean()) ** 0.5):.3f}")
    for term in ["const", "adp_actual", "claims_avg_mixed_thousands"]:
        print(
            f"{term}: coef={model.params[term]:.6f}, se={model.bse[term]:.6f}, "
            f"t={model.tvalues[term]:.6f}, p={model.pvalues[term]:.6f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
