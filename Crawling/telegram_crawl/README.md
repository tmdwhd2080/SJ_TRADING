# Telegram Crawl

Collects all posts from a public Telegram channel within the last N hours from the run time.

## Feasibility

`https://t.me/shmstory` is a public channel, so the reliable approach is to use Telegram's MTProto API through Telethon. The channel numeric ID is not required; the public username `shmstory` is enough.

The first run needs Telegram API credentials and an interactive login code. Later runs reuse the local `.telegram_sessions/telegram_user.session` file.

## Required values

- `TELEGRAM_API_ID`: create at https://my.telegram.org/apps
- `TELEGRAM_API_HASH`: create at https://my.telegram.org/apps
- `TELEGRAM_PHONE`: your Telegram phone number, only needed for first login

## Install

```powershell
python -m pip install -r telegram_crawl/requirements.txt
```

## Configure

Copy `telegram_crawl/.env.example` values into the root `.env` file or into `telegram_crawl/.env.local`, then fill in the real API values.

## Run

```powershell
python -m telegram_crawl.run --channel https://t.me/shmstory --hours 24
```

Outputs are written to:

- `out/telegram_crawl/YYYYMMDD_HHMMSS/posts.json`
- `out/telegram_crawl/YYYYMMDD_HHMMSS/posts.csv`
- `out/telegram_crawl/YYYYMMDD_HHMMSS/summary.json`

## Notes

- Bot tokens are not enough for arbitrary channel history. Use a normal Telegram account session.
- The crawler stops when it reaches a post older than the requested window.
- Keep `.session` files private. They are equivalent to a logged-in Telegram session.

