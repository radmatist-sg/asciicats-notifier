#!/usr/bin/env python3
"""
Multi-mint watcher + two-way Telegram bot (runs every ~5 min on GitHub Actions).

Each run it:
  1. Reads any commands you sent the bot (/list, /add, /remove, /status, /help)
     and replies to them.
  2. Checks every mint in targets.json and sends a LOUD alert the moment a mint
     goes live (supply starts rising, or mintOpen()/saleActive() flips true).
     Progress pings and replies are sent SILENTLY, so your phone only makes
     noise when a mint actually opens.

State (watched mints + which Telegram messages we've handled) lives in
targets.json, which the workflow commits back to the repo.

Secrets: env vars BOT_TOKEN and CHAT_ID (GitHub Secrets).
"""

import json
import os
import re
import urllib.request
import urllib.parse

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CHAT_ID   = os.environ.get("CHAT_ID", "")
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) mint-watcher"

TARGETS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "targets.json")

# Named chains so you don't have to paste an RPC URL. Add more as needed.
CHAINS = {
    "robinhood": "https://rpc.mainnet.chain.robinhood.com",
    "ethereum":  "https://eth.merkle.io",
    "eth":       "https://eth.merkle.io",
    "base":      "https://mainnet.base.org",
}
DEFAULT_CHAIN = "robinhood"

# Function selectors (keccak256(sig)[:4])
SEL = {
    "totalMinted": "0xa2309ff8",
    "totalSupply": "0x18160ddd",
    "MAX_SUPPLY":  "0x32cb6b0c",
    "maxSupply":   "0xd5abeb01",
    "mintOpen":    "0x24bbd049",
    "saleActive":  "0x68428a1b",
}

PROGRESS_STEP = 250  # send a (silent) progress ping every this many new mints


# ----------------------------------------------------------------------------- chain
def eth_call(rpc, to, data):
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "eth_call",
                          "params": [{"to": to, "data": data}, "latest"]}).encode()
    req = urllib.request.Request(rpc, data=payload,
                                 headers={"content-type": "application/json", "user-agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            out = json.load(r)
        res = out.get("result")
        if not res or res == "0x":
            return None
        return res
    except Exception:
        return None


def read_uint(rpc, contract, *sel_names):
    """Try each selector in order; return the first that returns a number."""
    for name in sel_names:
        res = eth_call(rpc, contract, SEL[name])
        if res:
            try:
                return int(res, 16)
            except ValueError:
                pass
    return None


def read_bool(rpc, contract, *sel_names):
    for name in sel_names:
        res = eth_call(rpc, contract, SEL[name])
        if res is not None:
            try:
                return int(res, 16) == 1
            except ValueError:
                pass
    return None


def read_supply(rpc, contract):
    return read_uint(rpc, contract, "totalMinted", "totalSupply")


def read_max(rpc, contract):
    return read_uint(rpc, contract, "MAX_SUPPLY", "maxSupply")


# ----------------------------------------------------------------------------- telegram
def tg(method, **params):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    data = urllib.parse.urlencode(params).encode()
    try:
        with urllib.request.urlopen(url, data=data, timeout=25) as r:
            return json.load(r)
    except Exception as e:
        print(f"!! telegram {method} error: {e}")
        return None


def send(text, loud=False):
    tg("sendMessage", chat_id=CHAT_ID, text=text, parse_mode="HTML",
       disable_web_page_preview="false",
       disable_notification=("false" if loud else "true"))


# ----------------------------------------------------------------------------- state
def load_state():
    try:
        with open(TARGETS_FILE) as f:
            s = json.load(f)
    except Exception:
        s = {}
    s.setdefault("targets", [])
    s.setdefault("last_update_id", 0)
    return s


def save_state(s):
    with open(TARGETS_FILE, "w") as f:
        json.dump(s, f, indent=2)


# ----------------------------------------------------------------------------- commands
HELP = (
    "🐱 <b>Mint Watcher — commands</b>\n\n"
    "/list — show every mint I'm watching + live status\n"
    "/status — same as /list\n"
    "/add — add a mint. Paste an address, a website, and (optionally) a chain:\n"
    "    <code>/add Cool Cats 0xabc123... https://coolcats.xyz robinhood</code>\n"
    "    (order doesn't matter; chain defaults to robinhood — also: eth, base)\n"
    "/remove Name — stop watching a mint (e.g. <code>/remove Cool Cats</code>)\n"
    "/test — send a loud test alert (to check your phone sound)\n"
    "/help — this message\n\n"
    "Tip: for stealth mints, you can also just paste the site to Zul's assistant "
    "and it'll dig out the contract for you."
)


def target_status_line(t):
    supply = read_supply(t["rpc"], t["contract"])
    cap = t.get("max_supply")
    count = f"{supply}" if supply is not None else "?"
    if cap:
        count += f"/{cap}"
    if t.get("sold_out"):
        state = "✅ sold out"
    elif t.get("alerted_open") or (supply is not None and supply > t.get("baseline_supply", 0)):
        state = "🟢 OPEN"
    else:
        state = "⏳ waiting"
    return f"• <b>{t['name']}</b> — {state} — minted {count}\n   {t['site']}"


def cmd_list(state):
    if not state["targets"]:
        send("I'm not watching any mints yet. Use /add to add one.")
        return
    lines = [target_status_line(t) for t in state["targets"]]
    send("👀 <b>Watching:</b>\n\n" + "\n".join(lines))


ADDR_RE = re.compile(r"0x[a-fA-F0-9]{40}")
URL_RE  = re.compile(r"https?://[^\s]+")


def cmd_add(state, arg):
    addr = ADDR_RE.search(arg)
    url = URL_RE.search(arg)
    if not addr:
        send("⚠ I couldn't find a contract address (0x...). Try:\n"
             "<code>/add Name 0xcontract https://site chain</code>")
        return
    contract = addr.group(0)
    site = url.group(0) if url else ""
    # figure out the chain from any known keyword
    chain_key = DEFAULT_CHAIN
    for key in CHAINS:
        if re.search(rf"\b{key}\b", arg, re.IGNORECASE):
            chain_key = key.lower()
            break
    rpc = CHAINS[chain_key]
    # name = whatever text is left after stripping address, url and chain word
    name = arg
    name = ADDR_RE.sub("", name)
    name = URL_RE.sub("", name)
    name = re.sub(rf"\b{chain_key}\b", "", name, flags=re.IGNORECASE)
    name = name.strip(" -|") or "Unnamed mint"

    if any(t["contract"].lower() == contract.lower() for t in state["targets"]):
        send(f"Already watching that contract ({name}).")
        return

    baseline = read_supply(rpc, contract)
    cap = read_max(rpc, contract)
    is_open = read_bool(rpc, contract, "mintOpen", "saleActive")

    target = {
        "name": name,
        "rpc": rpc,
        "chain": chain_key,
        "contract": contract,
        "site": site,
        "max_supply": cap,
        "baseline_supply": baseline if baseline is not None else 0,
        "alerted_open": False,
        "sold_out": False,
        "last_notified_count": baseline or 0,
    }
    state["targets"].append(target)
    cap_str = f", cap {cap}" if cap else ""
    open_str = " — ⚠ looks OPEN already!" if is_open else ""
    send(f"✅ Added <b>{name}</b> on {chain_key}.\n"
         f"Contract {contract[:10]}…{contract[-6:]}{cap_str}. "
         f"Baseline minted: {baseline if baseline is not None else '?'}{open_str}\n"
         f"I'll ping you loudly the moment it opens.")


def cmd_remove(state, arg):
    name = arg.strip()
    before = len(state["targets"])
    state["targets"] = [t for t in state["targets"]
                        if t["name"].lower() != name.lower()]
    if len(state["targets"]) < before:
        send(f"🗑 Stopped watching <b>{name}</b>.")
    else:
        send(f"Couldn't find a mint called “{name}”. Use /list to see names.")


def process_commands(state):
    """Read new messages sent to the bot and act on them."""
    resp = tg("getUpdates", offset=state["last_update_id"] + 1, timeout=0)
    if not resp or not resp.get("ok"):
        return
    for upd in resp.get("result", []):
        state["last_update_id"] = max(state["last_update_id"], upd["update_id"])
        msg = upd.get("message") or upd.get("channel_post")
        if not msg or "text" not in msg:
            continue
        text = msg["text"].strip()
        parts = text.split(maxsplit=1)
        cmd = parts[0].lower().lstrip("/").split("@")[0]
        arg = parts[1] if len(parts) > 1 else ""
        if cmd in ("list", "status"):
            cmd_list(state)
        elif cmd == "add":
            cmd_add(state, arg)
        elif cmd == "remove":
            cmd_remove(state, arg)
        elif cmd == "test":
            send("🚨🐱 <b>TEST alert</b> — this is how a MINT OPEN will sound. "
                 "If it pinged loudly, you're set. 🐱🚨", loud=True)
        elif cmd in ("help", "start"):
            send(HELP)
        else:
            send("Unknown command. Send /help for the list.")


# ----------------------------------------------------------------------------- watching
def check_targets(state):
    for t in state["targets"]:
        if t.get("sold_out"):
            continue
        supply = read_supply(t["rpc"], t["contract"])
        is_open = read_bool(t["rpc"], t["contract"], "mintOpen", "saleActive")
        cap = t.get("max_supply")
        base = t.get("baseline_supply", 0)

        started = (is_open is True) or (supply is not None and supply > base)
        count_str = f"{supply}" + (f"/{cap}" if cap else "") if supply is not None else "?"
        print(f"[{t['name']}] open={is_open} supply={supply} base={base} started={started}")

        if started and not t.get("alerted_open"):
            t["alerted_open"] = True
            t["last_notified_count"] = supply or 0
            site = t.get("site") or "(no website on file)"
            send(f"🚨🐱 <b>{t['name']} — MINT IS OPEN!</b> 🐱🚨\n\n"
                 f"Minted: <b>{count_str}</b>\n"
                 f"👉 Mint here: {site}\n\n"
                 "Go go go — check for wallet connect + any tasks needed for a ticket.",
                 loud=True)
            print(f"  >>> LOUD open alert for {t['name']}")

        elif t.get("alerted_open") and supply is not None and \
                supply - t.get("last_notified_count", 0) >= PROGRESS_STEP:
            send(f"🐾 {t['name']} progress: <b>{count_str}</b>")  # silent
            t["last_notified_count"] = supply

        if cap and supply is not None and supply >= cap and not t.get("sold_out"):
            t["sold_out"] = True
            send(f"✅ <b>{t['name']} sold out</b> ({count_str}).")  # silent


def main():
    if not BOT_TOKEN or not CHAT_ID:
        print("BOT_TOKEN/CHAT_ID missing"); return
    state = load_state()
    process_commands(state)
    check_targets(state)
    save_state(state)


if __name__ == "__main__":
    main()
