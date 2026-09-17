from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class OUParams:
    phi: float
    theta: float
    half_life_bd: float
    resid_std_bp: float
    stationary_std_bp: float


@dataclass(frozen=True)
class StrategyConfig:
    train_start: str = "2025-11-01"
    train_end: str = "2026-06-19"
    event_start: str = "2026-06-20"
    event_end: str = "2026-07-15"
    baseline_end: str = "2026-06-19"
    baseline_window: int = 60
    use_rolling_ou: bool = True
    rolling_ou_window: int = 60
    rolling_ou_min_obs: int = 40
    vol_lookback: int = 3
    vol_multiplier: float = 1.5
    driver_multiplier: float = 2.0
    require_kofr_driven: bool = False
    entry_z: float = 2.0
    exit_z_abs: float = 0.5
    stop_z: float = 3.25
    half_spread_bp: float = 0.5
    max_half_lives: float = 2.0
    max_units: int = 1


def find_default_excel() -> Path | None:
    matches = list((Path.home() / "Desktop").rglob("kofr.xlsm"))
    return matches[0] if matches else None


def load_data(path: Path | None) -> pd.DataFrame:
    if path is None:
        path = find_default_excel()
    if path is None:
        fallback = Path.cwd() / "out" / "kofr_cd_analysis_timeseries.csv"
        if not fallback.exists():
            raise FileNotFoundError("Could not find kofr.xlsm or out/kofr_cd_analysis_timeseries.csv")
        df = pd.read_csv(fallback, parse_dates=["Date"])
    else:
        df = pd.read_excel(path, sheet_name="Sheet1", header=4, engine="openpyxl")
        df = df.rename(
            columns={
                "KOFR rate": "KOFR",
                "CD91 rate": "CD91",
                "Compounded KOFR rate": "WorkbookComp",
            }
        )

    required = {"Date", "KOFR", "CD91"}
    missing = required.difference(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")

    out = df.dropna(subset=["Date", "KOFR", "CD91"]).copy()
    out["Date"] = pd.to_datetime(out["Date"])
    out = out.sort_values("Date").reset_index(drop=True)
    out["basis_bp"] = (out["CD91"] - out["KOFR"]) * 100.0
    out["d_cd_bp"] = out["CD91"].diff() * 100.0
    out["d_kofr_bp"] = out["KOFR"].diff() * 100.0
    out["d_basis_bp"] = out["basis_bp"].diff()
    return out


def fit_ou(series: pd.Series) -> OUParams:
    y = series.dropna().to_numpy(dtype=float)
    if len(y) < 10:
        raise ValueError("Need at least 10 observations for OU fit")

    lag = y[:-1]
    nxt = y[1:]
    x = np.vstack([np.ones_like(lag), lag]).T
    intercept, phi = np.linalg.lstsq(x, nxt, rcond=None)[0]
    theta = intercept / (1.0 - phi) if abs(1.0 - phi) > 1e-9 else float(np.mean(y))
    resid = nxt - (intercept + phi * lag)
    resid_std = float(np.std(resid, ddof=2))

    if 0.0 < phi < 1.0:
        half_life = float(-np.log(2.0) / np.log(phi))
        stationary_std = float(resid_std / np.sqrt(1.0 - phi**2))
    else:
        half_life = float("nan")
        stationary_std = float(np.std(y, ddof=1))

    return OUParams(
        phi=float(phi),
        theta=float(theta),
        half_life_bd=half_life,
        resid_std_bp=resid_std,
        stationary_std_bp=stationary_std,
    )


def rolling_ou_params(series: pd.Series, window: int, min_obs: int) -> pd.DataFrame:
    records: list[dict[str, float]] = []
    values = series.astype(float).reset_index(drop=True)
    fallback_std = values.rolling(window, min_periods=min_obs).std().shift(1)
    fallback_mean = values.rolling(window, min_periods=min_obs).mean().shift(1)

    for i in range(len(values)):
        hist = values.iloc[max(0, i - window) : i].dropna()
        if len(hist) < min_obs:
            records.append(
                {
                    "ou_phi": np.nan,
                    "ou_theta": np.nan,
                    "ou_half_life_bd": np.nan,
                    "ou_resid_std_bp": np.nan,
                    "ou_stationary_std_bp": np.nan,
                }
            )
            continue

        params = fit_ou(hist)
        theta = params.theta
        stationary_std = params.stationary_std_bp
        if not np.isfinite(theta):
            theta = float(fallback_mean.iloc[i])
        if not np.isfinite(stationary_std) or stationary_std <= 0:
            stationary_std = float(fallback_std.iloc[i])

        records.append(
            {
                "ou_phi": params.phi,
                "ou_theta": theta,
                "ou_half_life_bd": params.half_life_bd,
                "ou_resid_std_bp": params.resid_std_bp,
                "ou_stationary_std_bp": stationary_std,
            }
        )

    return pd.DataFrame(records)


def add_signals(df: pd.DataFrame, ou: OUParams, cfg: StrategyConfig) -> tuple[pd.DataFrame, float]:
    out = df.copy()
    baseline = out[out["Date"] <= pd.Timestamp(cfg.baseline_end)].tail(cfg.baseline_window)
    baseline_abs_kofr = float(baseline["d_kofr_bp"].abs().mean())
    vol_threshold = baseline_abs_kofr * cfg.vol_multiplier

    if cfg.use_rolling_ou:
        params = rolling_ou_params(out["basis_bp"], cfg.rolling_ou_window, cfg.rolling_ou_min_obs)
        out = pd.concat([out, params], axis=1)
    else:
        out["ou_phi"] = ou.phi
        out["ou_theta"] = ou.theta
        out["ou_half_life_bd"] = ou.half_life_bd
        out["ou_resid_std_bp"] = ou.resid_std_bp
        out["ou_stationary_std_bp"] = ou.stationary_std_bp

    out["ou_z"] = (out["basis_bp"] - out["ou_theta"]) / out["ou_stationary_std_bp"]
    out["kofr_abs_avg"] = out["d_kofr_bp"].abs().rolling(cfg.vol_lookback).mean()
    out["cd_abs_sum"] = out["d_cd_bp"].abs().rolling(cfg.vol_lookback).sum()
    out["kofr_abs_sum"] = out["d_kofr_bp"].abs().rolling(cfg.vol_lookback).sum()
    out["vol_regime"] = out["kofr_abs_avg"] > vol_threshold
    out["kofr_driven"] = out["kofr_abs_sum"] > cfg.driver_multiplier * out["cd_abs_sum"].replace(0, np.nan)
    out.loc[(out["cd_abs_sum"] == 0) & (out["kofr_abs_sum"] > 0), "kofr_driven"] = True
    out["event_window"] = (out["Date"] >= pd.Timestamp(cfg.event_start)) & (
        out["Date"] <= pd.Timestamp(cfg.event_end)
    )
    driver_filter = out["kofr_driven"] if cfg.require_kofr_driven else True
    out["short_signal"] = out["event_window"] & out["vol_regime"] & driver_filter & (out["ou_z"] >= cfg.entry_z)
    out["long_signal"] = out["event_window"] & out["vol_regime"] & driver_filter & (out["ou_z"] <= -cfg.entry_z)
    return out, vol_threshold


def fill_price(mid_basis: float, side: str, action: str, half_spread_bp: float) -> float:
    if side not in {"long", "short"}:
        raise ValueError(side)
    if action not in {"entry", "exit"}:
        raise ValueError(action)

    if side == "short":
        return mid_basis - half_spread_bp if action == "entry" else mid_basis + half_spread_bp
    return mid_basis + half_spread_bp if action == "entry" else mid_basis - half_spread_bp


def run_backtest(signal_df: pd.DataFrame, ou: OUParams, cfg: StrategyConfig) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = signal_df.reset_index(drop=True).copy()
    trades: list[dict[str, object]] = []
    positions: list[dict[str, object]] = []
    pending_entries: list[dict[str, object]] = []
    event_end = pd.Timestamp(cfg.event_end)
    next_trade_id = 1

    for i, row in rows.iterrows():
        date = row["Date"]

        if pending_entries:
            to_execute = pending_entries
            pending_entries = []
        else:
            to_execute = []

        for pending in to_execute:
            side = str(pending["side"])
            entry_basis = float(row["basis_bp"])
            entry_fill = fill_price(entry_basis, side, "entry", cfg.half_spread_bp)
            entry_theta = float(pending["ou_theta"]) if np.isfinite(float(pending["ou_theta"])) else ou.theta
            entry_std = (
                float(pending["ou_stationary_std_bp"])
                if np.isfinite(float(pending["ou_stationary_std_bp"]))
                else ou.stationary_std_bp
            )
            entry_half_life = (
                float(pending["ou_half_life_bd"])
                if np.isfinite(float(pending["ou_half_life_bd"]))
                else ou.half_life_bd
            )
            if not np.isfinite(entry_half_life) or entry_half_life <= 0:
                entry_half_life = 5.0
            entry_z = (entry_basis - entry_theta) / entry_std
            positions.append(
                {
                    "trade_id": next_trade_id,
                    "side": side,
                    "signal_date": pending["signal_date"],
                    "entry_date": date,
                    "entry_basis_mid": entry_basis,
                    "entry_fill_basis": entry_fill,
                    "signal_z": pending["signal_z"],
                    "entry_theta": entry_theta,
                    "entry_stationary_std_bp": entry_std,
                    "entry_half_life_bd": entry_half_life,
                    "entry_z": entry_z,
                    "entry_residual_abs": abs(entry_basis - entry_theta),
                    "bars_held": 0,
                    "min_basis": entry_basis,
                    "max_basis": entry_basis,
                    "max_favorable_bp": 0.0,
                    "max_adverse_bp": 0.0,
                }
            )
            next_trade_id += 1

        remaining_positions: list[dict[str, object]] = []
        for position in positions:
            position = dict(position)
            position["bars_held"] = int(position["bars_held"]) + 1
            side = str(position["side"])
            basis = float(row["basis_bp"])
            position["min_basis"] = min(float(position["min_basis"]), basis)
            position["max_basis"] = max(float(position["max_basis"]), basis)

            if side == "short":
                live_pnl_mid = float(position["entry_basis_mid"]) - basis
            else:
                live_pnl_mid = basis - float(position["entry_basis_mid"])
            position["max_favorable_bp"] = max(float(position["max_favorable_bp"]), live_pnl_mid)
            position["max_adverse_bp"] = min(float(position["max_adverse_bp"]), live_pnl_mid)

            current_theta = float(row["ou_theta"]) if np.isfinite(float(row["ou_theta"])) else float(position["entry_theta"])
            current_residual_abs = abs(basis - float(position["entry_theta"]))
            frozen_z = (basis - float(position["entry_theta"])) / float(position["entry_stationary_std_bp"])
            soft_half_life = int(np.ceil(float(position["entry_half_life_bd"])))
            hard_time_stop = max(
                soft_half_life,
                int(np.ceil(float(position["entry_half_life_bd"]) * cfg.max_half_lives)),
            )
            residual_halved = current_residual_abs <= 0.5 * float(position["entry_residual_abs"])
            z_exit = abs(frozen_z) <= cfg.exit_z_abs
            time_check_failed = (
                int(position["bars_held"]) >= soft_half_life
                and current_residual_abs > 0.5 * float(position["entry_residual_abs"])
            )
            hard_time_stop_hit = int(position["bars_held"]) >= hard_time_stop
            event_end_hit = date >= event_end
            if side == "short":
                stop_hit = frozen_z >= cfg.stop_z
            else:
                stop_hit = frozen_z <= -cfg.stop_z

            exit_reason = None
            if residual_halved:
                exit_reason = "residual_halved"
            elif z_exit:
                exit_reason = "z_mean_reverted"
            elif stop_hit:
                exit_reason = "stop_z"
            elif time_check_failed:
                exit_reason = "half_life_decay_failed"
            elif hard_time_stop_hit:
                exit_reason = "hard_time_stop"
            elif event_end_hit:
                exit_reason = "event_end"

            if exit_reason is None:
                remaining_positions.append(position)
                continue

            exit_basis = basis
            exit_fill = fill_price(exit_basis, side, "exit", cfg.half_spread_bp)
            if side == "short":
                gross_mid = float(position["entry_basis_mid"]) - exit_basis
                net = float(position["entry_fill_basis"]) - exit_fill
            else:
                gross_mid = exit_basis - float(position["entry_basis_mid"])
                net = exit_fill - float(position["entry_fill_basis"])

            trades.append(
                {
                    "trade_id": position["trade_id"],
                    "side": side,
                    "signal_date": position["signal_date"],
                    "entry_date": position["entry_date"],
                    "exit_date": date,
                    "exit_reason": exit_reason,
                    "entry_basis_mid": position["entry_basis_mid"],
                    "exit_basis_mid": exit_basis,
                    "entry_fill_basis": position["entry_fill_basis"],
                    "exit_fill_basis": exit_fill,
                    "signal_z": position["signal_z"],
                    "entry_theta": position["entry_theta"],
                    "exit_theta": current_theta,
                    "entry_stationary_std_bp": position["entry_stationary_std_bp"],
                    "entry_half_life_bd": position["entry_half_life_bd"],
                    "entry_z": position["entry_z"],
                    "exit_z": frozen_z,
                    "bars_held": position["bars_held"],
                    "gross_mid_pnl_bp": gross_mid,
                    "net_pnl_bp": net,
                    "cost_bp": gross_mid - net,
                    "max_favorable_bp": position["max_favorable_bp"],
                    "max_adverse_bp": position["max_adverse_bp"],
                }
            )
        positions = remaining_positions

        if i + 1 < len(rows):
            open_sides = {str(pos["side"]) for pos in positions}
            pending_sides = {str(entry["side"]) for entry in pending_entries}
            active_count = len(positions) + len(pending_entries)

            if bool(row["short_signal"]) and active_count < cfg.max_units and not (open_sides | pending_sides) - {"short"}:
                pending_entries.append(
                    {
                        "action": "entry",
                        "side": "short",
                        "signal_date": date,
                        "signal_z": float(row["ou_z"]),
                        "ou_theta": float(row["ou_theta"]),
                        "ou_stationary_std_bp": float(row["ou_stationary_std_bp"]),
                        "ou_half_life_bd": float(row["ou_half_life_bd"]),
                    }
                )
            elif bool(row["long_signal"]) and active_count < cfg.max_units and not (open_sides | pending_sides) - {"long"}:
                pending_entries.append(
                    {
                        "action": "entry",
                        "side": "long",
                        "signal_date": date,
                        "signal_z": float(row["ou_z"]),
                        "ou_theta": float(row["ou_theta"]),
                        "ou_stationary_std_bp": float(row["ou_stationary_std_bp"]),
                        "ou_half_life_bd": float(row["ou_half_life_bd"]),
                    }
                )

    trades_df = pd.DataFrame(trades)
    return rows, trades_df


def volatility_report(df: pd.DataFrame) -> pd.DataFrame:
    windows = [
        ("full_sample", None, None),
        ("pre_event_60_obs", None, "2026-06-19"),
        ("event_2026_06_20_to_07_15", "2026-06-20", "2026-07-15"),
        ("event_2026_07_01_to_07_15", "2026-07-01", "2026-07-15"),
    ]
    records = []
    for name, start, end in windows:
        x = df.copy()
        if start:
            x = x[x["Date"] >= pd.Timestamp(start)]
        if end:
            x = x[x["Date"] <= pd.Timestamp(end)]
        if name == "pre_event_60_obs":
            x = x.tail(61)
        x = x.dropna(subset=["d_kofr_bp"])
        if x.empty:
            continue
        records.append(
            {
                "window": name,
                "start": x["Date"].min().date(),
                "end": x["Date"].max().date(),
                "obs": len(x),
                "kofr_abs_change_avg_bp": x["d_kofr_bp"].abs().mean(),
                "kofr_change_std_bp": x["d_kofr_bp"].std(ddof=1),
                "kofr_change_std_annualized_bp": x["d_kofr_bp"].std(ddof=1) * np.sqrt(252),
                "basis_mean_bp": x["basis_bp"].mean(),
                "basis_min_bp": x["basis_bp"].min(),
                "basis_max_bp": x["basis_bp"].max(),
            }
        )
    return pd.DataFrame(records)


def print_summary(df: pd.DataFrame, ou: OUParams, vol_threshold: float, trades: pd.DataFrame) -> None:
    print("=== KOFR transition OU backtest ===")
    print(f"Rows: {len(df)}, date range: {df['Date'].min().date()} ~ {df['Date'].max().date()}")
    print("")
    print("Fixed OU training parameters, for reference")
    print(f"  phi: {ou.phi:.4f}")
    print(f"  theta: {ou.theta:.2f} bp")
    print(f"  half-life: {ou.half_life_bd:.2f} business days")
    print(f"  residual std: {ou.resid_std_bp:.2f} bp")
    print(f"  stationary std: {ou.stationary_std_bp:.2f} bp")
    print("")
    print(f"KOFR volatility threshold: {vol_threshold:.2f} bp/day average absolute move")
    print("")
    print("Volatility report")
    print(volatility_report(df).round(3).to_string(index=False))
    print("")
    if trades.empty:
        print("No trades.")
    else:
        print("Trades")
        cols = [
            "trade_id",
            "side",
            "signal_date",
            "entry_date",
            "exit_date",
            "exit_reason",
            "entry_basis_mid",
            "exit_basis_mid",
            "entry_theta",
            "exit_theta",
            "entry_stationary_std_bp",
            "entry_half_life_bd",
            "signal_z",
            "entry_z",
            "exit_z",
            "bars_held",
            "gross_mid_pnl_bp",
            "net_pnl_bp",
            "cost_bp",
            "max_favorable_bp",
            "max_adverse_bp",
        ]
        print(trades[cols].round(3).to_string(index=False))
        print("")
        print("Performance")
        print(f"  trades: {len(trades)}")
        print(f"  gross pnl: {trades['gross_mid_pnl_bp'].sum():.2f} bp")
        print(f"  net pnl: {trades['net_pnl_bp'].sum():.2f} bp")
        print(f"  win rate: {(trades['net_pnl_bp'] > 0).mean() * 100:.1f}%")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="CD-KOFR transition OU basis backtest")
    parser.add_argument("--input", type=Path, default=None, help="Path to kofr.xlsm or prepared csv")
    parser.add_argument("--train-start", default=StrategyConfig.train_start)
    parser.add_argument("--train-end", default=StrategyConfig.train_end)
    parser.add_argument("--event-start", default=StrategyConfig.event_start)
    parser.add_argument("--event-end", default=StrategyConfig.event_end)
    parser.add_argument("--fixed-ou", action="store_true", help="Use one fixed OU fit instead of rolling OU signals")
    parser.add_argument("--rolling-ou-window", type=int, default=StrategyConfig.rolling_ou_window)
    parser.add_argument("--rolling-ou-min-obs", type=int, default=StrategyConfig.rolling_ou_min_obs)
    parser.add_argument("--entry-z", type=float, default=StrategyConfig.entry_z)
    parser.add_argument("--exit-z-abs", type=float, default=StrategyConfig.exit_z_abs)
    parser.add_argument("--vol-multiplier", type=float, default=StrategyConfig.vol_multiplier)
    parser.add_argument("--driver-multiplier", type=float, default=StrategyConfig.driver_multiplier)
    parser.add_argument(
        "--require-kofr-driven",
        action="store_true",
        help="Require the KOFR-driven basis filter for entries. By default it is diagnostics-only.",
    )
    parser.add_argument("--half-spread-bp", type=float, default=StrategyConfig.half_spread_bp)
    parser.add_argument("--max-units", type=int, default=StrategyConfig.max_units)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cfg = StrategyConfig(
        train_start=args.train_start,
        train_end=args.train_end,
        event_start=args.event_start,
        event_end=args.event_end,
        baseline_end=args.train_end,
        use_rolling_ou=not args.fixed_ou,
        rolling_ou_window=args.rolling_ou_window,
        rolling_ou_min_obs=args.rolling_ou_min_obs,
        vol_multiplier=args.vol_multiplier,
        driver_multiplier=args.driver_multiplier,
        require_kofr_driven=args.require_kofr_driven,
        entry_z=args.entry_z,
        exit_z_abs=args.exit_z_abs,
        half_spread_bp=args.half_spread_bp,
        max_units=args.max_units,
    )
    df = load_data(args.input)
    train = df[(df["Date"] >= pd.Timestamp(cfg.train_start)) & (df["Date"] <= pd.Timestamp(cfg.train_end))]
    ou = fit_ou(train["basis_bp"])
    signal_df, vol_threshold = add_signals(df, ou, cfg)
    diagnostics, trades = run_backtest(signal_df, ou, cfg)

    out_dir = Path.cwd() / "out"
    out_dir.mkdir(exist_ok=True)
    diagnostics.to_csv(out_dir / "kofr_transition_ou_diagnostics.csv", index=False, encoding="utf-8-sig")
    trades.to_csv(out_dir / "kofr_transition_ou_trades.csv", index=False, encoding="utf-8-sig")
    volatility_report(df).to_csv(out_dir / "kofr_transition_volatility_report.csv", index=False, encoding="utf-8-sig")

    print_summary(df, ou, vol_threshold, trades)
    print("")
    print(f"Saved diagnostics: {out_dir / 'kofr_transition_ou_diagnostics.csv'}")
    print(f"Saved trades: {out_dir / 'kofr_transition_ou_trades.csv'}")
    print(f"Saved volatility report: {out_dir / 'kofr_transition_volatility_report.csv'}")


if __name__ == "__main__":
    main()
