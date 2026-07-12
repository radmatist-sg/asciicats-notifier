#!/usr/bin/env python3
"""
Multi-mint watcher + two-way Telegram bot (runs every ~2 min via cron-job.org).

Each run it:
  1. Registers the /command menu (so typing "/" shows the list).
  2. Reads any messages you sent and acts on them, including a guided,
     question-by-question flow for adding a new mint.
  3. Checks every mint in targets.json and sends a LOUD alert the moment a mint
     goes live. Progress pings and replies are silent.

State (watched mints, the getUpdates offset, and any in-progress /add
conversation) lives in targets.json, committed back by the workflow.

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

CHAINS = {
    "robinhood": "https://rpc.mainnet.chain.robinhood.com",
    "ethereum":  "https://eth.merkle.io",
    "eth":       "https://eth.merkle.io",
    "base":      "https://mainnet.base.org",
}
DEFAULT_CHAIN = "robinhood"

SEL = {
    "totalMinted": "0xa2309ff8",
    "totalSupply": "0x18160ddd",
    "MAX_SUPPLY":  "0x32cb6b0c",
    "maxSupply":   "0xd5abeb01",
    "mintOpen":    "0x24bbd049",
    "saleActive":  "0x68428a1b",
}

PROGRESS_STEP = 250

ADDR_RE = re.compile(r"0x[a-fA-F0-9]{40}")
URL_RE  = re.compile(r"https?://[^\s]+")

# The list shown when you type "/" in Telegram
COMMANDS = [
    ("list",   "Show the mints I'm watching + status"),
    ("add",    "Add a new mint (I'll ask you for details)"),
    ("remove", "Stop watching a mint"),
    ("test",   "Send a loud test alert"),
    ("cancel", "Cancel the current step"),
    ("help",   "Show help"),
]

HELP = (
    "🐱 <b>Mint Watcher</b>\n\n"
    "/list — show every mint I'm watching + live status\n"
    "/add — add a mint; I'll ask you for the contract, chain, website and name "
    "one step at a time (or paste it all at once: "
    "<code>/add Name 0xcontract https://site chain</code>)\n"
    "/remove Name — stop watching a mint\n"
    "/test — send a loud test alert\n"
    "/cancel — cancel whatever we're in the middle of\n"
    "/help — this message\n\n"
    "Chains: robinhood (default), eth, base. For stealth mints where you only "
    "have a website, paste the link to Zul's assistant and it'll find the contract."
)


# ----------------------------------------------------------------------------- chain reads
def eth_call(rpc, to, data):
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "eth_call",
                          "params": [{"to": to, "data": data}, "latest"]}).encode()
    req = urllib.request.Request(rpc, data=payload,
                                 headers={"content-type": "application/json", "user-agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            res = json.load(r).get("result")
        return res if res and res != "0x" else None
    except Exception:
        return None


def read_uint(rpc, contract, *names):
    for n in names:
        res = eth_call(rpc, contract, SEL[n])
        if res:
            try:
                return int(res, 16)
            except ValueError:
                pass
    return None


def read_bool(rpc, contract, *names):
    for n in names:
        res = eth_call(rpc, contract, SEL[n])
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


def register_commands():
    tg("setMyCommands",
       commands=json.dumps([{"command": c, "description": d} for c, d in COMMANDS]))


# ----------------------------------------------------------------------------- state
def load_state():
    try:
        with open(TARGETS_FILE) as f:
            s = json.load(f)
    except Exception:
        s = {}
    s.setdefault("targets", [])
    s.setdefault("last_update_id", 0)
    s.setdefault("pending", None)
    return s


def save_state(s):
    with open(TARGETS_FILE, "w") as f:
        json.dump(s, f, indent=2)


# ----------------------------------------------------------------------------- adding mints
def create_target(state, name, contract, chain, site):
    """Read the contract, add it to the watch list, and confirm."""
    if any(t["contract"].lower() == contract.lower() for t in state["targets"]):
        send(f"I'm already watching that contract.")
        return
    rpc = CHAINS.get(chain, CHAINS[DEFAULT_CHAIN])
    baseline = read_supply(rpc, contract)
    cap = read_max(rpc, contract)
    is_open = read_bool(rpc, contract, "mintOpen", "saleActive")
    state["targets"].append({
        "name": name or "Unnamed mint",
        "rpc": rpc,
        "chain": chain,
        "contract": contract,
        "site": site,
        "max_supply": cap,
        "baseline_supply": baseline if baseline is not None else 0,
        "alerted_open": False,
        "sold_out": False,
        "last_notified_count": baseline or 0,
    })
    cap_str = f", cap {cap}" if cap else ""
    open_str = " — ⚠ looks OPEN already!" if is_open else ""
    site_str = f"\n🔗 {site}" if site else ""
    send(f"✅ Now watching <b>{name}</b> on {chain}.{site_str}\n"
         f"Contract {contract[:10]}…{contract[-6:]}{cap_str}. "
         f"Baseline minted: {baseline if baseline is not None else '?'}{open_str}\n"
         f"I'll ping you loudly the moment it opens.")


def cmd_add_oneline(state, arg):
    """Old one-line form: /add Name 0xcontract https://site chain"""
    contract = ADDR_RE.search(arg).group(0)
    url = URL_RE.search(arg)
    site = url.group(0) if url else ""
    chain = DEFAULT_CHAIN
    for key in CHAINS:
        if re.search(rf"\b{key}\b", arg, re.IGNORECASE):
            chain = key.lower()
            break
    name = ADDR_RE.sub("", arg)
    name = URL_RE.sub("", name)
    name = re.sub(rf"\b{chain}\b", "", name, flags=re.IGNORECASE).strip(" -|") or "Unnamed mint"
    create_target(state, name, contract, chain, site)


# ---- guided step-by-step /add ----
ADD_Q = {
    "contract": "🐱 Let's add a mint.\n\nWhat's the <b>contract address</b>? "
                "(starts with <code>0x</code>)\n\nSend /cancel anytime to stop.",
    "chain":    "Which <b>chain</b> is it on? Reply <code>robinhood</code>, "
                "<code>eth</code>, or <code>base</code> — or <code>skip</code> for robinhood.",
    "site":     "What's the <b>mint website</b>? Paste the link, or reply <code>skip</code>.",
    "name":     "Last one — what should I <b>call</b> this mint? (a short name)",
}


def start_add(state, inline_arg):
    if ADDR_RE.search(inline_arg):       # they pasted everything at once
        cmd_add_oneline(state, inline_arg)
        return
    state["pending"] = {"mode": "add", "step": "contract", "data": {}}
    send(ADD_Q["contract"])


def continue_add(state, text):
    p = state["pending"]
    step = p["step"]
    data = p["data"]
    t = text.strip()

    if step == "contract":
        m = ADDR_RE.search(t)
        if not m:
            send("That doesn't look like a contract address (needs <code>0x</code> + 40 "
                 "characters). Try again, or /cancel.")
            return
        data["contract"] = m.group(0)
        p["step"] = "chain"
        send(ADD_Q["chain"])

    elif step == "chain":
        c = t.lower()
        if c in ("skip", ""):
            c = DEFAULT_CHAIN
        if c not in CHAINS:
            send("I don't know that chain. Reply <code>robinhood</code>, <code>eth</code>, "
                 "or <code>base</code> (or <code>skip</code>).")
            return
        data["chain"] = c
        p["step"] = "site"
        send(ADD_Q["site"])

    elif step == "site":
        if t.lower() == "skip":
            data["site"] = ""
        else:
            u = URL_RE.search(t)
            data["site"] = u.group(0) if u else t
        p["step"] = "name"
        send(ADD_Q["name"])

    elif step == "name":
        data["name"] = t or "Unnamed mint"
        create_target(state, data["name"], data["contract"], data["chain"], data["site"])
        state["pending"] = None


# ----------------------------------------------------------------------------- other commands
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
    return f"• <b>{t['name']}</b> — {state} — minted {count}\n   {t.get('site') or '(no site)'}"


def cmd_list(state):
    if not state["targets"]:
        send("I'm not watching any mints yet. Send /add to add one.")
        return
    send("👀 <b>Watching:</b>\n\n" + "\n".join(target_status_line(t) for t in state["targets"]))


def cmd_remove(state, arg):
    name = arg.strip()
    before = len(state["targets"])
    state["targets"] = [t for t in state["targets"] if t["name"].lower() != name.lower()]
    if len(state["targets"]) < before:
        send(f"🗑 Stopped watching <b>{name}</b>.")
    else:
        send(f"Couldn't find a mint called “{name}”. Use /list to see the names.")


# ----------------------------------------------------------------------------- message loop
def process_commands(state):
    resp = tg("getUpdates", offset=state["last_update_id"] + 1, timeout=0)
    if not resp or not resp.get("ok"):
        return
    for upd in resp.get("result", []):
        state["last_update_id"] = max(state["last_update_id"], upd["update_id"])
        msg = upd.get("message") or upd.get("channel_post")
        if not msg or "text" not in msg:
            continue
        text = msg["text"].strip()

        if text.startswith("/"):
            parts = text.split(maxsplit=1)
            cmd = parts[0].lower().lstrip("/").split("@")[0]
            arg = parts[1] if len(parts) > 1 else ""
            if cmd == "cancel":
                state["pending"] = None
                send("Okay, cancelled.")
            elif cmd == "add":
                start_add(state, arg)
            elif cmd in ("list", "status"):
                cmd_list(state)
            elif cmd == "remove":
                cmd_remove(state, arg)
            elif cmd == "test":
                send("🚨🐱 <b>TEST alert</b> — this is how a MINT OPEN will sound. "
                     "If it pinged loudly, you're set. 🐱🚨", loud=True)
            elif cmd in ("help", "start"):
                send(HELP)
            else:
                send("Unknown command. Send /help for the list.")
        else:
            # plain text — treat as an answer if we're mid-conversation
            if state.get("pending"):
                continue_add(state, text)
            else:
                send("Send /help to see what I can do — or /add to watch a new mint.")


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
        count_str = (f"{supply}" + (f"/{cap}" if cap else "")) if supply is not None else "?"
        print(f"[{t['name']}] open={is_open} supply={supply} base={base} started={started}")

        if started and not t.get("alerted_open"):
            t["alerted_open"] = True
            t["last_notified_count"] = supply or 0
            site = t.get("site") or "(no website on file)"
            send(f"🚨🐱 <b>{t['name']} — MINT IS OPEN!</b> 🐱🚨\n\n"
                 f"Minted: <b>{count_str}</b>\n"
                 f"👉 Mint here: {site}\n\n"
                 "Go go go — connect wallet and grab your cat.", loud=True)
            print(f"  >>> LOUD open alert for {t['name']}")
        elif t.get("alerted_open") and supply is not None and \
                supply - t.get("last_notified_count", 0) >= PROGRESS_STEP:
            send(f"🐾 {t['name']} progress: <b>{count_str}</b>")
            t["last_notified_count"] = supply

        if cap and supply is not None and supply >= cap and not t.get("sold_out"):
            t["sold_out"] = True
            send(f"✅ <b>{t['name']} sold out</b> ({count_str}).")


def main():
    if not BOT_TOKEN or not CHAT_ID:
        print("BOT_TOKEN/CHAT_ID missing"); return
    state = load_state()
    register_commands()
    process_commands(state)
    check_targets(state)
    save_state(state)


if __name__ == "__main__":
    main()
