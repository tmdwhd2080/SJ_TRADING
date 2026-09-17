from __future__ import annotations

import argparse
import asyncio
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from Crawling.telegram_crawl.config import TelegramCrawlConfig
from Crawling.telegram_crawl.crawler import collect_recent_posts
from Crawling.telegram_crawl.export import write_json, write_posts_csv


def _parse_as_of(value: str | None, timezone_name: str) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(timezone_name))
    return parsed


def _run_dir(base_dir: Path, now: datetime) -> Path:
    path = base_dir / now.strftime("%Y%m%d_%H%M%S")
    path.mkdir(parents=True, exist_ok=True)
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Crawl recent Telegram channel posts.")
    parser.add_argument("--channel", help="Telegram channel URL/username. Default: TELEGRAM_CHANNEL_URL or shmstory.")
    parser.add_argument("--hours", type=int, help="Lookback hours from run time. Default: 24.")
    parser.add_argument("--output-dir", help="Base output directory. Default: out/telegram_crawl.")
    parser.add_argument("--session", help="Telethon session path. Default: .telegram_sessions/telegram_user.")
    parser.add_argument("--timezone", help="Local timezone for output labels. Default: Asia/Seoul.")
    parser.add_argument("--as-of", help="Optional run time override, e.g. 2026-06-30T09:00:00+09:00.")
    parser.add_argument("--limit", type=int, help="Optional maximum messages to scan before stopping.")
    return parser


async def _run_async(args: argparse.Namespace) -> int:
    config = TelegramCrawlConfig.from_env()
    if args.output_dir:
        config = replace(config, output_dir=Path(args.output_dir))
    if args.session:
        config = replace(config, session_path=Path(args.session))
    if args.timezone:
        config = replace(config, timezone=args.timezone)
    if args.hours is not None:
        config = replace(config, hours=args.hours)
    if args.channel:
        config = replace(config, channel=args.channel)

    try:
        config.validate()
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    as_of = _parse_as_of(args.as_of, config.timezone)
    now = datetime.now(ZoneInfo(config.timezone))
    out_dir = _run_dir(config.output_dir, now)

    try:
        posts, meta = await collect_recent_posts(
            config,
            channel=config.channel,
            hours=config.hours,
            as_of=as_of,
            limit=args.limit,
        )
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
    post_rows = [post.to_dict() for post in posts]

    write_json(out_dir / "posts.json", post_rows)
    write_posts_csv(out_dir / "posts.csv", post_rows)
    write_json(out_dir / "summary.json", {**meta, "out_dir": str(out_dir)})

    print(f"[telegram] channel={meta['channel']}")
    print(f"[window] {meta['window_start_local']} -> {meta['window_end_local']}")
    print(f"[posts] {meta['count']}")
    print(f"[out] {out_dir}")
    return 0


def main() -> int:
    return asyncio.run(_run_async(build_parser().parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
