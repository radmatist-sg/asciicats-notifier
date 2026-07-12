#!/usr/bin/env python3
"""
Single-shot mint check, built for GitHub Actions (runs every ~5 min).

Reads mintOpen()/totalMinted() on the ASCII Cats NFT and sends a Telegram
alert the first time the mint opens, an occasional progress ping, and a
final "sold out" message. State is kept in state.json (committed back by the
workflow) so you only get each alert once.

Secrets come from env vars BOT_TOKEN and CHAT_ID (set as GitHub secrets).
"""

import json
import os
import urllib.request
import urllib.parse

RPC_URL      = "https://rpc.mainnet.chain.robinhood.com"
NFT_CONTRACT = "0xa3F56AdB32D3A8F3b41462e3fBF17f36829325bE"
SITE_URL     = "https://asciicats.xyz/mint"
MAX_SUPPLY   = 3333
SEL_MINT_OPEN    = "0x24bbd049"   # mintOpen()
SEL_TOTAL_MINTED = "0xa2309ff8"   # totalMinted()

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")
BOT_TOKEN  = os.environ.get("BOT_TOKEN", "")
CHAT_ID    = os.environ.get("CHAT_ID", "")

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) asciicats-notifier"


def eth_call(to, data):
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "eth_call",
                          "params": [{"to": to, "data": data}, "latest"]}).encode()
    req = urllib.request.Request(RPC_URL, data=payload,
                                 headers={"content-type": "application/json", "user-agent": UA})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.load(r).get("result")


def mint_is_open():
    res = eth_call(NFT_CONTRACT, SEL_MINT_OPEN)
    return bool(res) and int(res, 16) == 1


def total_minted():
    res = eth_call(NFT_CONTRACT, SEL_TOTAL_MINTED)
    return int(res, 16) if res else None


def notify(text):
    if not BOT_TOKEN or not CHAT_ID:
        print("!! BOT_TOKEN/CHAT_ID not set — cannot send Telegram")
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": CHAT_ID, "text": text, "parse_mode": "HTML",
        "disable_web_page_preview": "false",
    }).encode()
    with urllib.request.urlopen(url, data=data, timeout=25) as r:
        json.load(r)


def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {"alerted_open": False, "sold_out": False, "last_notified_count": 0}


def save_state(s):
    with open(STATE_FILE, "w") as f:
        json.dump(s, f, indent=2)


def main():
    state = load_state()
    is_open = mint_is_open()
    count = total_minted()
    count_str = f"{count}/{MAX_SUPPLY}" if count is not None else "?"
    print(f"mintOpen={is_open} minted={count_str} state={state}")

    if state.get("sold_out"):
        print("Already sold out — nothing to do. You can delete this repo.")
        return

    if is_open and not state.get("alerted_open"):
        notify("🚨🐱 <b>ASCII CATS MINT IS OPEN!</b> 🐱🚨\n\n"
               f"Minted so far: <b>{count_str}</b>\n"
               f"👉 Mint now: {SITE_URL}\n\n"
               "Free, 1 cat per wallet. You may need to do the X/Twitter tasks "
               "to get your mint ticket.")
        state["alerted_open"] = True
        state["last_notified_count"] = count or 0
        print(">>> sent OPEN alert")

    elif is_open and count is not None and count - state.get("last_notified_count", 0) >= 250:
        notify(f"🐾 ASCII Cats minting progress: <b>{count_str}</b>")
        state["last_notified_count"] = count
        print(">>> sent progress ping")

    if count is not None and count >= MAX_SUPPLY and not state.get("sold_out"):
        notify("✅ <b>ASCII Cats sold out</b> — all 3333 minted. "
               "I'll stop watching now.")
        state["sold_out"] = True
        print(">>> sent sold-out alert")

    save_state(state)


if __name__ == "__main__":
    main()
