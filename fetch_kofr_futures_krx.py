from __future__ import annotations

import argparse
import contextlib
import io
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd


KOFR_FUTURES_PRODUCT = "KRDRVFURFR"


def load_pykrx_stock():
    from etf_fair_value.krx_pdf import load_env_files

    # pykrx/login helpers can print account diagnostics. Keep secrets out of stdout.
    muted = io.StringIO()
    with contextlib.redirect_stdout(muted), contextlib.redirect_stderr(muted):
        load_env_files()
        from pykrx import stock

    return stock


def fetch_daily_kofr_futures(date: str, stock=None) -> pd.DataFrame:
    if stock is None:
        stock = load_pykrx_stock()
    df = stock.get_future_ohlcv_by_ticker(date, KOFR_FUTURES_PRODUCT)
    if df.empty:
        return df
    out = df.reset_index().rename(columns={"종목코드": "ticker"})
    out.insert(0, "date", pd.to_datetime(date))
    out["contract_month"] = out["종목명"].astype(str).str.extract(r"F\s+(\d{6})", expand=False)
    out["is_spread"] = out["종목명"].astype(str).str.contains("SP", regex=False)
    out["close_implied_rate"] = 100.0 - pd.to_numeric(out["종가"], errors="coerce")
    out["spot_implied_rate"] = 100.0 - pd.to_numeric(out["현물가"], errors="coerce")
    out.loc[pd.to_numeric(out["종가"], errors="coerce") <= 0, "close_implied_rate"] = pd.NA
    return out


def fetch_daily_with_retry(date: pd.Timestamp, retries: int = 2, sleep_sec: float = 0.5) -> pd.DataFrame:
    stock = load_pykrx_stock()
    date_str = date.strftime("%Y%m%d")
    for attempt in range(retries + 1):
        try:
            return fetch_daily_kofr_futures(date_str, stock=stock)
        except Exception as exc:
            if attempt >= retries:
                return pd.DataFrame(
                    [
                        {
                            "date": date,
                            "error": f"{type(exc).__name__}: {str(exc)[:200]}",
                        }
                    ]
                )
            time.sleep(sleep_sec * (attempt + 1))


def fetch_range(start: str, end: str, workers: int = 1) -> pd.DataFrame:
    days = pd.date_range(start, end, freq="B")
    frames = []
    if workers <= 1:
        stock = load_pykrx_stock()
        for day in days:
            date = day.strftime("%Y%m%d")
            try:
                frame = fetch_daily_kofr_futures(date, stock=stock)
            except Exception as exc:
                frame = pd.DataFrame(
                    [
                        {
                            "date": day,
                            "error": f"{type(exc).__name__}: {str(exc)[:200]}",
                        }
                    ]
                )
            if not frame.empty:
                frames.append(frame)
    else:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_day = {executor.submit(fetch_daily_with_retry, day): day for day in days}
            for future in as_completed(future_to_day):
                frame = future.result()
                if not frame.empty:
                    frames.append(frame)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch KRX 3M KOFR futures via pykrx")
    parser.add_argument("--start", required=True, help="YYYY-MM-DD or YYYYMMDD")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD or YYYYMMDD")
    parser.add_argument("--output", default="out/kofr_futures_krx.csv")
    parser.add_argument("--workers", type=int, default=1, help="Parallel KRX requests. Use 1 if KRX throttles.")
    args = parser.parse_args()

    start = pd.Timestamp(args.start).strftime("%Y-%m-%d")
    end = pd.Timestamp(args.end).strftime("%Y-%m-%d")
    df = fetch_range(start, end, workers=args.workers)
    if not df.empty and "date" in df.columns:
        df = df.sort_values(["date"] + (["ticker"] if "ticker" in df.columns else [])).reset_index(drop=True)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"saved={out}")
    print(f"rows={len(df)}")
    if not df.empty and "종목명" in df.columns:
        cols = ["date", "ticker", "종목명", "종가", "현물가", "거래량", "close_implied_rate", "spot_implied_rate"]
        print(df[cols].head(20).to_string(index=False))


if __name__ == "__main__":
    main()
