"""Analyze same-month ADP surprise vs PAYEMS surprise.

Surprise is defined as actual/real value minus market consensus.
Rows with missing actuals or consensus in either series are excluded.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Any

import pandas as pd
import statsmodels.api as sm


def default_desktop_path(filename: str) -> Path:
    return Path.home() / "Desktop" / filename


def read_series(path: Path, prefix: str) -> pd.DataFrame:
    if path.suffix.lower() in {".xlsx", ".xls"}:
        df = pd.read_excel(path)
    else:
        df = pd.read_csv(path, encoding="utf-8-sig")

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
            "release_date": f"{prefix}_release_date",
            "Real_value": f"{prefix}_actual",
            "Consensus": f"{prefix}_consensus",
        }
    )
    out[f"{prefix}_surprise"] = out[f"{prefix}_actual"] - out[f"{prefix}_consensus"]
    out = out.sort_values("target_date").drop_duplicates("target_date", keep="last")
    return out


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def format_dates(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for column in out.columns:
        if column.endswith("_date") or column == "target_date":
            out[column] = pd.to_datetime(out[column]).dt.strftime("%Y-%m-%d")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    script_dir = Path(__file__).resolve().parent
    parser.add_argument("--adp-file", default=str(default_desktop_path("ADP.csv")))
    parser.add_argument("--payems-file", default=str(default_desktop_path("PAYEMS.xlsx")))
    parser.add_argument(
        "--output-dir",
        default=str(script_dir / "data" / "adp_payems_consensus_surprise"),
    )
    args = parser.parse_args()

    adp_raw = pd.read_csv(args.adp_file, encoding="utf-8-sig")
    payems_raw = pd.read_excel(args.payems_file)

    adp = read_series(Path(args.adp_file), "adp")
    payems = read_series(Path(args.payems_file), "payems")
    panel = adp.merge(payems, on="target_date", how="inner")
    panel = panel.sort_values("target_date").reset_index(drop=True)

    if panel.empty:
        raise RuntimeError("No overlapping target_date rows remained after dropping missing actual/consensus values.")

    x = panel["adp_surprise"]
    y = panel["payems_surprise"]
    x_with_const = sm.add_constant(x)
    model = sm.OLS(y, x_with_const).fit()
    corr = x.corr(y)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    panel_out = format_dates(panel)
    panel_path = output_dir / "adp_payems_surprise_panel.csv"
    panel_out.to_csv(panel_path, index=False, encoding="utf-8-sig")

    summary = [
        {
            "model": "payems_surprise_on_adp_surprise",
            "equation": "PAYEMS_surprise = alpha + beta * ADP_surprise",
            "start_target_date": panel_out["target_date"].iloc[0],
            "end_target_date": panel_out["target_date"].iloc[-1],
            "n": int(model.nobs),
            "corr": corr,
            "alpha": model.params["const"],
            "beta": model.params["adp_surprise"],
            "r2": model.rsquared,
            "adj_r2": model.rsquared_adj,
            "alpha_se": model.bse["const"],
            "beta_se": model.bse["adp_surprise"],
            "alpha_t": model.tvalues["const"],
            "beta_t": model.tvalues["adp_surprise"],
            "alpha_pvalue": model.pvalues["const"],
            "beta_pvalue": model.pvalues["adp_surprise"],
            "rmse": float((model.resid.pow(2).mean()) ** 0.5),
            "adp_rows_original": len(adp_raw),
            "payems_rows_original": len(payems_raw),
            "adp_rows_after_missing_drop": len(adp),
            "payems_rows_after_missing_drop": len(payems),
            "merged_rows": len(panel),
        }
    ]
    summary_path = output_dir / "regression_summary.csv"
    write_csv(summary_path, summary, list(summary[0].keys()))

    print(f"Wrote panel to {panel_path}")
    print(f"Wrote summary to {summary_path}")
    row = summary[0]
    print(
        f"sample={row['start_target_date']}~{row['end_target_date']}, n={row['n']}, "
        f"corr={row['corr']:.6f}, r2={row['r2']:.6f}, beta={row['beta']:.6f}, "
        f"beta_t={row['beta_t']:.6f}, beta_p={row['beta_pvalue']:.6f}"
    )
    print(f"equation: PAYEMS_surprise = {row['alpha']:.6f} + {row['beta']:.6f} * ADP_surprise")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
