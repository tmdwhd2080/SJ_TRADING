"""Scrape public Investing.com economic-calendar tables with Selenium.

The scraper reads the visible event-history table, clicks the public "more"
button when available, and writes actual/forecast/previous values to CSV.
It does not log in or try to bypass access controls.
"""

from __future__ import annotations

import argparse
import csv
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.common.exceptions import JavascriptException, TimeoutException, WebDriverException
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


EVENTS = {
    "ADP": {
        "indicator": "ADP_consensus",
        "url": "https://kr.investing.com/economic-calendar/adp-nonfarm-employment-change-1",
        "frequency": "monthly",
    },
    "PAYEMS": {
        "indicator": "PAYEMS_consensus",
        "url": "https://kr.investing.com/economic-calendar/nonfarm-payrolls-227",
        "frequency": "monthly",
    },
    "ICSA": {
        "indicator": "ICSA_consensus",
        "url": "https://kr.investing.com/economic-calendar/initial-jobless-claims-294",
        "frequency": "weekly",
    },
}

MONTH_NAMES = {
    "1월": 1,
    "2월": 2,
    "3월": 3,
    "4월": 4,
    "5월": 5,
    "6월": 6,
    "7월": 7,
    "8월": 8,
    "9월": 9,
    "10월": 10,
    "11월": 11,
    "12월": 12,
    "Jan": 1,
    "Feb": 2,
    "Mar": 3,
    "Apr": 4,
    "May": 5,
    "Jun": 6,
    "Jul": 7,
    "Aug": 8,
    "Sep": 9,
    "Oct": 10,
    "Nov": 11,
    "Dec": 12,
}


@dataclass
class ParsedDate:
    release_date: str
    target_date: str
    target_label: str


def clean_cell(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def parse_value_to_thousands(raw: str) -> float | None:
    text = clean_cell(raw)
    if not text or text in {"-", "--", "N/A"}:
        return None

    negative = text.startswith("(") and text.endswith(")")
    text = text.strip("()")
    text = text.replace(",", "").replace("+", "")
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None

    value = float(match.group(0))
    if negative:
        value = -value

    upper = text.upper()
    if "M" in upper:
        return value * 1000.0
    if "B" in upper:
        return value * 1_000_000.0
    # For the three labor-market events here, K means thousands.
    return value


def parse_release_and_target(date_text: str, frequency: str) -> ParsedDate | None:
    text = clean_cell(date_text)
    match = re.search(r"(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일", text)
    if not match:
        match = re.search(r"([A-Za-z]{3})\s+(\d{1,2}),\s+(\d{4})", text)
        if not match:
            return None
        release_year = int(match.group(3))
        release_month = MONTH_NAMES[match.group(1)]
        release_day = int(match.group(2))
    else:
        release_year = int(match.group(1))
        release_month = int(match.group(2))
        release_day = int(match.group(3))

    release_date = f"{release_year:04d}-{release_month:02d}-{release_day:02d}"
    target_date = release_date
    target_label = ""

    reference = re.search(r"\(([^)]+)\)", text)
    if reference:
        target_label = reference.group(1).strip()
        if frequency == "monthly":
            month = MONTH_NAMES.get(target_label)
            if month is not None:
                target_year = release_year - 1 if month > release_month else release_year
                target_date = f"{target_year:04d}-{month:02d}-01"

    return ParsedDate(release_date=release_date, target_date=target_date, target_label=target_label)


def make_driver(headless: bool) -> webdriver.Chrome:
    options = ChromeOptions()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--window-size=1440,1400")
    options.add_argument("--lang=ko-KR")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.binary_location = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    return webdriver.Chrome(options=options)


def accept_public_cookie_prompt(driver: webdriver.Chrome) -> None:
    labels = ["동의", "동의합니다", "Accept", "Accept All", "I Accept", "AGREE"]
    for label in labels:
        xpath = (
            "//button[contains(normalize-space(.), {q})] | "
            "//a[contains(normalize-space(.), {q})]"
        ).format(q=repr(label))
        try:
            candidates = driver.find_elements(By.XPATH, xpath)
            for candidate in candidates[:2]:
                if candidate.is_displayed() and candidate.is_enabled():
                    candidate.click()
                    time.sleep(0.7)
                    return
        except WebDriverException:
            continue


def parse_rows_from_html(html: str, event_key: str, event: dict[str, str], scraped_at: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str, str]] = set()

    for tr in soup.find_all("tr"):
        cells = [clean_cell(cell.get_text(" ", strip=True)) for cell in tr.find_all(["td", "th"])]
        if len(cells) < 5:
            continue
        parsed = parse_release_and_target(cells[0], event["frequency"])
        if parsed is None:
            continue

        key = (event_key, parsed.release_date, parsed.target_date, cells[2], cells[3])
        if key in seen:
            continue
        seen.add(key)

        rows.append(
            {
                "indicator": event["indicator"],
                "event_key": event_key,
                "event_url": event["url"],
                "release_date": parsed.release_date,
                "release_time": cells[1],
                "target_date": parsed.target_date,
                "target_label": parsed.target_label,
                "actual_raw": cells[2],
                "forecast_raw": cells[3],
                "previous_raw": cells[4],
                "actual_value_thousands": parse_value_to_thousands(cells[2]),
                "forecast_value_thousands": parse_value_to_thousands(cells[3]),
                "previous_value_thousands": parse_value_to_thousands(cells[4]),
                "scraped_at": scraped_at,
            }
        )

    rows.sort(key=lambda row: (row["target_date"], row["release_date"]))
    return rows


def click_more(driver: webdriver.Chrome) -> bool:
    text_xpath = (
        "//*[contains(normalize-space(.), '더보기') or "
        "contains(normalize-space(.), '더 보기') or "
        "contains(normalize-space(.), '더 보여주기') or "
        "contains(normalize-space(.), 'Show More') or "
        "contains(normalize-space(.), 'Load More')]"
    )
    attr_xpath = (
        "//*[contains(translate(@id, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'showmore') or "
        "contains(translate(@class, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'showmore') or "
        "contains(translate(@data-test, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'showmore')]"
    )
    try:
        candidates = driver.find_elements(By.XPATH, f"({text_xpath}) | ({attr_xpath})")
    except WebDriverException:
        return False

    for candidate in candidates:
        try:
            text = clean_cell(candidate.text)
            if text and len(text) > 80:
                continue
            if not candidate.is_displayed() or not candidate.is_enabled():
                continue
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", candidate)
            time.sleep(0.4)
            try:
                candidate.click()
            except WebDriverException:
                driver.execute_script("arguments[0].click();", candidate)
            time.sleep(1.4)
            return True
        except (JavascriptException, WebDriverException):
            continue
    return False


def scrape_event(
    driver: webdriver.Chrome,
    event_key: str,
    event: dict[str, str],
    start_target_date: str,
    max_clicks: int,
    scraped_at: str,
) -> list[dict[str, Any]]:
    driver.get(event["url"])
    WebDriverWait(driver, 25).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    time.sleep(2.5)
    accept_public_cookie_prompt(driver)

    rows = parse_rows_from_html(driver.page_source, event_key, event, scraped_at)
    previous_count = -1

    for _ in range(max_clicks):
        if rows and min(row["target_date"] for row in rows) <= start_target_date:
            break
        if len(rows) == previous_count:
            break
        previous_count = len(rows)
        if not click_more(driver):
            break
        rows = parse_rows_from_html(driver.page_source, event_key, event, scraped_at)

    return [row for row in rows if row["target_date"] >= start_target_date]


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "indicator",
        "event_key",
        "event_url",
        "release_date",
        "release_time",
        "target_date",
        "target_label",
        "actual_raw",
        "forecast_raw",
        "previous_raw",
        "actual_value_thousands",
        "forecast_value_thousands",
        "previous_value_thousands",
        "scraped_at",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def parse_events(value: str) -> list[str]:
    selected = [item.strip().upper() for item in value.split(",") if item.strip()]
    unknown = [item for item in selected if item not in EVENTS]
    if unknown:
        raise argparse.ArgumentTypeError(f"Unknown event key(s): {', '.join(unknown)}")
    return selected


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    script_dir = Path(__file__).resolve().parent
    parser.add_argument("--events", type=parse_events, default=parse_events("ADP,PAYEMS,ICSA"))
    parser.add_argument("--start-target-date", default="2022-09-01")
    parser.add_argument("--max-clicks", type=int, default=40)
    parser.add_argument("--headed", action="store_true", help="Show Chrome instead of running headless.")
    parser.add_argument(
        "--output-file",
        default=str(script_dir / "data" / "investing_consensus_2022-09_present" / "investing_consensus.csv"),
    )
    args = parser.parse_args()

    scraped_at = datetime.now().isoformat(timespec="seconds")
    all_rows: list[dict[str, Any]] = []
    driver = make_driver(headless=not args.headed)
    try:
        for event_key in args.events:
            event = EVENTS[event_key]
            rows = scrape_event(
                driver=driver,
                event_key=event_key,
                event=event,
                start_target_date=args.start_target_date,
                max_clicks=args.max_clicks,
                scraped_at=scraped_at,
            )
            print(f"{event_key}: rows={len(rows)}")
            all_rows.extend(rows)
    finally:
        driver.quit()

    all_rows.sort(key=lambda row: (row["event_key"], row["target_date"], row["release_date"]))
    output_file = Path(args.output_file)
    write_csv(output_file, all_rows)
    print(f"Wrote {len(all_rows)} rows to {output_file}")
    print(f"generated_at={scraped_at}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
