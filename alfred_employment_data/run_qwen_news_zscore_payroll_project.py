"""News/Qwen Z-score payroll surprise project.

This project fixes the modeling sample at target_date >= 2022-09-01 and
predicts the first BLS release of private and government payroll components.

Workflow:
    1. init
       Create the project folder and a Qwen score template.
    2. collect-sample
       Test headline/body collection for a few sources and target months.
    3. build-prompts
       Create point-in-time prompt JSON files for Qwen scoring.
    4. run-regression
       Run expanding-window Z-score regressions after qwen_scores.csv is filled.

The Qwen prompt explicitly forbids information published after the release
month's BLS cutoff. For example, for a 2026-08 release of the 2026-07 target
month, the prompt forbids any data from after 2026-08-07 08:29 ET and any
future calendar-month information after the 2026-08 release month.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import math
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus, urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree

import pandas as pd
import statsmodels.api as sm

from run_nfp_twofactor_regression import claims_average_feature, latest_revised_claims, read_csv


START_TARGET_DATE = pd.Timestamp("2022-09-01")
MIN_TRAIN_MONTHS = 24
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) PayrollResearchBot/1.0"

PROJECT_NAME = "qwen_news_zscore_payroll_2022-09"
PRIVATE_QUERIES = {
    "private_adp_employment": "ADP employment",
    "private_private_payrolls": "private payrolls",
    "private_job_cuts": "job cuts",
    "private_hiring_slowdown": "hiring slowdown",
    "private_ism_employment": "ISM employment",
}
GOVERNMENT_QUERIES = {
    "gov_federal_workers": "federal workers",
    "gov_federal_employees": "federal employees",
    "gov_shutdown": "government shutdown",
    "gov_furlough": "furlough",
    "gov_hiring_freeze": "hiring freeze",
    "gov_state_local_jobs": "state government jobs",
}

SOURCE_FIELDS = [
    "target_date",
    "release_month",
    "cutoff_time_et",
    "component",
    "source",
    "query_tag",
    "published_at_utc",
    "title",
    "url",
    "domain",
    "body_text",
    "content_hash",
    "is_before_cutoff",
]


@dataclass(frozen=True)
class ReleaseWindow:
    target_date: pd.Timestamp
    release_date: pd.Timestamp
    cutoff_time_et: str
    start_date: pd.Timestamp

    @property
    def release_month(self) -> str:
        return self.release_date.strftime("%Y-%m")


def default_project_dir() -> Path:
    return Path(__file__).resolve().parent / "data" / PROJECT_NAME


def http_get_text(url: str, timeout: int = 45) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
            charset = response.headers.get_content_charset() or "utf-8"
    except HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code} for {url}") from exc
    except URLError as exc:
        raise RuntimeError(f"Request failed for {url}: {exc}") from exc
    return raw.decode(charset, errors="replace")


def strip_html(value: str) -> str:
    value = re.sub(r"<script[\s\S]*?</script>", " ", value, flags=re.IGNORECASE)
    value = re.sub(r"<style[\s\S]*?</style>", " ", value, flags=re.IGNORECASE)
    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def safe_body_from_url(url: str, max_chars: int = 4000, timeout: int = 8) -> str:
    try:
        body = strip_html(http_get_text(url, timeout=timeout))
    except Exception:
        return ""
    return body[:max_chars]


def hash_text(*parts: str) -> str:
    joined = "\n".join(part or "" for part in parts)
    return hashlib.sha256(joined.encode("utf-8", errors="ignore")).hexdigest()


def parse_utc(value: str | None) -> pd.Timestamp | None:
    if not value:
        return None
    text = str(value).strip()
    if re.fullmatch(r"\d{8}T\d{6}Z", text):
        return pd.Timestamp(datetime.strptime(text, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc))
    parsed = pd.to_datetime(text, utc=True, errors="coerce")
    if pd.isna(parsed):
        return None
    return pd.Timestamp(parsed)


def release_window(target_date: str, release_date: str, days_back: int = 38) -> ReleaseWindow:
    target = pd.Timestamp(target_date)
    release = pd.Timestamp(release_date)
    cutoff = f"{release.strftime('%Y-%m-%d')} 08:29:00 ET"
    start = release - pd.Timedelta(days=days_back)
    return ReleaseWindow(target_date=target, release_date=release, cutoff_time_et=cutoff, start_date=start)


def cutoff_as_utc(cutoff_time_et: str) -> pd.Timestamp:
    # Employment releases are at 08:30 ET. For this project we use 08:29 ET.
    # August is daylight saving time, but historical releases can span EST/EDT.
    # This conservative parser uses America/New_York if available through pandas.
    naive = pd.Timestamp(cutoff_time_et.replace(" ET", ""))
    try:
        localized = naive.tz_localize("America/New_York")
    except Exception:
        localized = naive.tz_localize("UTC") + pd.Timedelta(hours=5)
    return localized.tz_convert("UTC")


def article_row(
    window: ReleaseWindow,
    component: str,
    source: str,
    query_tag: str,
    published_at_utc: str,
    title: str,
    url: str,
    domain: str = "",
    body_text: str = "",
) -> dict[str, Any]:
    published = parse_utc(published_at_utc)
    cutoff_utc = cutoff_as_utc(window.cutoff_time_et)
    before_cutoff = bool(published is not None and published <= cutoff_utc)
    return {
        "target_date": window.target_date.strftime("%Y-%m-%d"),
        "release_month": window.release_month,
        "cutoff_time_et": window.cutoff_time_et,
        "component": component,
        "source": source,
        "query_tag": query_tag,
        "published_at_utc": "" if published is None else published.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "title": title,
        "url": url,
        "domain": domain,
        "body_text": body_text,
        "content_hash": hash_text(title, url, body_text),
        "is_before_cutoff": before_cutoff,
    }


def fetch_gdelt_articles(window: ReleaseWindow, component: str, query_tag: str, query: str, max_records: int) -> list[dict[str, Any]]:
    params = {
        "query": f"({query})",
        "mode": "artlist",
        "format": "json",
        "maxrecords": max_records,
        "sort": "datedesc",
        "STARTDATETIME": window.start_date.strftime("%Y%m%d%H%M%S"),
        "ENDDATETIME": cutoff_as_utc(window.cutoff_time_et).strftime("%Y%m%d%H%M%S"),
    }
    url = "https://api.gdeltproject.org/api/v2/doc/doc?" + urlencode(params)
    try:
        payload = json.loads(http_get_text(url))
    except Exception:
        return []

    rows: list[dict[str, Any]] = []
    for item in payload.get("articles", []):
        article_url = item.get("url", "")
        rows.append(
            article_row(
                window=window,
                component=component,
                source="gdelt_doc",
                query_tag=query_tag,
                published_at_utc=item.get("seendate", ""),
                title=item.get("title", ""),
                url=article_url,
                domain=item.get("domain", ""),
                body_text=safe_body_from_url(article_url),
            )
        )
        time.sleep(0.2)
    return rows


def fetch_google_news_rss(window: ReleaseWindow, component: str, query_tag: str, query: str, max_records: int) -> list[dict[str, Any]]:
    rss_url = (
        "https://news.google.com/rss/search?"
        + urlencode({"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"})
    )
    try:
        root = ElementTree.fromstring(http_get_text(rss_url))
    except Exception:
        return []

    rows: list[dict[str, Any]] = []
    for item in root.findall("./channel/item")[:max_records]:
        title = item.findtext("title") or ""
        link = item.findtext("link") or ""
        published = item.findtext("pubDate") or ""
        source = item.find("source")
        domain = "" if source is None else (source.text or "")
        rows.append(
            article_row(
                window=window,
                component=component,
                source="google_news_rss",
                query_tag=query_tag,
                published_at_utc=published,
                title=title,
                url=link,
                domain=domain,
                body_text="",
            )
        )
    return rows


def fetch_federal_register(window: ReleaseWindow, query_tag: str, query: str, max_records: int) -> list[dict[str, Any]]:
    params = {
        "conditions[term]": query,
        "conditions[publication_date][gte]": window.start_date.strftime("%Y-%m-%d"),
        "conditions[publication_date][lte]": window.release_date.strftime("%Y-%m-%d"),
        "per_page": max_records,
        "order": "newest",
        "fields[]": [
            "document_number",
            "title",
            "abstract",
            "publication_date",
            "html_url",
            "raw_text_url",
            "full_text_xml_url",
        ],
    }
    url = "https://www.federalregister.gov/api/v1/documents.json?" + urlencode(params, doseq=True)
    try:
        payload = json.loads(http_get_text(url))
    except Exception:
        return []

    rows: list[dict[str, Any]] = []
    for item in payload.get("results", []):
        body_url = item.get("raw_text_url") or item.get("full_text_xml_url") or item.get("html_url", "")
        rows.append(
            article_row(
                window=window,
                component="government",
                source="federal_register",
                query_tag=query_tag,
                published_at_utc=str(item.get("publication_date", "")),
                title=item.get("title", ""),
                url=item.get("html_url", ""),
                domain="federalregister.gov",
                body_text=safe_body_from_url(body_url),
            )
        )
        time.sleep(0.2)
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        fieldnames = []
        for row in rows:
            for key in row:
                if key not in fieldnames:
                    fieldnames.append(key)
    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def qwen_prompt(
    target_date: str,
    release_month: str,
    cutoff_time_et: str,
    component: str,
    numeric_context: dict[str, Any],
    articles: list[dict[str, Any]],
) -> str:
    article_lines = []
    for idx, row in enumerate(articles, start=1):
        body = str(row.get("body_text") or "")
        body = body[:1600]
        article_lines.append(
            f"[{idx}] source={row.get('source')} published_utc={row.get('published_at_utc')} "
            f"title={row.get('title')}\nurl={row.get('url')}\nexcerpt={body}"
        )
    article_block = "\n\n".join(article_lines) if article_lines else "(no eligible articles)"

    if component == "private":
        task = (
            "Score the directional pressure on BLS PRIVATE payroll surprise "
            "(USPRIV initial release) for the target month."
        )
        consider = (
            "- ADP strength/surprise and article interpretation\n"
            "- private hiring, layoffs, job cuts, temporary help, small business, ISM/PMI employment\n"
            "- whether the news implies private payrolls are stronger or weaker than pre-release expectation"
        )
        schema = {
            "target_date": target_date,
            "release_month": release_month,
            "component": "private",
            "surprise_score": "integer -3..3",
            "confidence": "number 0..1",
            "reason_codes": ["ADP_UPSIDE_OR_DOWNSIDE", "LAYOFFS", "HIRING_BREADTH", "SECTOR_MIX"],
            "evidence_urls": ["urls used"],
            "leakage_risk": "low/medium/high",
            "leakage_notes": "why no post-cutoff or future-month information was used",
        }
    else:
        task = (
            "Score the directional pressure on BLS GOVERNMENT payroll surprise "
            "(USGOVT initial release: federal + state + local) for the target month."
        )
        consider = (
            "- initial claims as broad labor market stress\n"
            "- federal workers, government shutdown, furloughs, RIF/reduction in force, hiring freeze\n"
            "- state/local government jobs, public school and teacher hiring, strikes or one-off public-sector events"
        )
        schema = {
            "target_date": target_date,
            "release_month": release_month,
            "component": "government",
            "surprise_score": "integer -3..3",
            "federal_score": "integer -3..3",
            "state_local_score": "integer -3..3",
            "confidence": "number 0..1",
            "reason_codes": ["SHUTDOWN", "FURLOUGH", "RIF", "HIRING_FREEZE", "STATE_LOCAL_EDUCATION", "CLAIMS"],
            "evidence_urls": ["urls used"],
            "leakage_risk": "low/medium/high",
            "leakage_notes": "why no post-cutoff or future-month information was used",
        }

    return f"""You are a point-in-time feature extractor for a US nonfarm payroll forecasting project.

Target month: {target_date}
Release month N: {release_month}
BLS pre-release cutoff: {cutoff_time_et}
Component: {component}

ABSOLUTE LOOK-AHEAD BIAS RULES:
1. Use only the numerical inputs and articles provided in this prompt.
2. Do not use, infer, mention, or rely on the actual BLS Employment Situation result for this target month.
3. Do not use any information published after {cutoff_time_et}.
4. Because the release month is {release_month}, do not use any future calendar-month information after release month N={release_month}, even if you know it from training or general knowledge.
5. If an article appears to discuss the actual BLS result, a later revision, or any post-release analysis, ignore it and set leakage_risk to "high" if it materially affects the evidence set.
6. Do not directly forecast payroll K values. Only assign a qualitative surprise score from -3 to +3.

Score scale:
+3 = very strong upside surprise signal
+2 = clear upside surprise signal
+1 = mild upside surprise signal
0 = neutral/mixed
-1 = mild downside surprise signal
-2 = clear downside surprise signal
-3 = very strong downside surprise signal

Task:
{task}

Consider:
{consider}

Numerical context available before cutoff:
{json.dumps(numeric_context, ensure_ascii=False, indent=2)}

Eligible pre-cutoff articles:
{article_block}

Return JSON only using this schema:
{json.dumps(schema, ensure_ascii=False, indent=2)}
"""


def init_project(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "articles").mkdir(exist_ok=True)
    (output_dir / "prompts").mkdir(exist_ok=True)
    (output_dir / "scores").mkdir(exist_ok=True)
    (output_dir / "regression").mkdir(exist_ok=True)
    template = output_dir / "scores" / "qwen_scores_template.csv"
    if not template.exists():
        write_csv(
            template,
            [
                {
                    "target_date": "2024-09-01",
                    "component": "private",
                    "release_month": "2024-10",
                    "cutoff_time_et": "2024-10-04 08:29:00 ET",
                    "qwen_model": "qwen-plus",
                    "prompt_version": "v1_no_future_after_release_month",
                    "article_count": "",
                    "latest_article_time_utc": "",
                    "surprise_score": "",
                    "confidence": "",
                    "leakage_risk": "",
                    "raw_json": "",
                },
                {
                    "target_date": "2024-09-01",
                    "component": "government",
                    "release_month": "2024-10",
                    "cutoff_time_et": "2024-10-04 08:29:00 ET",
                    "qwen_model": "qwen-plus",
                    "prompt_version": "v1_no_future_after_release_month",
                    "article_count": "",
                    "latest_article_time_utc": "",
                    "surprise_score": "",
                    "confidence": "",
                    "leakage_risk": "",
                    "raw_json": "",
                },
            ],
        )
    readme = output_dir / "README.md"
    if not readme.exists():
        readme.write_text(
            "# Qwen News Z-score Payroll Project\n\n"
            "- Fixed start target_date: 2022-09-01\n"
            "- Target: initial BLS private/government payroll changes\n"
            "- Workflow: collect articles -> build Qwen prompts -> fill qwen_scores.csv -> run expanding regressions\n"
            "- Look-ahead rule: prompts and code forbid data after the release cutoff and any future month after release month N.\n",
            encoding="utf-8",
        )


def collect_sample(output_dir: Path, target_date: str, release_date: str, max_records: int, include_gdelt: bool) -> None:
    window = release_window(target_date, release_date)
    rows: list[dict[str, Any]] = []
    # Keep the sample command intentionally small and fast. Full backfills should
    # be run source-by-source with stricter rate limits.
    sample_private = {
        "private_adp_employment": PRIVATE_QUERIES["private_adp_employment"],
        "private_private_payrolls": PRIVATE_QUERIES["private_private_payrolls"],
        "private_job_cuts": PRIVATE_QUERIES["private_job_cuts"],
    }
    sample_government = {
        "gov_federal_workers": GOVERNMENT_QUERIES["gov_federal_workers"],
        "gov_shutdown": GOVERNMENT_QUERIES["gov_shutdown"],
        "gov_hiring_freeze": GOVERNMENT_QUERIES["gov_hiring_freeze"],
    }
    for tag, query in sample_private.items():
        if include_gdelt:
            rows.extend(fetch_gdelt_articles(window, "private", tag, query, max_records))
        rows.extend(fetch_google_news_rss(window, "private", tag, query, max_records))
    for tag, query in sample_government.items():
        if include_gdelt:
            rows.extend(fetch_gdelt_articles(window, "government", tag, query, max_records))
        rows.extend(fetch_google_news_rss(window, "government", tag, query, max_records))
        rows.extend(fetch_federal_register(window, tag, query, max_records))

    unique: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row["is_before_cutoff"]:
            unique[row["content_hash"]] = row
    path = output_dir / "articles" / f"articles_{target_date}.csv"
    write_csv(path, list(unique.values()), SOURCE_FIELDS)
    print(f"wrote {len(unique)} pre-cutoff sample articles to {path}")


def load_claims_features(initial_file: Path, revision_file: Path, months: list[pd.Timestamp]) -> pd.DataFrame:
    initial_rows = read_csv(initial_file)
    revision_rows = read_csv(revision_file)
    latest_claims = latest_revised_claims(initial_rows, revision_rows)
    rows: list[dict[str, Any]] = []
    for month in months:
        avg, count, last_week = claims_average_feature(month.strftime("%Y-%m-01"), initial_rows, latest_claims)
        if avg is None:
            continue
        rows.append(
            {
                "target_date": month,
                "claims_avg_mixed_thousands": avg / 1000.0,
                "claims_week_count": count,
                "claims_last_week_initial_target": last_week,
            }
        )
    return pd.DataFrame(rows)


def numeric_context_for_month(panel: pd.DataFrame, target_date: pd.Timestamp) -> dict[str, Any]:
    row = panel[panel["target_date"] == target_date]
    if row.empty:
        return {"target_date": target_date.strftime("%Y-%m-%d")}
    item = row.iloc[0].to_dict()
    keys = [
        "target_date",
        "ADPMNUSNERSA_initial_change_k",
        "USPRIV_initial_lag1_change_k",
        "USGOVT_initial_lag1_change_k",
        "claims_avg_mixed_thousands",
        "claims_week_count",
        "claims_last_week_initial_target",
    ]
    out = {}
    for key in keys:
        value = item.get(key)
        if pd.isna(value):
            value = None
        if isinstance(value, pd.Timestamp):
            value = value.strftime("%Y-%m-%d")
        out[key] = value
    return out


def build_prompt_files(output_dir: Path, split_panel_file: Path, initial_file: Path, revision_file: Path) -> None:
    panel = pd.read_csv(split_panel_file)
    panel["target_date"] = pd.to_datetime(panel["target_date"], errors="coerce")
    months = list(panel.loc[panel["target_date"] >= START_TARGET_DATE, "target_date"].dropna().sort_values())
    claims = load_claims_features(initial_file, revision_file, months)
    panel = panel.merge(claims, on="target_date", how="left")
    panel["USPRIV_initial_lag1_change_k"] = panel["USPRIV_initial_change_k"].shift(1)
    panel["USGOVT_initial_lag1_change_k"] = panel["USGOVT_initial_change_k"].shift(1)

    article_files = sorted((output_dir / "articles").glob("articles_*.csv"))
    if not article_files:
        raise RuntimeError("No article CSV files found. Run collect-sample first or add article files.")

    for article_file in article_files:
        articles = pd.read_csv(article_file)
        if articles.empty:
            continue
        target_date = pd.Timestamp(articles["target_date"].iloc[0])
        release_month = str(articles["release_month"].iloc[0])
        cutoff = str(articles["cutoff_time_et"].iloc[0])
        numeric = numeric_context_for_month(panel, target_date)
        for component in ["private", "government"]:
            subset = articles[
                (articles["component"] == component)
                & (articles["is_before_cutoff"].astype(str).str.lower().isin(["true", "1"]))
            ].copy()
            subset = subset.sort_values("published_at_utc").tail(25)
            prompt = qwen_prompt(
                target_date=target_date.strftime("%Y-%m-%d"),
                release_month=release_month,
                cutoff_time_et=cutoff,
                component=component,
                numeric_context=numeric,
                articles=subset.to_dict("records"),
            )
            out = {
                "target_date": target_date.strftime("%Y-%m-%d"),
                "release_month": release_month,
                "cutoff_time_et": cutoff,
                "component": component,
                "prompt_version": "v1_no_future_after_release_month",
                "article_count": int(len(subset)),
                "latest_article_time_utc": "" if subset.empty else subset["published_at_utc"].max(),
                "prompt": prompt,
            }
            prompt_path = output_dir / "prompts" / f"qwen_prompt_{target_date.strftime('%Y-%m-%d')}_{component}.json"
            prompt_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"wrote {prompt_path}")


def expanding_zscore(series: pd.Series, train_index: pd.Index) -> tuple[float, float]:
    values = series.loc[train_index].dropna().astype(float)
    mean = float(values.mean())
    std = float(values.std(ddof=1))
    if not math.isfinite(std) or std == 0:
        std = 1.0
    return mean, std


def run_expanding_regression(output_dir: Path, split_panel_file: Path, initial_file: Path, revision_file: Path, qwen_scores_file: Path) -> None:
    panel = pd.read_csv(split_panel_file)
    panel["target_date"] = pd.to_datetime(panel["target_date"], errors="coerce")
    panel = panel.sort_values("target_date").reset_index(drop=True)
    panel["USGOVT_initial_lag1_change_k"] = panel["USGOVT_initial_change_k"].shift(1)
    panel = panel[panel["target_date"] >= START_TARGET_DATE].reset_index(drop=True)
    months = list(panel["target_date"].dropna())
    claims = load_claims_features(initial_file, revision_file, months)
    panel = panel.merge(claims, on="target_date", how="left")

    scores = pd.read_csv(qwen_scores_file)
    scores["target_date"] = pd.to_datetime(scores["target_date"], errors="coerce")
    scores["surprise_score"] = pd.to_numeric(scores["surprise_score"], errors="coerce")
    private_scores = scores[scores["component"].eq("private")][["target_date", "surprise_score"]].rename(
        columns={"surprise_score": "qwen_private_score"}
    )
    govt_scores = scores[scores["component"].eq("government")][["target_date", "surprise_score"]].rename(
        columns={"surprise_score": "qwen_government_score"}
    )
    panel = panel.merge(private_scores, on="target_date", how="left").merge(govt_scores, on="target_date", how="left")

    needed = [
        "USPRIV_initial_change_k",
        "USGOVT_initial_change_k",
        "ADPMNUSNERSA_initial_change_k",
        "claims_avg_mixed_thousands",
        "qwen_private_score",
        "qwen_government_score",
    ]
    panel = panel.dropna(subset=needed).reset_index(drop=True)
    if len(panel) <= MIN_TRAIN_MONTHS:
        raise RuntimeError(f"Need more than {MIN_TRAIN_MONTHS} complete rows, got {len(panel)}.")

    rows: list[dict[str, Any]] = []
    coef_rows: list[dict[str, Any]] = []
    for idx in range(MIN_TRAIN_MONTHS, len(panel)):
        train = panel.iloc[:idx].copy()
        current = panel.iloc[[idx]].copy()

        train_index = train.index
        scalers: dict[str, tuple[float, float]] = {}
        for col in [
            "USPRIV_initial_change_k",
            "USGOVT_initial_change_k",
            "ADPMNUSNERSA_initial_change_k",
            "claims_avg_mixed_thousands",
            "USGOVT_initial_lag1_change_k",
        ]:
            scalers[col] = expanding_zscore(panel[col], train_index)

        def z(col: str, frame: pd.DataFrame) -> pd.Series:
            mean, std = scalers[col]
            return (frame[col].astype(float) - mean) / std

        train["z_uspriv"] = z("USPRIV_initial_change_k", train)
        train["z_usgovt"] = z("USGOVT_initial_change_k", train)
        train["z_adp"] = z("ADPMNUSNERSA_initial_change_k", train)
        train["z_claims"] = z("claims_avg_mixed_thousands", train)
        train["z_usgovt_lag1"] = z("USGOVT_initial_lag1_change_k", train)
        current["z_adp"] = z("ADPMNUSNERSA_initial_change_k", current)
        current["z_claims"] = z("claims_avg_mixed_thousands", current)
        current["z_usgovt_lag1"] = z("USGOVT_initial_lag1_change_k", current)

        private_model = sm.OLS(
            train["z_uspriv"],
            sm.add_constant(train[["z_adp", "qwen_private_score"]], has_constant="add"),
        ).fit()
        govt_model = sm.OLS(
            train["z_usgovt"],
            sm.add_constant(train[["z_claims", "z_usgovt_lag1", "qwen_government_score"]], has_constant="add"),
        ).fit()
        pred_private_z = float(
            private_model.predict(sm.add_constant(current[["z_adp", "qwen_private_score"]], has_constant="add")).iloc[0]
        )
        pred_govt_z = float(
            govt_model.predict(
                sm.add_constant(current[["z_claims", "z_usgovt_lag1", "qwen_government_score"]], has_constant="add")
            ).iloc[0]
        )
        private_mean, private_std = scalers["USPRIV_initial_change_k"]
        govt_mean, govt_std = scalers["USGOVT_initial_change_k"]
        pred_private_k = pred_private_z * private_std + private_mean
        pred_govt_k = pred_govt_z * govt_std + govt_mean
        actual_private_k = float(current["USPRIV_initial_change_k"].iloc[0])
        actual_govt_k = float(current["USGOVT_initial_change_k"].iloc[0])
        rows.append(
            {
                "target_date": current["target_date"].iloc[0].strftime("%Y-%m-%d"),
                "train_start": train["target_date"].iloc[0].strftime("%Y-%m-%d"),
                "train_end": train["target_date"].iloc[-1].strftime("%Y-%m-%d"),
                "train_n": len(train),
                "pred_private_k": pred_private_k,
                "actual_private_k": actual_private_k,
                "private_error_actual_minus_pred_k": actual_private_k - pred_private_k,
                "pred_government_k": pred_govt_k,
                "actual_government_k": actual_govt_k,
                "government_error_actual_minus_pred_k": actual_govt_k - pred_govt_k,
                "pred_payems_k": pred_private_k + pred_govt_k,
                "actual_payems_k": actual_private_k + actual_govt_k,
                "payems_error_actual_minus_pred_k": (actual_private_k + actual_govt_k) - (pred_private_k + pred_govt_k),
            }
        )

        for model_name, model in [("private", private_model), ("government", govt_model)]:
            for term in model.params.index:
                coef_rows.append(
                    {
                        "target_date": current["target_date"].iloc[0].strftime("%Y-%m-%d"),
                        "model": model_name,
                        "term": "intercept" if term == "const" else term,
                        "coefficient": model.params[term],
                        "p_value": model.pvalues[term],
                        "r2": model.rsquared,
                        "adj_r2": model.rsquared_adj,
                    }
                )

    result = pd.DataFrame(rows)
    metrics = {
        "test_n": len(result),
        "private_rmse": float((result["private_error_actual_minus_pred_k"].pow(2).mean()) ** 0.5),
        "government_rmse": float((result["government_error_actual_minus_pred_k"].pow(2).mean()) ** 0.5),
        "payems_rmse": float((result["payems_error_actual_minus_pred_k"].pow(2).mean()) ** 0.5),
        "private_mae": float(result["private_error_actual_minus_pred_k"].abs().mean()),
        "government_mae": float(result["government_error_actual_minus_pred_k"].abs().mean()),
        "payems_mae": float(result["payems_error_actual_minus_pred_k"].abs().mean()),
    }
    reg_dir = output_dir / "regression"
    reg_dir.mkdir(parents=True, exist_ok=True)
    result.to_csv(reg_dir / "expanding_oos_predictions.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(coef_rows).to_csv(reg_dir / "expanding_coefficients.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame([metrics]).to_csv(reg_dir / "metrics.csv", index=False, encoding="utf-8-sig")
    print(json.dumps(metrics, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["init", "collect-sample", "build-prompts", "run-regression"])
    parser.add_argument("--output-dir", default=str(default_project_dir()))
    parser.add_argument("--target-date", default="2026-07-01")
    parser.add_argument("--release-date", default="2026-08-07")
    parser.add_argument("--max-records", type=int, default=3)
    parser.add_argument("--include-gdelt", action="store_true")
    script_dir = Path(__file__).resolve().parent
    parser.add_argument(
        "--split-panel",
        default=str(script_dir / "data" / "private_government_split_2020_present" / "monthly_split_model_panel.csv"),
    )
    parser.add_argument(
        "--initial-file",
        default=str(script_dir / "data" / "employment_events_2020_2026" / "initial_releases.csv"),
    )
    parser.add_argument(
        "--revision-file",
        default=str(script_dir / "data" / "employment_events_2020_2026" / "revision_events.csv"),
    )
    parser.add_argument("--qwen-scores-file", default="")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    if args.command == "init":
        init_project(output_dir)
    elif args.command == "collect-sample":
        init_project(output_dir)
        collect_sample(output_dir, args.target_date, args.release_date, args.max_records, args.include_gdelt)
    elif args.command == "build-prompts":
        init_project(output_dir)
        build_prompt_files(output_dir, Path(args.split_panel), Path(args.initial_file), Path(args.revision_file))
    elif args.command == "run-regression":
        qwen_scores = Path(args.qwen_scores_file) if args.qwen_scores_file else output_dir / "scores" / "qwen_scores.csv"
        run_expanding_regression(
            output_dir,
            Path(args.split_panel),
            Path(args.initial_file),
            Path(args.revision_file),
            qwen_scores,
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
