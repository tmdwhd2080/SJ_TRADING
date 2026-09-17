# -*- coding: utf-8 -*-
"""Backtest the intraday theme-stock GA rules with local theme_data files.

The local Theme_real data has full daily theme snapshots, but stock detail files
only for previously selected rebound themes.  For that reason the main realised
return reported here is a next-snapshot theme-return proxy.  A limited stock
return diagnostic is also reported when the same stock appears in the next
detail snapshot.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from Theme_intraday_stock_ga.pipeline import (
    PipelineConfig,
    build_portfolio,
    format_code,
    parse_percent,
)


BASE_DIR = Path(__file__).resolve().parents[1]


@dataclass
class BacktestConfig:
    data_dir: Path = BASE_DIR / "theme_data"
    output_dir: Path = BASE_DIR / "theme_intraday_ga_data" / "backtest"
    max_candidate_stocks: int = 80
    portfolio_size: int = 10
    max_stock_weight: float = 0.20
    min_final_weight: float = 0.005
    ga_population: int = 120
    ga_generations: int = 80
    random_seed: int = 42


def read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, encoding="utf-8-sig")


def pct(value: object) -> float:
    return parse_percent(value)


def stock_return_from_detail(df: pd.DataFrame) -> pd.Series:
    """Old Naver HTML detail files can have one shifted header.

    In many stored beta_rebound_detail files the visible return percentage is
    in the column labelled "매수호가", while "등락률" contains the price change.
    Detect that layout by scale and fall back to "등락률" otherwise.
    """
    if "등락률" not in df.columns:
        return pd.Series(np.nan, index=df.index)

    primary = df["등락률"].map(pct)
    alt = df["매수호가"].map(pct) if "매수호가" in df.columns else pd.Series(np.nan, index=df.index)

    primary_med = primary.abs().dropna().median()
    alt_med = alt.abs().dropna().median()
    if not math.isnan(alt_med) and alt_med <= 50 and (math.isnan(primary_med) or primary_med > 50):
        return alt
    return primary


def load_theme_snapshots(data_dir: Path) -> pd.DataFrame:
    frames = []
    for path in sorted(data_dir.glob("beta_all_themes_*.csv")):
        match = re.search(r"(\d{8})", path.name)
        if not match:
            continue
        raw = read_csv(path)
        if "코스피등락률" not in raw.columns:
            raise ValueError(f"KOSPI return is required in history file: {path}")
        df = pd.DataFrame(
            {
                "date": match.group(1),
                "theme_no": raw["theme_no"].astype(str),
                "theme_name": raw["테마명"].astype(str),
                "theme_return_pct": raw["등락률"].map(pct),
                "theme_avg_return_pct": raw["평균등락률"].map(pct),
                "kospi_return_pct": raw["코스피등락률"].map(pct),
                "total_count": (
                    raw["상승종목수"].map(pct)
                    + raw["보합종목수"].map(pct)
                    + raw["하락종목수"].map(pct)
                ),
            }
        )
        if df["kospi_return_pct"].isna().any():
            raise ValueError(f"KOSPI return could not be parsed in history file: {path}")
        df["theme_excess_return_pct"] = df["theme_return_pct"] - df["kospi_return_pct"]
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def load_detail_snapshots(data_dir: Path, themes: pd.DataFrame) -> dict[str, pd.DataFrame]:
    theme_avg = themes[[
        "date",
        "theme_no",
        "theme_avg_return_pct",
        "theme_return_pct",
        "theme_excess_return_pct",
        "kospi_return_pct",
    ]]
    result: dict[str, pd.DataFrame] = {}

    for path in sorted(data_dir.glob("beta_rebound_detail_*.csv")):
        match = re.search(r"(\d{8})", path.name)
        if not match:
            continue
        date = match.group(1)
        raw = read_csv(path)
        if raw.empty or "종목코드" not in raw.columns:
            continue
        df = pd.DataFrame(
            {
                "date": date,
                "theme_no": raw["theme_no"].astype(str),
                "theme_name": raw["테마명"].astype(str),
                "stock_code": raw["종목코드"].map(format_code),
                "stock_name": raw["종목명"].astype(str),
                "stock_return_pct": stock_return_from_detail(raw),
            }
        )
        df = df.merge(theme_avg, on=["date", "theme_no"], how="left")
        df["stock_alpha_pct"] = df["stock_return_pct"] - df["theme_avg_return_pct"]
        result[date] = df
    return result


def make_pipeline_config(cfg: BacktestConfig) -> PipelineConfig:
    return PipelineConfig(
        output_dir=cfg.output_dir,
        legacy_history_dir=cfg.data_dir,
        max_candidate_stocks=cfg.max_candidate_stocks,
        portfolio_size=cfg.portfolio_size,
        max_stock_weight=cfg.max_stock_weight,
        min_final_weight=cfg.min_final_weight,
        ga_population=cfg.ga_population,
        ga_generations=cfg.ga_generations,
        random_seed=cfg.random_seed,
    )


def max_drawdown(returns: pd.Series) -> float:
    if returns.empty:
        return 0.0
    curve = (1.0 + returns).cumprod()
    dd = curve / curve.cummax() - 1.0
    return float(dd.min())


def perf_stats(returns: pd.Series, label: str) -> dict:
    returns = returns.dropna()
    if returns.empty:
        return {
            "label": label,
            "n_trades": 0,
        }
    avg = float(returns.mean())
    std = float(returns.std(ddof=1)) if len(returns) > 1 else 0.0
    return {
        "label": label,
        "n_trades": int(len(returns)),
        "cumulative_return_pct": round(((1.0 + returns).prod() - 1.0) * 100, 2),
        "average_return_pct": round(avg * 100, 3),
        "median_return_pct": round(float(returns.median()) * 100, 3),
        "win_rate_pct": round(float((returns > 0).mean()) * 100, 1),
        "sharpe_like": round((avg / std) * np.sqrt(252), 3) if std > 0 else 0.0,
        "mdd_pct": round(max_drawdown(returns) * 100, 2),
    }


def run_backtest(cfg: BacktestConfig) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    themes = load_theme_snapshots(cfg.data_dir)
    if themes.empty:
        raise RuntimeError(f"No beta_all_themes_*.csv files found in {cfg.data_dir}")

    details_by_date = load_detail_snapshots(cfg.data_dir, themes)
    dates = sorted(themes["date"].unique())
    theme_by_date = {d: themes[themes["date"] == d].copy() for d in dates}
    pipe_cfg = make_pipeline_config(cfg)

    portfolios = []
    daily_records = []

    for i in range(2, len(dates) - 1):
        d_minus_1, d, k = dates[i - 2], dates[i - 1], dates[i]
        next_date = dates[i + 1]
        current = theme_by_date[k]
        prev1 = theme_by_date[d_minus_1][["theme_no", "theme_excess_return_pct"]].rename(
            columns={"theme_excess_return_pct": "excess_d_minus_1_pct"}
        )
        prev2 = theme_by_date[d][["theme_no", "theme_excess_return_pct"]].rename(
            columns={"theme_excess_return_pct": "excess_d_pct"}
        )

        stage1 = current.merge(prev1, on="theme_no", how="inner").merge(prev2, on="theme_no", how="inner")
        stage1 = stage1[
            (stage1["excess_d_minus_1_pct"] < 0)
            & (stage1["excess_d_pct"] > 0)
            & (stage1["theme_excess_return_pct"] > 0)
            & (pd.to_numeric(stage1["total_count"], errors="coerce") > 4)
        ].copy()

        detail = details_by_date.get(k)
        if detail is None or detail.empty or stage1.empty:
            continue

        candidates = detail[detail["theme_no"].isin(stage1["theme_no"].astype(str))].copy()
        candidates = candidates.dropna(subset=[
            "stock_code",
            "stock_return_pct",
            "theme_avg_return_pct",
            "kospi_return_pct",
            "theme_excess_return_pct",
        ])
        candidates = candidates[
            (candidates["stock_return_pct"] > candidates["kospi_return_pct"])
            & (candidates["stock_return_pct"] < candidates["theme_avg_return_pct"])
        ]
        if candidates.empty:
            continue

        candidates["candidate_objective_pct"] = candidates["theme_excess_return_pct"]
        candidates = candidates.sort_values(["candidate_objective_pct", "stock_return_pct"], ascending=False)
        candidates = candidates.drop_duplicates("stock_code", keep="first").reset_index(drop=True)
        candidates["run_date"] = k
        candidates["run_timestamp"] = k
        candidates["current_price"] = np.nan
        candidates["volume"] = np.nan
        candidates["trading_value"] = np.nan

        portfolio = build_portfolio(candidates, pipe_cfg, run_timestamp=k)
        if portfolio.empty:
            continue
        portfolio["decision_date"] = k
        portfolio["next_date"] = next_date
        portfolio["d_minus_1_date"] = d_minus_1
        portfolio["d_date"] = d

        next_themes = theme_by_date[next_date][["theme_no", "theme_return_pct", "theme_excess_return_pct", "kospi_return_pct"]].rename(
            columns={
                "theme_return_pct": "next_theme_return_pct",
                "theme_excess_return_pct": "next_theme_excess_pct",
                "kospi_return_pct": "next_kospi_return_pct",
            }
        )
        portfolio = portfolio.merge(next_themes, on="theme_no", how="left")
        theme_proxy_return = float((portfolio["weight"] * portfolio["next_theme_return_pct"].fillna(0.0)).sum() / 100.0)
        next_kospi_return = float(portfolio["next_kospi_return_pct"].dropna().iloc[0] / 100.0) if portfolio["next_kospi_return_pct"].notna().any() else np.nan
        theme_proxy_excess = theme_proxy_return - next_kospi_return if not math.isnan(next_kospi_return) else np.nan

        next_detail = details_by_date.get(next_date)
        stock_coverage_weight = 0.0
        stock_return_available = np.nan
        if next_detail is not None and not next_detail.empty:
            next_stock = (
                next_detail[["stock_code", "stock_return_pct"]]
                .dropna(subset=["stock_code", "stock_return_pct"])
                .groupby("stock_code", as_index=False)["stock_return_pct"]
                .mean()
                .rename(columns={"stock_return_pct": "next_stock_return_pct"})
            )
            portfolio = portfolio.merge(next_stock, on="stock_code", how="left")
            covered = portfolio["next_stock_return_pct"].notna()
            stock_coverage_weight = float(portfolio.loc[covered, "weight"].sum())
            if stock_coverage_weight > 0:
                stock_return_available = float(
                    (portfolio.loc[covered, "weight"] * portfolio.loc[covered, "next_stock_return_pct"]).sum()
                    / stock_coverage_weight
                    / 100.0
                )
        else:
            portfolio["next_stock_return_pct"] = np.nan

        daily_records.append(
            {
                "decision_date": k,
                "next_date": next_date,
                "stage1_themes": int(stage1["theme_no"].nunique()),
                "candidate_stocks": int(len(candidates)),
                "portfolio_stocks": int(len(portfolio)),
                "formation_objective_pct": float(portfolio["portfolio_objective_pct"].iloc[0]),
                "theme_proxy_return": theme_proxy_return,
                "next_kospi_return": next_kospi_return,
                "theme_proxy_excess": theme_proxy_excess,
                "stock_return_available": stock_return_available,
                "stock_coverage_weight": stock_coverage_weight,
            }
        )
        portfolios.append(portfolio)

    daily = pd.DataFrame(daily_records)
    portfolio_log = pd.concat(portfolios, ignore_index=True) if portfolios else pd.DataFrame()

    stats = {
        "data_dir": str(cfg.data_dir),
        "theme_snapshot_dates": int(len(dates)),
        "first_theme_date": dates[0] if dates else None,
        "last_theme_date": dates[-1] if dates else None,
        "detail_snapshot_dates": int(len(details_by_date)),
        "main_return_note": "theme_proxy_return uses next snapshot theme return for each selected stock's theme.",
        "stock_return_note": "stock_return_available only uses stocks found again in next beta_rebound_detail; coverage is partial and biased.",
    }
    if not daily.empty:
        stats.update(
            {
                "avg_stage1_themes": round(float(daily["stage1_themes"].mean()), 2),
                "avg_candidate_stocks": round(float(daily["candidate_stocks"].mean()), 2),
                "avg_portfolio_stocks": round(float(daily["portfolio_stocks"].mean()), 2),
                "avg_formation_objective_pct": round(float(daily["formation_objective_pct"].mean()), 3),
                "avg_stock_coverage_weight_pct": round(float(daily["stock_coverage_weight"].mean()) * 100, 2),
                "theme_proxy": perf_stats(daily["theme_proxy_return"], "theme_proxy_return"),
                "theme_proxy_excess": perf_stats(daily["theme_proxy_excess"], "theme_proxy_excess_vs_kospi"),
                "stock_available": perf_stats(daily["stock_return_available"], "stock_return_available_partial"),
            }
        )
    return daily, portfolio_log, stats


def parse_args(argv: list[str] | None = None) -> BacktestConfig:
    parser = argparse.ArgumentParser(description="Backtest theme intraday stock GA with local theme_data.")
    parser.add_argument("--data-dir", type=Path, default=BacktestConfig.data_dir)
    parser.add_argument("--output-dir", type=Path, default=BacktestConfig.output_dir)
    parser.add_argument("--max-candidate-stocks", type=int, default=BacktestConfig.max_candidate_stocks)
    parser.add_argument("--portfolio-size", type=int, default=BacktestConfig.portfolio_size)
    parser.add_argument("--max-stock-weight", type=float, default=BacktestConfig.max_stock_weight)
    parser.add_argument("--ga-population", type=int, default=BacktestConfig.ga_population)
    parser.add_argument("--ga-generations", type=int, default=BacktestConfig.ga_generations)
    parser.add_argument("--random-seed", type=int, default=BacktestConfig.random_seed)
    args = parser.parse_args(argv)
    return BacktestConfig(
        data_dir=args.data_dir,
        output_dir=args.output_dir,
        max_candidate_stocks=args.max_candidate_stocks,
        portfolio_size=args.portfolio_size,
        max_stock_weight=args.max_stock_weight,
        ga_population=args.ga_population,
        ga_generations=args.ga_generations,
        random_seed=args.random_seed,
    )


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass

    cfg = parse_args(argv)
    daily, portfolio_log, stats = run_backtest(cfg)
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    daily_path = cfg.output_dir / "theme_data_backtest_daily.csv"
    portfolio_path = cfg.output_dir / "theme_data_backtest_portfolios.csv"
    summary_path = cfg.output_dir / "theme_data_backtest_summary.json"
    daily.to_csv(daily_path, index=False, encoding="utf-8-sig")
    portfolio_log.to_csv(portfolio_path, index=False, encoding="utf-8-sig")
    summary_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")

    print("[Backtest summary]")
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    print(f"\nSaved daily: {daily_path}")
    print(f"Saved portfolios: {portfolio_path}")
    print(f"Saved summary: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
