# Mint Watcher

Telegram bot that watches NFT mints (e.g. ASCII Cats on Robinhood Chain) and
sends a **loud alert the moment a mint opens**, plus a guided `/add` flow to
watch new mints. Instant replies.

## How it runs

It's a **Cloudflare Worker** (`cf-worker/`):

- `fetch()` — Telegram webhook: instant replies to your commands.
- `scheduled()` — runs every minute: checks each watched mint, alerts on open.
- State lives in a Cloudflare KV namespace (`STATE`).
- Secrets (`BOT_TOKEN`, `CHAT_ID`, `WEBHOOK_SECRET`) are stored in the Worker.

Live at: `https://mint-watcher.radmatist.workers.dev`

## Deploy / update

```bash
cd cf-worker
npx wrangler deploy
```

## Commands (in the Telegram chat)

`/list` · `/add` · `/remove` · `/test` · `/cancel` · `/help`

---

_Earlier this ran on GitHub Actions + cron-job.org; that was retired in favour
of the Cloudflare Worker (instant replies + reliable 1-minute checks)._
