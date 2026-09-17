from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


POST_FIELDS = [
    "channel",
    "message_id",
    "tme_url",
    "date_utc",
    "date_local",
    "text",
    "views",
    "forwards",
    "replies",
    "reactions",
    "links",
    "media_type",
    "grouped_id",
    "is_forwarded",
    "edit_date_utc",
]


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_posts_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=POST_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            serializable = dict(row)
            serializable["reactions"] = json.dumps(row.get("reactions", []), ensure_ascii=False)
            serializable["links"] = json.dumps(row.get("links", []), ensure_ascii=False)
            writer.writerow(serializable)

