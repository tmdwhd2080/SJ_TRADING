"""Forecast the 2026-07 target-month payroll release with two target-date models.

Model 1 is the existing two-step surprise model:
    1. PAYEMS = a + b * ADP
    2. PAYEMS surprise = c + d * ADP-implied surprise + e * claims

Model 2 splits PAYEMS into private and government blocks, following the
user-specified formulas:
    government = f(ADP, claims)
    private = f(private lag1, claims)

All rows are aligned by target_date, not release_date.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
import statsmodels.api as sm

from run_nfp_twofactor_regression import claims_average_feature, latest_revised_claims, read_csv


FORECAST_TARGET_DATE = pd.Timestamp("2026-07-01")
PAYEMS_JULY_CONSENSUS_K = 88.0
DEFAULT_START_TARGET_DATE = pd.Timestamp("2022-09-01")


def fit_ols(y: pd.Series, x: pd.DataFrame):
    return sm.OLS(y, sm.add_constant(x, has_constant="add")).fit()


def regression_summary(model, model_name: str, equation: str, start: str, end: str) -> list[dict[str, object]]:
    rmse = float((model.resid.pow(2).mean()) ** 0.5)
    mae = float(model.resid.abs().mean())
    rows: list[dict[str, object]] = []
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


def read_adp_desktop(path: Path) -> pd.DataFrame:
    adp = pd.read_csv(path, encoding="utf-8-sig")
    adp["target_date"] = pd.to_datetime(adp["target_date"], errors="coerce")
    adp["Real_value"] = pd.to_numeric(adp["Real_value"], errors="coerce")
    return (
        adp.dropna(subset=["target_date", "Real_value"])
        .sort_values("target_date")
        .drop_duplicates("target_date", keep="last")
        .rename(columns={"Real_value": "adp_actual"})
    )


def claims_feature_table(initial_file: Path, revision_file: Path, months: list[pd.Timestamp]) -> pd.DataFrame:
    initial_rows = read_csv(initial_file)
    revision_rows = read_csv(revision_file)
    latest_claims = latest_revised_claims(initial_rows, revision_rows)

    rows: list[dict[str, object]] = []
    for month in months:
        month_text = month.strftime("%Y-%m-01")
        claims_avg, week_count, last_week = claims_average_feature(month_text, initial_rows, latest_claims)
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


def model1_two_step_surprise(
    surprise_panel_path: Path,
    adp_forecast_k: float,
    claims_forecast_k: float,
    payems_consensus_k: float,
    start_target_date: pd.Timestamp,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, float]]:
    df = pd.read_csv(surprise_panel_path)
    df["target_date"] = pd.to_datetime(df["target_date"], errors="coerce")
    needed = [
        "target_date",
        "payems_actual",
        "payems_consensus",
        "payems_surprise",
        "adp_actual",
        "claims_avg_mixed_thousands",
    ]
    df = df.dropna(subset=needed).sort_values("target_date").reset_index(drop=True)
    df = df[df["target_date"] >= start_target_date].reset_index(drop=True)

    step1 = fit_ols(df["payems_actual"], df[["adp_actual"]])
    df["adp_implied_payems"] = step1.predict(sm.add_constant(df[["adp_actual"]], has_constant="add"))
    df["adp_implied_surprise"] = df["adp_implied_payems"] - df["payems_consensus"]

    step2 = fit_ols(df["payems_surprise"], df[["adp_implied_surprise", "claims_avg_mixed_thousands"]])
    df["predicted_payems_surprise"] = step2.predict(
        sm.add_constant(df[["adp_implied_surprise", "claims_avg_mixed_thousands"]], has_constant="add")
    )
    df["error_actual_minus_predicted"] = df["payems_surprise"] - df["predicted_payems_surprise"]

    start = df["target_date"].iloc[0].strftime("%Y-%m-%d")
    end = df["target_date"].iloc[-1].strftime("%Y-%m-%d")
    summary = pd.DataFrame(
        regression_summary(
            step1,
            "model1_step1_adp_to_payems",
            "PAYEMS_initial_k = alpha + beta * ADP_initial_k",
            start,
            end,
        )
        + regression_summary(
            step2,
            "model1_step2_surprise",
            "PAYEMS_surprise_k = alpha + beta1 * ADP_implied_surprise_k + beta2 * claims_avg_k",
            start,
            end,
        )
    )
    summary["correlation_payems_adp"] = df["payems_actual"].corr(df["adp_actual"])
    summary["correlation_surprise_adp_implied_surprise"] = df["payems_surprise"].corr(df["adp_implied_surprise"])
    summary["correlation_surprise_claims"] = df["payems_surprise"].corr(df["claims_avg_mixed_thousands"])

    adp_implied_payems = float(
        step1.predict(sm.add_constant(pd.DataFrame({"adp_actual": [adp_forecast_k]}), has_constant="add")).iloc[0]
    )
    adp_implied_surprise = adp_implied_payems - payems_consensus_k
    predicted_surprise = float(
        step2.predict(
            sm.add_constant(
                pd.DataFrame(
                    {
                        "adp_implied_surprise": [adp_implied_surprise],
                        "claims_avg_mixed_thousands": [claims_forecast_k],
                    }
                ),
                has_constant="add",
            )
        ).iloc[0]
    )
    forecast = {
        "payems_consensus_k": payems_consensus_k,
        "adp_actual_k": adp_forecast_k,
        "claims_avg_k": claims_forecast_k,
        "adp_implied_payems_k": adp_implied_payems,
        "adp_implied_surprise_k": adp_implied_surprise,
        "predicted_payems_surprise_k": predicted_surprise,
        "predicted_payems_k": payems_consensus_k + predicted_surprise,
    }
    return df, summary, forecast


def model2_split_forecast(
    split_panel_path: Path,
    claims: pd.DataFrame,
    adp_forecast_k: float,
    claims_forecast_k: float,
    start_target_date: pd.Timestamp,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, float]]:
    panel = pd.read_csv(split_panel_path)
    panel["target_date"] = pd.to_datetime(panel["target_date"], errors="coerce")
    panel = panel.merge(claims, on="target_date", how="left")
    panel = panel.sort_values("target_date")
    panel["USPRIV_initial_lag1_change_k"] = panel["USPRIV_initial_change_k"].shift(1)

    train = panel[(panel["target_date"] >= start_target_date) & (panel["target_date"] < FORECAST_TARGET_DATE)].copy()
    govt_data = train.dropna(
        subset=["USGOVT_initial_change_k", "ADPMNUSNERSA_initial_change_k", "claims_avg_mixed_thousands"]
    ).copy()
    private_data = train.dropna(
        subset=["USPRIV_initial_change_k", "USPRIV_initial_lag1_change_k", "claims_avg_mixed_thousands"]
    ).copy()

    govt_model = fit_ols(govt_data["USGOVT_initial_change_k"], govt_data[["ADPMNUSNERSA_initial_change_k", "claims_avg_mixed_thousands"]])
    private_model = fit_ols(private_data["USPRIV_initial_change_k"], private_data[["USPRIV_initial_lag1_change_k", "claims_avg_mixed_thousands"]])

    rows = regression_summary(
        govt_model,
        "model2_government_adp_claims",
        "USGOVT_initial_k = alpha + beta1 * ADP_initial_k + beta2 * claims_avg_k",
        govt_data["target_date"].iloc[0].strftime("%Y-%m-%d"),
        govt_data["target_date"].iloc[-1].strftime("%Y-%m-%d"),
    )
    rows += regression_summary(
        private_model,
        "model2_private_ar1_claims",
        "USPRIV_initial_k = alpha + beta1 * USPRIV_lag1_initial_k + beta2 * claims_avg_k",
        private_data["target_date"].iloc[0].strftime("%Y-%m-%d"),
        private_data["target_date"].iloc[-1].strftime("%Y-%m-%d"),
    )
    summary = pd.DataFrame(rows)

    last_private_change = float(
        panel.loc[panel["target_date"] == pd.Timestamp("2026-06-01"), "USPRIV_initial_change_k"].dropna().iloc[-1]
    )
    government_forecast = float(
        govt_model.predict(
            sm.add_constant(
                pd.DataFrame(
                    {
                        "ADPMNUSNERSA_initial_change_k": [adp_forecast_k],
                        "claims_avg_mixed_thousands": [claims_forecast_k],
                    }
                ),
                has_constant="add",
            )
        ).iloc[0]
    )
    private_forecast = float(
        private_model.predict(
            sm.add_constant(
                pd.DataFrame(
                    {
                        "USPRIV_initial_lag1_change_k": [last_private_change],
                        "claims_avg_mixed_thousands": [claims_forecast_k],
                    }
                ),
                has_constant="add",
            )
        ).iloc[0]
    )
    forecast = {
        "adp_actual_k": adp_forecast_k,
        "claims_avg_k": claims_forecast_k,
        "private_lag1_k": last_private_change,
        "predicted_private_k": private_forecast,
        "predicted_government_k": government_forecast,
        "predicted_payems_k": private_forecast + government_forecast,
    }
    return panel, summary, forecast


def format_dates(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for column in out.columns:
        if "date" in column:
            out[column] = pd.to_datetime(out[column], errors="coerce").dt.strftime("%Y-%m-%d")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    script_dir = Path(__file__).resolve().parent
    parser.add_argument("--output-dir", default=str(script_dir / "data" / "aug2026_target_forecasts"))
    parser.add_argument("--start-target-date", default=DEFAULT_START_TARGET_DATE.strftime("%Y-%m-%d"))
    parser.add_argument("--adp-file", default=str(Path.home() / "Desktop" / "ADP.csv"))
    parser.add_argument(
        "--surprise-panel",
        default=str(script_dir / "data" / "payems_surprise_adp_claims_regression" / "model_panel.csv"),
    )
    parser.add_argument(
        "--split-panel",
        default=str(script_dir / "data" / "private_government_split_2020_present" / "monthly_split_model_panel.csv"),
    )
    parser.add_argument(
        "--initial-file",
        default=str(script_dir / "data" / "employment_events_2020_2026" / "initial_releases.csv"),
    )
    parser.add_argument(
        "--revision-file",
        default=str(script_dir / "data" / "employment_events_2020_2026" / "revision_events.csv"),
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    start_target_date = pd.Timestamp(args.start_target_date)

    adp = read_adp_desktop(Path(args.adp_file))
    adp_forecast_k = float(adp.loc[adp["target_date"].eq(FORECAST_TARGET_DATE), "adp_actual"].iloc[-1])

    months = list(pd.date_range("2020-01-01", "2026-07-01", freq="MS"))
    claims = claims_feature_table(Path(args.initial_file), Path(args.revision_file), months)
    claims_forecast_k = float(
        claims.loc[claims["target_date"].eq(FORECAST_TARGET_DATE), "claims_avg_mixed_thousands"].iloc[-1]
    )

    model1_panel, model1_summary, model1_forecast = model1_two_step_surprise(
        Path(args.surprise_panel),
        adp_forecast_k,
        claims_forecast_k,
        PAYEMS_JULY_CONSENSUS_K,
        start_target_date,
    )
    model2_panel, model2_summary, model2_forecast = model2_split_forecast(
        Path(args.split_panel),
        claims,
        adp_forecast_k,
        claims_forecast_k,
        start_target_date,
    )

    forecast = pd.DataFrame(
        [
            {
                "model": "model1_two_step_surprise",
                "target_date": FORECAST_TARGET_DATE,
                **model1_forecast,
            },
            {
                "model": "model2_split_private_government",
                "target_date": FORECAST_TARGET_DATE,
                "payems_consensus_k": PAYEMS_JULY_CONSENSUS_K,
                **model2_forecast,
                "predicted_payems_surprise_k": model2_forecast["predicted_payems_k"] - PAYEMS_JULY_CONSENSUS_K,
            },
        ]
    )

    format_dates(model1_panel).to_csv(output_dir / "model1_training_panel.csv", index=False, encoding="utf-8-sig")
    model1_summary.to_csv(output_dir / "model1_regression_summary.csv", index=False, encoding="utf-8-sig")
    format_dates(model2_panel).to_csv(output_dir / "model2_training_panel.csv", index=False, encoding="utf-8-sig")
    model2_summary.to_csv(output_dir / "model2_regression_summary.csv", index=False, encoding="utf-8-sig")
    format_dates(claims).to_csv(output_dir / "claims_features.csv", index=False, encoding="utf-8-sig")
    format_dates(forecast).to_csv(output_dir / "aug7_2026_forecast.csv", index=False, encoding="utf-8-sig")

    print(f"Wrote outputs to {output_dir}")
    print("Model 1 summary")
    print(model1_summary.to_string(index=False))
    print("\nModel 2 summary")
    print(model2_summary.to_string(index=False))
    print("\nForecast")
    print(forecast.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
