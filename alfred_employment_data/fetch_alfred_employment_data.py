"""Fetch ALFRED/FRED labor-market revision events into a single CSV."""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen


API_BASE = "https://api.stlouisfed.org/fred"

SERIES = {
    "PAYEMS": {
        "label": "BLS all employees, total nonfarm",
        "source": "BLS via FRED/ALFRED",
        "notes": "Monthly level, thousands of persons, seasonally adjusted. Use MoM difference as NFP headline proxy.",
        "frequency": "monthly",
        "scale_to_thousands": 1.0,
    },
    "ADPMNUSNERSA": {
        "label": "ADP total nonfarm private payroll employment",
        "source": "ADP via FRED/ALFRED",
        "notes": "Monthly level, persons, seasonally adjusted. Use MoM difference / 1000 for thousands.",
        "frequency": "monthly",
        "scale_to_thousands": 0.001,
    },
    "ICSA": {
        "label": "Initial claims",
        "source": "DOL/ETA via FRED/ALFRED",
        "notes": "Weekly initial unemployment insurance claims, seasonally adjusted.",
        "frequency": "weekly",
        "scale_to_thousands": 0.001,
    },
}

INITIAL_INDICATORS = {
    "PAYEMS": "PAYEMS_monthly_change_thousands",
    "ADPMNUSNERSA": "ADP_monthly_change_thousands",
    "ICSA": "ICSA_weekly_level_count",
}


def read_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    raw = path.read_bytes()
    text: str | None = None
    for encoding in ("utf-8-sig", "cp949", "latin-1"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        return {}

    values: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def find_env_file() -> Path | None:
    candidates: list[Path] = []
    for start in (Path.cwd(), Path(__file__).resolve().parent):
        candidates.extend(parent / ".env" for parent in (start, *start.parents))

    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if resolved.exists():
            return resolved
    return None


def get_api_key() -> str:
    key = os.environ.get("FRED_API_KEY")
    if key:
        return key

    env_file = find_env_file()
    if env_file is not None:
        env_values = read_env_file(env_file)
        key = env_values.get("FRED_API_KEY")
        if key:
            return key

    raise RuntimeError("FRED_API_KEY was not found in the environment or .env")


def fred_get(endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
    api_key = get_api_key()
    query = {
        **params,
        "api_key": api_key,
        "file_type": "json",
    }
    url = f"{API_BASE}/{endpoint}?{urlencode(query)}"
    try:
        with urlopen(url, timeout=45) as response:
            payload = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"FRED API HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"FRED API request failed: {exc}") from exc

    data = json.loads(payload)
    if "error_code" in data:
        raise RuntimeError(f"FRED API error {data['error_code']}: {data.get('error_message')}")
    return data


def paged_observations(params: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    limit = 100000
    offset = 0
    while True:
        data = fred_get("series/observations", {**params, "limit": limit, "offset": offset})
        batch = data.get("observations", [])
        rows.extend(batch)
        count = int(data.get("count", len(rows)))
        offset += len(batch)
        if not batch or offset >= count:
            break
        time.sleep(0.2)
    return rows


def fetch_series_metadata(series_id: str) -> dict[str, Any]:
    data = fred_get("series", {"series_id": series_id})
    series = data.get("seriess") or data.get("series") or []
    return series[0] if series else {"id": series_id}


def fetch_vintage_dates(series_id: str, realtime_start: str, realtime_end: str) -> list[dict[str, str]]:
    data = fred_get(
        "series/vintagedates",
        {
            "series_id": series_id,
            "realtime_start": realtime_start,
            "realtime_end": realtime_end,
        },
    )
    return [{"series_id": series_id, "vintage_date": item} for item in data.get("vintage_dates", [])]


def clean_value(value: str) -> float | None:
    if value in ("", "."):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def vintage_column_to_date(series_id: str, column_name: str) -> str | None:
    prefix = f"{series_id}_"
    if not column_name.startswith(prefix):
        return None
    raw = column_name.removeprefix(prefix)
    if len(raw) != 8 or not raw.isdigit():
        return None
    return f"{raw[0:4]}-{raw[4:6]}-{raw[6:8]}"


def normalize_observations(series_id: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        if "value" in row:
            value = row.get("value")
            value_float = clean_value(str(value))
            if value_float is None:
                continue
            out.append(
                {
                    "series_id": series_id,
                    "date": row.get("date"),
                    "realtime_start": row.get("realtime_start"),
                    "realtime_end": row.get("realtime_end"),
                    "value": value,
                    "value_float": value_float,
                }
            )
            continue

        for key, value in row.items():
            vintage_date = vintage_column_to_date(series_id, key)
            if vintage_date is None:
                continue
            value_float = clean_value(str(value))
            if value_float is None:
                continue
            out.append(
                {
                    "series_id": series_id,
                    "date": row.get("date"),
                    "realtime_start": vintage_date,
                    "realtime_end": "",
                    "value": value,
                    "value_float": value_float,
                }
            )
    return out


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        field_set: list[str] = []
        for row in rows:
            for key in row:
                if key not in field_set:
                    field_set.append(key)
        fieldnames = field_set

    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def observation_year(row: dict[str, Any]) -> int | None:
    try:
        return datetime.strptime(str(row["date"]), "%Y-%m-%d").year
    except (KeyError, TypeError, ValueError):
        return None


def observation_in_range(row: dict[str, Any], start_date: str, end_date: str) -> bool:
    obs_date = str(row.get("date", ""))
    return start_date <= obs_date <= end_date


def revision_events(rows: list[dict[str, Any]], year: int) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    by_key: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        if observation_year(row) != year:
            continue
        key = (str(row["series_id"]), str(row["date"]))
        by_key.setdefault(key, []).append(row)

    for (series_id, obs_date), group in sorted(by_key.items()):
        group.sort(key=lambda item: str(item.get("realtime_start", "")))
        previous: dict[str, Any] | None = None
        for row in group:
            if previous is None:
                events.append(
                    {
                        "series_id": series_id,
                        "date": obs_date,
                        "event_type": "initial_or_first_available_in_window",
                        "revision_vintage_date": row.get("realtime_start"),
                        "previous_vintage_date": "",
                        "previous_value": "",
                        "revised_value": row.get("value"),
                        "revision_delta": "",
                    }
                )
                previous = row
                continue

            prev_value = previous.get("value_float")
            value = row.get("value_float")
            if prev_value != value:
                delta = "" if prev_value is None or value is None else value - prev_value
                events.append(
                    {
                        "series_id": series_id,
                        "date": obs_date,
                        "event_type": "revision",
                        "revision_vintage_date": row.get("realtime_start"),
                        "previous_vintage_date": previous.get("realtime_start"),
                        "previous_value": previous.get("value"),
                        "revised_value": row.get("value"),
                        "revision_delta": delta,
                    }
                )
            previous = row
    return events


def latest_snapshot(rows: list[dict[str, Any]], year: int) -> list[dict[str, Any]]:
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        if observation_year(row) != year:
            continue
        key = (str(row["series_id"]), str(row["date"]))
        if key not in latest or str(row.get("realtime_start", "")) > str(latest[key].get("realtime_start", "")):
            latest[key] = row
    return [latest[key] for key in sorted(latest)]


def monthly_changes(rows: list[dict[str, Any]], start_date: str, end_date: str) -> list[dict[str, Any]]:
    monthly_ids = [series_id for series_id, config in SERIES.items() if config["frequency"] == "monthly"]
    out: list[dict[str, Any]] = []

    for series_id in monthly_ids:
        series_rows = [row for row in rows if row["series_id"] == series_id and row["value_float"] is not None]
        vintages = sorted({str(row["realtime_start"]) for row in series_rows})
        for vintage in vintages:
            vintage_rows = [row for row in series_rows if row["realtime_start"] == vintage]
            vintage_rows.sort(key=lambda item: str(item["date"]))
            previous: dict[str, Any] | None = None
            for row in vintage_rows:
                if previous is not None and observation_in_range(row, start_date, end_date):
                    change = row["value_float"] - previous["value_float"]
                    out.append(
                        {
                            "series_id": series_id,
                            "date": row["date"],
                            "realtime_start": row["realtime_start"],
                            "realtime_end": row["realtime_end"],
                            "level": row["value_float"],
                            "previous_date": previous["date"],
                            "previous_level": previous["value_float"],
                            "monthly_change_native_units": change,
                            "monthly_change_thousands": change * SERIES[series_id]["scale_to_thousands"],
                        }
                    )
                previous = row
    return out


def monthly_change_revision_events(changes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    by_key: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in changes:
        key = (str(row["series_id"]), str(row["date"]))
        by_key.setdefault(key, []).append(row)

    for (series_id, obs_date), group in sorted(by_key.items()):
        group.sort(key=lambda item: str(item.get("realtime_start", "")))
        previous: dict[str, Any] | None = None
        for row in group:
            if previous is None:
                events.append(
                    {
                        "series_id": series_id,
                        "date": obs_date,
                        "event_type": "initial_or_first_available_in_window",
                        "revision_vintage_date": row.get("realtime_start"),
                        "previous_vintage_date": "",
                        "previous_monthly_change_native_units": "",
                        "revised_monthly_change_native_units": row.get("monthly_change_native_units"),
                        "revision_delta_native_units": "",
                        "previous_monthly_change_thousands": "",
                        "revised_monthly_change_thousands": row.get("monthly_change_thousands"),
                        "revision_delta_thousands": "",
                    }
                )
                previous = row
                continue

            prev_change = float(previous["monthly_change_native_units"])
            current_change = float(row["monthly_change_native_units"])
            if prev_change != current_change:
                prev_change_thousands = float(previous["monthly_change_thousands"])
                current_change_thousands = float(row["monthly_change_thousands"])
                events.append(
                    {
                        "series_id": series_id,
                        "date": obs_date,
                        "event_type": "revision",
                        "revision_vintage_date": row.get("realtime_start"),
                        "previous_vintage_date": previous.get("realtime_start"),
                        "previous_monthly_change_native_units": previous.get("monthly_change_native_units"),
                        "revised_monthly_change_native_units": row.get("monthly_change_native_units"),
                        "revision_delta_native_units": current_change - prev_change,
                        "previous_monthly_change_thousands": previous.get("monthly_change_thousands"),
                        "revised_monthly_change_thousands": row.get("monthly_change_thousands"),
                        "revision_delta_thousands": current_change_thousands - prev_change_thousands,
                    }
                )
            previous = row
    return events


def level_revision_rows(
    rows: list[dict[str, Any]],
    series_id: str,
    indicator: str,
    start_date: str,
    end_date: str,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    by_date: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if row["series_id"] != series_id or not observation_in_range(row, start_date, end_date):
            continue
        by_date.setdefault(str(row["date"]), []).append(row)

    for target_date, group in sorted(by_date.items()):
        group.sort(key=lambda item: str(item.get("realtime_start", "")))
        previous: dict[str, Any] | None = None
        for row in group:
            if previous is not None and previous.get("value_float") != row.get("value_float"):
                previous_value = float(previous["value_float"])
                revised_value = float(row["value_float"])
                out.append(
                    {
                        "indicator": indicator,
                        "release_date": row["realtime_start"],
                        "target_date": target_date,
                        "published_value": previous_value,
                        "revised_value": revised_value,
                        "change": revised_value - previous_value,
                    }
                )
            previous = row
    return out


def monthly_change_revision_rows(
    changes: list[dict[str, Any]],
    series_id: str,
    indicator: str,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for event in monthly_change_revision_events(changes):
        if event["series_id"] != series_id or event["event_type"] != "revision":
            continue
        published_value = float(event["previous_monthly_change_thousands"])
        revised_value = float(event["revised_monthly_change_thousands"])
        out.append(
            {
                "indicator": indicator,
                "release_date": event["revision_vintage_date"],
                "target_date": event["date"],
                "published_value": published_value,
                "revised_value": revised_value,
                "change": revised_value - published_value,
            }
        )
    return out


def final_revision_rows(rows: list[dict[str, Any]], start_date: str, end_date: str) -> list[dict[str, Any]]:
    changes = monthly_changes(rows, start_date, end_date)
    out: list[dict[str, Any]] = []
    out.extend(monthly_change_revision_rows(changes, "PAYEMS", "PAYEMS_monthly_change_thousands"))
    out.extend(monthly_change_revision_rows(changes, "ADPMNUSNERSA", "ADP_monthly_change_thousands"))
    out.extend(level_revision_rows(rows, "ICSA", "ICSA_weekly_level_count", start_date, end_date))
    out.sort(key=lambda item: (item["indicator"], item["release_date"], item["target_date"]))
    return out


def initial_monthly_rows(
    rows: list[dict[str, Any]],
    series_id: str,
    indicator: str,
    start_date: str,
    end_date: str,
) -> list[dict[str, Any]]:
    changes = monthly_changes(rows, start_date, end_date)
    first_by_date: dict[str, dict[str, Any]] = {}
    for row in changes:
        if row["series_id"] != series_id:
            continue
        target_date = str(row["date"])
        if target_date not in first_by_date or str(row["realtime_start"]) < str(first_by_date[target_date]["realtime_start"]):
            first_by_date[target_date] = row

    out: list[dict[str, Any]] = []
    for target_date, row in sorted(first_by_date.items()):
        out.append(
            {
                "indicator": indicator,
                "release_date": row["realtime_start"],
                "target_date": target_date,
                "published_value": float(row["monthly_change_thousands"]),
            }
        )
    return out


def initial_weekly_rows(
    rows: list[dict[str, Any]],
    series_id: str,
    indicator: str,
    start_date: str,
    end_date: str,
) -> list[dict[str, Any]]:
    first_by_date: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row["series_id"] != series_id or not observation_in_range(row, start_date, end_date):
            continue
        target_date = str(row["date"])
        if target_date not in first_by_date or str(row["realtime_start"]) < str(first_by_date[target_date]["realtime_start"]):
            first_by_date[target_date] = row

    out: list[dict[str, Any]] = []
    for target_date, row in sorted(first_by_date.items()):
        out.append(
            {
                "indicator": indicator,
                "release_date": row["realtime_start"],
                "target_date": target_date,
                "published_value": float(row["value_float"]),
            }
        )
    return out


def final_initial_rows(rows: list[dict[str, Any]], start_date: str, end_date: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    out.extend(initial_monthly_rows(rows, "PAYEMS", INITIAL_INDICATORS["PAYEMS"], start_date, end_date))
    out.extend(initial_monthly_rows(rows, "ADPMNUSNERSA", INITIAL_INDICATORS["ADPMNUSNERSA"], start_date, end_date))
    out.extend(initial_weekly_rows(rows, "ICSA", INITIAL_INDICATORS["ICSA"], start_date, end_date))
    out.sort(key=lambda item: (item["indicator"], item["release_date"], item["target_date"]))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, default=None, help="Fetch one calendar year; overrides --start-year/--end-year.")
    parser.add_argument("--start-year", type=int, default=2022)
    parser.add_argument("--end-year", type=int, default=date.today().year)
    parser.add_argument("--realtime-end", default="9999-12-31")
    parser.add_argument("--initial-output-file", default=None)
    parser.add_argument("--revision-output-file", default=None)
    args = parser.parse_args()

    start_year = args.year if args.year is not None else args.start_year
    end_year = args.year if args.year is not None else args.end_year
    start_date = f"{start_year}-01-01"
    end_date = f"{end_year}-12-31"
    realtime_end = args.realtime_end
    script_dir = Path(__file__).resolve().parent
    default_output_dir = script_dir / "data" / f"employment_events_{start_year}_{end_year}"
    initial_output_file = (
        Path(args.initial_output_file)
        if args.initial_output_file
        else default_output_dir / "initial_releases.csv"
    )
    revision_output_file = (
        Path(args.revision_output_file)
        if args.revision_output_file
        else default_output_dir / "revision_events.csv"
    )

    all_rows: list[dict[str, Any]] = []

    for series_id, config in SERIES.items():
        series_vintage_rows = fetch_vintage_dates(series_id, start_date, realtime_end)
        series_vintage_dates = [row["vintage_date"] for row in series_vintage_rows]

        fetch_start = f"{start_year - 1}-12-01" if config["frequency"] == "monthly" else start_date
        common_params = {
            "series_id": series_id,
            "observation_start": fetch_start,
            "observation_end": end_date,
            "sort_order": "asc",
        }

        vintage = normalize_observations(
            series_id,
            paged_observations(
                {
                    **common_params,
                    "output_type": 2,
                    "vintage_dates": ",".join(series_vintage_dates),
                }
            )
            if series_vintage_dates
            else [],
        )
        all_rows.extend(vintage)
        time.sleep(0.2)

    initial_rows = final_initial_rows(all_rows, start_date, end_date)
    revision_rows = final_revision_rows(all_rows, start_date, end_date)
    write_csv(
        initial_output_file,
        initial_rows,
        ["indicator", "release_date", "target_date", "published_value"],
    )
    write_csv(
        revision_output_file,
        revision_rows,
        ["indicator", "release_date", "target_date", "published_value", "revised_value", "change"],
    )

    print(f"Wrote ALFRED employment initial releases to {initial_output_file}")
    print(f"initial rows: {len(initial_rows)}")
    print(f"Wrote ALFRED employment revision events to {revision_output_file}")
    print(f"revision rows: {len(revision_rows)}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
