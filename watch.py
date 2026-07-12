#!/usr/bin/env python3
"""
ASCII Cats mint notifier.

Watches the ASCII Cats NFT contract on Robinhood Chain and sends you a
Telegram message the instant the mint opens (mintOpen() flips to true),
plus a live count of how many of the 3333 cats have been minted.

Setup: put your bot token + chat id in config.txt (see setup.md), then run:
    python3 watch.py
"""

import json
import time
import urllib.request
import urllib.error
import urllib.parse
import os
import sys

# ---- What we're watching -----------------------------------------------------
RPC_URL       = "https://rpc.mainnet.chain.robinhood.com"
NFT_CONTRACT  = "0xa3F56AdB32D3A8F3b41462e3fBF17f36829325bE"  # ASCII CATS NFT
SITE_URL      = "https://asciicats.xyz/mint"
MAX_SUPPLY    = 3333

# Function selectors (first 4 bytes of keccak256 of the signature)
SEL_MINT_OPEN     = "0x24bbd049"  # mintOpen()   -> bool
SEL_TOTAL_MINTED  = "0xa2309ff8"  # totalMinted() -> uint256

POLL_SECONDS      = 20   # how often to check
HEARTBEAT_MINUTES = 60   # send an "I'm still watching" ping this often

# ---- Config (bot token + chat id) -------------------------------------------
def load_config():
    cfg = {"BOT_TOKEN": "", "CHAT_ID": ""}
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.txt")
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip()
    # env vars override the file if present
    cfg["BOT_TOKEN"] = os.environ.get("BOT_TOKEN", cfg["BOT_TOKEN"])
    cfg["CHAT_ID"]   = os.environ.get("CHAT_ID",   cfg["CHAT_ID"])
    return cfg

CFG = load_config()

# ---- Telegram ----------------------------------------------------------------
def telegram_api(method, params):
    url = f"https://api.telegram.org/bot{CFG['BOT_TOKEN']}/{method}"
    data = urllib.parse.urlencode(params).encode()
    try:
        with urllib.request.urlopen(url, data=data, timeout=20) as r:
            return json.load(r)
    except Exception as e:
        print(f"  ! telegram error: {e}")
        return None

def find_chat_id():
    """If CHAT_ID is blank, grab it from the most recent message sent to the bot."""
    url = f"https://api.telegram.org/bot{CFG['BOT_TOKEN']}/getUpdates"
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            data = json.load(r)
    except Exception as e:
        print(f"  ! could not reach Telegram: {e}")
        return None
    for upd in reversed(data.get("result", [])):
        msg = upd.get("message") or upd.get("channel_post")
        if msg and "chat" in msg:
            return str(msg["chat"]["id"])
    return None

def notify(text):
    if not CFG["BOT_TOKEN"] or not CFG["CHAT_ID"]:
        print(f"  (telegram not configured) {text}")
        return
    telegram_api("sendMessage", {
        "chat_id": CFG["CHAT_ID"],
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": "false",
    })

# ---- Chain reads -------------------------------------------------------------
def eth_call(to, data):
    payload = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "eth_call",
        "params": [{"to": to, "data": data}, "latest"],
    }).encode()
    req = urllib.request.Request(RPC_URL, data=payload, headers={
        "content-type": "application/json",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) asciicats-notifier",
    })
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r).get("result")

def mint_is_open():
    res = eth_call(NFT_CONTRACT, SEL_MINT_OPEN)
    return bool(res) and int(res, 16) == 1

def total_minted():
    res = eth_call(NFT_CONTRACT, SEL_TOTAL_MINTED)
    return int(res, 16) if res else None

# ---- Main loop ---------------------------------------------------------------
def main():
    if not CFG["BOT_TOKEN"]:
        print("No BOT_TOKEN set. Edit config.txt first (see setup.md).")
        sys.exit(1)

    if not CFG["CHAT_ID"]:
        print("No CHAT_ID set — trying to detect it from your Telegram messages...")
        cid = find_chat_id()
        if cid:
            CFG["CHAT_ID"] = cid
            print(f"  found chat id: {cid}")
            print(f"  -> add this line to config.txt so you don't repeat this:")
            print(f"     CHAT_ID={cid}")
        else:
            print("  Could not find it. Open Telegram, send any message to your bot,")
            print("  then run this script again.")
            sys.exit(1)

    print(f"Watching ASCII Cats mint every {POLL_SECONDS}s. Ctrl+C to stop.")
    notify("👀 <b>ASCII Cats watcher is live.</b>\n"
           "I'll message you the moment the mint opens.")

    already_open = False
    last_heartbeat = time.time()
    last_count = None

    while True:
        try:
            is_open = mint_is_open()
            count = total_minted()
            count_str = f"{count}/{MAX_SUPPLY}" if count is not None else "?"
            stamp = time.strftime("%H:%M:%S")
            print(f"[{stamp}] mintOpen={is_open}  minted={count_str}")

            if is_open and not already_open:
                already_open = True
                notify(
                    "🚨🐱 <b>ASCII CATS MINT IS OPEN!</b> 🐱🚨\n\n"
                    f"Minted so far: <b>{count_str}</b>\n"
                    f"👉 Go mint now: {SITE_URL}\n\n"
                    "Remember: free, 1 cat per wallet. You may need to do the\n"
                    "X/Twitter tasks to get your mint ticket."
                )
                print("  >>> SENT OPEN ALERT <<<")

            # Once open, ping every ~2 min with the running count until sold out
            if already_open and count is not None:
                if last_count is None or count - last_count >= 25 or count >= MAX_SUPPLY:
                    if last_count is not None:
                        notify(f"🐾 Minting progress: <b>{count_str}</b>")
                    last_count = count
                if count >= MAX_SUPPLY:
                    notify("✅ <b>Sold out — all 3333 cats minted.</b> Watcher stopping.")
                    break

            # Heartbeat so you know it's still alive before the drop
            if not already_open and time.time() - last_heartbeat > HEARTBEAT_MINUTES * 60:
                last_heartbeat = time.time()
                notify(f"⏳ Still watching. Mint not open yet ({count_str} minted).")

        except urllib.error.URLError as e:
            print(f"  ! network hiccup: {e}")
        except Exception as e:
            print(f"  ! error: {e}")

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
