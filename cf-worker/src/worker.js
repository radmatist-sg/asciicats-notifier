/**
 * Mint Watcher — Cloudflare Worker
 *
 *  fetch()      -> Telegram webhook: instant replies to your messages, including
 *                  the guided /add flow.
 *  scheduled()  -> runs every minute: checks each watched mint and sends a LOUD
 *                  alert the moment one opens.
 *
 * State (watched mints + any in-progress /add conversation) lives in a KV
 * namespace bound as STATE. Secrets: BOT_TOKEN, CHAT_ID, WEBHOOK_SECRET.
 */

const CHAINS = {
  robinhood: "https://rpc.mainnet.chain.robinhood.com",
  ethereum: "https://eth.merkle.io",
  eth: "https://eth.merkle.io",
  base: "https://mainnet.base.org",
};
const DEFAULT_CHAIN = "robinhood";

const SEL = {
  totalMinted: "0xa2309ff8",
  totalSupply: "0x18160ddd",
  MAX_SUPPLY: "0x32cb6b0c",
  maxSupply: "0xd5abeb01",
  mintOpen: "0x24bbd049",
  saleActive: "0x68428a1b",
};

const PROGRESS_STEP = 250;
const ADDR_RE = /0x[a-fA-F0-9]{40}/;
const URL_RE = /https?:\/\/[^\s]+/;

const COMMANDS = [
  ["list", "Show the mints I'm watching + status"],
  ["add", "Add a new mint (I'll ask you for details)"],
  ["remove", "Stop watching a mint"],
  ["test", "Send a loud test alert"],
  ["cancel", "Cancel the current step"],
  ["help", "Show help"],
];

const HELP =
  "🐱 <b>Mint Watcher</b>\n\n" +
  "/list — show every mint I'm watching + live status\n" +
  "/add — add a mint; I'll ask for the contract, chain, website and name one " +
  "step at a time (or paste it all: <code>/add Name 0xcontract https://site chain</code>)\n" +
  "/remove Name — stop watching a mint\n" +
  "/test — send a loud test alert\n" +
  "/cancel — cancel whatever we're in the middle of\n" +
  "/help — this message\n\n" +
  "Chains: robinhood (default), eth, base. Replies are instant now. 🐾";

// ---------------------------------------------------------------- chain reads
async function ethCall(rpc, to, data) {
  try {
    const r = await fetch(rpc, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "eth_call", params: [{ to, data }, "latest"] }),
    });
    const j = await r.json();
    const res = j.result;
    return res && res !== "0x" ? res : null;
  } catch {
    return null;
  }
}

async function readUint(rpc, contract, names) {
  for (const n of names) {
    const res = await ethCall(rpc, contract, SEL[n]);
    if (res) {
      try { return BigInt(res); } catch {}
    }
  }
  return null;
}

async function readBool(rpc, contract, names) {
  for (const n of names) {
    const res = await ethCall(rpc, contract, SEL[n]);
    if (res !== null) {
      try { return BigInt(res) === 1n; } catch {}
    }
  }
  return null;
}

const readSupply = (rpc, c) => readUint(rpc, c, ["totalMinted", "totalSupply"]);
const readMax = (rpc, c) => readUint(rpc, c, ["MAX_SUPPLY", "maxSupply"]);

// ---------------------------------------------------------------- telegram
async function tg(env, method, params) {
  try {
    const r = await fetch(`https://api.telegram.org/bot${env.BOT_TOKEN}/${method}`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(params),
    });
    return await r.json();
  } catch (e) {
    console.log("telegram error", method, e);
    return null;
  }
}

function send(env, text, loud = false) {
  return tg(env, "sendMessage", {
    chat_id: env.CHAT_ID,
    text,
    parse_mode: "HTML",
    disable_web_page_preview: false,
    disable_notification: !loud,
  });
}

// ---------------------------------------------------------------- state (KV)
async function loadState(env) {
  const s = (await env.STATE.get("state", "json")) || {};
  if (!s.targets) s.targets = [];
  if (s.pending === undefined) s.pending = null;
  return s;
}
function saveState(env, s) {
  return env.STATE.put("state", JSON.stringify(s));
}

// ---------------------------------------------------------------- adding mints
async function createTarget(env, state, name, contract, chain, site) {
  if (state.targets.some((t) => t.contract.toLowerCase() === contract.toLowerCase())) {
    await send(env, "I'm already watching that contract.");
    return;
  }
  const rpc = CHAINS[chain] || CHAINS[DEFAULT_CHAIN];
  const baseline = await readSupply(rpc, contract);
  const cap = await readMax(rpc, contract);
  const isOpen = await readBool(rpc, contract, ["mintOpen", "saleActive"]);
  state.targets.push({
    name: name || "Unnamed mint",
    rpc,
    chain,
    contract,
    site: site || "",
    max_supply: cap !== null ? cap.toString() : null,
    baseline_supply: baseline !== null ? baseline.toString() : "0",
    alerted_open: false,
    sold_out: false,
    last_notified_count: baseline !== null ? baseline.toString() : "0",
  });
  const capStr = cap !== null ? `, cap ${cap}` : "";
  const openStr = isOpen ? " — ⚠ looks OPEN already!" : "";
  const siteStr = site ? `\n🔗 ${site}` : "";
  await send(
    env,
    `✅ Now watching <b>${name}</b> on ${chain}.${siteStr}\n` +
      `Contract ${contract.slice(0, 10)}…${contract.slice(-6)}${capStr}. ` +
      `Baseline minted: ${baseline !== null ? baseline : "?"}${openStr}\n` +
      `I'll ping you loudly the moment it opens.`
  );
}

async function addOneLine(env, state, arg) {
  const contract = arg.match(ADDR_RE)[0];
  const url = arg.match(URL_RE);
  const site = url ? url[0] : "";
  let chain = DEFAULT_CHAIN;
  for (const key of Object.keys(CHAINS)) {
    if (new RegExp(`\\b${key}\\b`, "i").test(arg)) { chain = key.toLowerCase(); break; }
  }
  let name = arg.replace(ADDR_RE, "").replace(URL_RE, "")
    .replace(new RegExp(`\\b${chain}\\b`, "i"), "").replace(/[-|\s]+$/, "").replace(/^[-|\s]+/, "").trim();
  if (!name) name = "Unnamed mint";
  await createTarget(env, state, name, contract, chain, site);
}

const ADD_Q = {
  contract: "🐱 Let's add a mint.\n\nWhat's the <b>contract address</b>? (starts with <code>0x</code>)\n\nSend /cancel anytime to stop.",
  chain: "Which <b>chain</b> is it on? Reply <code>robinhood</code>, <code>eth</code>, or <code>base</code> — or <code>skip</code> for robinhood.",
  site: "What's the <b>mint website</b>? Paste the link, or reply <code>skip</code>.",
  name: "Last one — what should I <b>call</b> this mint? (a short name)",
};

async function startAdd(env, state, inlineArg) {
  if (ADDR_RE.test(inlineArg)) { await addOneLine(env, state, inlineArg); return; }
  state.pending = { mode: "add", step: "contract", data: {} };
  await send(env, ADD_Q.contract);
}

async function continueAdd(env, state, text) {
  const p = state.pending;
  const d = p.data;
  const t = text.trim();
  if (p.step === "contract") {
    const m = t.match(ADDR_RE);
    if (!m) { await send(env, "That doesn't look like a contract address (needs <code>0x</code> + 40 characters). Try again, or /cancel."); return; }
    d.contract = m[0]; p.step = "chain"; await send(env, ADD_Q.chain);
  } else if (p.step === "chain") {
    let c = t.toLowerCase();
    if (c === "skip" || c === "") c = DEFAULT_CHAIN;
    if (!(c in CHAINS)) { await send(env, "I don't know that chain. Reply <code>robinhood</code>, <code>eth</code>, or <code>base</code> (or <code>skip</code>)."); return; }
    d.chain = c; p.step = "site"; await send(env, ADD_Q.site);
  } else if (p.step === "site") {
    if (t.toLowerCase() === "skip") d.site = "";
    else { const u = t.match(URL_RE); d.site = u ? u[0] : t; }
    p.step = "name"; await send(env, ADD_Q.name);
  } else if (p.step === "name") {
    d.name = t || "Unnamed mint";
    await createTarget(env, state, d.name, d.contract, d.chain, d.site);
    state.pending = null;
  }
}

// ---------------------------------------------------------------- other commands
async function cmdList(env, state) {
  if (!state.targets.length) { await send(env, "I'm not watching any mints yet. Send /add to add one."); return; }
  const lines = [];
  for (const t of state.targets) {
    const supply = await readSupply(t.rpc, t.contract);
    const cap = t.max_supply ? BigInt(t.max_supply) : null;
    let count = supply !== null ? `${supply}` : "?";
    if (cap) count += `/${cap}`;
    let st;
    if (t.sold_out) st = "✅ sold out";
    else if (t.alerted_open || (supply !== null && supply > BigInt(t.baseline_supply || "0"))) st = "🟢 OPEN";
    else st = "⏳ waiting";
    lines.push(`• <b>${t.name}</b> — ${st} — minted ${count}\n   ${t.site || "(no site)"}`);
  }
  await send(env, "👀 <b>Watching:</b>\n\n" + lines.join("\n"));
}

async function cmdRemove(env, state, arg) {
  const name = arg.trim();
  const before = state.targets.length;
  state.targets = state.targets.filter((t) => t.name.toLowerCase() !== name.toLowerCase());
  if (state.targets.length < before) await send(env, `🗑 Stopped watching <b>${name}</b>.`);
  else await send(env, `Couldn't find a mint called “${name}”. Use /list to see the names.`);
}

// ---------------------------------------------------------------- webhook handling
async function handleUpdate(env, update) {
  const msg = update.message || update.channel_post;
  if (!msg || !msg.text) return;
  const state = await loadState(env);
  const text = msg.text.trim();

  if (text.startsWith("/")) {
    const sp = text.indexOf(" ");
    const cmd = (sp === -1 ? text : text.slice(0, sp)).slice(1).split("@")[0].toLowerCase();
    const arg = sp === -1 ? "" : text.slice(sp + 1);
    if (cmd === "cancel") { state.pending = null; await send(env, "Okay, cancelled."); }
    else if (cmd === "add") await startAdd(env, state, arg);
    else if (cmd === "list" || cmd === "status") await cmdList(env, state);
    else if (cmd === "remove") await cmdRemove(env, state, arg);
    else if (cmd === "test") await send(env, "🚨🐱 <b>TEST alert</b> — this is how a MINT OPEN will sound. If it pinged loudly, you're set. 🐱🚨", true);
    else if (cmd === "help" || cmd === "start") await send(env, HELP);
    else await send(env, "Unknown command. Send /help for the list.");
  } else if (state.pending) {
    await continueAdd(env, state, text);
  } else {
    await send(env, "Send /help to see what I can do — or /add to watch a new mint.");
  }
  await saveState(env, state);
}

// ---------------------------------------------------------------- cron: check mints
async function checkTargets(env) {
  const state = await loadState(env);
  let changed = false;
  for (const t of state.targets) {
    if (t.sold_out) continue;
    const supply = await readSupply(t.rpc, t.contract);
    const isOpen = await readBool(t.rpc, t.contract, ["mintOpen", "saleActive"]);
    const cap = t.max_supply ? BigInt(t.max_supply) : null;
    const base = BigInt(t.baseline_supply || "0");
    const started = isOpen === true || (supply !== null && supply > base);
    const countStr = supply !== null ? `${supply}${cap ? `/${cap}` : ""}` : "?";

    if (started && !t.alerted_open) {
      t.alerted_open = true;
      t.last_notified_count = supply !== null ? supply.toString() : "0";
      changed = true;
      await send(env,
        `🚨🐱 <b>${t.name} — MINT IS OPEN!</b> 🐱🚨\n\n` +
        `Minted: <b>${countStr}</b>\n👉 Mint here: ${t.site || "(no website on file)"}\n\n` +
        "Go go go — connect wallet and grab your cat.", true);
    } else if (t.alerted_open && supply !== null && supply - BigInt(t.last_notified_count || "0") >= BigInt(PROGRESS_STEP)) {
      await send(env, `🐾 ${t.name} progress: <b>${countStr}</b>`);
      t.last_notified_count = supply.toString();
      changed = true;
    }
    if (cap && supply !== null && supply >= cap && !t.sold_out) {
      t.sold_out = true; changed = true;
      await send(env, `✅ <b>${t.name} sold out</b> (${countStr}).`);
    }
  }
  if (changed) await saveState(env, state);
}

// ---------------------------------------------------------------- entrypoints
export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    // one-time helper: /setup registers the command menu + reports webhook info
    if (url.pathname === "/setup") {
      await tg(env, "setMyCommands", { commands: COMMANDS.map(([c, d]) => ({ command: c, description: d })) });
      const info = await tg(env, "getWebhookInfo", {});
      return new Response("commands set. webhook: " + JSON.stringify(info?.result || {}), { status: 200 });
    }
    if (request.method !== "POST") return new Response("mint-watcher up", { status: 200 });
    // verify Telegram's secret header so randoms can't POST to us
    if (env.WEBHOOK_SECRET && request.headers.get("X-Telegram-Bot-Api-Secret-Token") !== env.WEBHOOK_SECRET) {
      return new Response("forbidden", { status: 403 });
    }
    let update;
    try { update = await request.json(); } catch { return new Response("bad", { status: 400 }); }
    await handleUpdate(env, update);
    return new Response("ok", { status: 200 });
  },

  async scheduled(event, env) {
    await checkTargets(env);
  },
};
