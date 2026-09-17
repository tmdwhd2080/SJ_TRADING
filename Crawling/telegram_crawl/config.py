from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def load_local_env() -> None:
    package_dir = Path(__file__).resolve().parent
    root_dir = package_dir.parent
    for path in (
        root_dir / ".env",
        package_dir / ".env",
        package_dir / ".env.local",
    ):
        _load_env_file(path)


def _env_int(name: str, default: int | None = None) -> int | None:
    raw = os.environ.get(name)
    if raw in (None, ""):
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer.") from exc


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw in (None, ""):
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number.") from exc


@dataclass(frozen=True)
class TelegramCrawlConfig:
    api_id: int | None = None
    api_hash: str = ""
    phone: str = ""
    session_path: Path = Path(".telegram_sessions") / "telegram_user"
    channel: str = "https://t.me/shmstory"
    timezone: str = "Asia/Seoul"
    hours: int = 24
    output_dir: Path = Path("out") / "telegram_crawl"
    wait_time: float = 1.0

    @classmethod
    def from_env(cls) -> "TelegramCrawlConfig":
        load_local_env()
        return cls(
            api_id=_env_int("TELEGRAM_API_ID", cls.api_id),
            api_hash=os.environ.get("TELEGRAM_API_HASH", cls.api_hash),
            phone=os.environ.get("TELEGRAM_PHONE", cls.phone),
            session_path=Path(os.environ.get("TELEGRAM_SESSION", str(cls.session_path))),
            channel=os.environ.get("TELEGRAM_CHANNEL_URL", os.environ.get("TELEGRAM_CHANNEL", cls.channel)),
            timezone=os.environ.get("TELEGRAM_TIMEZONE", cls.timezone),
            hours=_env_int("TELEGRAM_LOOKBACK_HOURS", cls.hours) or cls.hours,
            output_dir=Path(os.environ.get("TELEGRAM_OUTPUT_DIR", str(cls.output_dir))),
            wait_time=_env_float("TELEGRAM_WAIT_TIME", cls.wait_time),
        )

    def validate(self) -> None:
        missing = []
        if not self.api_id:
            missing.append("TELEGRAM_API_ID")
        if not self.api_hash:
            missing.append("TELEGRAM_API_HASH")
        if missing:
            joined = ", ".join(missing)
            raise ValueError(
                f"Missing {joined}. Create Telegram API credentials at "
                "https://my.telegram.org/apps and set them in .env."
            )

