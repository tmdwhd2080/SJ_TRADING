# -*- coding: utf-8 -*-
"""
Collect GICS sector ETF data and save CSV files.

Usage:
    python -m sector_fundflow.run_collect
    python sector_fundflow/run_collect.py
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from MCSI.sector_fundflow.collector import DEFAULT_LOOKBACK_DAYS, collect_all
from MCSI.sector_fundflow.etf_map import SECTOR_ETF_MAP, ticker_sector_map

try:
    from trading.config import load_config

    _cfg = load_config()
    _env_label = f"KIWOOM_ENV={_cfg.env}"
except Exception:
    _env_label = "(trading config unavailable)"


OUTPUT_DIR = Path(__file__).resolve().parent / "output"


def _hr(w: int = 60) -> str:
    return "-" * w


def main() -> int:
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    print(_hr())
    print("  GICS 11 Sector ETF Data Collection")
    print(f"  {datetime.now():%Y-%m-%d %H:%M:%S}  |  {_env_label}")
    print(f"  Period: last {DEFAULT_LOOKBACK_DAYS} calendar days (~3 years), daily")
    print(_hr())
    print()

    print("[Sector -> ETF Mapping]")
    print(f"  {'GICS Sector':<28} {'ETF Name':<34} {'Code':<8} {'Brand'}")
    print("  " + _hr(90))
    for sector in SECTOR_ETF_MAP:
        note = f"  *{sector.note}" if sector.note else ""
        print(
            f"  {sector.gics_sector:<28} {sector.etf_name:<34} "
            f"{sector.ticker:<8} {sector.brand}{note}"
        )
    print()

    print("[Data Sources]")
    print("  ETF OHLCV + Volume : Kiwoom REST API (ka10081)")
    print("  KOSPI Index        : Kiwoom REST API (ka20006)")
    print("  Flow Proxy         : Kiwoom REST API (ka10060 investor net buying)")
    print("  fund_flow column   : institution_net_buy + foreign_net_buy")
    print()

    print("[Data Collection Start]")
    data = collect_all(lookback_days=DEFAULT_LOOKBACK_DAYS)

    etf_price = data["etf_price"]
    fund_flow = data["fund_flow"]
    kospi = data["kospi"]

    if etf_price.empty:
        print("[ERROR] ETF price data is empty.", file=sys.stderr)
        return 1

    sec_map = ticker_sector_map()
    if not etf_price.empty:
        etf_price["gics_sector"] = etf_price["ticker"].map(sec_map)
    if not fund_flow.empty:
        fund_flow["gics_sector"] = fund_flow["ticker"].map(sec_map)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    p_path = OUTPUT_DIR / "sector_etf_price.csv"
    f_path = OUTPUT_DIR / "sector_fund_flow.csv"
    k_path = OUTPUT_DIR / "kospi_daily.csv"
    m_path = OUTPUT_DIR / "sector_all_merged.csv"

    etf_price.to_csv(p_path, index=False, encoding="utf-8-sig")
    fund_flow.to_csv(f_path, index=False, encoding="utf-8-sig")
    kospi.to_csv(k_path, index=False, encoding="utf-8-sig")

    if not fund_flow.empty:
        flow_cols = [
            "date",
            "ticker",
            "close_kiwoom",
            "trading_amount_kiwoom",
            "fund_flow",
            "flow_source",
            "institution_net_buy",
            "foreign_net_buy",
            "individual_net_buy",
            "finance_invest_net_buy",
            "insurance_net_buy",
            "trust_net_buy",
            "other_finance_net_buy",
            "bank_net_buy",
            "pension_net_buy",
            "private_fund_net_buy",
            "nation_net_buy",
            "other_corp_net_buy",
            "other_foreign_net_buy",
        ]
        flow_cols = [c for c in flow_cols if c in fund_flow.columns]
        merged = pd.merge(etf_price, fund_flow[flow_cols], on=["date", "ticker"], how="left")
    else:
        merged = etf_price.copy()

    if not kospi.empty and {"date", "close"}.issubset(kospi.columns):
        kospi_join = kospi[["date", "close"]].rename(columns={"close": "kospi_close"})
        merged = pd.merge(merged, kospi_join, on="date", how="left")

    merged.to_csv(m_path, index=False, encoding="utf-8-sig")

    print()
    print(_hr())
    print("[Save Complete]")
    print(f"  [>] ETF Price/Volume : {p_path}")
    print(f"  [>] Fund Flow        : {f_path}")
    print(f"  [>] KOSPI Daily      : {k_path}")
    print(f"  [>] Merged           : {m_path}")
    print()
    print(f"  ETF tickers  : {etf_price['ticker'].nunique()}")
    print(f"  Date range   : {etf_price['date'].min()} ~ {etf_price['date'].max()}")
    print(f"  ETF rows     : {len(etf_price):,}")
    print(f"  KOSPI rows   : {len(kospi):,}")
    print(f"  Flow rows    : {len(fund_flow):,}")
    print(_hr())

    return 0


if __name__ == "__main__":
    sys.exit(main())
