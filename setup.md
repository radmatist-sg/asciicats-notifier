# Mint Watcher — Telegram bot

Watches NFT mints and sends you a **loud Telegram alert the moment one opens**,
with the mint's website in the message. Everything else (progress, replies) is
**silent**, so your phone only makes noise when a mint actually goes live.

It runs 24/7 in the cloud on GitHub Actions (checks every ~5 minutes) — your
Mac does **not** need to be on.

- Repo: https://github.com/radmatist-sg/asciicats-notifier
- Currently watching: **ASCII Cats** (asciicats.xyz/mint, Robinhood Chain)

---

## Talk to the bot (in your Telegram chat with it)

Send any of these:

| Command | What it does |
|---|---|
| `/list` or `/status` | Show every mint I'm watching + live status |
| `/add ...` | Add a new mint to watch (see below) |
| `/remove Name` | Stop watching a mint, e.g. `/remove ASCII Cats` |
| `/help` | Show the command list |

**Replies take up to ~5 minutes** (that's how often the cloud checks in). This
is normal and doesn't affect the important part — mint-open alerts.

### Adding a mint

Paste an address, a website, and optionally a chain — order doesn't matter:

```
/add Cool Cats 0x1234...abcd https://coolcats.xyz robinhood
```

- Chain defaults to **robinhood**. Also supported: **eth**, **base**.
- The bot reads the contract's supply cap automatically and starts watching.
- It alerts when minting begins (supply starts rising, or the contract's
  open/sale flag flips) — works even on stealth contracts.

**For stealth mints where you only have a website**, paste the link to Zul's
assistant instead — it digs the contract address out of the site for you.

---

## Make the alert LOUD on your phone (one-time, 2 min)

So your phone stays quiet except when a mint opens:

1. Open the bot chat in Telegram → tap its **name at the top**.
2. **Notifications / Customize** → turn notifications **On** and pick a
   **distinctive, loud sound** you'll recognise.
3. (Optional) Mute your other Telegram chats so only this one can ping you.
4. **iPhone Focus/Do Not Disturb:** Settings → Focus → (your focus) → add
   **Telegram** to Allowed Apps, so alerts still come through when you're in DND.

Note: a Telegram bot can't override your phone's physical mute switch (only
Apple's built-in alarms can). If you ever want a true "screaming" alert that
pierces silent mode, ask Zul's assistant to add **Pushover emergency alerts**.

---

## Turning it off

When you're done watching mints, delete the repo (Settings → Delete this
repository) or just ask Zul's assistant to do it.

## Files (for reference)

- `bot.py` — the watcher + command handler (runs in the cloud)
- `targets.json` — the list of mints being watched (auto-updated)
- `.github/workflows/watch.yml` — the every-5-min schedule
- `watch.py` — optional local-only version (runs on your Mac, checks every 20s)
- `config.txt` — your token, kept **only** on your Mac (never uploaded)
