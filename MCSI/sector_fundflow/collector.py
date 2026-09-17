# -*- coding: utf-8 -*-
"""
Sector ETF data collector.

Data sources:
  1) ETF daily OHLCV and turnover: Kiwoom REST API (ka10081)
  2) KOSPI daily chart: Kiwoom REST API (ka20006)
  3) ETF flow proxy: Kiwoom REST API (ka10060), daily investor net buying
"""

from __future__ import annotations

import logging
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from MCSI.sector_fundflow.etf_map import ticker_name_map, tickers  # noqa: E402

logger = logging.getLogger(__name__)


DEFAULT_LOOKBACK_DAYS = 365 * 3

# ka10060 amount mode is requested with unit_tp="1000", matching the official
# example. Store output in KRW-scale columns by multiplying raw values by 1,000.
FLOW_AMOUNT_UNIT_MULTIPLIER = 1000


def _date_str(dt: datetime | date) -> str:
    return dt.strftime("%Y%m%d")


def _to_date(v: str | date | datetime) -> date:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return datetime.strptime(str(v).replace("-", ""), "%Y%m%d").date()


def _to_number(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if not text or text == "-":
        return None
    # Kiwoom sometimes represents negative values as "--123".
    sign = -1 if text.startswith("-") else 1
    text = text.lstrip("+-")
    text = text.lstrip("-")
    try:
        return sign * float(text)
    except ValueError:
        return None


# ============================================================
#  1) ETF daily OHLCV - Kiwoom API (ka10081)
# ============================================================


def fetch_etf_ohlcv_kiwoom(stk_cd: str, start: str, end: str) -> pd.DataFrame:
    """Fetch one ETF's daily OHLCV from Kiwoom REST API."""
    from trading.service.data_loader import DataLoader

    loader = DataLoader()
    return loader.daily_ohlcv(stk_cd, start=start, end=end, adjusted=True)


# ============================================================
#  2) KOSPI daily chart - Kiwoom API (ka20006)
# ============================================================


def fetch_kospi_kiwoom(start: str, end: str) -> pd.DataFrame:
    """Fetch KOSPI daily chart from Kiwoom sector daily chart."""
    from trading.kiwoom.http_client import KiwoomClient
    from trading.kiwoom.tr.market_data import sector_daily_chart

    client = KiwoomClient()
    candles = sector_daily_chart(client, upjong_cd="001", base_dt=end, max_pages=10)

    if not candles:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume", "amount"])

    start_d = _to_date(start)
    end_d = _to_date(end)
    df = pd.DataFrame(
        [
            {
                "date": c.dt,
                "open": float(c.open),
                "high": float(c.high),
                "low": float(c.low),
                "close": float(c.close),
                "volume": c.volume,
                "amount": c.amount,
            }
            for c in candles
        ]
    )
    df = df.set_index("date").sort_index()
    return df[(df.index >= start_d) & (df.index <= end_d)]


# ============================================================
#  3) ETF flow proxy - Kiwoom API (ka10060)
# ============================================================


def fetch_etf_investor_flow_kiwoom(
    ticker: str,
    start: str,
    end: str,
    *,
    amount_unit_multiplier: int = FLOW_AMOUNT_UNIT_MULTIPLIER,
) -> pd.DataFrame:
    """
    Fetch daily ETF investor net buying from Kiwoom ka10060.

    This replaces ETF creation/redemption fund flow. It is secondary-market
    supply/demand, so `fund_flow` below is a proxy:

        fund_flow = institution_net_buy + foreign_net_buy

    Columns ending with `_net_buy` are KRW-scale amount proxies.
    """
    from trading.kiwoom.http_client import KiwoomClient

    client = KiwoomClient()
    rows = client.call_paginated(
        "ka10060",
        {
            "dt": end,
            "stk_cd": ticker,
            "amt_qty_tp": "1",  # 1: amount, 2: quantity
            "trde_tp": "0",     # net buying
            "unit_tp": "1000",
        },
        list_key="stk_invsr_orgn_chart",
        max_pages=80,
    )
    if not rows:
        return pd.DataFrame()

    start_d = _to_date(start)
    end_d = _to_date(end)
    records: list[dict[str, Any]] = []
    for row in rows:
        row_date_raw = row.get("dt")
        if not row_date_raw:
            continue
        row_date = _to_date(str(row_date_raw))
        if row_date < start_d or row_date > end_d:
            continue

        def amount(key: str) -> float | None:
            value = _to_number(row.get(key))
            return None if value is None else value * amount_unit_multiplier

        individual = amount("ind_invsr")
        foreign = amount("frgnr_invsr")
        institution = amount("orgn")
        finance_invest = amount("fnnc_invt")
        insurance = amount("insrnc")
        trust = amount("invtrt")
        other_finance = amount("etc_fnnc")
        bank = amount("bank")
        pension = amount("penfnd_etc")
        private_fund = amount("samo_fund")
        nation = amount("natn")
        other_corp = amount("etc_corp")
        other_foreign = amount("natfor")

        fund_flow_proxy = (institution or 0) + (foreign or 0)
        records.append(
            {
                "date": row_date,
                "close_kiwoom": _to_number(row.get("cur_prc")),
                "trading_amount_kiwoom": amount("acc_trde_prica"),
                "individual_net_buy": individual,
                "foreign_net_buy": foreign,
                "institution_net_buy": institution,
                "finance_invest_net_buy": finance_invest,
                "insurance_net_buy": insurance,
                "trust_net_buy": trust,
                "other_finance_net_buy": other_finance,
                "bank_net_buy": bank,
                "pension_net_buy": pension,
                "private_fund_net_buy": private_fund,
                "nation_net_buy": nation,
                "other_corp_net_buy": other_corp,
                "other_foreign_net_buy": other_foreign,
                "fund_flow": fund_flow_proxy,
                "flow_source": "kiwoom_ka10060_institution_plus_foreign_net_buy",
            }
        )

    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records).drop_duplicates(subset=["date"]).set_index("date")
    return df.sort_index()


def fetch_fund_flow(ticker: str, start: str, end: str) -> pd.DataFrame:
    """Fetch the ETF flow proxy used by this package."""
    try:
        return fetch_etf_investor_flow_kiwoom(ticker, start, end)
    except Exception as exc:
        logger.warning("Kiwoom ETF investor flow failed (%s): %s", ticker, exc)
        return pd.DataFrame()


# ============================================================
#  4) Collect and merge
# ============================================================


def collect_all(
    start: str | None = None,
    end: str | None = None,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> dict[str, pd.DataFrame]:
    """Collect all sector ETF, flow-proxy and KOSPI data."""
    if end is None:
        end_dt = datetime.now() - timedelta(days=1)
    else:
        end_dt = datetime.strptime(end, "%Y%m%d")

    if start is None:
        start_dt = end_dt - timedelta(days=lookback_days)
    else:
        start_dt = datetime.strptime(start, "%Y%m%d")

    s, e = _date_str(start_dt), _date_str(end_dt)
    etf_tickers = tickers()
    name_map = ticker_name_map()

    price_frames: list[pd.DataFrame] = []
    flow_frames: list[pd.DataFrame] = []

    for tk in etf_tickers:
        name = name_map.get(tk, tk)
        print(f"  [+] {name} ({tk}) ...")

        try:
            print("      -> Kiwoom API: OHLCV ...", end="")
            ohlcv = fetch_etf_ohlcv_kiwoom(tk, s, e)
            if ohlcv.empty:
                print(" (empty)")
            else:
                print(f" OK ({len(ohlcv)} rows)")
                price_frames.append(
                    pd.DataFrame(
                        {
                            "date": [
                                d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)
                                for d in ohlcv.index
                            ],
                            "ticker": tk,
                            "name": name,
                            "open": ohlcv["open"].values,
                            "high": ohlcv["high"].values,
                            "low": ohlcv["low"].values,
                            "close": ohlcv["close"].values,
                            "volume": ohlcv["volume"].values,
                            "amount": ohlcv["amount"].values,
                        }
                    )
                )
        except Exception as exc:
            print(f" FAIL: {exc}")

        try:
            print("      -> Kiwoom API: investor flow proxy ...", end="")
            flow = fetch_fund_flow(tk, s, e)
            if flow.empty:
                print(" (empty)")
            else:
                print(f" OK ({len(flow)} rows)")
                out = flow.reset_index()
                out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%d")
                out["ticker"] = tk
                out["name"] = name
                flow_frames.append(out)
        except Exception as exc:
            print(f" FAIL: {exc}")

        time.sleep(0.3)

    etf_price = pd.concat(price_frames, ignore_index=True) if price_frames else pd.DataFrame()
    fund_flow = pd.concat(flow_frames, ignore_index=True) if flow_frames else pd.DataFrame()

    print("  [+] KOSPI index ...")
    try:
        print("      -> Kiwoom API: ka20006 ...", end="")
        kospi_df = fetch_kospi_kiwoom(s, e)
        if kospi_df.empty:
            print(" (empty)")
        else:
            print(f" OK ({len(kospi_df)} rows)")
    except Exception as exc:
        print(f" FAIL: {exc}")
        kospi_df = pd.DataFrame()

    if not kospi_df.empty and "date" not in kospi_df.columns:
        kospi_out = kospi_df.reset_index()
        kospi_out.rename(columns={"index": "date"}, inplace=True)
    else:
        kospi_out = kospi_df.copy()

    return {
        "etf_price": etf_price,
        "fund_flow": fund_flow,
        "kospi": kospi_out,
    }
