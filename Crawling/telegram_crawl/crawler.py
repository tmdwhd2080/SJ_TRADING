from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from Crawling.telegram_crawl.config import TelegramCrawlConfig


URL_RE = re.compile(r"https?://[^\s<>)\]]+")


@dataclass(frozen=True)
class TelegramPost:
    channel: str
    message_id: int
    tme_url: str
    date_utc: str
    date_local: str
    text: str
    views: int | None
    forwards: int | None
    replies: int | None
    reactions: list[dict[str, int | str]]
    links: list[str]
    media_type: str
    grouped_id: int | None
    is_forwarded: bool
    edit_date_utc: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_channel(value: str) -> str:
    channel = (value or "").strip()
    if not channel:
        raise ValueError("Channel is empty.")
    parsed = urlparse(channel)
    if parsed.netloc:
        parts = [part for part in parsed.path.split("/") if part]
        if parts and parts[0] == "s":
            parts = parts[1:]
        if parts:
            return parts[0].lstrip("@")
    return channel.lstrip("@")


def public_message_url(channel: str, message_id: int) -> str:
    normalized = normalize_channel(channel)
    if normalized.startswith("-"):
        return ""
    return f"https://t.me/{normalized}/{message_id}"


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso_or_none(value: datetime | None) -> str | None:
    if value is None:
        return None
    return _aware_utc(value).isoformat()


def _reaction_name(reaction: Any) -> str:
    raw = getattr(reaction, "reaction", reaction)
    emoticon = getattr(raw, "emoticon", None)
    if emoticon:
        return str(emoticon)
    document_id = getattr(raw, "document_id", None)
    if document_id:
        return f"custom:{document_id}"
    return str(raw)


def _extract_reactions(message: Any) -> list[dict[str, int | str]]:
    reactions = getattr(message, "reactions", None)
    results = getattr(reactions, "results", None) or []
    rows: list[dict[str, int | str]] = []
    for item in results:
        rows.append(
            {
                "reaction": _reaction_name(getattr(item, "reaction", "")),
                "count": int(getattr(item, "count", 0) or 0),
            }
        )
    return rows


def _extract_links(message: Any, text: str) -> list[str]:
    links = set(URL_RE.findall(text or ""))
    for entity in getattr(message, "entities", None) or []:
        url = getattr(entity, "url", None)
        if url:
            links.add(str(url))
    return sorted(links)


def _reply_count(message: Any) -> int | None:
    replies = getattr(message, "replies", None)
    if replies is None:
        return None
    count = getattr(replies, "replies", None)
    return int(count) if count is not None else None


def _media_type(message: Any) -> str:
    media = getattr(message, "media", None)
    if media is None:
        return ""
    return type(media).__name__


async def collect_recent_posts(
    config: TelegramCrawlConfig,
    *,
    channel: str | None = None,
    hours: int | None = None,
    as_of: datetime | None = None,
    limit: int | None = None,
) -> tuple[list[TelegramPost], dict[str, Any]]:
    try:
        from telethon import TelegramClient
    except ImportError as exc:
        raise RuntimeError(
            "Telethon is not installed. Run: python -m pip install -r telegram_crawl/requirements.txt"
        ) from exc

    config.validate()

    tz = ZoneInfo(config.timezone)
    run_time = as_of.astimezone(tz) if as_of and as_of.tzinfo else (as_of.replace(tzinfo=tz) if as_of else datetime.now(tz))
    window_end_utc = run_time.astimezone(timezone.utc)
    window_start_utc = window_end_utc - timedelta(hours=hours or config.hours)
    target_channel = normalize_channel(channel or config.channel)

    session_path = Path(config.session_path)
    session_path.parent.mkdir(parents=True, exist_ok=True)

    client = TelegramClient(str(session_path), config.api_id, config.api_hash)
    posts: list[TelegramPost] = []

    await client.start(phone=config.phone or None)
    try:
        entity = await client.get_entity(target_channel)
        entity_username = getattr(entity, "username", None) or target_channel
        async for message in client.iter_messages(entity, limit=limit, wait_time=config.wait_time):
            if not getattr(message, "date", None):
                continue
            message_date = _aware_utc(message.date)
            if message_date > window_end_utc:
                continue
            if message_date < window_start_utc:
                break

            text = getattr(message, "message", None) or getattr(message, "raw_text", "") or ""
            posts.append(
                TelegramPost(
                    channel=target_channel,
                    message_id=int(message.id),
                    tme_url=public_message_url(entity_username, int(message.id)),
                    date_utc=message_date.isoformat(),
                    date_local=message_date.astimezone(tz).isoformat(),
                    text=text,
                    views=getattr(message, "views", None),
                    forwards=getattr(message, "forwards", None),
                    replies=_reply_count(message),
                    reactions=_extract_reactions(message),
                    links=_extract_links(message, text),
                    media_type=_media_type(message),
                    grouped_id=getattr(message, "grouped_id", None),
                    is_forwarded=getattr(message, "fwd_from", None) is not None,
                    edit_date_utc=_iso_or_none(getattr(message, "edit_date", None)),
                )
            )
    finally:
        await client.disconnect()

    posts.sort(key=lambda item: item.date_utc)
    meta = {
        "channel": target_channel,
        "window_start_utc": window_start_utc.isoformat(),
        "window_end_utc": window_end_utc.isoformat(),
        "window_start_local": window_start_utc.astimezone(tz).isoformat(),
        "window_end_local": window_end_utc.astimezone(tz).isoformat(),
        "timezone": config.timezone,
        "count": len(posts),
    }
    return posts, meta

