# -*- coding: utf-8 -*-
"""Naver theme intraday stock portfolio pipeline.

The pipeline intentionally keeps its own English-column CSV files.  It can read
the older Theme_real beta_all_themes_YYYYMMDD.csv files as history, but every
file produced by this module is overwritten for the current run date.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import re
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from io import StringIO
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
import requests
from bs4 import BeautifulSoup


BASE_DIR = Path(__file__).resolve().parents[1]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Referer": "https://finance.naver.com/sise/theme.naver",
}

THEME_PAGE_URL = "https://finance.naver.com/sise/theme.naver?&page={page}"
THEME_DETAIL_URL = (
    "https://finance.naver.com/sise/sise_group_detail.naver?type=theme&no={theme_no}"
)
STOCK_NAVER_BASE = "https://stock.naver.com"
THEME_LIST_API = STOCK_NAVER_BASE + "/api/domestic/market/theme/list"
THEME_STOCKLIST_API = STOCK_NAVER_BASE + "/api/domestic/market/theme/{theme_no}/stocklist"

# Korean tokens are represented with escapes to keep this source ASCII-friendly.
K_THEME_NAME = "\ud14c\ub9c8\uba85"
K_RETURN = "\ub4f1\ub77d\ub960"
K_AVG_RETURN = "\ud3c9\uade0\ub4f1\ub77d\ub960"
K_KOSPI_RETURN = "\ucf54\uc2a4\ud53c\ub4f1\ub77d\ub960"
K_STOCK_NAME = "\uc885\ubaa9\uba85"
K_CURRENT_PRICE = "\ud604\uc7ac\uac00"
K_CHANGE_PRICE = "\uc804\uc77c\ube44"
K_VOLUME = "\uac70\ub798\ub7c9"
K_TRADING_VALUE = "\uac70\ub798\ub300\uae08"
K_PREV_VOLUME = "\uc804\uc77c\uac70\ub798\ub7c9"
K_UP = "\uc0c1\uc2b9"
K_DOWN = "\ud558\ub77d"


@dataclass
class PipelineConfig:
    output_dir: Path = BASE_DIR / "theme_intraday_ga_data"
    legacy_history_dir: Path = BASE_DIR / "theme_data"
    max_theme_pages: int = 20
    request_timeout: int = 10
    request_retries: int = 3
    request_sleep_sec: float = 0.35
    max_history_gap_days: int = 10
    allow_stale_history: bool = False
    max_candidate_stocks: int = 80
    portfolio_size: int = 10
    max_stock_weight: float = 0.20
    min_final_weight: float = 0.005
    ga_population: int = 120
    ga_generations: int = 80
    ga_mutation_rate: float = 0.18
    ga_elite_ratio: float = 0.12
    ga_tournament_k: int = 3
    random_seed: int = 42


class PipelineStop(RuntimeError):
    """Raised when the run saved useful partial data but cannot form a portfolio."""


def setup_logging() -> logging.Logger:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s")
    return logging.getLogger("theme_intraday_stock_ga")


log = setup_logging()


def clean_text(value: object) -> str:
    if value is None:
        return ""
    text = str(value).replace("\xa0", " ").strip()
    return re.sub(r"\s+", " ", text)


def parse_number(value: object) -> float:
    text = clean_text(value)
    if not text or text in {"-", "nan", "None"}:
        return float("nan")
    text = text.replace(",", "").replace("%", "").replace("+", "")
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return float("nan")
    try:
        return float(match.group(0))
    except ValueError:
        return float("nan")


def parse_percent(value: object) -> float:
    text = clean_text(value)
    if not text:
        return float("nan")
    sign = -1 if K_DOWN in text.lower() else 1
    value_num = parse_number(text)
    if math.isnan(value_num):
        return value_num
    if text.lstrip().startswith("-"):
        return value_num
    return sign * abs(value_num)


def parse_int(value: object) -> int | None:
    value_num = parse_number(value)
    if math.isnan(value_num):
        return None
    return int(value_num)


def parse_api_time(value: object, fallback: str) -> str:
    text = clean_text(value)
    if len(text) != 14 or not text.isdigit():
        return fallback
    return f"{text[:4]}-{text[4:6]}-{text[6:8]} {text[8:10]}:{text[10:12]}:{text[12:14]}"


def previous_business_dates(current_date: str, n_dates: int) -> list[str]:
    """Return previous Mon-Fri business dates before current_date."""
    current = np.datetime64(datetime.strptime(current_date, "%Y%m%d").date())
    dates = []
    cursor = current
    for _ in range(n_dates):
        cursor = np.busday_offset(cursor, -1, roll="backward")
        dates.append(pd.Timestamp(cursor).strftime("%Y%m%d"))
    return dates


def format_code(code: object) -> str:
    text = clean_text(code)
    if not text:
        return ""
    digits = re.sub(r"\D", "", text)
    return digits.zfill(6) if digits else text


def find_col(columns: Iterable[object], token: str, exact_first: bool = True) -> object | None:
    columns = list(columns)
    if exact_first:
        for col in columns:
            if str(col) == token:
                return col
    for col in columns:
        if token in str(col):
            return col
    return None


def request_get(url: str, config: PipelineConfig, *, headers: dict | None = None) -> requests.Response:
    last_exc: Exception | None = None
    for attempt in range(1, config.request_retries + 1):
        try:
            resp = requests.get(
                url,
                headers=headers or HEADERS,
                timeout=config.request_timeout,
            )
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:
            last_exc = exc
            if attempt < config.request_retries:
                wait = 1.2 * attempt
                log.warning("request failed %s/%s, retrying in %.1fs: %s", attempt, config.request_retries, wait, url)
                time.sleep(wait)
    raise RuntimeError(f"request failed: {url}") from last_exc


def request_json(url: str, config: PipelineConfig, *, headers: dict | None = None) -> object:
    resp = request_get(
        url,
        config,
        headers=headers
        or {
            **HEADERS,
            "Referer": "https://stock.naver.com/market/stock/kr/theme",
            "Accept": "application/json,text/plain,*/*",
        },
    )
    return resp.json()


def fetch_kospi_index(config: PipelineConfig, run_timestamp: str) -> dict:
    try:
        url = "https://m.stock.naver.com/api/index/KOSPI/basic"
        resp = request_get(
            url,
            config,
            headers={**HEADERS, "Referer": "https://m.stock.naver.com/"},
        )
        data = resp.json()
        return {
            "kospi_value": clean_text(data.get("closePrice")),
            "kospi_change": clean_text(data.get("compareToPreviousClosePrice")),
            "kospi_return_pct": parse_percent(data.get("fluctuationsRatio")),
            "kospi_timestamp": run_timestamp,
            "kospi_source": "naver_mobile_api",
        }
    except Exception as exc:  # pragma: no cover - network fallback
        log.warning("KOSPI mobile API failed, trying finance HTML: %s", exc)

    url = "https://finance.naver.com/sise/sise_index.naver?code=KOSPI"
    resp = request_get(url, config)
    resp.encoding = "euc-kr"
    soup = BeautifulSoup(resp.text, "html.parser")
    now_value = soup.select_one("#now_value")
    change_value = soup.select_one("#change_value_and_rate")
    change_text = clean_text(change_value.get_text(" ", strip=True) if change_value else "")
    return {
        "kospi_value": clean_text(now_value.get_text(strip=True) if now_value else ""),
        "kospi_change": change_text,
        "kospi_return_pct": parse_percent(change_text),
        "kospi_timestamp": run_timestamp,
        "kospi_source": "naver_finance_html",
    }


def get_last_theme_page(config: PipelineConfig) -> int:
    resp = request_get(THEME_PAGE_URL.format(page=1), config)
    resp.encoding = "euc-kr"
    soup = BeautifulSoup(resp.text, "html.parser")

    last = soup.select_one("td.pgRR a")
    if last:
        match = re.search(r"page=(\d+)", last.get("href", ""))
        if match:
            return int(match.group(1))

    page_numbers = []
    for tag in soup.select("table.Nnavi td a, table.Nnavi td strong"):
        text = clean_text(tag.get_text())
        if text.isdigit():
            page_numbers.append(int(text))
    return max(page_numbers) if page_numbers else 1


def parse_theme_page(page: int, config: PipelineConfig) -> pd.DataFrame:
    resp = request_get(THEME_PAGE_URL.format(page=page), config)
    resp.encoding = "euc-kr"
    soup = BeautifulSoup(resp.text, "html.parser")
    rows: list[dict] = []

    for tr in soup.select("table.type_1 tr"):
        tds = tr.find_all("td")
        if len(tds) < 6:
            continue
        link = tds[0].find("a")
        if not link:
            continue
        href = link.get("href", "")
        match = re.search(r"no=(\d+)", href)
        if not match:
            continue

        theme_return = parse_percent(tds[1].get_text(" ", strip=True))
        img = tds[1].find("img")
        if img:
            img_text = f"{img.get('src', '')} {img.get('alt', '')}".lower()
            if "down" in img_text or K_DOWN in img_text:
                theme_return = -abs(theme_return)
            elif "up" in img_text or K_UP in img_text:
                theme_return = abs(theme_return)

        rows.append(
            {
                "theme_no": str(int(match.group(1))),
                "theme_name": clean_text(link.get_text(strip=True)),
                "theme_return_pct": theme_return,
                "avg_stock_return_pct": parse_percent(tds[2].get_text(" ", strip=True)),
                "up_count": parse_int(tds[3].get_text(" ", strip=True)),
                "flat_count": parse_int(tds[4].get_text(" ", strip=True)),
                "down_count": parse_int(tds[5].get_text(" ", strip=True)),
            }
        )
    return pd.DataFrame(rows)


def crawl_all_themes_api(config: PipelineConfig, run_timestamp: str) -> pd.DataFrame:
    page_size = 100
    max_batches = max(config.max_theme_pages, 1)
    rows: list[dict] = []

    for batch in range(max_batches):
        start_idx = batch * page_size
        params = f"startIdx={start_idx}&pageSize={page_size}&sortType=changeRate"
        url = f"{THEME_LIST_API}?{params}"
        data = request_json(url, config)
        if not isinstance(data, list) or not data:
            break

        log.info("theme API batch %s: %s rows", batch + 1, len(data))
        for item in data:
            rows.append(
                {
                    "theme_no": str(item.get("no", "")),
                    "theme_name": clean_text(item.get("name")),
                    "theme_return_pct": parse_percent(item.get("changeRate")),
                    "avg_stock_return_pct": np.nan,
                    "up_count": parse_int(item.get("riseCnt")),
                    "flat_count": parse_int(item.get("steadyCnt")),
                    "down_count": parse_int(item.get("fallCnt")),
                    "total_count": parse_int(item.get("totalCnt")),
                    "total_acc_volume": parse_number(item.get("totalAccQuant")),
                    "total_acc_amount": parse_number(item.get("totalAccAmount")),
                    "total_market_cap": parse_number(item.get("totalMarketSum")),
                    "recent_3d_return_pct": parse_percent(item.get("recent3daysChangeRate")),
                    "naver_timestamp": parse_api_time(item.get("thistime"), run_timestamp),
                    "leading_item": clean_text(item.get("leadingItem")),
                    "source": "stock_naver_api",
                }
            )

        if len(data) < page_size:
            break
        time.sleep(config.request_sleep_sec)

    return pd.DataFrame(rows)


def finalize_theme_snapshot(
    df: pd.DataFrame,
    kospi: dict,
    run_date: str,
    run_timestamp: str,
) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()
    df["theme_no"] = df["theme_no"].astype(str)
    df["run_date"] = run_date
    df["run_timestamp"] = run_timestamp
    for key, value in kospi.items():
        df[key] = value
    df["theme_return_pct"] = pd.to_numeric(df["theme_return_pct"], errors="coerce")
    if "total_count" not in df.columns and {"up_count", "flat_count", "down_count"}.issubset(df.columns):
        counts = df[["up_count", "flat_count", "down_count"]].apply(pd.to_numeric, errors="coerce")
        df["total_count"] = counts.sum(axis=1)
    if "kospi_return_pct" not in df.columns:
        raise ValueError("KOSPI return is required but missing from current theme snapshot.")
    df["kospi_return_pct"] = pd.to_numeric(df["kospi_return_pct"], errors="coerce")
    if df["kospi_return_pct"].isna().any():
        raise ValueError("KOSPI return is required but could not be parsed.")
    df["theme_excess_return_pct"] = df["theme_return_pct"] - df["kospi_return_pct"]
    return df.sort_values("theme_excess_return_pct", ascending=False).reset_index(drop=True)


def crawl_all_themes(config: PipelineConfig, kospi: dict, run_date: str, run_timestamp: str) -> pd.DataFrame:
    try:
        api_df = crawl_all_themes_api(config, run_timestamp)
        if not api_df.empty:
            log.info("crawled Naver themes from API: %s rows", len(api_df))
            return finalize_theme_snapshot(api_df, kospi, run_date, run_timestamp)
    except Exception as exc:
        log.warning("theme API failed, falling back to legacy HTML parser: %s", exc)

    last_page = min(get_last_theme_page(config), config.max_theme_pages)
    log.info("crawling Naver themes: %s pages", last_page)
    frames = []
    for page in range(1, last_page + 1):
        log.info("theme page %s/%s", page, last_page)
        df = parse_theme_page(page, config)
        if df.empty:
            break
        frames.append(df)
        time.sleep(config.request_sleep_sec)

    if not frames:
        return pd.DataFrame()

    df = pd.concat(frames, ignore_index=True).drop_duplicates("theme_no", keep="first")
    df["source"] = "finance_naver_html"
    return finalize_theme_snapshot(df, kospi, run_date, run_timestamp)


def extract_stock_codes(table: BeautifulSoup) -> list[str]:
    codes = []
    for link in table.select('a[href*="main.naver?code="]'):
        match = re.search(r"code=(\w+)", link.get("href", ""))
        if match:
            codes.append(format_code(match.group(1)))
    return codes


def read_detail_table(table: BeautifulSoup) -> pd.DataFrame:
    html = str(table)
    df = pd.read_html(StringIO(html), encoding="euc-kr")[0]
    df = df.dropna(how="all")
    name_col = find_col(df.columns, K_STOCK_NAME)
    if name_col is not None:
        df = df.dropna(subset=[name_col])
    return df.reset_index(drop=True)


def get_theme_detail(theme_row: pd.Series, config: PipelineConfig, run_date: str, run_timestamp: str) -> pd.DataFrame:
    try:
        api_detail = get_theme_detail_api(theme_row, config, run_date, run_timestamp)
        if not api_detail.empty:
            return api_detail
    except Exception as exc:
        log.warning("stocklist API failed for theme_no=%s, falling back to HTML: %s", theme_row["theme_no"], exc)

    theme_no = str(theme_row["theme_no"])
    url = THEME_DETAIL_URL.format(theme_no=theme_no)
    resp = request_get(url, config)
    resp.encoding = "euc-kr"
    soup = BeautifulSoup(resp.text, "html.parser")
    table = soup.find("table", {"class": "type_5"})
    if table is None:
        return pd.DataFrame()

    try:
        raw = read_detail_table(table)
    except Exception as exc:
        log.warning("read_html failed for theme_no=%s: %s", theme_no, exc)
        return parse_detail_table_manually(table, theme_row, run_date, run_timestamp)

    if raw.empty:
        return pd.DataFrame()

    codes = extract_stock_codes(table)
    name_col = find_col(raw.columns, K_STOCK_NAME)
    return_col = find_col(raw.columns, K_RETURN)
    price_col = find_col(raw.columns, K_CURRENT_PRICE)
    change_col = find_col(raw.columns, K_CHANGE_PRICE)
    volume_col = find_col(raw.columns, K_VOLUME)
    value_col = find_col(raw.columns, K_TRADING_VALUE)
    prev_volume_col = find_col(raw.columns, K_PREV_VOLUME)

    records = []
    for idx, row in raw.iterrows():
        stock_code = codes[idx] if idx < len(codes) else ""
        stock_name = clean_text(row.get(name_col, "")) if name_col is not None else ""
        if not stock_code and not stock_name:
            continue
        records.append(
            {
                "run_date": run_date,
                "run_timestamp": run_timestamp,
                "theme_no": theme_no,
                "theme_name": theme_row.get("theme_name", ""),
                "theme_return_pct": theme_row.get("theme_return_pct", np.nan),
                "theme_excess_return_pct": theme_row.get("theme_excess_return_pct", np.nan),
                "theme_avg_return_pct": theme_row.get("avg_stock_return_pct", np.nan),
                "kospi_return_pct": theme_row.get("kospi_return_pct", np.nan),
                "stock_code": stock_code,
                "stock_name": stock_name,
                "stock_return_pct": parse_percent(row.get(return_col, np.nan)) if return_col is not None else np.nan,
                "current_price": parse_number(row.get(price_col, np.nan)) if price_col is not None else np.nan,
                "change_price": parse_number(row.get(change_col, np.nan)) if change_col is not None else np.nan,
                "volume": parse_number(row.get(volume_col, np.nan)) if volume_col is not None else np.nan,
                "trading_value": parse_number(row.get(value_col, np.nan)) if value_col is not None else np.nan,
                "prev_volume": parse_number(row.get(prev_volume_col, np.nan)) if prev_volume_col is not None else np.nan,
            }
        )
    return pd.DataFrame(records)


def get_theme_detail_api(theme_row: pd.Series, config: PipelineConfig, run_date: str, run_timestamp: str) -> pd.DataFrame:
    theme_no = str(theme_row["theme_no"])
    page_size = 100
    rows: list[dict] = []
    start_idx = 0

    while True:
        params = (
            "marketType=ALL&orderType=quantTop"
            f"&startIdx={start_idx}&pageSize={page_size}"
        )
        url = f"{THEME_STOCKLIST_API.format(theme_no=theme_no)}?{params}"
        data = request_json(url, config)
        if not isinstance(data, list) or not data:
            break

        for item in data:
            rows.append(
                {
                    "run_date": run_date,
                    "run_timestamp": run_timestamp,
                    "theme_no": theme_no,
                    "theme_name": theme_row.get("theme_name", ""),
                    "theme_return_pct": theme_row.get("theme_return_pct", np.nan),
                    "theme_excess_return_pct": theme_row.get("theme_excess_return_pct", np.nan),
                    "theme_avg_return_pct": theme_row.get("avg_stock_return_pct", np.nan),
                    "kospi_return_pct": theme_row.get("kospi_return_pct", np.nan),
                    "stock_code": format_code(item.get("itemcode")),
                    "stock_name": clean_text(item.get("itemname")),
                    "stock_return_pct": parse_percent(item.get("prevChangeRate")),
                    "current_price": parse_number(item.get("nowPrice")),
                    "change_price": parse_number(item.get("prevChangePrice")),
                    "volume": parse_number(item.get("tradeVolume")),
                    "trading_value": parse_number(item.get("tradeAmount")),
                    "prev_volume": parse_number(item.get("prevQuant")),
                    "market_cap": parse_number(item.get("marketSum")),
                    "market_status": clean_text(item.get("marketStatus")),
                    "trading_session_type": clean_text(item.get("tradingSessionType")),
                    "stock_info": clean_text(item.get("itemInfo")),
                    "source": "stock_naver_api",
                }
            )

        if len(data) < page_size:
            break
        start_idx += page_size
        time.sleep(config.request_sleep_sec)

    return pd.DataFrame(rows)


def parse_detail_table_manually(
    table: BeautifulSoup,
    theme_row: pd.Series,
    run_date: str,
    run_timestamp: str,
) -> pd.DataFrame:
    records = []
    for tr in table.select("tr"):
        link = tr.select_one('a[href*="main.naver?code="]')
        if not link:
            continue
        match = re.search(r"code=(\w+)", link.get("href", ""))
        texts = [clean_text(td.get_text(" ", strip=True)) for td in tr.find_all("td")]
        pct_text = next((text for text in texts if "%" in text), "")
        records.append(
            {
                "run_date": run_date,
                "run_timestamp": run_timestamp,
                "theme_no": str(theme_row["theme_no"]),
                "theme_name": theme_row.get("theme_name", ""),
                "theme_return_pct": theme_row.get("theme_return_pct", np.nan),
                "theme_excess_return_pct": theme_row.get("theme_excess_return_pct", np.nan),
                "theme_avg_return_pct": theme_row.get("avg_stock_return_pct", np.nan),
                "kospi_return_pct": theme_row.get("kospi_return_pct", np.nan),
                "stock_code": format_code(match.group(1) if match else ""),
                "stock_name": clean_text(link.get_text(strip=True)),
                "stock_return_pct": parse_percent(pct_text),
                "current_price": np.nan,
                "change_price": np.nan,
                "volume": np.nan,
                "trading_value": np.nan,
                "prev_volume": np.nan,
            }
        )
    return pd.DataFrame(records)


def crawl_details_for_themes(stage1_df: pd.DataFrame, config: PipelineConfig, run_date: str, run_timestamp: str) -> pd.DataFrame:
    frames = []
    total = len(stage1_df)
    for idx, (_, row) in enumerate(stage1_df.iterrows(), 1):
        log.info("theme detail %s/%s: %s (%s)", idx, total, row.get("theme_name", ""), row["theme_no"])
        detail = get_theme_detail(row, config, run_date, run_timestamp)
        if not detail.empty:
            frames.append(detail)
        time.sleep(config.request_sleep_sec)

    if not frames:
        return pd.DataFrame()

    df = pd.concat(frames, ignore_index=True)
    df["stock_return_pct"] = pd.to_numeric(df["stock_return_pct"], errors="coerce")
    df["theme_avg_return_pct"] = pd.to_numeric(df["theme_avg_return_pct"], errors="coerce")
    df["kospi_return_pct"] = pd.to_numeric(df["kospi_return_pct"], errors="coerce")
    df["theme_excess_return_pct"] = pd.to_numeric(df["theme_excess_return_pct"], errors="coerce")

    missing_avg = df["theme_avg_return_pct"].isna()
    if missing_avg.any():
        fallback_avg = df.groupby("theme_no")["stock_return_pct"].transform("mean")
        df.loc[missing_avg, "theme_avg_return_pct"] = fallback_avg[missing_avg]

    df["stock_alpha_pct"] = df["stock_return_pct"] - df["theme_avg_return_pct"]
    return df.sort_values("stock_alpha_pct", ascending=False).reset_index(drop=True)


def read_csv_any(path: Path) -> pd.DataFrame:
    for enc in ("utf-8-sig", "utf-8", "cp949"):
        try:
            return pd.read_csv(path, encoding=enc)
        except UnicodeDecodeError:
            continue
    return pd.read_csv(path)


def normalize_theme_history(df: pd.DataFrame, snapshot_date: str, source_file: Path) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()

    if "theme_return_pct" in df.columns:
        out = df.copy()
        if "kospi_return_pct" not in out.columns:
            raise ValueError(f"KOSPI return is required in history file: {source_file}")
    else:
        theme_name_col = find_col(df.columns, K_THEME_NAME)
        theme_return_col = find_col(df.columns, K_RETURN)
        avg_return_col = find_col(df.columns, K_AVG_RETURN)
        kospi_return_col = find_col(df.columns, K_KOSPI_RETURN)
        required = ["theme_no", theme_return_col]
        if any(col is None or col not in df.columns for col in required):
            return pd.DataFrame()
        if kospi_return_col is None or kospi_return_col not in df.columns:
            raise ValueError(f"KOSPI return is required in history file: {source_file}")
        out = pd.DataFrame(
            {
                "theme_no": df["theme_no"].astype(str),
                "theme_name": df[theme_name_col] if theme_name_col in df.columns else "",
                "theme_return_pct": df[theme_return_col].map(parse_percent),
                "avg_stock_return_pct": df[avg_return_col].map(parse_percent)
                if avg_return_col in df.columns
                else np.nan,
                "kospi_return_pct": df[kospi_return_col].map(parse_percent),
            }
        )

    out["theme_no"] = out["theme_no"].astype(str)
    out["theme_return_pct"] = pd.to_numeric(out["theme_return_pct"], errors="coerce")
    if "kospi_return_pct" not in out.columns:
        raise ValueError(f"KOSPI return is required in history file: {source_file}")
    out["kospi_return_pct"] = pd.to_numeric(out["kospi_return_pct"], errors="coerce")
    if out["kospi_return_pct"].isna().any():
        raise ValueError(f"KOSPI return could not be parsed in history file: {source_file}")
    out["avg_stock_return_pct"] = pd.to_numeric(out.get("avg_stock_return_pct", np.nan), errors="coerce")
    out["theme_excess_return_pct"] = out["theme_return_pct"] - out["kospi_return_pct"]
    out["snapshot_date"] = snapshot_date
    out["source_file"] = str(source_file)
    keep_cols = [
        "snapshot_date",
        "theme_no",
        "theme_name",
        "theme_return_pct",
        "avg_stock_return_pct",
        "kospi_return_pct",
        "theme_excess_return_pct",
        "source_file",
    ]
    for col in keep_cols:
        if col not in out.columns:
            out[col] = np.nan
    return out[keep_cols]


def load_theme_history(config: PipelineConfig, current_date: str) -> pd.DataFrame:
    sources: list[tuple[int, Path, str]] = []
    for path in sorted(config.output_dir.glob("theme_snapshot_*.csv")):
        match = re.search(r"theme_snapshot_(\d{8})\.csv$", path.name)
        if match and match.group(1) < current_date:
            sources.append((0, path, match.group(1)))

    for path in sorted(config.legacy_history_dir.glob("beta_all_themes_*.csv")):
        match = re.search(r"beta_all_themes_(\d{8})\.csv$", path.name)
        if match and match.group(1) < current_date:
            sources.append((1, path, match.group(1)))

    frames = []
    for priority, path, snapshot_date in sources:
        try:
            raw = read_csv_any(path)
            normalized = normalize_theme_history(raw, snapshot_date, path)
            if not normalized.empty:
                normalized["_priority"] = priority
                frames.append(normalized)
        except ValueError:
            raise
        except Exception as exc:
            log.warning("history load failed: %s (%s)", path, exc)

    if not frames:
        return pd.DataFrame()

    history = pd.concat(frames, ignore_index=True)
    history = history.sort_values(["snapshot_date", "theme_no", "_priority"])
    history = history.drop_duplicates(["snapshot_date", "theme_no"], keep="first")
    return history.drop(columns=["_priority"]).reset_index(drop=True)


def select_recent_history_dates(history: pd.DataFrame, current_date: str, config: PipelineConfig) -> tuple[str, str]:
    dates = sorted(history["snapshot_date"].dropna().astype(str).unique().tolist())
    if len(dates) < 2:
        raise PipelineStop("Need at least two prior theme snapshots before current run date.")

    if not config.allow_stale_history:
        d_date, d_minus_1_date = previous_business_dates(current_date, 2)
        available_dates = set(dates)
        missing_dates = [d for d in (d_minus_1_date, d_date) if d not in available_dates]
        if missing_dates:
            raise PipelineStop(
                f"Missing required prior business-day snapshots for {current_date}: "
                f"{', '.join(missing_dates)}. Need D-1 and D business-day snapshots."
            )
    else:
        d_minus_1_date, d_date = dates[-2], dates[-1]
    return d_minus_1_date, d_date


def filter_stage1_themes(current_df: pd.DataFrame, history: pd.DataFrame, config: PipelineConfig) -> tuple[pd.DataFrame, dict]:
    d_minus_1_date, d_date = select_recent_history_dates(history, current_df["run_date"].iloc[0], config)
    prev1 = history[history["snapshot_date"] == d_minus_1_date][
        ["theme_no", "theme_excess_return_pct", "theme_return_pct", "kospi_return_pct"]
    ].rename(
        columns={
            "theme_excess_return_pct": "excess_d_minus_1_pct",
            "theme_return_pct": "theme_return_d_minus_1_pct",
            "kospi_return_pct": "kospi_return_d_minus_1_pct",
        }
    )
    prev2 = history[history["snapshot_date"] == d_date][
        ["theme_no", "theme_excess_return_pct", "theme_return_pct", "kospi_return_pct"]
    ].rename(
        columns={
            "theme_excess_return_pct": "excess_d_pct",
            "theme_return_pct": "theme_return_d_pct",
            "kospi_return_pct": "kospi_return_d_pct",
        }
    )
    merged = current_df.merge(prev1, on="theme_no", how="inner").merge(prev2, on="theme_no", how="inner")
    if "total_count" in merged.columns:
        theme_count = pd.to_numeric(merged["total_count"], errors="coerce")
    else:
        theme_count = pd.Series(np.nan, index=merged.index)
    stage1 = merged[
        (merged["excess_d_minus_1_pct"] < 0)
        & (merged["excess_d_pct"] > 0)
        & (merged["theme_excess_return_pct"] > 0)
        & (theme_count > 4)
    ].copy()
    stage1["d_minus_1_date"] = d_minus_1_date
    stage1["d_date"] = d_date
    stage1 = stage1.sort_values("theme_excess_return_pct", ascending=False).reset_index(drop=True)
    meta = {
        "d_minus_1_date": d_minus_1_date,
        "d_date": d_date,
        "stage1_theme_count": int(len(stage1)),
        "stage1_min_theme_constituents": 5,
    }
    return stage1, meta


def filter_candidate_stocks(stock_df: pd.DataFrame) -> pd.DataFrame:
    if stock_df.empty:
        return pd.DataFrame()
    required = [
        "stock_code",
        "stock_return_pct",
        "theme_avg_return_pct",
        "kospi_return_pct",
        "theme_excess_return_pct",
    ]
    df = stock_df.dropna(subset=required).copy()
    df = df[
        (df["stock_return_pct"] > df["kospi_return_pct"])
        & (df["stock_return_pct"] < df["theme_avg_return_pct"])
    ]
    if df.empty:
        return pd.DataFrame()
    df["candidate_objective_pct"] = df["theme_excess_return_pct"]
    df = df.sort_values(["candidate_objective_pct", "stock_return_pct"], ascending=False)
    df = df.drop_duplicates("stock_code", keep="first")
    return df.reset_index(drop=True)


def normalize_with_cap(weights: np.ndarray, max_weight: float) -> np.ndarray:
    n = len(weights)
    if n == 0:
        return weights
    cap = max(float(max_weight), 1.0 / n)
    weights = np.maximum(weights.astype(float), 0.0)
    total = weights.sum()
    if total <= 1e-12:
        weights = np.ones(n) / n
    else:
        weights = weights / total

    for _ in range(50):
        over = weights > cap + 1e-12
        if not over.any():
            break
        excess = (weights[over] - cap).sum()
        weights[over] = cap
        under = ~over
        under_sum = weights[under].sum()
        if under_sum <= 1e-12:
            break
        weights[under] += weights[under] / under_sum * excess
    return weights / weights.sum()


def deterministic_top_cap(alpha: np.ndarray, max_weight: float) -> np.ndarray:
    n = len(alpha)
    weights = np.zeros(n)
    cap = max(float(max_weight), 1.0 / n)
    remaining = 1.0
    for idx in np.argsort(alpha)[::-1]:
        if remaining <= 1e-12:
            break
        alloc = min(cap, remaining)
        weights[idx] = alloc
        remaining -= alloc
    if remaining > 1e-12:
        weights += remaining / n
    return normalize_with_cap(weights, max_weight)


def normalize_selected_weights(weights: np.ndarray, max_weight: float) -> np.ndarray:
    """Normalize only currently positive weights, using a feasible cap.

    This keeps min-weight and portfolio-size pruning from reintroducing names
    that were intentionally removed.  If too few names remain for max_weight to
    sum to 100%, the effective cap is lifted to 1 / n_selected.
    """
    out = np.zeros_like(weights, dtype=float)
    active = weights > 0
    if not active.any():
        return out
    selected = weights[active]
    cap = max(float(max_weight), 1.0 / len(selected))
    selected = np.maximum(selected, 0.0)
    if selected.sum() <= 1e-12:
        selected = np.ones(len(selected)) / len(selected)
    else:
        selected = selected / selected.sum()

    for _ in range(50):
        over = selected > cap + 1e-12
        if not over.any():
            break
        excess = float((selected[over] - cap).sum())
        selected[over] = cap
        under = selected < cap - 1e-12
        capacity = cap - selected[under]
        capacity_sum = float(capacity.sum())
        if capacity_sum <= 1e-12:
            break
        selected[under] += excess * capacity / capacity_sum

    selected = selected / selected.sum()
    out[active] = selected
    return out


def tournament_select(rng: np.random.Generator, fitness: np.ndarray, k: int) -> int:
    k = min(k, len(fitness))
    contenders = rng.choice(len(fitness), size=k, replace=False)
    return int(contenders[np.argmax(fitness[contenders])])


def ga_optimize(alpha: np.ndarray, config: PipelineConfig) -> np.ndarray:
    n = len(alpha)
    if n == 1:
        return np.ones(1)

    rng = np.random.default_rng(config.random_seed)
    pop_size = max(config.ga_population, 8)
    elite_n = max(1, int(pop_size * config.ga_elite_ratio))

    population = rng.dirichlet(np.ones(n), size=pop_size)
    population = np.array([normalize_with_cap(w, config.max_stock_weight) for w in population])
    population[0] = np.ones(n) / n
    population[1] = deterministic_top_cap(alpha, config.max_stock_weight)

    best_w = population[1].copy()
    best_fit = float(best_w @ alpha)

    for _ in range(config.ga_generations):
        fitness = population @ alpha
        best_idx = int(np.argmax(fitness))
        if fitness[best_idx] > best_fit:
            best_fit = float(fitness[best_idx])
            best_w = population[best_idx].copy()

        elite_idx = np.argsort(fitness)[-elite_n:]
        new_population = [population[idx].copy() for idx in elite_idx]

        while len(new_population) < pop_size:
            p1 = population[tournament_select(rng, fitness, config.ga_tournament_k)]
            p2 = population[tournament_select(rng, fitness, config.ga_tournament_k)]
            blend = rng.random(n)
            child = blend * p1 + (1.0 - blend) * p2
            if rng.random() < config.ga_mutation_rate:
                child = child + rng.normal(0.0, 0.08, size=n)
            new_population.append(normalize_with_cap(child, config.max_stock_weight))

        population = np.vstack(new_population[:pop_size])

    return normalize_with_cap(best_w, config.max_stock_weight)


def build_portfolio(candidate_df: pd.DataFrame, config: PipelineConfig, run_timestamp: str) -> pd.DataFrame:
    if candidate_df.empty:
        return pd.DataFrame()

    objective_col = "candidate_objective_pct" if "candidate_objective_pct" in candidate_df.columns else "theme_excess_return_pct"
    universe = candidate_df.sort_values(objective_col, ascending=False).head(config.max_candidate_stocks).copy()
    objective_values = universe[objective_col].to_numpy(dtype=float)
    weights = ga_optimize(objective_values, config)

    weights[weights < config.min_final_weight] = 0.0
    if weights.sum() <= 1e-12:
        weights = deterministic_top_cap(objective_values, config.max_stock_weight)
    else:
        weights = normalize_selected_weights(weights, config.max_stock_weight)

    if config.portfolio_size > 0 and (weights > 0).sum() > config.portfolio_size:
        keep = np.argsort(weights)[::-1][: config.portfolio_size]
        trimmed = np.zeros_like(weights)
        trimmed[keep] = weights[keep]
        weights = normalize_selected_weights(trimmed, config.max_stock_weight)

    result = universe.copy()
    result["weight"] = weights
    result = result[result["weight"] > 0].copy()
    result["ga_objective_pct"] = result[objective_col]
    result["objective_contribution_pct"] = result["weight"] * result["ga_objective_pct"]
    objective = float(result["objective_contribution_pct"].sum())
    result["portfolio_objective_pct"] = objective
    result["run_timestamp"] = run_timestamp

    cols = [
        "run_date",
        "run_timestamp",
        "stock_code",
        "stock_name",
        "theme_no",
        "theme_name",
        "stock_return_pct",
        "theme_avg_return_pct",
        "stock_alpha_pct",
        "kospi_return_pct",
        "ga_objective_pct",
        "weight",
        "objective_contribution_pct",
        "portfolio_objective_pct",
        "current_price",
        "theme_return_pct",
        "theme_excess_return_pct",
        "volume",
        "trading_value",
    ]
    for col in cols:
        if col not in result.columns:
            result[col] = np.nan
    return result[cols].sort_values(["weight", "ga_objective_pct"], ascending=False).reset_index(drop=True)


def write_csv_overwrite(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")
    log.info("saved: %s (%s rows)", path, len(df))


def write_json_overwrite(data: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("saved: %s", path)


def write_dated_and_latest(df: pd.DataFrame, output_dir: Path, stem: str, run_date: str) -> None:
    write_csv_overwrite(df, output_dir / f"{stem}_{run_date}.csv")
    write_csv_overwrite(df, output_dir / f"latest_{stem}.csv")


def print_table(df: pd.DataFrame, cols: list[str], title: str, n: int = 20) -> None:
    print(f"\n[{title}]")
    if df.empty:
        print("  empty")
        return
    print(df[cols].head(n).to_string(index=False))


def run_pipeline(config: PipelineConfig) -> dict:
    now = datetime.now()
    run_date = now.strftime("%Y%m%d")
    run_timestamp = now.strftime("%Y-%m-%d %H:%M:%S")
    config.output_dir.mkdir(parents=True, exist_ok=True)

    summary: dict = {
        "status": "started",
        "run_date": run_date,
        "run_timestamp": run_timestamp,
        "config": {k: str(v) if isinstance(v, Path) else v for k, v in asdict(config).items()},
    }

    try:
        log.info("run timestamp: %s", run_timestamp)
        kospi = fetch_kospi_index(config, run_timestamp)
        log.info("KOSPI return: %s%% (%s)", kospi.get("kospi_return_pct"), kospi.get("kospi_source"))

        themes = crawl_all_themes(config, kospi, run_date, run_timestamp)
        if themes.empty:
            raise PipelineStop("No theme rows were crawled from Naver.")
        write_dated_and_latest(themes, config.output_dir, "theme_snapshot", run_date)
        summary["theme_count"] = int(len(themes))

        history = load_theme_history(config, run_date)
        stage1, stage_meta = filter_stage1_themes(themes, history, config)
        summary.update(stage_meta)
        write_dated_and_latest(stage1, config.output_dir, "stage1_themes", run_date)
        print_table(
            stage1,
            [
                "theme_no",
                "theme_name",
                "excess_d_minus_1_pct",
                "excess_d_pct",
                "theme_excess_return_pct",
                "theme_return_pct",
            ],
            "Stage 1 themes: excess down -> up -> up",
        )
        if stage1.empty:
            raise PipelineStop("No themes passed stage 1.")

        stock_snapshot = crawl_details_for_themes(stage1, config, run_date, run_timestamp)
        write_dated_and_latest(stock_snapshot, config.output_dir, "stock_snapshot", run_date)
        summary["stage1_stock_rows"] = int(len(stock_snapshot))
        if stock_snapshot.empty:
            raise PipelineStop("No stock detail rows were crawled for stage 1 themes.")

        candidates = filter_candidate_stocks(stock_snapshot)
        write_dated_and_latest(candidates, config.output_dir, "candidate_stocks", run_date)
        summary["candidate_stock_count"] = int(len(candidates))
        print_table(
            candidates,
            ["stock_code", "stock_name", "theme_name", "stock_return_pct", "theme_avg_return_pct", "stock_alpha_pct"],
            "Candidate stocks: stock return - theme average > 0",
        )
        if candidates.empty:
            raise PipelineStop("No stocks had positive stock alpha.")

        portfolio = build_portfolio(candidates, config, run_timestamp)
        write_dated_and_latest(portfolio, config.output_dir, "portfolio", run_date)
        summary["portfolio_stock_count"] = int(len(portfolio))
        summary["portfolio_objective_pct"] = (
            float(portfolio["portfolio_objective_pct"].iloc[0]) if not portfolio.empty else 0.0
        )
        print_table(
            portfolio,
            ["stock_code", "stock_name", "theme_name", "stock_alpha_pct", "weight", "objective_contribution_pct"],
            "Final GA stock portfolio",
        )
        summary["status"] = "completed"
        return summary
    except PipelineStop as exc:
        summary["status"] = "stopped"
        summary["reason"] = str(exc)
        log.warning("%s", exc)
        return summary
    finally:
        write_json_overwrite(summary, config.output_dir / f"run_summary_{run_date}.json")
        write_json_overwrite(summary, config.output_dir / "latest_run_summary.json")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Naver intraday theme stock GA portfolio pipeline.")
    parser.add_argument("--output-dir", type=Path, default=PipelineConfig.output_dir)
    parser.add_argument("--legacy-history-dir", type=Path, default=PipelineConfig.legacy_history_dir)
    parser.add_argument("--max-pages", type=int, default=PipelineConfig.max_theme_pages)
    parser.add_argument("--allow-stale-history", action="store_true")
    parser.add_argument("--max-history-gap-days", type=int, default=PipelineConfig.max_history_gap_days)
    parser.add_argument("--portfolio-size", type=int, default=PipelineConfig.portfolio_size)
    parser.add_argument("--max-stock-weight", type=float, default=PipelineConfig.max_stock_weight)
    parser.add_argument("--max-candidate-stocks", type=int, default=PipelineConfig.max_candidate_stocks)
    parser.add_argument("--ga-population", type=int, default=PipelineConfig.ga_population)
    parser.add_argument("--ga-generations", type=int, default=PipelineConfig.ga_generations)
    parser.add_argument("--random-seed", type=int, default=PipelineConfig.random_seed)
    return parser


def config_from_args(args: argparse.Namespace) -> PipelineConfig:
    return PipelineConfig(
        output_dir=args.output_dir,
        legacy_history_dir=args.legacy_history_dir,
        max_theme_pages=args.max_pages,
        allow_stale_history=args.allow_stale_history,
        max_history_gap_days=args.max_history_gap_days,
        portfolio_size=args.portfolio_size,
        max_stock_weight=args.max_stock_weight,
        max_candidate_stocks=args.max_candidate_stocks,
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

    parser = build_arg_parser()
    args = parser.parse_args(argv)
    summary = run_pipeline(config_from_args(args))
    print("\n[Run summary]")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary.get("status") in {"completed", "stopped"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
