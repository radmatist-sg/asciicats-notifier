# ASCII Cats Mint Notifier — Setup

This little program watches the ASCII Cats NFT on Robinhood Chain and sends
you a **Telegram message the second the mint opens**, plus a running count of
how many of the 3333 cats have been minted.

You only need to do the setup **once**.

---

## Step 1 — Make your Telegram bot (2 minutes)

1. Open Telegram, search for **@BotFather**, tap **Start**.
2. Send: `/newbot`
3. Give it any name (e.g. `ASCII Cats Watcher`) and a username ending in `bot`
   (e.g. `zul_asciicats_bot`).
4. BotFather replies with a **token** that looks like
   `8123456789:AAH...long-random-string...`
5. Copy that token.

## Step 2 — Put the token in config.txt

Open `config.txt` (in this same folder) and paste your token after `BOT_TOKEN=`
so it looks like:

```
BOT_TOKEN=8123456789:AAH...your-token...
CHAT_ID=
```

Leave `CHAT_ID` blank for now — the program fills it in automatically.

## Step 3 — Say hi to your bot

In Telegram, open the bot you just made and tap **Start** (or send it any
message like "hi"). This is what lets it message you back.

## Step 4 — Run it

Open the Terminal app and paste this, then press Enter:

```
python3 "/Users/Zul/Desktop/asciicats-notifier/watch.py"
```

- The first time, it detects your Chat ID and prints a line like
  `CHAT_ID=123456789`. Paste that line into `config.txt` (replacing the blank
  `CHAT_ID=`) so you never have to do it again.
- You'll get a Telegram message: **"👀 ASCII Cats watcher is live."**
  That means it's working.

Leave that Terminal window open. When the mint opens you'll get a
**🚨 MINT IS OPEN** message with the mint link.

To stop it, click the Terminal window and press **Ctrl + C**.

---

## Notes

- It checks every 20 seconds.
- **Your Mac must be awake and the Terminal running** for alerts to arrive.
  If you want it to run in the cloud 24/7 (even with your laptop closed), tell
  Zul's assistant — that's a small extra step we can add.
- The mint is **free, 1 cat per wallet**, and gated by an anti-bot check that
  may ask you to follow/like the @ASCIIcats_ posts on X to get a mint ticket.
  This notifier just tells you *when* to go — you still mint on the website.

## What it's watching (for reference)

- NFT contract: `0xa3F56AdB32D3A8F3b41462e3fBF17f36829325bE` (ASCII CATS)
- Chain: Robinhood Chain (chain id 4663)
- Mint site: https://asciicats.xyz/mint
