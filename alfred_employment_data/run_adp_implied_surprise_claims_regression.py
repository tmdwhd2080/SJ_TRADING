"""Two-step PAYEMS surprise model using ADP-implied surprise plus claims.

Step 1:
    PAYEMS_actual = a + b * ADP_actual

Step 2:
    ADP_implied_surprise = fitted_PAYEMS_from_ADP - PAYEMS_consensus
    PAYEMS_surprise = alpha + beta1 * ADP_implied_surprise + beta2 * ICSA_avg_mixed_1000

The in-sample result is useful as a diagnostic. The script also writes an
expanding-window out-of-sample panel to avoid using future data in Step 1.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
import statsmodels.api as sm


def fit_ols(y: pd.Series, x: pd.DataFrame):
    return sm.OLS(y, sm.add_constant(x)).fit()


def write_summary(model, path: Path, extra: dict[str, object]) -> None:
    rows = []
    for term in model.params.index:
        rows.append(
            {
                **extra,
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
            }
        )
    pd.DataFrame(rows).to_csv(path, index=False, encoding="utf-8-sig")


def expanding_predictions(df: pd.DataFrame, min_train: int) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for idx in range(min_train, len(df)):
        train = df.iloc[:idx].copy()
        current = df.iloc[idx].copy()

        step1 = fit_ols(train["payems_actual"], train[["adp_actual"]])
        train["adp_implied_payems"] = step1.predict(sm.add_constant(train[["adp_actual"]]))
        train["adp_implied_surprise"] = train["adp_implied_payems"] - train["payems_consensus"]

        current_x_step1 = pd.DataFrame({"adp_actual": [current["adp_actual"]]})
        current["adp_implied_payems"] = float(step1.predict(sm.add_constant(current_x_step1, has_constant="add")).iloc[0])
        current["adp_implied_surprise"] = current["adp_implied_payems"] - current["payems_consensus"]

        step2 = fit_ols(train["payems_surprise"], train[["adp_implied_surprise", "claims_avg_mixed_thousands"]])
        current_x_step2 = pd.DataFrame(
            {
                "adp_implied_surprise": [current["adp_implied_surprise"]],
                "claims_avg_mixed_thousands": [current["claims_avg_mixed_thousands"]],
            }
        )
        predicted = float(step2.predict(sm.add_constant(current_x_step2, has_constant="add")).iloc[0])

        rows.append(
            {
                "target_date": current["target_date"],
                "train_start": train["target_date"].iloc[0],
                "train_end": train["target_date"].iloc[-1],
                "train_n": len(train),
                "payems_actual": current["payems_actual"],
                "payems_consensus": current["payems_consensus"],
                "payems_surprise": current["payems_surprise"],
                "adp_actual": current["adp_actual"],
                "claims_avg_mixed_thousands": current["claims_avg_mixed_thousands"],
                "adp_implied_payems": current["adp_implied_payems"],
                "adp_implied_surprise": current["adp_implied_surprise"],
                "predicted_payems_surprise": predicted,
                "error_actual_minus_predicted": current["payems_surprise"] - predicted,
                "step1_alpha": step1.params["const"],
                "step1_beta_adp": step1.params["adp_actual"],
                "step2_alpha": step2.params["const"],
                "step2_beta_adp_implied_surprise": step2.params["adp_implied_surprise"],
                "step2_beta_claims": step2.params["claims_avg_mixed_thousands"],
            }
        )
    return pd.DataFrame(rows)


def regression_metrics(actual: pd.Series, predicted: pd.Series) -> dict[str, float]:
    error = actual - predicted
    sse = float((error.pow(2)).sum())
    sst = float(((actual - actual.mean()).pow(2)).sum())
    return {
        "n": float(len(actual)),
        "r2": 1 - sse / sst if sst else float("nan"),
        "rmse": float((error.pow(2).mean()) ** 0.5),
        "mae": float(error.abs().mean()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    script_dir = Path(__file__).resolve().parent
    parser.add_argument(
        "--input-panel",
        default=str(script_dir / "data" / "payems_surprise_adp_claims_regression" / "model_panel.csv"),
    )
    parser.add_argument("--min-train", type=int, default=24)
    parser.add_argument(
        "--output-dir",
        default=str(script_dir / "data" / "adp_implied_surprise_claims_regression"),
    )
    args = parser.parse_args()

    df = pd.read_csv(args.input_panel)
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

    step1 = fit_ols(df["payems_actual"], df[["adp_actual"]])
    df["adp_implied_payems"] = step1.predict(sm.add_constant(df[["adp_actual"]]))
    df["adp_implied_surprise"] = df["adp_implied_payems"] - df["payems_consensus"]

    step2 = fit_ols(df["payems_surprise"], df[["adp_implied_surprise", "claims_avg_mixed_thousands"]])
    df["predicted_payems_surprise"] = step2.predict(
        sm.add_constant(df[["adp_implied_surprise", "claims_avg_mixed_thousands"]])
    )
    df["error_actual_minus_predicted"] = df["payems_surprise"] - df["predicted_payems_surprise"]

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    panel_out = df.copy()
    panel_out["target_date"] = panel_out["target_date"].dt.strftime("%Y-%m-%d")
    panel_out.to_csv(output_dir / "in_sample_model_panel.csv", index=False, encoding="utf-8-sig")

    write_summary(
        step1,
        output_dir / "step1_adp_to_payems_actual.csv",
        {
            "model": "step1_adp_to_payems_actual",
            "equation": "PAYEMS_actual = alpha + beta * ADP_actual",
            "start_target_date": panel_out["target_date"].iloc[0],
            "end_target_date": panel_out["target_date"].iloc[-1],
        },
    )
    write_summary(
        step2,
        output_dir / "step2_payems_surprise_regression.csv",
        {
            "model": "step2_payems_surprise_on_adp_implied_surprise_and_claims",
            "equation": "PAYEMS_surprise = alpha + beta1 * ADP_implied_surprise + beta2 * ICSA_avg_mixed_1000",
            "start_target_date": panel_out["target_date"].iloc[0],
            "end_target_date": panel_out["target_date"].iloc[-1],
        },
    )

    correlations = df[
        [
            "payems_surprise",
            "adp_implied_surprise",
            "claims_avg_mixed_thousands",
            "adp_actual",
            "payems_actual",
        ]
    ].corr()
    correlations.to_csv(output_dir / "correlation_matrix.csv", encoding="utf-8-sig")

    oos = expanding_predictions(df, args.min_train)
    oos_out = oos.copy()
    for column in ["target_date", "train_start", "train_end"]:
        oos_out[column] = pd.to_datetime(oos_out[column]).dt.strftime("%Y-%m-%d")
    oos_out.to_csv(output_dir / "expanding_oos_predictions.csv", index=False, encoding="utf-8-sig")
    oos_metrics = regression_metrics(oos["payems_surprise"], oos["predicted_payems_surprise"])
    pd.DataFrame([oos_metrics]).to_csv(output_dir / "expanding_oos_metrics.csv", index=False, encoding="utf-8-sig")

    print(f"Wrote outputs to {output_dir}")
    print(f"sample={panel_out['target_date'].iloc[0]}~{panel_out['target_date'].iloc[-1]}, n={len(df)}")
    print(
        "step1: PAYEMS_actual = "
        f"{step1.params['const']:.6f} + {step1.params['adp_actual']:.6f} * ADP_actual; "
        f"r2={step1.rsquared:.6f}"
    )
    print(
        "step2: PAYEMS_surprise = "
        f"{step2.params['const']:.6f} "
        f"+ {step2.params['adp_implied_surprise']:.6f} * ADP_implied_surprise "
        f"+ {step2.params['claims_avg_mixed_thousands']:.6f} * ICSA_avg_mixed_1000; "
        f"r2={step2.rsquared:.6f}, adj_r2={step2.rsquared_adj:.6f}, "
        f"rmse={(step2.resid.pow(2).mean() ** 0.5):.3f}"
    )
    print(
        "oos expanding: "
        f"min_train={args.min_train}, test_n={int(oos_metrics['n'])}, "
        f"r2={oos_metrics['r2']:.6f}, rmse={oos_metrics['rmse']:.3f}, mae={oos_metrics['mae']:.3f}"
    )
    for term in ["const", "adp_implied_surprise", "claims_avg_mixed_thousands"]:
        print(
            f"{term}: coef={step2.params[term]:.6f}, se={step2.bse[term]:.6f}, "
            f"t={step2.tvalues[term]:.6f}, p={step2.pvalues[term]:.6f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
