#!/usr/bin/env node
"use strict";
/*
 * Browser tests for Signal Mobile: the REAL app (the web export of the Expo project, at phone size) talking to the REAL backend, with scripted market data,
 * news and directory (e2e/fake_backend.py, no network). Each scenario starts its own backend.
 *
 *   npm run export:web                      # builds dist/ (the app under test)
 *   export SIGNAL_E2E_PYTHON=/path/to/atlas/backend/.venv/bin/python    # a Python with the backend installed
 *   node e2e/signal.e2e.cjs [scenario ...]  # healthy | stale | partial | missing | login | demo   (default: all)
 *
 * SIGNAL_E2E_SHOTS=<dir> saves a screenshot of the key states (and of any failure). Needs `playwright` (npm i -D playwright && npx playwright install chromium).
 */
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const http = require("node:http");
const net = require("node:net");
const os = require("node:os");
const path = require("node:path");

let chromium;
try { ({ chromium } = require("playwright")); } catch { console.error("The browser tests need Playwright: npm i -D playwright && npx playwright install chromium"); process.exit(2); }

const ROOT = path.resolve(__dirname, "..");
const DIST = path.join(ROOT, "dist");
const PY = process.env.SIGNAL_E2E_PYTHON || "python3";
const SHOTS = process.env.SIGNAL_E2E_SHOTS || "";
if (SHOTS) fs.mkdirSync(SHOTS, { recursive: true });
const T = (id) => `[data-testid="${id}"]`;
const ID = { btc: "CRYPTO:COINBASE:BTC-USD:SPOT", btcEtf: "ETF:ARCA:BTC", solCoin: "CRYPTO:COINBASE:SOL-USD:SPOT", solStock: "EQUITY:NYSE:SOL", aapl: "EQUITY:NASDAQ:AAPL" };
const AGENTS = ["news", "technical", "macro", "fundamentals"];

// ---------------------------------------------------------------------------------------------------------------- tiny test harness
const results = [];
let scenarioName = "";
let livePage = null;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const assert = (c, m) => { if (!c) throw new Error(m || "assertion failed"); };
const eq = (a, b, m) => { const x = JSON.stringify(a), y = JSON.stringify(b); if (x !== y) throw new Error(`${m || "values differ"}\n    expected: ${y}\n    actual:   ${x}`); };
const match = (t, re, m) => { if (!re.test(t)) throw new Error(`${m || `expected text to match ${re}`}\n    text: ${String(t).replace(/\s+/g, " ").slice(0, 500)}`); };
const noMatch = (t, re, m) => { const r = re.exec(t); if (r) throw new Error(`${m || `text must not match ${re}`}\n    found: "${r[0]}"`); };

async function check(name, fn) {
  const t0 = Date.now();
  try {
    await fn();
    results.push({ scenario: scenarioName, name, ok: true });
    console.log(`  ✓ ${name} (${((Date.now() - t0) / 1000).toFixed(1)}s)`);
  } catch (e) {
    results.push({ scenario: scenarioName, name, ok: false, err: e });
    console.log(`  ✗ ${name}\n    ${String(e && e.message ? e.message : e).split("\n").join("\n    ")}`);
    if (SHOTS && livePage) await livePage.screenshot({ path: path.join(SHOTS, `FAIL-${scenarioName}-${name.replace(/[^a-z0-9]+/gi, "-").slice(0, 60)}.png`) }).catch(() => undefined);
  }
}
const shot = async (page, name) => { if (SHOTS) await page.screenshot({ path: path.join(SHOTS, `${scenarioName}-${name}.png`) }).catch(() => undefined); };

// ---------------------------------------------------------------------------------------------------------------- servers
const freePort = () => new Promise((ok, no) => { const s = net.createServer(); s.on("error", no); s.listen(0, "127.0.0.1", () => { const p = s.address().port; s.close(() => ok(p)); }); });
const TYPES = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".png": "image/png", ".ico": "image/x-icon", ".ttf": "font/ttf", ".svg": "image/svg+xml", ".map": "application/json" };
let WEB_ORIGIN = "";

/** Serves the exported app; unknown paths fall back to index.html so deep links such as /asset/<id> work after a reload. */
async function startStatic() {
  const port = await freePort();
  const srv = http.createServer((req, res) => {
    const p = decodeURIComponent(new URL(req.url, "http://x").pathname);
    let file = path.join(DIST, path.normalize(p));
    if (!file.startsWith(DIST) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) file = path.join(DIST, "index.html");
    res.writeHead(200, { "content-type": TYPES[path.extname(file)] || "application/octet-stream" });
    fs.createReadStream(file).pipe(res);
  });
  await new Promise((ok) => srv.listen(port, "127.0.0.1", ok));
  WEB_ORIGIN = `http://localhost:${port}`;
  return srv;
}

const stopProc = (proc) => new Promise((ok) => {
  if (proc.exitCode !== null || proc.signalCode !== null) return ok();          // already gone (a process killed by a signal has a null exit code)
  const t = setTimeout(() => proc.kill("SIGKILL"), 4000);
  proc.once("exit", () => { clearTimeout(t); ok(); });
  proc.kill("SIGTERM");
});

async function startBackend(args = [], { port } = {}) {
  port = port || (await freePort());
  const proc = spawn(PY, [path.join(__dirname, "fake_backend.py"), "--port", String(port), ...args], { env: { ...process.env, ATLAS_CORS_ORIGINS: WEB_ORIGIN, PYTHONUNBUFFERED: "1" }, stdio: ["ignore", "pipe", "pipe"] });
  let log = "";
  proc.stdout.on("data", (d) => (log += d));
  proc.stderr.on("data", (d) => (log += d));
  const url = `http://localhost:${port}`;
  const t0 = Date.now();
  while (Date.now() - t0 < 60000) {
    if (proc.exitCode !== null) throw new Error(`the scripted backend exited:\n${log.slice(-1500)}`);
    try { const r = await fetch(`${url}/api/auth/status`); if (r.ok) return { url, port, origin: new URL(url).origin, proc, stop: () => stopProc(proc) }; } catch { /* not up yet */ }
    await sleep(300);
  }
  await stopProc(proc);
  throw new Error(`the scripted backend did not start:\n${log.slice(-1500)}`);
}

async function api(be, p, { method = "GET", body, token } = {}) {
  const r = await fetch(be.url + p, { method, headers: { ...(body ? { "content-type": "application/json" } : {}), ...(token ? { authorization: `Bearer ${token}` } : {}) }, body: body ? JSON.stringify(body) : undefined });
  let json = null;
  try { json = await r.json(); } catch { /* not json */ }
  return { status: r.status, json };
}
const addVia = (be, id, token) => api(be, "/api/signal/watchlist", { method: "POST", body: { id }, token });

// ---------------------------------------------------------------------------------------------------------------- browser helpers
async function phone(browser) {
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true, locale: "en-US", timezoneId: "UTC" });
  await ctx.addInitScript(() => { window.__opened = []; window.open = (u) => { window.__opened.push(String(u)); return null; }; });     // record links instead of leaving the app
  const origins = new Set();
  const pageErrors = [];
  const consoleErrors = [];
  ctx.on("request", (r) => { try { origins.add(new URL(r.url()).origin); } catch { /* ignore */ } });
  const page = await ctx.newPage();
  page.setDefaultTimeout(20000);
  page.on("pageerror", (e) => pageErrors.push(String(e).slice(0, 300)));
  // React warnings (for example "React does not recognize the ... prop on a DOM element") arrive as console errors, not page errors.
  page.on("console", (m) => { if (m.type() === "error" && /React does not recognize|Warning:|Invalid DOM property|unique "key"|validateDOMNesting/.test(m.text())) consoleErrors.push(m.text().slice(0, 300)); });
  livePage = page;
  return { ctx, page, origins, pageErrors, consoleErrors };
}
const text = (page) => page.evaluate(() => document.body.innerText);
// Screens stay mounted under the one on top, so an id like "stale-banner" can exist twice: always talk about the one the user can see.
const V = (id) => `${T(id)}:visible`;
const inner = (page, testId) => page.locator(V(testId)).first().innerText();
const present = async (page, testId) => (await page.locator(V(testId)).count()) > 0;
// A live card reads the real internet, so in a given run it may show "unavailable" and its content checks then cannot run. That is not a failure (the card is meant to say so), but it must not pass in silence: the healthy run lists every such card at the end.
const SKIPPED = new Set();
const liveCard = async (page, testId) => {
  const here = await present(page, testId);
  if (!here && scenarioName === "healthy") SKIPPED.add(testId.replace(/-body$/, ""));
  return here;
};
const rowIds = (page) => page.$$eval('[data-testid^="row-"]', (els) => els.map((e) => e.getAttribute("data-testid").slice(4)));
const ready = (page) => page.waitForSelector(T("tab-stocks"), { timeout: 25000 });

async function connectTo(page, url, password) {
  await page.goto(WEB_ORIGIN);
  await page.waitForSelector(T("server-url"), { timeout: 25000 });
  await page.fill(T("server-url"), url);
  if (password !== undefined) await page.fill(T("server-password"), password);
  await page.click(T("connect-submit"));
}
async function waitRows(page, ids, ms = 25000) {
  const t0 = Date.now();
  let got = [];
  while (Date.now() - t0 < ms) { got = await rowIds(page); if (JSON.stringify(got) === JSON.stringify(ids)) return got; await sleep(250); }
  eq(got, ids, "watchlist rows");
}
async function openFromWatchlist(page, id) {
  await toStocks(page);
  await page.waitForSelector(T(`row-${id}`));
  await page.locator(T(`row-${id}`)).locator('[role="button"]').first().click();
  await page.waitForSelector(T("asset-name"));
}
const waitAgents = (page, names = AGENTS) => page.waitForFunction((ns) => ns.every((a) => document.querySelector(`[data-testid="takeaway-${a}"]`)), names, { timeout: 45000 });
async function expand(page, agent) {
  await page.locator(T(`agent-toggle-${agent}`)).click();
  await page.waitForSelector(T(`refresh-${agent}`));
  return inner(page, `agent-${agent}`);
}
async function toStocks(page) {            // search is a screen over the tabs on a phone: step back out of it first
  if (await present(page, "search-back")) await page.click(V("search-back"));
  await page.click(V("tab-stocks"));
}
async function gotoSearch(page) {
  if (await present(page, "search-input")) return;
  await toStocks(page);
  await page.click(V("open-search"));
  await page.waitForSelector(T("search-input"));
}
async function search(page, q) {
  await gotoSearch(page);
  const answered = page.waitForResponse((r) => r.url().includes(`/api/signal/search?q=${encodeURIComponent(q)}`), { timeout: 20000 });
  await page.fill(T("search-input"), q);
  await answered;
  await page.waitForFunction(() => !document.querySelector('[data-testid="search-loading"]'), null, { timeout: 10000 });
  await sleep(250);
}
const addFromSearch = async (page, id) => { await page.click(T(`toggle-${id}`)); await page.waitForSelector(`${T(`toggle-${id}`)}[aria-label^="Remove"]`); };
// Every piece of text inside the element with this test id that carries a raw ISO date (2026-11-18), with the test ids of the elements around it, so a failure says where it is. Only that screen is searched: an earlier tab stays in the page behind it.
const rawIsoDates = (page, rootId) => page.evaluate((id) => {
  const root = document.querySelector(`[data-testid="${id}"]`), re = /\b20\d\d-\d\d-\d\d\b/, out = [];
  if (!root) return [`no element with the test id ${id}`];
  const walk = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  for (let n = walk.nextNode(); n; n = walk.nextNode()) {
    if (!re.test(n.nodeValue)) continue;
    const ids = []; for (let p = n.parentElement; p && ids.length < 5; p = p.parentElement) ids.push(p.getAttribute("data-testid") || p.tagName.toLowerCase());
    out.push(`${n.nodeValue.trim().slice(0, 70)}   <- ${ids.join(" < ")}`);
  }
  return out;
}, rootId);
const clickableNames = (page) => page.evaluate(() => [...document.querySelectorAll('button, [role="button"], a, input, [role="link"]')].map((e) => (e.getAttribute("aria-label") || e.innerText || e.getAttribute("placeholder") || "").trim()).filter(Boolean));
const TRADING_CONTROL = /^(buy|sell|short|trade|place|order|submit order|go long|go short)\b/i;
const FORECASTS = /\b(price target of|will (rise|fall|rally|crash|moon)|guaranteed|you should (buy|sell)|buy now|sell now)\b/i;

// ---------------------------------------------------------------------------------------------------------------- scenario 1: everything works
async function healthy(browser) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "signal-e2e-"));
  const db = path.join(dir, "signal.db");
  let be = await startBackend(["--db", db]);
  const S = await phone(browser);
  const page = S.page;
  const state = {};
  try {
    await check("first launch asks for a server address and explains an unreachable one", async () => {
      await page.goto(WEB_ORIGIN);
      await page.waitForSelector(T("connect-title"));
      await page.fill(T("server-url"), "http://localhost:9");
      await page.click(T("connect-submit"));
      await page.waitForSelector(V("connect-error"));
      match(await inner(page, "connect-error"), /reach|connect|server|address/i);
      assert(!(await present(page, "tab-stocks")), "must stay on the connect screen");
    });

    await check("connects and shows an honest empty watchlist under six tabs and a profile icon", async () => {
      await page.fill(T("server-url"), be.url);
      await page.click(T("connect-submit"));
      await page.waitForSelector(T("tab-stocks"));
      await toStocks(page);
      await page.waitForSelector(T("watchlist-empty"));
      const tabs = await page.$$eval('[data-testid^="tab-"]', (els) => els.map((e) => e.innerText.replace(/[^A-Za-z]+/g, "")));
      eq(tabs, ["BTC", "Journey", "Stocks", "Macro", "Discover", "Journal"], "the only tabs");
      assert(await present(page, "profile-button"), "settings must sit behind the profile icon");
      assert(!(await present(page, "demo-banner")), "no demo label on a live server");
      await shot(page, "01-empty-watchlist");
    });

    await check("search tells two assets with the same ticker apart (Bitcoin the coin vs the Bitcoin ETF)", async () => {
      await search(page, "btc");
      const coin = await page.locator(T(`result-${ID.btc}`)).innerText();
      const etf = await page.locator(T(`result-${ID.btcEtf}`)).innerText();
      match(coin, /Bitcoin/); match(coin, /Crypto/); match(coin, /Coinbase/);
      match(etf, /Grayscale/); match(etf, /\bETF\b/); match(etf, /NYSE Arca/); noMatch(etf, /Coinbase/);
      eq((await page.$$eval('[data-testid^="result-"]', (e) => e.map((x) => x.getAttribute("data-testid")))).sort(), [`result-${ID.btc}`, `result-${ID.btcEtf}`].sort(), "results for btc");
      await shot(page, "02-search-btc");
      await addFromSearch(page, ID.btc);
      await addFromSearch(page, ID.btcEtf);
    });

    await check("the same ticker on a stock and a token stay separate too (SOL)", async () => {
      await search(page, "sol");
      const coin = await page.locator(T(`result-${ID.solCoin}`)).innerText();
      const stock = await page.locator(T(`result-${ID.solStock}`)).innerText();
      match(coin, /Crypto/); match(coin, /Coinbase/); match(stock, /Stock/); match(stock, /NYSE/); noMatch(stock, /Coinbase/);
      await addFromSearch(page, ID.solCoin);
    });

    await check("an unknown or unsupported name is said to be unsupported, not silently dropped", async () => {
      await search(page, "zzzzq");
      assert(await present(page, "search-unsupported"), "expected the 'not supported' message");
      match(await inner(page, "search-unsupported"), /No supported asset matches/i);
      assert((await page.locator('[data-testid^="result-"]').count()) === 0, "no results expected");
    });

    await check("a stock is found by company name and recent searches list each asset once, newest first", async () => {
      await search(page, "apple");
      await addFromSearch(page, ID.aapl);
      await page.fill(T("search-input"), "");
      await page.waitForSelector(T("clear-recents"));
      const ids = await page.$$eval('[data-testid^="result-"]', (e) => e.map((x) => x.getAttribute("data-testid").slice(7)));
      eq(ids, [ID.aapl, ID.solCoin, ID.btcEtf, ID.btc], "recent searches");
    });

    await check("the watchlist shows each saved asset with name, type, price, change, sparkline and a takeaway", async () => {
      await toStocks(page);
      await waitRows(page, [ID.btc, ID.btcEtf, ID.solCoin, ID.aapl]);
      for (const id of [ID.btc, ID.btcEtf, ID.aapl]) {
        await page.waitForSelector(T(`price-${id}`));
        const row = await page.locator(T(`row-${id}`)).innerText();
        match(row, /\$[\d,]+\.\d{2}/, `price in ${id}`);
        match(row, /\d+\.\d+%/, `change in ${id}`);
        match(row, /trend|Uptrend|Downtrend|Sideways|range/i, `takeaway in ${id}`);
        assert((await page.locator(T(`row-${id}`)).locator("svg").count()) > 0, `sparkline in ${id}`);
      }
      match(await page.locator(T(`row-${ID.btc}`)).innerText(), /BTC\s+Crypto/);
      match(await page.locator(T(`row-${ID.btcEtf}`)).innerText(), /BTC\s+ETF/);
      await shot(page, "03-watchlist");
    });

    await check("the watchlist survives a page reload", async () => {
      await page.reload(); await ready(page);
      await waitRows(page, [ID.btc, ID.btcEtf, ID.solCoin, ID.aapl]);
    });

    await check("the watchlist lives on the server: a brand-new browser profile sees the same list", async () => {
      const fresh = await phone(browser);
      try {
        await connectTo(fresh.page, be.url);
        await ready(fresh.page);
        await waitRows(fresh.page, [ID.btc, ID.btcEtf, ID.solCoin, ID.aapl]);
      } finally { await fresh.ctx.close(); livePage = page; }
    });

    await check("reordering and removing are saved on the server and survive a reload", async () => {
      await page.click(T("edit-toggle"));
      await page.click(T(`up-${ID.aapl}`));
      await waitRows(page, [ID.btc, ID.btcEtf, ID.aapl, ID.solCoin]);
      await page.click(T(`remove-${ID.solCoin}`));
      await waitRows(page, [ID.btc, ID.btcEtf, ID.aapl]);
      await page.click(T("edit-toggle"));
      await shot(page, "04-watchlist-after-edit");
      await page.reload(); await ready(page);
      await waitRows(page, [ID.btc, ID.btcEtf, ID.aapl]);
      const server = await api(be, "/api/signal/watchlist");
      eq(server.json.data.items.map((r) => r.asset.id), [ID.btc, ID.btcEtf, ID.aapl], "the server's own list");
    });

    await check("Bitcoin the coin: identity, price, freshness with source and time, chart ranges", async () => {
      await openFromWatchlist(page, ID.btc);
      eq(await inner(page, "asset-name"), "Bitcoin");
      eq((await inner(page, "asset-sub")).replace(/\s+/g, " "), "BTC Crypto Coinbase spot (USD)");
      eq(await inner(page, "asset-id"), ID.btc);
      await page.waitForSelector(T("asset-price"));
      match(await inner(page, "asset-price"), /^\$[\d,]+\.\d{2}$/);
      const fresh = await inner(page, "asset-freshness");
      match(fresh, /Live|Delayed|Market closed|Last known|Stale|Demo/, "an explicit freshness label");
      match(fresh, /\d{1,2}:\d{2}/, "the time of the last update");
      match(fresh, /Coinbase/, "the source");
      await page.waitForSelector(T("price-chart"));
      const before = await inner(page, "chart-meta");
      await page.click(T("range-1W"));
      await page.waitForFunction((b) => { const e = document.querySelector('[data-testid="chart-meta"]'); return e && e.innerText !== b; }, before);
      match(await inner(page, "asset-change"), /1W/);
      match(await inner(page, "chart-meta"), /Coinbase/);
      await shot(page, "05-asset-top");
    });

    await check("the briefing answers four questions, names the agent behind each line and says what is missing", async () => {
      await waitAgents(page);
      await page.waitForSelector(T("briefing-headline"));
      for (const k of ["changed", "supports", "risks", "watch"]) assert(await present(page, `briefing-${k}`), `briefing section ${k}`);
      const b = await text(page);
      const lines = (await Promise.all(["changed", "supports", "risks", "watch"].map((k) => inner(page, `briefing-${k}`)))).join("\n");
      match(lines, /\b(Technical|Fundamentals|News|Macro)\s*$/m, "briefing lines name the agent behind them");
      match(await inner(page, "briefing-coverage"), /Macro unavailable/, "coverage note names the agent that is missing");
      noMatch(b, FORECASTS, "no forecasts or advice in the briefing");
      const tops = await Promise.all(AGENTS.map((a) => page.locator(T(`agent-${a}`)).evaluate((e) => e.getBoundingClientRect().top)));
      assert(tops.every((t, i) => i === 0 || t > tops[i - 1]), `agents must appear in the order News, Technical, Macro, Fundamentals (tops: ${tops})`);
      assert((await page.$$eval('[data-testid^="agent-toggle-"]', (e) => e.length)) === 4, "exactly four agent rows, no screens per agent");
    });

    await check("Fundamentals for a coin: protocol figures with sources, and what is NOT available is listed", async () => {
      const f = await expand(page, "fundamentals");
      match(f, /supply/i); match(f, /halving/i);
      match(f, /Key figures/i); match(f, /calculated|reported/);
      match(f, /Not available/i, "missing information is listed");
      match(f, /Sources/i);
      noMatch(f, /P\/E|expense ratio/i, "no stock or ETF figures on a coin");
    });

    await check("Macro explains it is unavailable (no FRED key configured) instead of inventing a view", async () => {
      const m = await expand(page, "macro");
      match(m, /not available right now/i); match(m, /FRED/);
      assert(!(await present(page, "stance-macro")), "no stance without data");
    });

    await check("Bitcoin the ETF is a different asset: its own page, price, and ETF figures instead of coin figures", async () => {
      const coinPrice = await inner(page, "asset-price");
      await page.goto(`${WEB_ORIGIN}/asset/${encodeURIComponent(ID.btcEtf)}`);
      await page.waitForSelector(T("asset-name"));
      eq(await inner(page, "asset-name"), "Grayscale Bitcoin Mini Trust ETF");
      eq((await inner(page, "asset-sub")).replace(/\s+/g, " "), "BTC ETF NYSE Arca");
      eq(await inner(page, "asset-id"), ID.btcEtf);
      await page.waitForSelector(T("asset-price"));
      assert((await inner(page, "asset-price")) !== coinPrice, "the ETF and the coin must not share a price");
      await waitAgents(page);
      const f = await expand(page, "fundamentals");
      match(f, /expense|a year|top 10|assets/i, "ETF figures");
      noMatch(f, /halving/i, "no coin figures on an ETF");
      const n = await expand(page, "news");
      match(n, /also used by/i, "the news agent warns that the ticker is shared");
    });

    await check("Technical (AAPL, trending up): names timeframes, shows calculated levels and an invalidation point, no forecasts", async () => {
      await page.goto(`${WEB_ORIGIN}/asset/${encodeURIComponent(ID.aapl)}`);
      await page.waitForSelector(T("asset-name"));
      await waitAgents(page);
      assert(await present(page, "stance-technical"), "a stance label");
      eq(await inner(page, "stance-technical"), "Supportive");
      const t = await expand(page, "technical");
      match(t, /(Weekly|Daily|1-hour|weekly|daily)/, "timeframe in the takeaway");
      match(t, /Key levels \(calculated from past prices\)/i);
      match(t, /(Support|Resistance) · (1D|1W|1H|4H|15M)/i, "levels name their timeframe");
      match(t, /A daily close below \$[\d,.]+ \(the nearest daily support\) would weaken this setup/i, "an invalidation point");
      match(t, /not a stop-loss or price target/i, "the invalidation level is a reference, not an instruction");
      match(t, /Limits of this analysis/i);
      match(t, /not a forecast/i);
      match(t, /as of .*\d{1,2}:\d{2}/, "data timestamp");
      noMatch(t, FORECASTS);
      await shot(page, "06-technical-open");
    });

    await check("News: sources, publication times, wording labels; unsafe links and markup stay inert", async () => {
      const n = await expand(page, "news");
      match(n, /Stories \(reporting, with sources\)/i);
      match(n, /Yahoo Finance \(per symbol\) · published \d+h ago/, "source and publication time on every story");
      match(n, /Unconfirmed report \(judged by wording only\)/); match(n, /Opinion \(judged by wording only\)/);
      match(n, /Why it may matter/i);
      match(n, /Ignore all previous instructions/, "the hostile headline is shown as plain text");
      const stories = page.locator('[data-testid^="story-"]');
      const hostile = stories.filter({ hasText: "Ignore all previous instructions" });
      assert((await hostile.locator('[role="link"]').count()) === 0, "a headline with an unsafe link must not be a link");
      const linked = stories.filter({ hasText: "Record quarterly revenue" });
      await linked.locator('[role="link"]').first().click();
      await hostile.locator("div").first().click({ force: true }).catch(() => undefined);
      eq(await page.evaluate(() => window.__opened), ["https://news.example/revenue"], "only the safe https link opens");
      assert((await page.evaluate(() => window.__pwned)) === undefined, "markup in a headline must not run");
      assert((await page.locator('img[src="x"]').count()) === 0, "markup in a headline must not become elements");
      const b = await inner(page, "briefing-changed");
      if (/Ignore all previous/.test(b)) match(b, /“[^”]*Ignore all previous[^”]*”/, "an injected instruction may only ever appear quoted as a headline");
      assert(!/BUY NOW/.test(await inner(page, "takeaway-technical")) && !/BUY NOW/.test(await inner(page, "takeaway-fundamentals")), "other agents are unaffected by a hostile headline");
      await shot(page, "07-news-open");
    });

    await check("when agents disagree the briefing says so and each agent keeps its own view (SOL the stock: Technical cautious, Fundamentals supportive)", async () => {
      await page.goto(`${WEB_ORIGIN}/asset/${encodeURIComponent(ID.solStock)}`);
      await page.waitForSelector(T("asset-name"));
      await waitAgents(page);
      await page.waitForSelector(T("briefing-disagreement"));
      const d = await inner(page, "briefing-disagreement");
      match(d, /Technical/); match(d, /Fundamentals/); match(d, /cautious/i); match(d, /supportive/i);
      eq(await inner(page, "stance-technical"), "Cautious");
      eq(await inner(page, "stance-fundamentals"), "Supportive");
      await shot(page, "07b-disagreement");
    });

    await check("the app never offers to trade and never talks to a data provider directly", async () => {
      const bad = [];
      bad.push(...(await clickableNames(page)).filter((n) => TRADING_CONTROL.test(n)));          // asset screen, every agent that was opened
      await page.click(T("back"));
      bad.push(...(await clickableNames(page)).filter((n) => TRADING_CONTROL.test(n)));          // watchlist
      await gotoSearch(page);
      bad.push(...(await clickableNames(page)).filter((n) => TRADING_CONTROL.test(n)));          // search
      eq(bad, [], "trading controls");
      const probe = await api(be, "/api/signal/orders", { method: "POST", body: {} });
      assert(probe.status === 404 || probe.status === 405, `there must be no order endpoint (got ${probe.status})`);
      const meta = await api(be, "/api/signal/meta");
      eq(meta.json.data.live_trading, false, "live_trading flag");
      const allowed = new Set([new URL(WEB_ORIGIN).origin, be.origin, "http://localhost:9"]);       // :9 is the deliberately wrong address typed in the first check
      const stray = [...S.origins].filter((o) => !allowed.has(o) && !o.startsWith("data:") && !o.startsWith("blob:") && o !== "null");
      eq(stray, [], "every request goes to the app or its own server");
      const jsDir = path.join(DIST, "_expo/static/js/web");
      const bundle = fs.readdirSync(jsDir).map((f) => fs.readFileSync(path.join(jsDir, f), "utf8")).join("\n");
      noMatch(bundle, /FRED_API_KEY|ATLAS_AUTH_PASSWORD|COINGECKO_API_KEY|sk-ant-|api\.stlouisfed\.org|query1\.finance\.yahoo\.com|api\.exchange\.coinbase\.com/, "the app bundle holds no provider keys or provider endpoints");
    });

    await check("settings sit behind the profile icon and say what mode the server is in", async () => {
      await toStocks(page);
      await page.click(T("profile-button"));
      await page.waitForSelector(T("settings-title"));
      eq(await inner(page, "settings-server"), be.url);
      match(await text(page), /Live mode/);
      noMatch(await text(page), /Demo mode/);
      await shot(page, "08-settings");
      await page.click(T("settings-close"));
      await page.waitForSelector(T("tab-stocks"));
    });

    await check("Operations in Settings: scheduler status, jobs with freshness and next run, honest Claude usage, budgets, pause and resume, no trading controls", async () => {
      await toStocks(page);
      await page.click(T("profile-button"));
      await page.waitForSelector(T("settings-title"));
      await page.waitForSelector(T("ops-body") + ", " + T("ops-error"), { timeout: 30000 });
      const t = await text(page);
      match(t, /Operations/); match(t, /Health and data-quality checks/); match(t, /Last success/); match(t, /Claude access: not set/);
      match(t, /not known to this app/, "remaining Claude allowance is never invented"); match(t, /Dollar cost is unknown/, "no price is assumed");
      match(t, /ai_tokens \(per day\)/); match(t, /Emergency stop/);
      await page.click(T("ops-pause"));
      await page.waitForSelector(T("ops-resume"), { timeout: 20000 });
      match(await text(page), /Paused/);
      await page.click(T("ops-resume"));
      await page.waitForSelector(T("ops-pause"), { timeout: 20000 });
      eq((await clickableNames(page)).filter((n) => TRADING_CONTROL.test(n)), [], "trading controls in Operations");
      await page.click(T("settings-close"));
      await page.waitForSelector(T("tab-stocks"));
    });

    await check("offline: the saved list is shown with a clear notice; the server's return clears it; nothing is lost", async () => {
      await page.goto(WEB_ORIGIN); await ready(page);
      await waitRows(page, [ID.btc, ID.btcEtf, ID.aapl]);
      assert(!(await present(page, "offline-banner")), "no offline notice while the server answers");
      await be.stop();
      await page.reload(); await ready(page);
      await page.waitForSelector(V("offline-banner"), { timeout: 30000 });
      match(await inner(page, "offline-banner"), /Can't reach the server/);
      await waitRows(page, [ID.btc, ID.btcEtf, ID.aapl]);
      assert(!(await present(page, "demo-banner")), "a live server's saved copy is never labelled demo");
      await shot(page, "09-offline");
      be = await startBackend(["--db", db], { port: be.port });
      await page.click(T("offline-retry"));
      await page.waitForFunction(() => !document.querySelector('[data-testid="offline-banner"]'), null, { timeout: 30000 });
      await waitRows(page, [ID.btc, ID.btcEtf, ID.aapl]);
    });

    await check("wide screens: watchlist on the left, research in the middle, news on the right, a ticker on top, and still no trading", async () => {
      const d = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: "en-US", timezoneId: "UTC" });
      const w = await d.newPage();
      w.setDefaultTimeout(20000);
      livePage = w;
      try {
        await connectTo(w, be.url);
        await w.waitForSelector(T("ticker"));
        for (const d of ["btc", "journey", "stocks", "macro", "discover", "journal"]) assert(await present(w, `nav-${d}`), `top navigation must offer ${d}`);
        await w.click(T("nav-stocks"));
        await w.waitForSelector(T("pane-watchlist"));
        await w.waitForSelector(T("news-panel"));
        await waitRows(w, [ID.btc, ID.btcEtf, ID.aapl]);
        await w.locator(T(`row-${ID.aapl}`)).locator('[role="button"]').first().click();
        await w.waitForFunction(() => document.querySelector('[data-testid="asset-name"]')?.textContent === "Apple Inc.");
        await w.waitForSelector(T("story-1"), { timeout: 30000 }).catch(() => undefined);
        await w.waitForFunction(() => document.querySelectorAll('[data-testid="news-panel"] [data-testid^="story-"]').length > 0, null, { timeout: 30000 });
        const x = async (id) => (await w.locator(T(id)).first().boundingBox()).x;
        const left = await x(`row-${ID.aapl}`), mid = await x("asset-name"), right = await x("news-panel");
        assert(left < mid && mid < right, `panes must run left to right (x: ${left}, ${mid}, ${right})`);
        match(await inner(w, "news-panel"), /Yahoo Finance \(per symbol\)/, "stories name their source");
        eq((await clickableNames(w)).filter((n) => TRADING_CONTROL.test(n)), [], "trading controls on the wide layout");
        await shot(w, "10-wide");
        await w.click(T("pane-search"));
        await w.waitForSelector(T("search-input"));
        await w.click(T("profile-button"));
        await w.waitForSelector(T("settings-drawer"));
        await shot(w, "11-wide-settings");
      } finally { await d.close(); livePage = page; }
    });

    await check("Journal tab: a note, then a trade with exact P&L, filter, edit and delete", async () => {
      await page.click(T("tab-journal"));
      await page.waitForSelector(T("journal-empty"));
      await page.click(T("journal-empty-add"));
      await page.fill(T("f-symbol"), "btc");
      await page.fill(T("f-note"), "Watching the 200 day average");
      await page.click(T("entry-save"));
      await page.waitForSelector(V("journal-list"));
      assert(await page.locator('[data-testid^="entry-e:"]').count() === 1, "one entry after saving a bare note");
      const noteRow = await page.locator('[data-testid^="entry-e:"]').first().innerText();
      match(noteRow, /Note/, "a plain note is tagged Note");
      noMatch(noteRow, /Long|Short/, "a plain note must not look like a long or short position");
      await page.click(T("journal-add"));
      await page.fill(T("f-symbol"), "aapl");
      await page.fill(T("f-size"), "10");
      await page.fill(T("f-entry"), "100");
      await page.fill(T("f-exit"), "110");
      await page.click(T("entry-save"));
      await page.waitForSelector(V("journal-stats"));
      const st = await inner(page, "journal-stats");
      match(st, /\+100\.00/, "net P&L is 10 x (110 - 100)");
      match(await text(page), /\+10\.00%/, "return on cost");
      await shot(page, "12b-journal-with-trade");
      await page.click(T("journal-filter-note"));
      await sleep(400);
      eq(await page.locator('[data-testid^="entry-e:"]').count(), 1, "notes filter");
      await page.click(T("journal-filter-all"));
      await sleep(300);
      await page.locator('[data-testid^="entry-e:"]').first().click();
      await page.waitForSelector(T("entry-delete"));
      await page.click(T("entry-delete"));
      await sleep(500);
      eq(await page.locator('[data-testid^="entry-e:"]').count(), 1, "one entry left after a delete");
      eq((await clickableNames(page)).filter((n) => TRADING_CONTROL.test(n)), [], "trading controls in the journal");
      await shot(page, "12-journal");
    });

    await check("Journey tab: the paper lab says what the research run decided, lists each strategy with its backtest and verdict, records orders on signal, and offers no trading controls", async () => {
      await page.click(V("tab-journey"));
      await page.waitForSelector(`${T("journey-headline")}, ${T("journey-unavailable")}, ${T("journey-error")}`);
      if (!(await present(page, "journey-headline"))) {          // no daily run on this machine: the page must say so plainly, and that is all there is to check
        match(await text(page), /paper lab has not run yet|Can't load the paper lab/i, "the page must say why there is nothing to show");
        return;
      }
      const head = await inner(page, "journey-headline");
      match(head, /strategies passed|No research run yet/i, "the verdict of the research run is the first thing said");
      match(head, /DISABLED|nothing in this system can place an order/i, "real trading is stated as disabled");
      const qFile = path.join(ROOT, "..", "btcquant", "owner_question.json");          // the question the loop waits for the owner to answer: its card is there exactly when the file is
      const squash = (s) => String(s).replace(/\s+/g, " ").trim();
      if (fs.existsSync(qFile)) {
        const q = JSON.parse(fs.readFileSync(qFile, "utf8"));
        assert(await present(page, "journey-question"), "the question for the owner is shown on the Journey page");
        eq(squash(await inner(page, "journey-question-title")), squash(q.title), "the question's title");
        const qBody = squash(await inner(page, "journey-question"));
        match(qBody, /^A decision is waiting for you · asked \d{1,2} [A-Z][a-z]{2} 20\d\d /, "when it was asked, in the page's date style");
        for (const p of q.paragraphs) assert(qBody.includes(squash(p)), `a paragraph of the question is shown: ${p.slice(0, 40)}`);
        for (const o of q.options) assert(squash(await inner(page, `journey-question-option-${o.id}`)).startsWith(`${o.id} ${squash(o.text)}`), `option ${o.id} is shown with its text`);
        eq((qBody.match(/Recommended/g) || []).length, q.options.filter((o) => o.recommended).length, "the recommended tag is on the option marked so, and only there");
        assert(qBody.endsWith(squash(q.how_to_answer)), "how to answer comes last");
        eq(await page.locator(`${T("journey-question")} [role="button"], ${T("journey-question")} a, ${T("journey-question")} button, ${T("journey-question")} input`).count(), 0, "the question is text only: nothing in it can be tapped");
        noMatch(qBody, FORECASTS, "the question makes no promise of profit");
      } else {
        eq(await page.locator(T("journey-question")).count(), 0, "no question card when no question is waiting");
      }
      eq(await page.locator(T("journey-question-problem")).count(), 0, "no problem line while the file is sound");
      assert(await present(page, "journey-cards"), "the paper accounts are shown as cards");
      const ids = await page.$$eval('[data-testid^="journey-row-"]', (els) => els.map((e) => e.getAttribute("data-testid")));
      assert(ids.length >= 1, "at least one strategy row");
      for (const id of ids) match(await page.locator(`${T(id)}:visible`).first().innerText(), /Rejected|Too few trades to judge|Admitted/, `${id} must show its verdict`);
      await page.locator(`${T(ids[0])}:visible`).locator('[role="button"]').first().click();
      await page.waitForSelector(V(`journey-detail-${ids[0].slice("journey-row-".length)}`));
      assert(await present(page, "curve-chart"), "an opened strategy shows its backtest as a chart");
      const detail = await inner(page, `journey-detail-${ids[0].slice("journey-row-".length)}`);
      match(detail, /Holding Bitcoin over the same days/, "the backtest is set beside holding Bitcoin");
      match(detail, /Paper: day \d+/, "the forward paper record is stated");
      match(await inner(page, "journey-note"), /simulations/i, "the page says these are simulations");
      await shot(page, "17-journey");
      const names = await clickableNames(page);
      eq(names.filter((n) => TRADING_CONTROL.test(n)), [], "trading controls on the Journey page");
      noMatch(await text(page), FORECASTS, "no promise of profit");
      eq(await rawIsoDates(page, "journey-scroll"), [], "no raw ISO date on the Journey page (dates read like 17 Nov 2026)");
      await page.evaluate(() => { const el = document.querySelector('[data-testid="journey-scroll"]'); if (el) el.scrollTop = 0; });      // the top of the page: the verdict card with its label and sentence
      await sleep(300);
      await shot(page, "17a-journey-top");
      if (fs.existsSync(qFile)) {
        await page.locator(V("journey-question")).first().evaluate((el) => el.scrollIntoView({ block: "start" })).catch(() => undefined);      // the question card itself, from its top
        await sleep(300);
        await shot(page, "17d-journey-question");
      }
      await page.evaluate(() => { const el = document.querySelector('[data-testid="journey-scroll"]'); if (el) el.scrollTop = 1e6; });
      await sleep(300);
      await shot(page, "17b-journey-feed");
      await page.locator(V("journey-feed")).first().evaluate((el) => el.scrollIntoView({ block: "start" })).catch(() => undefined);      // the newest orders: where an account's first order and a signal waiting for the next open are worded
      await sleep(300);
      await shot(page, "17c-journey-feed-top");
    });

    await check("Macro: what matters today, indicators and headlines are labelled, gaps are listed, and a missing FRED key is said plainly", async () => {
      await page.click(T("tab-macro"));
      await page.waitForSelector(V("macro-brief"));
      await page.waitForSelector(V("treasury-card"));
      await page.waitForSelector(V("treasury-body") + ", " + V("treasury-error"), { timeout: 45000 });
      const t = await text(page);
      await page.waitForSelector(V("fx-card"));
      await page.waitForSelector(V("fx-body") + ", " + V("fx-unavailable") + ", " + V("fx-error"), { timeout: 45000 });
      const fxText = await text(page);
      await page.waitForSelector(V("world-card"));
      await page.waitForSelector(V("world-body") + ", " + V("world-unavailable") + ", " + V("world-error"), { timeout: 60000 });
      const wt = await text(page);
      await page.waitForSelector(V("fedops-card"));
      await page.waitForSelector(V("fedops-body") + ", " + V("fedops-unavailable") + ", " + V("fedops-error"), { timeout: 45000 });
      const fo = await text(page);
      match(fo, /Fed liquidity operations/); match(fo, /New York Fed/); noMatch(fo, FORECASTS, "the Fed operations card makes no forecasts");
      if (await liveCard(page, "fedops-body")) match(fo, /not market signals or forecasts/, "the plumbing caveat is shown");
      await page.waitForSelector(V("tga-card"));
      await page.waitForSelector(V("tga-body") + ", " + V("tga-unavailable") + ", " + V("tga-error"), { timeout: 45000 });
      const tg = await text(page);
      match(tg, /Treasury cash balance/); match(tg, /US Treasury/); noMatch(tg, FORECASTS, "the Treasury balance card makes no forecasts");
      if (await liveCard(page, "tga-body")) match(tg, /not a market signal or a forecast/, "the plumbing caveat is shown");
      await page.waitForSelector(V("auctions-card"));
      await page.waitForSelector(V("auctions-body") + ", " + V("auctions-unavailable") + ", " + V("auctions-error"), { timeout: 45000 });
      const au = await text(page);
      match(au, /Treasury auctions/); match(au, /US Treasury/); noMatch(au, FORECASTS, "the auctions card makes no forecasts");
      if (await liveCard(page, "auctions-body")) match(au, /not market signals or forecasts/, "the auction caveat is shown");
      await page.waitForSelector(V("budget-card"));
      await page.waitForSelector(V("budget-body") + ", " + V("budget-unavailable") + ", " + V("budget-error"), { timeout: 45000 });
      const bu = await text(page);
      match(bu, /Federal budget/); match(bu, /US Treasury/); noMatch(bu, FORECASTS, "the budget card makes no forecasts");
      if (await liveCard(page, "budget-body")) match(bu, /not market signals or forecasts/, "the budget caveat is shown");
      await page.waitForSelector(V("interest-card"));
      await page.waitForSelector(V("interest-body") + ", " + V("interest-unavailable") + ", " + V("interest-error"), { timeout: 45000 });
      const ie = await text(page);
      match(ie, /Interest on the debt/); match(ie, /US Treasury/); noMatch(ie, FORECASTS, "the interest card makes no forecasts");
      if (await liveCard(page, "interest-body")) {
        match(ie, /not a market signal or a forecast/, "the interest caveat is shown");
        match(await inner(page, "interest-body"), /Treasury bills[\s\S]*Treasury notes[\s\S]*Treasury bonds/, "the breakdown lists the security types");
        const ib = await inner(page, "interest-body");
        match(ib, /^(January|February|March|April|May|June|July|August|September|October|November|December) 20\d\d/, "the month is written out, not a raw 2026-10");
        noMatch(ib, /\b20\d\d-\d\d\b/, "no raw year-month codes on screen");
        noMatch(ib, /\([+\u2212-]\d/, "the comparison is a sentence, not a bracketed signed number");
      }
      await page.locator(V("interest-card")).scrollIntoViewIfNeeded().catch(() => undefined);
      await shot(page, "07b-interest");
      await page.waitForSelector(V("buybacks-card"));
      await page.waitForSelector(V("buybacks-body") + ", " + V("buybacks-unavailable") + ", " + V("buybacks-error"), { timeout: 45000 });
      const bb = await text(page);
      match(bb, /Treasury buybacks/); match(bb, /US Treasury/); noMatch(bb, FORECASTS, "the buybacks card makes no forecasts");
      if (await liveCard(page, "buybacks-body")) {
        match(bb, /not a market signal or a forecast/, "the buybacks caveat is shown");
        const bbody = await inner(page, "buybacks-body");
        match(bbody, /Latest operation · [A-Z][a-z]{2} \d{1,2}, 20\d\d/, "the date is written out");
        match(bbody, /Last 90 days[\s\S]*Last 12 months/, "both windows are shown");
        noMatch(bbody, /\b20\d\d-\d\d-\d\d\b/, "no raw ISO dates on screen");
      }
      await page.locator(V("buybacks-card")).scrollIntoViewIfNeeded().catch(() => undefined);
      await shot(page, "07c-buybacks");
      await page.waitForSelector(V("bills-card"));
      await page.waitForSelector(V("bills-body") + ", " + V("bills-unavailable") + ", " + V("bills-error"), { timeout: 45000 });
      const bl = await text(page);
      match(bl, /Treasury bill auctions/); match(bl, /US Treasury/); noMatch(bl, FORECASTS, "the bill auctions card makes no forecasts");
      if (await liveCard(page, "bills-body")) {
        match(bl, /not market signals or forecasts/, "the bill auctions caveat is shown");
        const bbody = await inner(page, "bills-body");
        match(bbody, /4-week[\s\S]*13-week[\s\S]*26-week/, "the terms are listed");
        match(bbody, /Newest completed auction · [A-Z][a-z]{2} \d{1,2}, 20\d\d/, "the date is written out");
        noMatch(bbody, /\b20\d\d-\d\d-\d\d\b/, "no raw ISO dates on screen");
      }
      await page.locator(V("bills-card")).scrollIntoViewIfNeeded().catch(() => undefined);
      await shot(page, "07d-bills");
      await page.waitForSelector(V("borrowing-card"));
      await page.waitForSelector(V("borrowing-body") + ", " + V("borrowing-unavailable") + ", " + V("borrowing-error"), { timeout: 45000 });
      const bo = await text(page);
      match(bo, /Treasury borrowing/); match(bo, /US Treasury/); noMatch(bo, FORECASTS, "the borrowing card makes no forecasts");
      if (await liveCard(page, "borrowing-body")) {
        match(bo, /not a market signal or a forecast/, "the borrowing caveat is shown");
        const bbody = await inner(page, "borrowing-body");
        match(bbody, /^(January|February|March|April|May|June|July|August|September|October|November|December) 20\d\d so far · through [A-Z][a-z]{2} \d{1,2}, 20\d\d/, "the month and the date are written out");
        match(bbody, /Net new borrowing this month[\s\S]*Fiscal 20\d\d so far[\s\S]*Treasury bills[\s\S]*Treasury notes[\s\S]*Treasury bonds/, "month, fiscal year and the types are shown");
        noMatch(bbody, /\b20\d\d-\d\d-\d\d\b/, "no raw ISO dates on screen");
        noMatch(bbody, /DOES NOT MATCH/, "the self-check against the source must pass");
      }
      await page.locator(V("borrowing-card")).scrollIntoViewIfNeeded().catch(() => undefined);
      await shot(page, "07e-borrowing");
      await page.waitForSelector(V("dealers-card"));
      await page.waitForSelector(V("dealers-body") + ", " + V("dealers-unavailable") + ", " + V("dealers-error"), { timeout: 45000 });
      const dl = await text(page);
      match(dl, /Dealer Treasury positions/); match(dl, /New York Fed/); noMatch(dl, FORECASTS, "the dealer positions card makes no forecasts");
      if (await liveCard(page, "dealers-body")) {
        match(dl, /not a market signal or a forecast/, "the dealer caveat is shown");
        const dbody = await inner(page, "dealers-body");
        match(dbody, /Net position in US Treasuries · as of [A-Z][a-z]{2} \d{1,2}, 20\d\d/, "the date is written out");
        match(dbody, /Same week a year earlier[\s\S]*Last \d+ weeks/, "year-ago and range are shown");
        noMatch(dbody, /\b20\d\d-\d\d-\d\d\b/, "no raw ISO dates on screen");
        noMatch(dbody, /DOES NOT MATCH/, "the week shown must fit the source's own change figure");
        const dcheck = await inner(page, "dealers-check");
        match(dcheck, /^Checked: /, "the self-check line is there: either every week fits, or the latest week fits and the older weeks that do not are named");
        if (!/equal the source's own change figures for the last/.test(dcheck)) match(dcheck, /^Checked: the latest week's change equals the source's own change figure\. In \d+ of the last \d+ weeks the source's own figures do not fit each other \(week of [A-Z][a-z]{2} \d{1,2}, 20\d\d: its levels give -?\$[\d,.]+B, its change figure says -?\$[\d,.]+B/, "an older week the source itself no longer fits is named, with both figures");
      }
      await page.locator(V("dealers-card")).scrollIntoViewIfNeeded().catch(() => undefined);
      await shot(page, "07f-dealers");

      await page.waitForSelector(V("futurespos-card"));
      await page.waitForSelector(V("futurespos-body") + ", " + V("futurespos-unavailable") + ", " + V("futurespos-error"), { timeout: 45000 });
      const fp = await text(page);
      match(fp, /Futures positioning/); match(fp, /CFTC/); noMatch(fp, FORECASTS, "the futures positioning card makes no forecasts");
      if (await liveCard(page, "futurespos-body")) {
        const fbody = await inner(page, "futurespos-body");
        match(fbody, /S&P 500 futures \(E-mini\) · as of [A-Z][a-z]{2} \d{1,2}, 20\d\d/, "the date is written out");
        match(fbody, /Leveraged funds: net/); match(fbody, /Asset managers: net/); match(fbody, /10-year Treasury note futures/);
        match(fbody, /checked against the report's own totals/, "the self-check is stated");
        match(fbody, /not a market signal or a forecast/, "the caveat is shown");
        noMatch(fbody, /\b20\d\d-\d\d-\d\d\b/, "no raw ISO dates on screen");
      }
      await page.locator(V("futurespos-card")).scrollIntoViewIfNeeded().catch(() => undefined);
      await shot(page, "07g-futurespos");

      await page.waitForSelector(V("commoditypos-card"));
      await page.waitForSelector(V("commoditypos-body") + ", " + V("commoditypos-unavailable") + ", " + V("commoditypos-error"), { timeout: 45000 });
      const cp = await text(page);
      match(cp, /Commodity positioning/); match(cp, /CFTC/); noMatch(cp, FORECASTS, "the commodity positioning card makes no forecasts");
      if (await liveCard(page, "commoditypos-body")) {
        const cbody = await inner(page, "commoditypos-body");
        match(cbody, /Gold futures · as of [A-Z][a-z]{2} \d{1,2}, 20\d\d/, "the date is written out");
        match(cbody, /Managed money: net/); match(cbody, /Swap dealers: net/); match(cbody, /Natural gas futures/);
        match(cbody, /checked against the report's own totals/, "the self-check is stated");
        match(cbody, /not a market signal or a forecast/, "the caveat is shown");
        noMatch(cbody, /\b20\d\d-\d\d-\d\d\b/, "no raw ISO dates on screen");
      }
      await page.locator(V("commoditypos-card")).scrollIntoViewIfNeeded().catch(() => undefined);
      await shot(page, "07h-commoditypos");

      await page.waitForSelector(V("currencypos-card"));
      await page.waitForSelector(V("currencypos-body") + ", " + V("currencypos-unavailable") + ", " + V("currencypos-error"), { timeout: 45000 });
      const cu = await text(page);
      match(cu, /Currency and volatility positioning/); match(cu, /CFTC/); noMatch(cu, FORECASTS, "the currency positioning card makes no forecasts");
      if (await liveCard(page, "currencypos-body")) {
        const ubody = await inner(page, "currencypos-body");
        match(ubody, /Euro futures · as of [A-Z][a-z]{2} \d{1,2}, 20\d\d/, "the date is written out");
        match(ubody, /Leveraged funds: net/); match(ubody, /VIX futures/); match(ubody, /Japanese yen futures/);
        match(ubody, /checked against the report's own totals/); match(ubody, /not a market signal or a forecast/);
        noMatch(ubody, /\b20\d\d-\d\d-\d\d\b/, "no raw ISO dates on screen");
      }
      await page.locator(V("currencypos-card")).scrollIntoViewIfNeeded().catch(() => undefined);
      await shot(page, "07j-currencypos");

      await page.waitForSelector(V("agripos-card"));
      await page.waitForSelector(V("agripos-body") + ", " + V("agripos-unavailable") + ", " + V("agripos-error"), { timeout: 45000 });
      const ag = await text(page);
      match(ag, /Silver and farm positioning/); match(ag, /CFTC/); noMatch(ag, FORECASTS, "the silver and farm positioning card makes no forecasts");
      if (await liveCard(page, "agripos-body")) {
        const abody = await inner(page, "agripos-body");
        match(abody, /Silver futures · as of [A-Z][a-z]{2} \d{1,2}, 20\d\d/, "the date is written out");
        match(abody, /Managed money: net/); match(abody, /Corn futures/); match(abody, /Sugar futures/);
        match(abody, /checked against the report's own totals/); match(abody, /not a market signal or a forecast/);
        noMatch(abody, /\b20\d\d-\d\d-\d\d\b/, "no raw ISO dates on screen");
      }
      await page.locator(V("agripos-card")).scrollIntoViewIfNeeded().catch(() => undefined);
      await shot(page, "07n-agripos");

      await page.waitForSelector(V("realyields-card"));
      await page.waitForSelector(V("realyields-body") + ", " + V("realyields-unavailable") + ", " + V("realyields-error"), { timeout: 45000 });
      const ry = await text(page);
      match(ry, /Real yields and breakeven inflation/); match(ry, /US Treasury/); noMatch(ry, FORECASTS, "the real yields card makes no forecasts");
      if (await liveCard(page, "realyields-body")) {
        const rbody = await inner(page, "realyields-body");
        match(rbody, /As of [A-Z][a-z]{2} \d{1,2}, 20\d\d/, "the date is written out");
        match(rbody, /10-year: breakeven inflation \d\.\d\d% \(regular yield \d\.\d\d%, real yield -?\d\.\d\d%\)/, "a 10-year line with the three numbers");
        match(rbody, /Compared with [A-Z][a-z]{2} \d{1,2}, 20\d\d and [A-Z][a-z]{2} \d{1,2}, 20\d\d/, "comparison dates in words");
        match(rbody, /Checked: both curves are for the same day/); match(rbody, /not a forecast of inflation/); match(rbody, /not a market signal or a forecast/);
        noMatch(rbody, /\b20\d\d-\d\d-\d\d\b/, "no raw ISO dates on screen");
      }
      await page.locator(V("realyields-card")).scrollIntoViewIfNeeded().catch(() => undefined);
      await shot(page, "07i-realyields");

      await page.waitForSelector(V("fincond-card"));
      await page.waitForSelector(V("fincond-body") + ", " + V("fincond-unavailable") + ", " + V("fincond-error"), { timeout: 45000 });
      const fc = await text(page);
      match(fc, /Financial conditions/); match(fc, /Chicago Fed/); noMatch(fc, FORECASTS, "the financial conditions card makes no forecasts");
      if (await liveCard(page, "fincond-body")) {
        const fbody = await inner(page, "fincond-body");
        match(fbody, /Week ending [A-Z][a-z]{2} \d{1,2}, 20\d\d/, "the date is written out");
        match(fbody, /Index [+-]?\d\.\d{3}: (tighter|looser) than average|Index [+-]?\d\.\d{3}: at the average/, "the index with a plain reading");
        match(fbody, /Pieces as published: risk [+-]?\d\.\d{3}, credit [+-]?\d\.\d{3}, leverage [+-]?\d\.\d{3}/, "the three pieces");
        match(fbody, /Checked: every series is for the same week/); match(fbody, /not a market signal or a forecast/);
        noMatch(fbody, /\b20\d\d-\d\d-\d\d\b/, "no raw ISO dates on screen");
      }
      await page.locator(V("fincond-card")).scrollIntoViewIfNeeded().catch(() => undefined);
      await shot(page, "07o-fincond");

      await page.waitForSelector(V("claims-card"));
      await page.waitForSelector(V("claims-body") + ", " + V("claims-unavailable") + ", " + V("claims-error"), { timeout: 45000 });
      const jc = await text(page);
      match(jc, /Weekly jobless claims/); match(jc, /US Department of Labor/); noMatch(jc, FORECASTS, "the jobless claims card makes no forecasts");
      if (await liveCard(page, "claims-body")) {
        const cbody = await inner(page, "claims-body");
        match(cbody, /Week ending [A-Z][a-z]{2} \d{1,2}, 20\d\d/, "the date is written out");
        match(cbody, /Initial claims \d{2,3},\d{3}: (toward the low end|toward the high end|in the middle) of the past year's range\. Four-week average \d{2,3},\d{3}\./, "the claims with a plain reading");
        match(cbody, /Past year: low [\d,]+, high [\d,]+; \d{1,3}% of its \d{2} weeks were at or below this level\./, "the reading is explained in weeks, so a spike-stretched range cannot be misread");
        match(cbody, /Continuing claims [\d,]+ for the week ending [A-Z][a-z]{2} \d{1,2}, 20\d\d/, "continuing claims with their own week");
        match(cbody, /Checked: every date is a Saturday/); match(cbody, /not a market signal or a forecast/);
        noMatch(cbody, /\b20\d\d-\d\d-\d\d\b/, "no raw ISO dates on screen");
      }
      await page.locator(V("claims-card")).scrollIntoViewIfNeeded().catch(() => undefined);
      await shot(page, "07p-claims");

      await page.waitForSelector(V("jolts-card"));
      await page.waitForSelector(V("jolts-body") + ", " + V("jolts-unavailable") + ", " + V("jolts-error"), { timeout: 45000 });
      const joTxt = await text(page);
      match(joTxt, /Job openings and turnover/); match(joTxt, /Bureau of Labor Statistics/); noMatch(joTxt, FORECASTS, "the job openings card makes no forecasts");
      if (await liveCard(page, "jolts-body")) {
        const joBody = await inner(page, "jolts-body");
        const JMONTH = "(January|February|March|April|May|June|July|August|September|October|November|December) 20\\d\\d";
        const JVS = "(up \\d{1,3}\\.\\d% on a year ago|down \\d{1,3}\\.\\d% on a year ago|the same as a year ago)";
        const JSTEP = "(up [\\d,.]+ thousand on the month before|down [\\d,.]+ thousand on the month before|unchanged on the month before)";
        match(await inner(page, "jolts-openings"), new RegExp(`^Employers had \\d{1,2}\\.\\d{3} million job openings at the end of ${JMONTH}, ${JSTEP} and ${JVS}\\. The openings rate, the share of all jobs \\(filled and open\\) that were open, was \\d{1,2}\\.\\d% \\(\\d{1,2}\\.\\d% a year ago\\)\\.$`), "the openings with their month, changes and rate");
        match(joBody, new RegExp(`Over the last 10 years \\(\\d{3} months\\) it ran from \\d{1,2}\\.\\d% \\(${JMONTH}\\) to \\d{1,2}\\.\\d% \\(${JMONTH}\\); \\d{1,3}% of those months were lower than now\\.`), "the ten-year range of the openings rate is explained in months");
        match(await inner(page, "jolts-ratio"), new RegExp(`^In ${JMONTH} there were \\d\\.\\d{2} job openings for each unemployed person \\(\\d{1,2}\\.\\d{3} million people were unemployed\\), (against \\d\\.\\d{2} a year earlier|and no figure for a year earlier is available)\\.$`), "openings per unemployed person with their own month");
        match(joBody, new RegExp(`Over the last 10 years \\(\\d{3} months\\) it ran from \\d\\.\\d{2} \\(${JMONTH}\\) to \\d\\.\\d{2} \\(${JMONTH}\\); \\d{1,3}% of those months were lower than now\\.`), "the ten-year range of the ratio is explained in months");
        match(await inner(page, "jolts-flows"), new RegExp(`^(?:(Hires|Total separations|Quits|Layoffs and discharges|Other separations): (\\d{1,2}\\.\\d{3} million|\\d{1,3} thousand), \\d{1,2}\\.\\d% of payroll employment \\(\\d{1,2}\\.\\d% a year ago\\), ${JVS}\\.\\s*){5}$`), "the five flows with level, rate and yearly change");
        match(joBody, /Check: in each of the \d{3} months from [A-Z][a-z]+ 20\d\d to [A-Z][a-z]+ 20\d\d the twelve JOLTS series covered the same months with none missing, every level lay inside its range and payroll employment was there for each month \(plain checks, not the source's sums\)/, "the plain checks are shown");
        match(joBody, /total separations equal quits plus layoffs plus other separations \(largest gap [\d.]+ thousand, which is rounding\), and each published rate equals its level over payroll employment, job openings over payroll employment plus openings \(largest gap 0\.\d+ points, which is rounding\)/, "the sums are shown");
        match(joBody, /not that the figures are right/); match(joBody, /last business day of the month/); match(joBody, /preliminary/); match(joBody, /not a market signal or a forecast/);
        noMatch(joBody, /\b20\d\d-\d\d(-\d\d)?\b/, "no raw ISO dates on screen");
      }
      await page.locator(V("jolts-card")).first().evaluate((el) => el.scrollIntoView({ block: "start" })).catch(() => undefined);
      await shot(page, "07zi-jolts-top");
      await page.locator(V("jolts-card")).first().evaluate((el) => el.scrollIntoView({ block: "end" })).catch(() => undefined);         // and its bottom: the check line, the note and the source link
      await shot(page, "07zi-jolts-bottom");

      await page.waitForSelector(V("joltsind-card"));
      await page.waitForSelector(V("joltsind-body") + ", " + V("joltsind-unavailable") + ", " + V("joltsind-error"), { timeout: 45000 });
      const jiTxt = await text(page);
      match(jiTxt, /Job openings by industry/); match(jiTxt, /Bureau of Labor Statistics/); noMatch(jiTxt, FORECASTS, "the job openings by industry card makes no forecasts");
      if (await liveCard(page, "joltsind-body")) {
        const jiBody = await inner(page, "joltsind-body");
        const JIMONTH = "(January|February|March|April|May|June|July|August|September|October|November|December) 20\\d\\d";
        const JIAMT = "(?:\\d{1,2}\\.\\d{3} million|-?\\d{1,3} thousand)";
        const JIVS = "(?:up \\d{1,3}\\.\\d% on a year ago|down \\d{1,3}\\.\\d% on a year ago|the same as a year ago|not available against a year ago)";
        match(await inner(page, "joltsind-headline"), new RegExp(`^Employers had \\d{1,2}\\.\\d{3} million job openings at the end of ${JIMONTH}, ${JIVS}\\. ${JIAMT} \\(\\d{1,2}\\.\\d%\\) were in the private sector and ${JIAMT} \\(\\d{1,2}\\.\\d%\\) in government\\.$`), "the total with its split between private and government");
        match(jiBody, new RegExp(`Over the last 10 years \\(\\d{3} months\\) total openings ran from ${JIAMT} \\(${JIMONTH}\\) to ${JIAMT} \\(${JIMONTH}\\); \\d{1,3}% of those months were lower than now\\.`), "the ten-year range of the total is explained in months");
        for (const [id, label] of [["education_health", "Private education and health services"], ["business", "Professional and business services"], ["trade_transport", "Trade, transportation and utilities"], ["government", "Government"], ["leisure", "Leisure and hospitality"], ["manufacturing", "Manufacturing"], ["construction", "Construction"]]) {
          match(await inner(page, `joltsind-industry-${id}`), new RegExp(`^${label}: ${JIAMT}, \\d{1,2}\\.\\d% of all openings, ${JIVS}\\.$`), `${label} is its own row`);
        }
        match(await inner(page, "joltsind-industry-other_private"), new RegExp(`^Everything else in the private sector \\(mining and logging, information, financial activities, other services\\), by subtraction: ${JIAMT}, -?\\d{1,2}\\.\\d% of all openings, ${JIVS}\\.$`), "the remainder says it is found by subtraction");
        const JIPART = `[A-Z][A-Za-z,' ]+ ${JIAMT} \\(${JIVS}(?:, by subtraction)?\\)`;
        for (const id of ["education_health", "trade_transport", "government", "leisure", "manufacturing"]) {
          match(await inner(page, `joltsind-parts-${id}`), new RegExp(`^Of which: ${JIPART}; ${JIPART}\\.$`), `the two parts of ${id}`);
        }
        match(await inner(page, "joltsind-parts-education_health"), /Private educational services \d{1,3} thousand \([^)]*, by subtraction\)/, "private education is marked as found by subtraction");
        match(await inner(page, "joltsind-parts-government"), /Federal government \d{1,3} thousand \([^)]*, by subtraction\)/, "the federal government is marked as found by subtraction");
        match(await inner(page, "joltsind-parts-trade_transport"), /Wholesale trade, transportation and utilities \d{1,3} thousand \([^)]*, by subtraction\)/, "wholesale trade with transportation and utilities is marked as found by subtraction");
        match(await inner(page, "joltsind-check"), new RegExp(`^Check: in each of the \\d{3} months from ${JIMONTH} to ${JIMONTH} the sixteen series covered the same months with none missing and every figure lay inside its range \\(plain checks, not the source's sums\\); the survey's own arithmetic held, which shows that the series belong to one release, not that the figures are right: total nonfarm equalled private plus government, manufacturing equalled durable plus nondurable goods and leisure and hospitality equalled arts plus accommodation and food \\(largest gap [\\d.]+ thousand, which is rounding; 1\\.5 is allowed\\), and retail trade, health care and state and local government were never above the industries that contain them \\(the closest was -?[\\d.]+ thousand\\)\\. What is left of private after the six industries was at least -?[\\d.]+ thousand\\.$`), "the checks are shown with their gaps");
        match(jiBody, /not that the figures are right/); match(jiBody, /worked out by subtraction/); match(jiBody, /preliminary/); match(jiBody, /Smaller samples make industry figures noisier/); match(jiBody, /not a market signal or a forecast/);
        noMatch(jiBody, /\b20\d\d-\d\d(-\d\d)?\b/, "no raw ISO dates on screen");
      }
      await page.locator(V("joltsind-card")).first().evaluate((el) => el.scrollIntoView({ block: "start" })).catch(() => undefined);
      await shot(page, "07zia-joltsind-top");
      if (await page.locator(V("joltsind-industries")).count()) {                                                                          // the list of industries sits in the middle of the card
        await page.locator(V("joltsind-industries")).first().evaluate((el) => el.scrollIntoView({ block: "center" })).catch(() => undefined);
        await shot(page, "07zia-joltsind-middle");
      }
      await page.locator(V("joltsind-card")).first().evaluate((el) => el.scrollIntoView({ block: "end" })).catch(() => undefined);         // and its bottom: the check line, the note and the source link
      await shot(page, "07zia-joltsind-bottom");

      await page.waitForSelector(V("usjobs-card"));
      await page.waitForSelector(V("usjobs-body") + ", " + V("usjobs-unavailable") + ", " + V("usjobs-error"), { timeout: 45000 });
      const ujTxt = await text(page);
      match(ujTxt, /US jobs and unemployment/); match(ujTxt, /Bureau of Labor Statistics/); noMatch(ujTxt, FORECASTS, "the US jobs card makes no forecasts");
      if (await liveCard(page, "usjobs-body")) {
        const ujBody = await inner(page, "usjobs-body");
        const UMONTH = "(January|February|March|April|May|June|July|August|September|October|November|December) 20\\d\\d";
        const USW = "(?:up [\\d,.]+ thousand|down [\\d,.]+ thousand|unchanged)";
        const UMV = "(?:added [\\d,.]+ thousand|lost [\\d,.]+ thousand|changed by nothing)";
        const UBEFORE = "(?:(?:up|down) from \\d{1,2}\\.\\d% the month before|unchanged from the month before|no figure for the month before)";
        match(await inner(page, "usjobs-payrolls"), new RegExp(`^Employers had \\d{3}\\.\\d{3} million jobs on their payrolls in ${UMONTH}, ${USW} on the month before and ${USW} on a year earlier\\. Of the change on the month, private employers ${UMV} and government ${UMV}\\.$`), "the payrolls with their month, their changes and their parts");
        match(await inner(page, "usjobs-recent"), new RegExp(`^(?:${UMONTH}: ${USW}\\s*){6}$`), "six months of jobs added");
        match(await inner(page, "usjobs-unemployment"), new RegExp(`^The unemployment rate was \\d{1,2}\\.\\d% in ${UMONTH}, ${UBEFORE} \\((?:\\d{1,2}\\.\\d% a year earlier|a year earlier: the household survey has no figure for ${UMONTH}|no figure for a year earlier)\\)\\. \\d{1,2}\\.\\d{3} million people were unemployed, out of a labour force of \\d{3}\\.\\d{3} million\\.$`), "the unemployment rate with its comparisons");
        match(ujBody, new RegExp(`Over the last 10 years \\(\\d{3} months with a figure\\) the unemployment rate ran from \\d{1,2}\\.\\d% \\(${UMONTH}\\) to \\d{1,2}\\.\\d% \\(${UMONTH}\\); \\d{1,3}% of those months were lower than now\\.`), "the ten-year range is explained in months");
        match(await inner(page, "usjobs-participation"), new RegExp(`^\\d{2}\\.\\d% of the population aged 16 and over was working or looking for work, ${UBEFORE}; \\d{2}\\.\\d% had a job, ${UBEFORE}\\.$`), "participation and the employment ratio");
        if (await present(page, "usjobs-gaps")) match(await inner(page, "usjobs-gaps"), new RegExp(`^The household survey has no figure for ${UMONTH}(, ${UMONTH})*\\.$`), "the months without a household figure are named");
        match(ujBody, /Check: in each of the \d{3} months from [A-Z][a-z]+ 20\d\d to [A-Z][a-z]+ 20\d\d the three payroll series covered the same months with none missing and every level lay inside its range, and the seven household series covered the same months \(\d{3} of them with a figure\) \(plain checks, not the source's sums\)/, "the plain checks are shown");
        match(ujBody, /total payrolls equal private plus government payrolls \(largest gap \d+(\.\d+)? thousand\), the labour force equals the employed plus the unemployed \(largest gap \d+(\.\d+)? thousand, which is rounding\), and each published rate equals its own numerator over its own denominator \(largest gap 0(\.\d+)? points, which is rounding\)/, "the three relations are shown");
        match(ujBody, /not that the figures are right/); match(ujBody, /do not agree month to month/); match(ujBody, /not looking is not unemployed/); match(ujBody, /not a market signal or a forecast/);
        noMatch(ujBody, /\b20\d\d-\d\d(-\d\d)?\b/, "no raw ISO dates on screen");
      }
      await page.locator(V("usjobs-card")).first().evaluate((el) => el.scrollIntoView({ block: "start" })).catch(() => undefined);
      await shot(page, "07zj-usjobs-top");
      await page.locator(V("usjobs-card")).first().evaluate((el) => el.scrollIntoView({ block: "end" })).catch(() => undefined);         // and its bottom: the check line, the note and the source link
      await shot(page, "07zj-usjobs-bottom");

      await page.waitForSelector(V("usgdp-card"));
      await page.waitForSelector(V("usgdp-body") + ", " + V("usgdp-unavailable") + ", " + V("usgdp-error"), { timeout: 45000 });
      const gdTxt = await text(page);
      match(gdTxt, /US GDP by component/); match(gdTxt, /Bureau of Economic Analysis/); noMatch(gdTxt, FORECASTS, "the US GDP card makes no forecasts");
      if (await liveCard(page, "usgdp-body")) {
        const gdBody = await inner(page, "usgdp-body");
        const GQ = "Q[1-4] 20\\d\\d";
        match(await inner(page, "usgdp-headline"), new RegExp(`^The US economy produced \\$\\d{2}\\.\\d{3} trillion of goods and services at an annual rate in ${GQ}, (?:(?:up|down) \\$[\\d,]+\\.\\d billion \\(\\d+\\.\\d{2}%\\)|unchanged) on the quarter before and (?:(?:up|down) \\d+\\.\\d{2}%|unchanged) on a year earlier, in the prices of the time\\.$`), "the level, its change on the quarter and on the year");
        match(await inner(page, "usgdp-growth"), new RegExp(`^With price changes taken out, real GDP (?:grew \\d+\\.\\d%|shrank \\d+\\.\\d%|was unchanged) at an annual rate in ${GQ} \\(-?\\d+\\.\\d% in the quarter before and -?\\d+\\.\\d% a year earlier\\)\\.$`), "real growth with its comparisons");
        match(gdBody, new RegExp(`Over the last 10 years \\(40 quarters\\) real growth ran from -?\\d+\\.\\d% \\(${GQ}\\) to -?\\d+\\.\\d% \\(${GQ}\\); \\d{1,3}% of those quarters were lower than now\\.`), "the ten-year range is explained in quarters");
        match(await inner(page, "usgdp-components"), /^(?:(?:Consumer spending|Private investment|Government spending|Net exports): -?\$[\d,]+\.\d billion, -?\d+\.\d% of GDP, [+-]?\d+\.\d{2} points of the real growth\s*){4}$/, "the four parts with their share and their contribution");
        match(await inner(page, "usgdp-part-consumption"), /^Consumer spending: \$[\d,]+\.\d billion, \d+\.\d% of GDP, [+-]?\d+\.\d{2} points of the real growth$/, "consumer spending is its own row");
        match(await inner(page, "usgdp-part-net_exports"), /^Net exports: -?\$[\d,]+\.\d billion, -?\d+\.\d% of GDP, [+-]?\d+\.\d{2} points of the real growth$/, "net exports is its own row");
        match(await inner(page, "usgdp-trade"), /^Net exports are exports of \$[\d,]+\.\d billion minus imports of \$[\d,]+\.\d billion\. The four contributions add to [+-]?\d+\.\d{2} points; the published growth is -?\d+\.\d%\.$/, "the trade and the sum of the contributions");
        match(await inner(page, "usgdp-recent"), new RegExp(`^(?:${GQ}: [+-]?\\d+\\.\\d%\\s*){6}$`), "six quarters of real growth");
        match(gdBody, new RegExp(`Check: in each of the \\d{2} quarters from ${GQ} to ${GQ} the twelve series covered the same quarters with none missing and every figure lay inside its range \\(plain checks, not the source's sums\\)`), "the plain checks are shown");
        match(gdBody, /consumer spending plus private investment plus government spending plus net exports equal GDP \(largest gap \d\.\d{3} billion, which is rounding\), exports minus imports equal net exports \(largest gap \d\.\d{3} billion, rounding\), and the four contributions add up to real growth \(largest gap \d\.\d{2} points, rounding\)/, "the three relations are shown");
        match(gdBody, /not that the figures are right/); match(gdBody, /counted by what it was spent on/); match(gdBody, /revised in later releases/); match(gdBody, /not a market signal or a forecast/);
        noMatch(gdBody, /\b20\d\d-\d\d(-\d\d)?\b/, "no raw ISO dates on screen");
        noMatch(gdBody, /\b20\d\d-Q[1-4]\b/, "no raw quarter labels on screen");
      }
      await page.locator(V("usgdp-card")).first().evaluate((el) => el.scrollIntoView({ block: "start" })).catch(() => undefined);
      await shot(page, "07zk-usgdp-top");
      await page.locator(V("usgdp-card")).first().evaluate((el) => el.scrollIntoView({ block: "end" })).catch(() => undefined);         // and its bottom: the check line, the note and the source link
      await shot(page, "07zk-usgdp-bottom");

      await page.waitForSelector(V("ushousehold-card"));
      await page.waitForSelector(V("ushousehold-body") + ", " + V("ushousehold-unavailable") + ", " + V("ushousehold-error"), { timeout: 45000 });
      const hhTxt = await text(page);
      match(hhTxt, /US household income and saving/); match(hhTxt, /Bureau of Economic Analysis/); noMatch(hhTxt, FORECASTS, "the US household card makes no forecasts");
      if (await liveCard(page, "ushousehold-body")) {
        const hhBody = await inner(page, "ushousehold-body");
        const AMT = "-?\\$(?:[\\d,]+\\.\\d billion|\\d+\\.\\d{3} trillion)";
        const MOVE = "(?:(?:up|down) \\d+\\.\\d{2}%|unchanged)";
        const HQ = "Q[1-4] (?:19|20)\\d\\d";
        const HM = "[A-Z][a-z]+ (?:19|20)\\d\\d";
        match(await inner(page, "ushousehold-headline"), new RegExp(`^Households saved \\d+\\.\\d% of their after-tax income in ${HM}\\. That is (?:up from|down from|unchanged from) -?\\d+\\.\\d% the month before and (?:up from|down from|unchanged from) -?\\d+\\.\\d% a year earlier\\.$`), "the saving rate with the month before and a year earlier");
        match(hhBody, new RegExp(`Over the last \\d+ years \\(\\d+ months\\) the saving rate ran from -?\\d+\\.\\d% \\(${HM}\\) to -?\\d+\\.\\d% \\(${HM}\\); \\d{1,3}% of those months were lower than now\\.`), "the long range is explained in months");
        for (const [id, label] of [["income", "Personal income"], ["taxes", "Taxes on it"], ["disposable", "Disposable income"]]) {
          match(await inner(page, `ushousehold-line-${id}`), new RegExp(`^${label}: ${AMT}, ${MOVE} on the month and ${MOVE} on a year earlier$`), `${label} is its own row`);
        }
        match(await inner(page, "ushousehold-outlays"), new RegExp(`^Spent \\(personal outlays\\): ${AMT}, ${MOVE} on the month and ${MOVE} on a year earlier$`), "outlays are their own row");
        match(await inner(page, "ushousehold-part-spending"), new RegExp(`^Consumer spending: ${AMT}, \\d+\\.\\d% of what was spent, ${MOVE} on the month and ${MOVE} on a year earlier$`), "consumer spending is the first part of outlays");
        match(await inner(page, "ushousehold-part-interest"), new RegExp(`^Interest payments: ${AMT}, \\d+\\.\\d% of what was spent, ${MOVE} on the month and ${MOVE} on a year earlier$`), "interest payments are the second part");
        match(await inner(page, "ushousehold-part-other"), new RegExp(`^Everything else: ${AMT}, -?\\d+\\.\\d% of what was spent$`), "the rest is found by subtraction and has no changes");
        match(await inner(page, "ushousehold-saving"), new RegExp(`^Saved \\(disposable income minus what was spent\\): ${AMT}, (?:(?:up|down) \\$[\\d,]+\\.\\d billion|unchanged) on the month and (?:(?:up|down) \\$[\\d,]+\\.\\d billion|unchanged) on a year earlier$`), "saving in billions");
        match(await inner(page, "ushousehold-split-total"), new RegExp(`^Consumer spending in total: ${AMT} at an annual rate, ${MOVE} on a year earlier$`), "the quarterly total");
        for (const [id, label] of [["durable", "Durable goods"], ["nondurable", "Nondurable goods"], ["services", "Services"]]) {
          match(await inner(page, `ushousehold-type-${id}`), new RegExp(`^${label}: ${AMT}, \\d+\\.\\d% of consumer spending, ${MOVE} on a year earlier$`), `${label} is its own row`);
        }
        match(hhBody, new RegExp(`Consumer spending by type, ${HQ} \\(quarterly\\)`), "the quarter of the split is named");
        match(await inner(page, "ushousehold-recent"), new RegExp(`^(?:${HM}: saving rate -?\\d+\\.\\d%, income after tax [+-]?\\d+\\.\\d{2}%, consumer spending [+-]?\\d+\\.\\d{2}% on the month before\\s*){6}$`), "six months of saving rate and changes");
        match(await inner(page, "ushousehold-check"), new RegExp(`^Check: in each of the \\d+ months from ${HM} to ${HM} and the \\d+ quarters from ${HQ} to ${HQ} the twelve series covered the same months or quarters with none missing and every figure lay inside its range \\(plain checks, not the source's sums\\); the source's own accounting held, which shows that the series belong to one release, not that the figures are right: personal income minus taxes equalled disposable income and disposable income minus spending equalled saving \\(largest gaps \\d\\.\\d and \\d\\.\\d billion, the rounding of the published tenths\\), the saving rate equalled saving over disposable income \\(largest gap 0\\.\\d{3} points\\), the three types of consumer spending added up to the quarterly total \\(largest gap 0\\.\\d{3} billion\\) and consumer spending plus interest never exceeded outlays \\(the rest was never below ${AMT}\\)\\. One check is between two tables: in \\d+ quarters the quarterly consumer spending equalled the average of its three monthly figures to within 0\\.\\d{3} billion\\.`), "the checks are shown, and what they do not prove");
        match(hhBody, /not that the figures are right/); match(hhBody, /disposable income/); match(hhBody, /revised in later releases/); match(hhBody, /not a market signal or a forecast/);
        noMatch(hhBody, /\b(?:19|20)\d\d-\d\d(-\d\d)?\b/, "no raw ISO dates on screen");
        noMatch(hhBody, /\b(?:19|20)\d\d-Q[1-4]\b/, "no raw quarter labels on screen");
      }
      await page.locator(V("ushousehold-card")).first().evaluate((el) => el.scrollIntoView({ block: "start" })).catch(() => undefined);
      await shot(page, "07zl-ushousehold-top");
      if (await page.locator(V("ushousehold-split")).count()) {                                                                            // the split of consumer spending by type sits in the middle of the card
        await page.locator(V("ushousehold-split")).first().evaluate((el) => el.scrollIntoView({ block: "center" })).catch(() => undefined);
        await shot(page, "07zl-ushousehold-middle");
      }
      await page.locator(V("ushousehold-card")).first().evaluate((el) => el.scrollIntoView({ block: "end" })).catch(() => undefined);         // and its bottom: the check line, the note and the source link
      await shot(page, "07zl-ushousehold-bottom");

      await page.waitForSelector(V("oil-card"));
      await page.waitForSelector(V("oil-body") + ", " + V("oil-unavailable") + ", " + V("oil-error"), { timeout: 45000 });
      const oilTxt = await text(page);
      match(oilTxt, /Oil prices/); match(oilTxt, /Energy Information Administration/); noMatch(oilTxt, FORECASTS, "the oil prices card makes no forecasts");
      if (await liveCard(page, "oil-body")) {
        const oilBody = await inner(page, "oil-body");
        match(oilBody, /WTI crude \(US\) \$\d{2,3}\.\d{2} a barrel on [A-Z][a-z]{2} \d{1,2}, 20\d\d: (toward the low end|toward the high end|in the middle) of the past year's range\./, "WTI with its own date and a plain reading");
        match(oilBody, /Brent crude \(Europe\) \$\d{2,3}\.\d{2} a barrel on [A-Z][a-z]{2} \d{1,2}, 20\d\d/, "Brent with its own date");
        eq((oilBody.match(/Past year: low \$\d{2,3}\.\d{2}, high \$\d{2,3}\.\d{2}; \d{1,3}% of its \d{3} days were at or below this price\./g) || []).length, 2, "each crude price says what share of the past year's days were at or below it");
        match(oilBody, /Brent is \$\d+\.\d{2} (above|below) WTI on [A-Z][a-z]{2} \d{1,2}, 20\d\d|Brent and WTI cost the same on/, "the spread with its date");
        match(oilBody, /Checked: every recent price is above zero/); match(oilBody, /not a market signal or a forecast/);
        noMatch(oilBody, /\b20\d\d-\d\d-\d\d\b/, "no raw ISO dates on screen");
      }
      await page.locator(V("oil-card")).scrollIntoViewIfNeeded().catch(() => undefined);
      await shot(page, "07q-oil");

      await page.waitForSelector(V("gasoline-card"));
      await page.waitForSelector(V("gasoline-body") + ", " + V("gasoline-unavailable") + ", " + V("gasoline-error"), { timeout: 45000 });
      const gasTxt = await text(page);
      match(gasTxt, /Gasoline prices/); match(gasTxt, /Energy Information Administration/); noMatch(gasTxt, FORECASTS, "the gasoline prices card makes no forecasts");
      if (await liveCard(page, "gasoline-body")) {
        const gasBody = await inner(page, "gasoline-body");
        match(gasBody, /Monday [A-Z][a-z]{2} \d{1,2}, 20\d\d/, "the Monday is written out");
        noMatch(gasBody, /Week starting/i, "it is the Monday price, not a week starting on it");
        match(gasBody, /Regular gasoline \$\d\.\d{3} a gallon: (toward the low end|toward the high end|in the middle) of the past year's range\./, "the price with a plain reading");
        match(gasBody, /Past year: low \$\d\.\d{3}, high \$\d\.\d{3}; \d{1,3}% of its \d{2} weeks were at or below this price\./, "the reading is explained in weeks, so a spike-stretched range cannot be misread");
        match(gasBody, /That is \$\d{2,3}\.\d{2} a barrel-equivalent .* against WTI crude at \$\d{2,3}\.\d{2} a barrel: a gap of \$\d{2,3}\.\d{2}/, "the gap to crude");
        match(gasBody, /Checked: every date is a Monday/); match(gasBody, /not a market signal or a forecast/);
        noMatch(gasBody, /\b20\d\d-\d\d-\d\d\b/, "no raw ISO dates on screen");
      }
      await page.locator(V("gasoline-card")).scrollIntoViewIfNeeded().catch(() => undefined);
      await shot(page, "07r-gasoline");

      await page.waitForSelector(V("natgas-card"));
      await page.waitForSelector(V("natgas-body") + ", " + V("natgas-unavailable") + ", " + V("natgas-error"), { timeout: 45000 });
      const ngTxt = await text(page);
      match(ngTxt, /Natural gas prices/); match(ngTxt, /Energy Information Administration/); noMatch(ngTxt, FORECASTS, "the natural gas card makes no forecasts");
      if (await liveCard(page, "natgas-body")) {
        const ngBody = await inner(page, "natgas-body");
        match(ngBody, /Natural gas \$\d{1,2}\.\d{2} per million BTU on [A-Z][a-z]{2} \d{1,2}, 20\d\d: (toward the low end|toward the high end|in the middle) of the past year's range\./, "the price with its own date and a plain reading");
        match(ngBody, /(unchanged|up \$\d{1,2}\.\d{2}|down \$\d{1,2}\.\d{2}) since the previous trading day/, "the move since the previous trading day"); match(ngBody, /Past year: low \$\d{1,2}\.\d{2}, high \$\d{1,2}\.\d{2}; \d{1,3}% of its \d{2,3} days were at or below this price\./, "the reading is explained in days, so one winter spike cannot be misread as a range");
        match(ngBody, /Cross-check: the daily prices for (January|February|March|April|May|June|July|August|September|October|November|December) 20\d\d average \$\d{1,2}\.\d{2}; the EIA publishes \$\d{1,2}\.\d{2} for the month\./, "the monthly cross-check is shown with its month");
        match(ngBody, /Checked: every recent price is between \$0\.50 and \$60/); match(ngBody, /not a market signal or a forecast/);
        noMatch(ngBody, /\b20\d\d-\d\d-\d\d\b/, "no raw ISO dates on screen");
      }
      await page.locator(V("natgas-card")).scrollIntoViewIfNeeded().catch(() => undefined);
      await shot(page, "07s-natgas");

      await page.waitForSelector(V("m2-card"));
      await page.waitForSelector(V("m2-body") + ", " + V("m2-unavailable") + ", " + V("m2-error"), { timeout: 45000 });
      const m2Txt = await text(page);
      match(m2Txt, /M2 money supply/); match(m2Txt, /Federal Reserve Board/); noMatch(m2Txt, FORECASTS, "the money supply card makes no forecasts");
      if (await liveCard(page, "m2-body")) {
        const m2Body = await inner(page, "m2-body");
        const MONTH = "(January|February|March|April|May|June|July|August|September|October|November|December) 20\\d\\d";
        match(m2Body, new RegExp(`M2 was \\$\\d{1,2}\\.\\d{2} trillion in ${MONTH}, (up \\d{1,2}\\.\\d% on a year ago|down \\d{1,2}\\.\\d% on a year ago|the same as a year ago)\\.`), "the level with its month and the yearly change");
        match(m2Body, /(up \d{1,2}\.\d% on a month ago|down \d{1,2}\.\d% on a month ago|the same as a month ago), (up \d{1,2}\.\d% on three months ago|down \d{1,2}\.\d% on three months ago|the same as three months ago)\./, "the one- and three-month changes");
        match(m2Body, new RegExp(`growth over a year ran from [-+]?\\d{1,2}\\.\\d% \\(${MONTH}\\) to [-+]?\\d{1,2}\\.\\d% \\(${MONTH}\\); \\d{1,3}% of those months grew slower than now\\.`), "the ten-year growth range is explained in months");
        match(m2Body, new RegExp(`Cross-checks: seasonal adjustment moved ${MONTH}'s figure by [+-]?\\d\\.\\d% \\(\\$[\\d,]+\\.\\d billion adjusted against \\$[\\d,]+\\.\\d billion unadjusted\\), and its \\d weekly figures average \\$[\\d,]+\\.\\d billion`), "both cross-checks are shown");
        match(m2Body, /Checked: every recent monthly value is between \$5 trillion and \$60 trillion/); match(m2Body, /not a market signal or a forecast/);
        noMatch(m2Body, /\b20\d\d-\d\d(-\d\d)?\b/, "no raw ISO dates on screen");
      }
      await page.locator(V("m2-card")).scrollIntoViewIfNeeded().catch(() => undefined);
      await shot(page, "07t-m2");

      await page.waitForSelector(V("reserves-card"));
      await page.waitForSelector(V("reserves-body") + ", " + V("reserves-unavailable") + ", " + V("reserves-error"), { timeout: 45000 });
      const resTxt = await text(page);
      match(resTxt, /Bank reserves and currency/); match(resTxt, /Federal Reserve Board/); noMatch(resTxt, FORECASTS, "the bank reserves card makes no forecasts");
      if (await liveCard(page, "reserves-body")) {
        const resBody = await inner(page, "reserves-body");
        const MON = "(January|February|March|April|May|June|July|August|September|October|November|December) 20\\d\\d";
        match(resBody, /Week ending Wednesday [A-Z][a-z]{2} \d{1,2}, 20\d\d/, "the Wednesday is written out");
        match(resBody, /Bank reserves at the Fed were \$\d\.\d{2} trillion, (up \d{1,2}\.\d% on the week before|down \d{1,2}\.\d% on the week before|the same as the week before)\. Currency in circulation was \$\d\.\d{2} trillion\./, "reserves and currency with the weekly change");
        match(resBody, /Past year: low \$\d\.\d{2} trillion, high \$\d\.\d{2} trillion; \d{1,3}% of its \d{2} weeks were at or below this level\./, "the reading is explained in weeks");
        match(resBody, new RegExp(`Monetary base \\(monthly\\): \\$\\d\\.\\d{2} trillion in ${MON} = currency \\$\\d\\.\\d{2} trillion \\+ reserve balances \\$\\d\\.\\d{2} trillion; the three figures add up to within \\$0\\.1 billion`), "the base is shown as the sum of its two parts");
        match(resBody, new RegExp(`Cross-check: the weekly figures for ${MON} \\(\\d weeks\\) add up to an average of \\$[\\d,]+\\.\\d billion, (the same as|\\d\\.\\d{2}% (under|over)) the monthly base\\.`), "the weekly figures are checked against the monthly base");
        match(resBody, /Checked: every recent weekly figure is in a plausible range/); match(resBody, /not a market signal or a forecast/);
        noMatch(resBody, /\b20\d\d-\d\d(-\d\d)?\b/, "no raw ISO dates on screen");
      }
      await page.locator(V("reserves-card")).scrollIntoViewIfNeeded().catch(() => undefined);
      await shot(page, "07u-reserves");

      await page.waitForSelector(V("ecbrates-card"));
      await page.waitForSelector(V("ecbrates-body") + ", " + V("ecbrates-unavailable") + ", " + V("ecbrates-error"), { timeout: 45000 });
      const ecbTxt = await text(page);
      match(ecbTxt, /ECB interest rates/); match(ecbTxt, /European Central Bank/); noMatch(ecbTxt, FORECASTS, "the ECB rates card makes no forecasts");
      if (await liveCard(page, "ecbrates-body")) {
        const ecbBody = await inner(page, "ecbrates-body");
        const DAY = "[A-Z][a-z]{2} \\d{1,2}, 20\\d\\d";
        match(ecbBody, new RegExp(`In force on ${DAY}`), "the date is written out");
        match(ecbBody, /Deposit facility rate\s+-?\d{1,2}\.\d{2}%\s+What the ECB pays banks for money left with it overnight\./, "the deposit rate with its plain meaning");
        match(ecbBody, /Main refinancing rate\s+-?\d{1,2}\.\d{2}%\s+What banks pay for the ECB's regular one-week loans at a fixed rate; \d\.\d{2} points above the deposit rate\./, "the main refinancing rate sits above the deposit rate");
        match(ecbBody, /Marginal lending rate\s+-?\d{1,2}\.\d{2}%\s+What banks pay to borrow from the ECB overnight; \d\.\d{2} points above the deposit rate\./, "the marginal lending rate sits above the deposit rate");
        match(ecbBody, new RegExp(`Last changed on ${DAY}: (up|down) \\d\\.\\d{2} points, from -?\\d{1,2}\\.\\d{2}%\\.`), "when each rate last changed, found from the data");
        match(ecbBody, /(Up|Down) \d\.\d{2} points on a year ago \(-?\d{1,2}\.\d{2}%\)\.|The same as a year ago \(-?\d{1,2}\.\d{2}%\)\./, "against a year ago");
        match(ecbBody, new RegExp(`Recent changes to the deposit rate\\s+${DAY}: (up|down) \\d\\.\\d{2} points, from -?\\d{1,2}\\.\\d{2}% to -?\\d{1,2}\\.\\d{2}%`), "the recent changes are listed");
        match(ecbBody, new RegExp(`Market check: the euro short-term rate \\(€STR\\), .* was -?\\d{1,2}\\.\\d{3}% on ${DAY}.*, (\\d\\.\\d{3} points (under|over)|level with) the deposit rate \\(-?\\d{1,2}\\.\\d{2}%\\)\\.`), "the market rate against the deposit rate");
        match(ecbBody, new RegExp(`On each of its last 60 business days \\(${DAY} to ${DAY}\\) it was (between \\d\\.\\d{3} points and \\d\\.\\d{3} points|from \\d\\.\\d{3} points).* the deposit rate\\.`), "the 60-day range is explained");
        match(ecbBody, /Checked: every recent day is present/); match(ecbBody, /not a market signal or a forecast/);
        noMatch(ecbBody, /\b20\d\d-\d\d(-\d\d)?\b/, "no raw ISO dates on screen");
      }
      await page.locator(V("ecbrates-card")).first().evaluate((el) => el.scrollIntoView({ block: "start" })).catch(() => undefined);      // the top of a tall card, not its nearest edge
      await shot(page, "07v-ecbrates");

      await page.waitForSelector(V("retail-card"));
      await page.waitForSelector(V("retail-body") + ", " + V("retail-unavailable") + ", " + V("retail-error"), { timeout: 45000 });
      const retTxt = await text(page);
      match(retTxt, /Retail sales/); match(retTxt, /Census Bureau/); noMatch(retTxt, FORECASTS, "the retail sales card makes no forecasts");
      if (await liveCard(page, "retail-body")) {
        const retBody = await inner(page, "retail-body");
        const RMONTH = "(January|February|March|April|May|June|July|August|September|October|November|December) 20\\d\\d";
        const RVS = "(up \\d{1,2}\\.\\d% on a year ago|down \\d{1,2}\\.\\d% on a year ago|the same as a year ago)";
        match(retBody, new RegExp(`Retail and food services sales were \\$[\\d,]+\\.\\d billion in ${RMONTH}, ${RVS}\\.`), "the level with its month and the yearly change");
        match(retBody, /(up \d{1,2}\.\d% on a month ago|down \d{1,2}\.\d% on a month ago|the same as a month ago), (up \d{1,2}\.\d% on three months ago|down \d{1,2}\.\d% on three months ago|the same as three months ago)\. Not adjusted for price changes\./, "the one- and three-month changes and the price warning");
        match(retBody, new RegExp(`growth over a year ran from [-+]?\\d{1,2}\\.\\d% \\(${RMONTH}\\) to [-+]?\\d{1,2}\\.\\d% \\(${RMONTH}\\); \\d{1,3}% of those months grew slower than now\\.`), "the ten-year growth range is explained in months");
        match(retBody, new RegExp(`Made up of retail trade, \\$[\\d,]+\\.\\d billion \\(\\d{1,2}\\.\\d% of the total; ${RVS}\\), and food services and drinking places, \\$[\\d,]+\\.\\d billion \\(\\d{1,2}\\.\\d% of the total; ${RVS}\\)\\.`), "the two parts with their shares and yearly changes");
        match(retBody, /Check: in each of the last \d{2} months, retail trade plus food services adds up to the total (exactly|to within \$\d+(\.\d+)? million)\./, "the parts-add-up check is shown");
        match(retBody, /Checked: every recent monthly total is between \$100 billion and \$2 trillion/); match(retBody, /not a market signal or a forecast/); match(retBody, /advance estimate/);
        noMatch(retBody, /\b20\d\d-\d\d(-\d\d)?\b/, "no raw ISO dates on screen");
      }
      await page.locator(V("retail-card")).scrollIntoViewIfNeeded().catch(() => undefined);
      await shot(page, "07w-retail");

      await page.waitForSelector(V("housing-card"));
      await page.waitForSelector(V("housing-body") + ", " + V("housing-unavailable") + ", " + V("housing-error"), { timeout: 45000 });
      const houTxt = await text(page);
      match(houTxt, /Housing starts/); match(houTxt, /Census Bureau and HUD/); noMatch(houTxt, FORECASTS, "the housing starts card makes no forecasts");
      if (await liveCard(page, "housing-body")) {
        const houBody = await inner(page, "housing-body");
        const HMONTH = "(January|February|March|April|May|June|July|August|September|October|November|December) 20\\d\\d";
        const HVS = "(up \\d{1,3}\\.\\d% on a year ago|down \\d{1,3}\\.\\d% on a year ago|the same as a year ago)";
        match(houBody, new RegExp(`Builders began new homes at a pace of \\d\\.\\d{3} million a year in ${HMONTH}, ${HVS}\\.`), "the pace with its month and the yearly change");
        match(houBody, /(up \d{1,3}\.\d% on a month ago|down \d{1,3}\.\d% on a month ago|the same as a month ago), (up \d{1,3}\.\d% on three months ago|down \d{1,3}\.\d% on three months ago|the same as three months ago)\. This is a yearly pace, not the number of homes started in the month\./, "the one- and three-month changes and what the pace means");
        match(houBody, new RegExp(`the change over a year ran from [-+]?\\d{1,3}\\.\\d% \\(${HMONTH}\\) to [-+]?\\d{1,3}\\.\\d% \\(${HMONTH}\\); \\d{1,3}% of those months were weaker than now\\.`), "the ten-year range is explained in months");
        match(houBody, new RegExp(`Single-family homes, \\d{1,3}(,\\d{3})* thousand \\(\\d{1,2}\\.\\d% of the total; ${HVS}\\)\\. Homes in buildings of five or more units, \\d{1,3}(,\\d{3})* thousand \\(\\d{1,2}\\.\\d% of the total; ${HVS}\\)\\.`), "the two parts with their shares and yearly changes");
        match(houBody, /Check: in each of the last \d{2} months, single-family plus five-or-more-unit starts are no more than the total; what is left, mostly buildings of two to four units, was between \d{1,3} thousand and \d{1,3} thousand\./, "the parts check is shown");
        match(houBody, /Checked: every recent monthly total is between 300 and 3,000 thousand/); match(houBody, /not a market signal or a forecast/); match(houBody, /estimate that is revised/); match(houBody, /no exact parts-add-up check/);
        noMatch(houBody, /\b20\d\d-\d\d(-\d\d)?\b/, "no raw ISO dates on screen");
      }
      await page.locator(V("housing-card")).scrollIntoViewIfNeeded().catch(() => undefined);
      await shot(page, "07x-housing");

      await page.waitForSelector(V("industrial-card"));
      await page.waitForSelector(V("industrial-body") + ", " + V("industrial-unavailable") + ", " + V("industrial-error"), { timeout: 45000 });
      const indTxt = await text(page);
      match(indTxt, /Industrial production/); match(indTxt, /Federal Reserve/); noMatch(indTxt, FORECASTS, "the industrial production card makes no forecasts");
      if (await liveCard(page, "industrial-body")) {
        const indBody = await inner(page, "industrial-body");
        const IMONTH = "(January|February|March|April|May|June|July|August|September|October|November|December) 20\\d\\d";
        const IVS = "(up \\d{1,3}\\.\\d% on a year ago|down \\d{1,3}\\.\\d% on a year ago|the same as a year ago)";
        match(indBody, new RegExp(`Output of US factories, mines and power and gas utilities was \\d{2,3}\\.\\d{2} on an index where 2017 is 100 in ${IMONTH}, ${IVS}\\.`), "the index with its month and the yearly change");
        match(indBody, /(up \d{1,3}\.\d% on a month ago|down \d{1,3}\.\d% on a month ago|the same as a month ago), (up \d{1,3}\.\d% on three months ago|down \d{1,3}\.\d% on three months ago|the same as three months ago)\. This is the volume produced, not its value in dollars\./, "the one- and three-month changes and what the index measures");
        match(indBody, new RegExp(`the change over a year ran from [-+]?\\d{1,3}\\.\\d% \\(${IMONTH}\\) to [-+]?\\d{1,3}\\.\\d% \\(${IMONTH}\\); \\d{1,3}% of those months were weaker than now\\.`), "the ten-year range is explained in months");
        match(indBody, new RegExp(`Capacity in use: \\d{2}\\.\\d% of what the plants could sustainably produce in ${IMONTH}(, (up|down) \\d{1,2}\\.\\d points on a year ago|, the same as a year ago)?\\.`), "capacity in use with its month");
        match(indBody, new RegExp(`Manufacturing, \\d{2,3}\\.\\d{2} \\(${IVS}\\)\\. Mining, \\d{2,3}\\.\\d{2} \\(${IVS}\\)\\. Electric and gas utilities, \\d{2,3}\\.\\d{2} \\(${IVS}\\)\\.`), "the three groups with their yearly changes");
        match(indBody, /Check: in each of the last \d{2} months, the total's change lay between those of manufacturing, mining and utilities, and the capacity implied by output and utilization moved by between [-+]\d\.\d{2}% and [-+]\d\.\d{2}% a month\./, "the checks are shown");
        match(indBody, /Checked: every recent index is between 30 and 300/); match(indBody, /not a market signal or a forecast/); match(indBody, /estimate that is revised/);
        noMatch(indBody, /\b20\d\d-\d\d(-\d\d)?\b/, "no raw ISO dates on screen");
      }
      await page.locator(V("industrial-card")).scrollIntoViewIfNeeded().catch(() => undefined);
      await shot(page, "07y-industrial");

      await page.waitForSelector(V("euromoney-card"));
      await page.waitForSelector(V("euromoney-body") + ", " + V("euromoney-unavailable") + ", " + V("euromoney-error"), { timeout: 45000 });
      const emTxt = await text(page);
      match(emTxt, /Euro-area money supply/); match(emTxt, /European Central Bank/); noMatch(emTxt, FORECASTS, "the euro money supply card makes no forecasts");
      if (await liveCard(page, "euromoney-body")) {
        const emBody = await inner(page, "euromoney-body");
        const EMONTH = "(January|February|March|April|May|June|July|August|September|October|November|December) 20\\d\\d";
        const EVS = "(up \\d{1,3}\\.\\d% on (a month|three months) ago|down \\d{1,3}\\.\\d% on (a month|three months) ago|the same as (a month|three months) ago)";
        match(emBody, new RegExp(`At the end of ${EMONTH} the euro area's broad money supply \\(M3\\) was €\\d{1,2}\\.\\d{2} trillion, ((growing|shrinking) \\d{1,2}\\.\\d% a year|not growing) \\(the ECB's own annual rate\\)\\.`), "M3 with its month and the ECB's growth rate");
        match(emBody, new RegExp(`The amount was ${EVS} and ${EVS}\\.`), "the one- and three-month changes of the amount");
        match(emBody, new RegExp(`the ECB's growth rate ran from [-+]?\\d{1,2}\\.\\d% \\(${EMONTH}\\) to [-+]?\\d{1,2}\\.\\d% \\(${EMONTH}\\); \\d{1,3}% of those months were slower than now\\.`), "the ten-year range is explained in months");
        match(emBody, /M2, €\d{1,2}\.\d{2} trillion, (growing|shrinking) \d{1,2}\.\d% a year\. M1, €\d{1,2}\.\d{2} trillion, (growing|shrinking) \d{1,2}\.\d% a year\./, "M2 and M1");
        match(emBody, /M3 is made of: currency and overnight deposits, \d{1,2}\.\d%; deposits with an agreed maturity of up to two years, \d{1,2}\.\d%; deposits redeemable at notice of up to three months, \d{1,2}\.\d%; repurchase agreements, money market fund shares and debt securities of up to two years, \d{1,2}\.\d%\./, "what M3 is made of");
        match(emBody, /Check: in each of the last \d{2} months, M1, M2 and M3 equal the sums of their parts to the million euro/, "the sums check is shown"); match(emBody, /not that they are right/);
        match(emBody, /Plain checks: the units are the ones assumed/); match(emBody, /not a market signal or a forecast/); match(emBody, /provisional and is revised later/);
        noMatch(emBody, /\b20\d\d-\d\d(-\d\d)?\b/, "no raw ISO dates on screen");
      }
      await page.locator(V("euromoney-card")).scrollIntoViewIfNeeded().catch(() => undefined);
      await shot(page, "07z-euromoney");

      await page.waitForSelector(V("eurolending-card"));
      await page.waitForSelector(V("eurolending-body") + ", " + V("eurolending-unavailable") + ", " + V("eurolending-error"), { timeout: 60000 });
      const elTxt = await text(page);
      match(elTxt, /Euro-area bank lending/); match(elTxt, /European Central Bank/); noMatch(elTxt, FORECASTS, "the euro bank lending card makes no forecasts");
      if (await liveCard(page, "eurolending-body")) {
        const elBody = await inner(page, "eurolending-body");
        const LMONTH = "(January|February|March|April|May|June|July|August|September|October|November|December) 20\\d\\d";
        const LGROW = "(?:grew \\d{1,2}\\.\\d{2}%|shrank \\d{1,2}\\.\\d{2}%|was unchanged)";
        const LS = "[+-]?\\d{1,2}\\.\\d{2}%";
        const LR = "(?:growing \\d{1,2}\\.\\d{2}% a year|shrinking \\d{1,2}\\.\\d{2}% a year|not growing)";
        const LS1 = "[+-]?\\d{1,2}\\.\\d%";                                                                                  // the ten-year extremes come with one decimal
        const LRANGE = (who) => new RegExp(`${who}: over the past 10 years \\(\\d{2,3} months\\) the annual growth ran from ${LS1} \\(${LMONTH}\\) to ${LS1} \\(${LMONTH}\\); \\d{1,3}% of those months were slower than now\\.`);
        const LROW = (label, of) => `${label}: €\\d{1,2}\\.\\d{2} trillion, \\d{1,2}\\.\\d% of ${of}, ${LR}\\.`;
        match(elBody, new RegExp(`Loans of euro-area banks to firms ${LGROW} over the twelve months to ${LMONTH}, against ${LS} over the twelve months to ${LMONTH}; loans to households ${LGROW}, against ${LS}\\.`), "the growth of loans to firms and to households against a year earlier");
        match(elBody, LRANGE("Loans to firms"), "the ten-year range of the growth of loans to firms"); match(elBody, LRANGE("Loans to households"), "the ten-year range of the growth of loans to households");
        match(elBody, new RegExp(`At the end of ${LMONTH} euro-area banks had lent €\\d{1,2}\\.\\d{2} trillion to firms \\(net (?:new lending|repayments) of €[\\d,]+\\.\\d billion in the month\\) and €\\d{1,2}\\.\\d{2} trillion to households \\(net (?:new lending|repayments) of €[\\d,]+\\.\\d billion in the month\\)\\.`), "the amounts lent and the month's net lending");
        match(await inner(page, "eurolending-households"), new RegExp(`^${LROW("Lending to households for house purchase", "household loans")}\\s*${LROW("Consumer credit", "household loans")}\\s*${LROW("Other lending to households", "household loans")}$`), "the three purposes of household loans");
        match(await inner(page, "eurolending-firms"), new RegExp(`^${LROW("Loans to firms of up to one year", "loans to firms")}\\s*${LROW("Loans to firms of one to five years", "loans to firms")}\\s*${LROW("Loans to firms of over five years", "loans to firms")}$`), "the three maturities of loans to firms");
        match(await inner(page, "eurolending-recent"), new RegExp(`^(?:${LMONTH}: firms ${LS}, households ${LS}\\s*){6}$`), "six months with their growth");
        match(elBody, /Check: in each of the last 36 months every amount, every monthly change and every growth rate lay inside its range \(plain checks\)/, "the checks are shown");
        match(elBody, /in each of the last 24 months the published annual growth equalled the growth rebuilt from the monthly flows and amounts to within 0\.0625 points/); match(elBody, /not that the figures are right/);
        match(elBody, /adjusted for loan sales and securitisation/); match(elBody, /not a market signal or a forecast/); match(elBody, /provisional and is revised later/);
        noMatch(elBody, /\b20\d\d-\d\d(-\d\d)?\b/, "no raw ISO dates on screen");
      }
      await page.locator(V("eurolending-card")).first().evaluate((el) => el.scrollIntoView({ block: "start" })).catch(() => undefined);      // the top of a tall card, not its nearest edge
      await shot(page, "07zf-eurolending-top");
      await page.locator(V("eurolending-card")).first().evaluate((el) => el.scrollIntoView({ block: "end" })).catch(() => undefined);        // and its bottom: the note and the source link
      await shot(page, "07zf-eurolending-bottom");

      await page.waitForSelector(V("eurobankrates-card"));
      await page.waitForSelector(V("eurobankrates-body") + ", " + V("eurobankrates-unavailable") + ", " + V("eurobankrates-error"), { timeout: 110000 });         // the ECB's MIR service is slow when it has to compute: up to 90 s for one request
      const ebTxt = await text(page);
      match(ebTxt, /Euro-area bank interest rates/); match(ebTxt, /European Central Bank/); noMatch(ebTxt, FORECASTS, "the euro bank interest rates card makes no forecasts");
      if (await liveCard(page, "eurobankrates-body")) {
        const ebBody = await inner(page, "eurobankrates-body");
        const BMONTH = "(January|February|March|April|May|June|July|August|September|October|November|December) 20\\d\\d";
        const BP = "-?\\d{1,2}\\.\\d{2}%";                                                                                 // a rate may be below zero (firms' deposits were)
        const BMOVE = (vs) => `(?:up \\d{1,2}\\.\\d{2} points on ${vs}|down \\d{1,2}\\.\\d{2} points on ${vs}|unchanged on ${vs})`;
        const BVOL = (what) => ` ${what} in the month: €[\\d,]+\\.\\d billion\\.`;
        const BROW = (label, extra = "") => `${label}: ${BP} a year, ${BMOVE("a month earlier")}, ${BMOVE("a year earlier")}\\.${extra}`;
        const BRANGE = `\\s*Over the past 10 years \\(\\d{2,3} months\\) it ran from ${BP} \\(${BMONTH}\\) to ${BP} \\(${BMONTH}\\); \\d{1,3}% of those months were lower than now\\.`;
        match(await inner(page, "eurobankrates-loans"), new RegExp(`^${BROW("Loans to firms", BVOL("New loans"))}\\s*${BROW("Loans for house purchase", BVOL("New loans"))}\\s*${BROW("Consumer credit", BVOL("New loans"))}\\s*${BROW("Other loans to households", BVOL("New loans"))}$`), "the four kinds of new loans");
        match(await inner(page, "eurobankrates-costs"), new RegExp(`^${BROW("The ECB's cost of borrowing for firms")}${BRANGE}\\s*${BROW("The ECB's cost of borrowing for house purchase")}${BRANGE}$`), "the two composites with their ten-year ranges");
        match(await inner(page, "eurobankrates-deposits"), new RegExp(`^${BROW("Household overnight deposits")}\\s*${BROW("Household term deposits", BVOL("New deposits"))}\\s*${BROW("Firms' overnight deposits")}\\s*${BROW("Firms' term deposits", BVOL("New deposits"))}$`), "the four kinds of new deposits");
        match(await inner(page, "eurobankrates-recent"), new RegExp(`^(?:${BMONTH}: firms ${BP}, house purchase ${BP}\\s*){6}$`), "six months of the cost of borrowing");
        match(ebBody, /Check: in each of the last 36 months every rate and volume lay inside its range, no loan, term-deposit or composite rate moved by more than 2 points in a month and no overnight deposit rate by more than 1 point \(plain checks\)/, "the plain checks are shown");
        match(ebBody, /equalled the volume with a floating rate or up to one year of fixed interest plus the volume fixed for over one year, to 0\.016 million euro/, "the volume sums are shown");
        match(ebBody, /in each of the last 24 months the rate on all of it equalled the average of the two parts' rates weighted by their volumes, to 0\.016 points/, "the weighted average identity is shown"); match(ebBody, /not that the figures are right/);
        match(ebBody, /NEW loans and pay on NEW deposits/); match(ebBody, /not a market signal or a forecast/); match(ebBody, /provisional and is revised later/);
        noMatch(ebBody, /\b20\d\d-\d\d(-\d\d)?\b/, "no raw ISO dates on screen");
      }
      await page.locator(V("eurobankrates-card")).first().evaluate((el) => el.scrollIntoView({ block: "start" })).catch(() => undefined);      // the top of a tall card, not its nearest edge
      await shot(page, "07zg-eurobankrates-top");
      await page.locator(V("eurobankrates-deposits")).first().evaluate((el) => el.scrollIntoView({ block: "center" })).catch(() => undefined);   // the middle: the deposit rows and the monthly cost of borrowing
      await shot(page, "07zg-eurobankrates-middle");
      await page.locator(V("eurobankrates-card")).first().evaluate((el) => el.scrollIntoView({ block: "end" })).catch(() => undefined);        // and its bottom: the note and the source link
      await shot(page, "07zg-eurobankrates-bottom");

      await page.waitForSelector(V("euroemployment-card"));
      await page.waitForSelector(V("euroemployment-body") + ", " + V("euroemployment-unavailable") + ", " + V("euroemployment-error"), { timeout: 110000 });         // the ECB's national accounts service takes 5 to 35 s per request when it has to compute, and the card asks for four at once
      const eeTxt = await text(page);
      match(eeTxt, /Euro-area employment and productivity/); match(eeTxt, /European Central Bank/); noMatch(eeTxt, FORECASTS, "the euro employment card makes no forecasts");
      if (await liveCard(page, "euroemployment-body")) {
        const eeBody = await inner(page, "euroemployment-body");
        const EMOVE = "(?:up \\d{1,2}\\.\\d{2}%|down \\d{1,2}\\.\\d{2}%|unchanged)";
        const EQ = "Q[1-4] 20\\d\\d";
        match(eeBody, new RegExp(`\\d{3}\\.\\d million people were in work in ${EQ}, ${EMOVE} from the previous quarter \\(${EQ}\\) and ${EMOVE} from the same quarter a year earlier \\(${EQ}\\)\\.`), "the headline");
        match(await inner(page, "euroemployment-recent"), new RegExp(`^(?:${EQ}: \\d{3}\\.\\d million, [+-]?\\d{1,2}\\.\\d{2}% on the previous quarter, [+-]?\\d{1,2}\\.\\d{2}% on a year earlier\\s*){6}$`), "six quarters of people in work");
        match(await inner(page, "euroemployment-hours"), new RegExp(`^In ${EQ} \\(the newest quarter with a breakdown\\) people worked \\d{2}\\.\\d billion hours, \\d{3}\\.\\d hours each in the quarter; hours worked were ${EMOVE} from a year earlier\\.\\s*Employees were \\d{2}\\.\\d% of the people in work \\(\\d{3}\\.\\d million\\) and \\d{2}\\.\\d% of the hours; the self-employed were \\d{2}\\.\\d% \\(\\d{2}\\.\\d million\\) and \\d{2}\\.\\d% of the hours\\.$`), "hours and employees");
        match(await inner(page, "euroemployment-sectors"), new RegExp(`^(?:[A-Z][a-z ,]+: \\d{1,2}\\.\\d million people \\(\\d{1,2}\\.\\d% of all jobs\\), ${EMOVE} \\([+-]?[\\d,]+ thousand\\) on a year earlier\\.\\s*){10}$`), "the ten activities");
        match(await inner(page, "euroemployment-productivity"), new RegExp(`^Real GDP per person in work was ${EMOVE} on the previous quarter and ${EMOVE} on a year earlier \\(${EQ}\\)\\.\\s*Real GDP per hour worked was ${EMOVE} on the previous quarter and ${EMOVE} on a year earlier \\(${EQ}\\)\\.$`), "output per worker");
        match(eeBody, /Check: in each of the last 45 quarters \(44 for persons, where total employment is a quarter ahead of its breakdown\) every figure lay inside its range and total employment moved by no more than 10% in a quarter \(plain checks, not the source's sums\)/, "the plain checks are shown");
        match(eeBody, /the ten activities add up to total employment, and employees plus the self-employed add up to total employment, for persons \(largest gap under 0\.000001 thousand persons\) and for hours \(largest gap under 0\.000001 thousand hours\)/, "the sums are shown");
        match(eeBody, /equals real GDP growth over employment growth \(largest gap under 0\.000001 points\)/, "the productivity relation is shown"); match(eeBody, /not that the figures are right/);
        match(eeBody, /about 45 days/); match(eeBody, /not a market signal or a forecast/);
        noMatch(eeBody, /\b20\d\d-\d\d(-\d\d)?\b/, "no raw ISO dates on screen");
      }
      await page.locator(V("euroemployment-card")).first().evaluate((el) => el.scrollIntoView({ block: "start" })).catch(() => undefined);      // the top of a tall card, not its nearest edge
      await shot(page, "07zh-euroemployment-top");
      await page.locator(V("euroemployment-sectors")).first().evaluate((el) => el.scrollIntoView({ block: "center" })).catch(() => undefined);   // the middle: the ten activities
      await shot(page, "07zh-euroemployment-middle");
      await page.locator(V("euroemployment-card")).first().evaluate((el) => el.scrollIntoView({ block: "end" })).catch(() => undefined);        // and its bottom: the note and the source link
      await shot(page, "07zh-euroemployment-bottom");

      await page.waitForSelector(V("euroinflation-card"));
      await page.waitForSelector(V("euroinflation-body") + ", " + V("euroinflation-unavailable") + ", " + V("euroinflation-error"), { timeout: 45000 });
      const eiTxt = await text(page);
      match(eiTxt, /Euro-area consumer prices/); match(eiTxt, /Eurostat/); noMatch(eiTxt, FORECASTS, "the euro consumer prices card makes no forecasts");
      if (await liveCard(page, "euroinflation-body")) {
        const eiBody = await inner(page, "euroinflation-body");
        const EIMONTH = "(January|February|March|April|May|June|July|August|September|October|November|December) 20\\d\\d";
        const EIMV = "(up \\d{1,2}\\.\\d points on (a month|three months) ago|down \\d{1,2}\\.\\d points on (a month|three months) ago|the same as (a month|three months) ago)";
        match(eiBody, new RegExp(`In ${EIMONTH} consumer prices in the euro area were (\\d{1,2}\\.\\d% (higher|lower) than a year earlier|unchanged from a year earlier)\\. Without energy, food, alcohol and tobacco \\(core\\) the rate was -?\\d{1,2}\\.\\d%\\.`), "the headline with its month, and the core rate");
        match(eiBody, new RegExp(`The annual rate was ${EIMV} and ${EIMV}\\.`), "the one- and three-month changes of the rate, in points");
        match(eiBody, new RegExp(`it ran from [-+]?\\d{1,2}\\.\\d% \\(${EIMONTH}\\) to [-+]?\\d{1,2}\\.\\d% \\(${EIMONTH}\\); \\d{1,3}% of those months were lower than now\\.`), "the ten-year range is explained in months");
        const PARTS = { FOODPR: "Processed food, alcohol and tobacco", FOODUN: "Unprocessed food", IGXE00: "Non-energy industrial goods", NRGY00: "Energy", SERV00: "Services" };
        let shares = 0;
        for (const [id, label] of Object.entries(PARTS)) {
          const line = (await inner(page, `euroinflation-part-${id}`)).trim();
          match(line, new RegExp(`^${label}: (\\d{1,2}\\.\\d)% of the basket, [-+]?\\d{1,2}\\.\\d% a year(, about -?\\d{1,2}\\.\\d points of the -?\\d{1,2}\\.\\d%)?\\.$`), `the ${label} line has its share, its rate and (when they agree) its points`);
          shares += Number(/(\d{1,2}\.\d)% of the basket/.exec(line)[1]);
        }
        if (Math.abs(shares - 100) > 0.3) throw new Error(`the five shares of the basket add up to ${shares.toFixed(1)}%, not 100`);
        match(eiBody, /The points (are each part's share of the basket times its annual rate: an approximation|are not shown this month)/, "the points say what they are");
        match(eiBody, /Check: in each of the last \d{2} months the headline lay between the rates of its five parts and core between the goods and the services/, "the checks are shown");
        match(eiBody, /largest gap \d\.\d{3} index points/); match(eiBody, /largest gap \d\.\d{2} points/); match(eiBody, /not that the figures are right/);
        match(eiBody, /early \(flash\) estimate/); match(eiBody, /not a market signal or a forecast/);
        noMatch(eiBody, /\b20\d\d-\d\d(-\d\d)?\b/, "no raw ISO dates on screen");
      }
      await page.locator(V("euroinflation-card")).first().evaluate((el) => el.scrollIntoView({ block: "start" })).catch(() => undefined);      // the top of a tall card, not its nearest edge
      await shot(page, "07za-euroinflation-top");
      await page.locator(V("euroinflation-card")).scrollIntoViewIfNeeded().catch(() => undefined);
      await shot(page, "07za-euroinflation");

      await page.waitForSelector(V("eurounemployment-card"));
      await page.waitForSelector(V("eurounemployment-body") + ", " + V("eurounemployment-unavailable") + ", " + V("eurounemployment-error"), { timeout: 45000 });
      const euTxt = await text(page);
      match(euTxt, /Euro-area unemployment/); match(euTxt, /Eurostat/); noMatch(euTxt, FORECASTS, "the euro unemployment card makes no forecasts");
      if (await liveCard(page, "eurounemployment-body")) {
        const euBody = await inner(page, "eurounemployment-body");
        const EUMONTH = "(January|February|March|April|May|June|July|August|September|October|November|December) 20\\d\\d";
        const EUMV = "(up \\d\\.\\d points on (a month|three months|a year) ago|down \\d\\.\\d points on (a month|three months|a year) ago|the same as (a month|three months|a year) ago)";
        match(euBody, new RegExp(`In ${EUMONTH}, \\d{1,2}\\.\\d% of the euro area's labour force was unemployed: \\d{1,2}\\.\\d{2} million people \\(the euro area of 20 countries\\)\\.`), "the rate and the number of people, with the month");
        match(euBody, new RegExp(`The rate was ${EUMV}, ${EUMV} and ${EUMV}\\.( There are \\d{1,3}(,\\d{3})* thousand (more|fewer) unemployed people than a year ago\\.| The number of unemployed is the same as a year ago\\.)? Over the past 10 years \\(\\d{2,3} months\\), the rate ran from \\d{1,2}\\.\\d% \\(${EUMONTH}\\) to \\d{1,2}\\.\\d% \\(${EUMONTH}\\); \\d{1,3}% of those months were lower than now\\.`), "the changes in points, the change over a year in people and the ten-year range in months");
        for (const [id, label] of Object.entries({ "15_74.F": "women", "15_74.M": "men", "15_24.T": "people under 25", "25_74.T": "people aged 25 to 74" })) {
          match((await inner(page, `eurounemployment-group-${id}`)).trim(), new RegExp(`^Unemployment among ${label}: \\d{1,2}\\.\\d%\\.$`), `the ${label} line has its rate`);
        }
        match(euBody, /Of the \d{1,2}\.\d{2} million unemployed, \d{1,2}% are women and \d{1,2}% are under 25 \(calculated here from the published numbers\)\./, "the shares are said to be calculated here");
        match(euBody, /Check: in each of the last \d{2} months the rate for everybody lay between the rates of women and men and between those of the under 25 and the 25 to 74/, "the checks are shown");
        match(euBody, /largest gap \d+\.\d thousand/); match(euBody, /largest gap \d\.\d{2}%/); match(euBody, /not that the figures are right/);
        match(euBody, /fixed composition/); match(euBody, /not a market signal or a forecast/);
        noMatch(euBody, /\b20\d\d-\d\d(-\d\d)?\b/, "no raw ISO dates on screen");
      }
      await page.locator(V("eurounemployment-card")).first().evaluate((el) => el.scrollIntoView({ block: "start" })).catch(() => undefined);      // the top of a tall card, not its nearest edge
      await shot(page, "07zb-eurounemployment-top");
      await page.locator(V("eurounemployment-card")).scrollIntoViewIfNeeded().catch(() => undefined);
      await shot(page, "07zb-eurounemployment");

      await page.waitForSelector(V("eurostress-card"));
      await page.waitForSelector(V("eurostress-body") + ", " + V("eurostress-unavailable") + ", " + V("eurostress-error"), { timeout: 45000 });
      const esTxt = await text(page);
      match(esTxt, /Euro-area financial stress/); match(esTxt, /European Central Bank/); noMatch(esTxt, FORECASTS, "the euro stress card makes no forecasts");
      if (await liveCard(page, "eurostress-body")) {
        const esBody = await inner(page, "eurostress-body");
        const ESD = "[A-Z][a-z]{2} \\d{1,2}, 20\\d\\d";
        const ESV = "\\d\\.\\d{4}";
        const ESN = "(unchanged|(up|down) \\d\\.\\d{4})";
        match(esBody, new RegExp(`On ${ESD} the ECB's index of systemic stress in the euro area's financial markets stood at ${ESV} \\(the scale runs from 0 to 1; higher means more stress\\)\\.`), "the index with its day and its scale");
        match(esBody, new RegExp(`A week ago \\(${ESD}\\) it was ${ESV}, now ${ESN}; a month ago \\(${ESD}\\) it was ${ESV}, now ${ESN}\\. Over the past 10 years \\(\\d,\\d{3} days\\), \\d{1,3}% of the days were calmer than now; the middle day was ${ESV}, the calmest ${ESV} \\(${ESD}\\) and the most stressed ${ESV} \\(${ESD}\\)\\.`), "the week and month back with their days, and the ten-year comparison");
        for (const [id, label] of Object.entries({ SS_BMN: "Bond market", SS_EMN: "Equity market", SS_FIN: "Financial intermediaries", SS_FXN: "Foreign exchange market", SS_MMN: "Money market" })) {
          match((await inner(page, `eurostress-segment-${id}`)).trim(), new RegExp(`^${label}: ${ESV}$`), `the ${label} line has its contribution`);
        }
        match(esBody, /Together \d\.\d{4}; the ECB's correlation term between the segments -\d\.\d{4} \(it has been negative on every day since 1999\); index \d\.\d{4}\. Figures are rounded/, "the sum is shown with the correlation term");
        match(esBody, /Check: in each of the last \d,\d{3} days the index lay between 0 and 1 and moved by at most 0\.25 in a day, and in each of the last 520 days each segment contributed between 0 and 1/, "the checks are shown");
        match(esBody, /largest gap within 0\.000001/); match(esBody, /not that the figures are right/);
        match(esBody, /changing composition/); match(esBody, /not a market signal or a forecast/);
        noMatch(esBody, /\b20\d\d-\d\d-\d\d\b/, "no raw ISO dates on screen");
      }
      await page.locator(V("eurostress-card")).first().evaluate((el) => el.scrollIntoView({ block: "start" })).catch(() => undefined);      // the top of a tall card, not its nearest edge
      await shot(page, "07zc-eurostress-top");
      await page.locator(V("eurostress-card")).first().evaluate((el) => el.scrollIntoView({ block: "end" })).catch(() => undefined);           // and its bottom: the note and the source link
      await shot(page, "07zc-eurostress-bottom");

      await page.waitForSelector(V("euroyields-card"));
      await page.waitForSelector(V("euroyields-body") + ", " + V("euroyields-unavailable") + ", " + V("euroyields-error"), { timeout: 45000 });
      const eyTxt = await text(page);
      match(eyTxt, /Euro-area government bond yields/); match(eyTxt, /European Central Bank/); noMatch(eyTxt, FORECASTS, "the euro yields card makes no forecasts");
      if (await liveCard(page, "euroyields-body")) {
        const eyBody = await inner(page, "euroyields-body");
        const EYD = "[A-Z][a-z]{2} \\d{1,2}, 20\\d\\d";
        const EYP = "-?\\d{1,2}\\.\\d{2}%";
        match(eyBody, new RegExp(`On ${EYD} the ECB's curve for AAA-rated euro-area government bonds gave ${EYP} for 10 years, ${EYP} for 2 years and ${EYP} for 3 months \\(spot rates\\)\\.`), "the 10-year, 2-year and 3-month rates with their day");
        match(eyBody, new RegExp(`Over the past 10 years \\(\\d,\\d{3} days\\) the 10-year rate was lower than now on \\d{1,3}% of the days; the middle day was ${EYP}, the lowest ${EYP} \\(${EYD}\\) and the highest ${EYP} \\(${EYD}\\)\\.`), "the ten-year comparison");
        for (const [id, label] of Object.entries({ SR_3M: "3 months", SR_1Y: "1 year", SR_2Y: "2 years", SR_5Y: "5 years", SR_10Y: "10 years", SR_30Y: "30 years" })) {
          match((await inner(page, `euroyields-rate-${id}`)).trim(), new RegExp(`^${label}: ${EYP} \\(((up|down) \\d\\.\\d{2}|unchanged) on a week ago, ((up|down) \\d\\.\\d{2}|unchanged) on a month ago\\)$`), `the ${label} line has its rate and its changes`);
        }
        match(eyBody, /10 years minus 3 months: -?\d\.\d{2} points; minus 1 year: -?\d\.\d{2}; minus 2 years: -?\d\.\d{2}\./, "the ECB's own spreads are shown");
        match(eyBody, /Check: in each of the last \d,\d{3} days the 10-year rate, and in each of the last 520 days every other rate and spread/, "the checks are shown");
        match(eyBody, /largest gap within 0\.000001/); match(eyBody, /not that the figures are right/);
        match(eyBody, /fitted curve, not a market quote/); match(eyBody, /not a market signal or a forecast/);
        noMatch(eyBody, /\b20\d\d-\d\d-\d\d\b/, "no raw ISO dates on screen");
      }
      await page.locator(V("euroyields-card")).first().evaluate((el) => el.scrollIntoView({ block: "start" })).catch(() => undefined);      // the top of a tall card, not its nearest edge
      await shot(page, "07zd-euroyields-top");
      await page.locator(V("euroyields-card")).first().evaluate((el) => el.scrollIntoView({ block: "end" })).catch(() => undefined);           // and its bottom: the note and the source link
      await shot(page, "07zd-euroyields-bottom");

      await page.waitForSelector(V("eurogdp-card"));
      await page.waitForSelector(V("eurogdp-body") + ", " + V("eurogdp-unavailable") + ", " + V("eurogdp-error"), { timeout: 60000 });
      const egTxt = await text(page);
      match(egTxt, /Euro-area GDP/); match(egTxt, /European Central Bank/); noMatch(egTxt, FORECASTS, "the euro GDP card makes no forecasts");
      if (await liveCard(page, "eurogdp-body")) {
        const egBody = await inner(page, "eurogdp-body");
        const EGQ = "Q[1-4] 20\\d\\d";
        const EGC = "(?:grew \\d{1,2}\\.\\d{2}%|shrank \\d{1,2}\\.\\d{2}%|was unchanged)";
        const EGP = "-?\\d{1,2}\\.\\d{2}%";
        const EGS = "[+-]?\\d{1,2}\\.\\d{2}";
        match(egBody, new RegExp(`Real GDP ${EGC} from the previous quarter \\(${EGQ}\\) and ${EGC} from the same quarter a year earlier \\(${EGQ}\\)\\.`), "the growth on the quarter and on the year with their quarters");
        match(egBody, new RegExp(`Over the past 10 years \\(\\d\\d quarters\\) growth on the quarter was lower than now in \\d{1,3}% of the quarters; the middle quarter was ${EGP}, the lowest ${EGP} \\(${EGQ}\\) and the highest ${EGP} \\(${EGQ}\\)\\.`), "the ten-year comparison");
        match(await inner(page, "eurogdp-recent"), new RegExp(`^(?:${EGQ}: ${EGS}% on the previous quarter, ${EGS}% on a year earlier\\s*){6}$`), "six quarters with their growth");
        match(egBody, new RegExp(`GDP at current prices in ${EGQ} \\(the newest quarter with a breakdown\\): €[\\d,]+\\.\\d billion for the quarter, seasonally adjusted and not annualised; domestic demand €[\\d,]+\\.\\d billion plus exports €[\\d,]+\\.\\d billion minus imports €[\\d,]+\\.\\d billion\\.`), "the breakdown at current prices");
        match(egBody, new RegExp(`Contributions to that quarter's real growth of ${EGP}: domestic demand ${EGS} points and net trade ${EGS} points \\(exports ${EGS}, imports ${EGS}\\)\\.`), "the contributions to growth");
        match(egBody, /Check: in each of the last 45 quarters every figure lay inside its range and nominal GDP moved by no more than 15% in a quarter/, "the checks are shown");
        match(egBody, /to within 0\.02 million euros/); match(egBody, /to within 0\.000001 points/); match(egBody, /not that the figures are right/);
        match(egBody, /not a market signal or a forecast/); match(egBody, /stopped at Q1 2026/);
        noMatch(egBody, /\b20\d\d-\d\d-\d\d\b/, "no raw ISO dates on screen");
        noMatch(egBody, /\b20\d\d-Q[1-4]\b/, "no raw quarter codes on screen");
      }
      await page.locator(V("eurogdp-card")).first().evaluate((el) => el.scrollIntoView({ block: "start" })).catch(() => undefined);          // the top of a tall card, not its nearest edge
      await shot(page, "07ze-eurogdp-top");
      await page.locator(V("eurogdp-card")).first().evaluate((el) => el.scrollIntoView({ block: "end" })).catch(() => undefined);           // and its bottom: the note and the source link
      await shot(page, "07ze-eurogdp-bottom");

      await page.waitForSelector(V("customs-card"));
      await page.waitForSelector(V("customs-body") + ", " + V("customs-unavailable") + ", " + V("customs-error"), { timeout: 45000 });
      const cd = await text(page);
      match(cd, /Customs duties/); match(cd, /US Treasury/); noMatch(cd, FORECASTS, "the customs card makes no forecasts");
      if (await liveCard(page, "customs-body")) {
        const kbody = await inner(page, "customs-body");
        match(kbody, /(January|February|March|April|May|June|July|August|September|October|November|December) 20\d\d/, "the month is written out");
        match(kbody, /Kept after refunds\. Collected/); match(kbody, /Fiscal 20\d\d so far/); match(kbody, /Same point last year/); match(kbody, /Last \d+ months, kept after refunds/);
        match(kbody, /Checked: each month's collected minus refunded equals what was kept/); match(kbody, /does not say why refunds/); match(kbody, /not a market signal or a forecast/);
        noMatch(kbody, /\b20\d\d-\d\d-\d\d\b/, "no raw ISO dates on screen");
      }
      await page.locator(V("customs-card")).scrollIntoViewIfNeeded().catch(() => undefined);
      await shot(page, "07k-customs");

      await page.waitForSelector(V("receipts-card"));
      await page.waitForSelector(V("receipts-body") + ", " + V("receipts-unavailable") + ", " + V("receipts-error"), { timeout: 45000 });
      const rc = await text(page);
      match(rc, /Where federal revenue comes from/); match(rc, /US Treasury/); noMatch(rc, FORECASTS, "the receipts card makes no forecasts");
      if (await liveCard(page, "receipts-body")) {
        const gbody = await inner(page, "receipts-body");
        match(gbody, /Fiscal 20\d\d so far \(\d+ months? from October\) · through (January|February|March|April|May|June|July|August|September|October|November|December) 20\d\d/, "the month is written out");
        match(gbody, /Individual income taxes: \$[\d,.]+B/); match(gbody, /Corporate income taxes: /); match(gbody, /Customs duties \(tariffs\): /);
        match(gbody, /Checked: the seven sources add up/); match(gbody, /does not say why any category rose or fell/); match(gbody, /not a market signal or a forecast/);
        noMatch(gbody, /\b20\d\d-\d\d-\d\d\b/, "no raw ISO dates on screen");
      }
      await page.locator(V("receipts-card")).scrollIntoViewIfNeeded().catch(() => undefined);
      await shot(page, "07l-receipts");

      await page.waitForSelector(V("outlays-card"));
      await page.waitForSelector(V("outlays-body") + ", " + V("outlays-unavailable") + ", " + V("outlays-error"), { timeout: 45000 });
      const oc = await text(page);
      match(oc, /Where federal money goes/); match(oc, /US Treasury/); noMatch(oc, FORECASTS, "the outlays card makes no forecasts");
      if (await liveCard(page, "outlays-body")) {
        const obody = await inner(page, "outlays-body");
        match(obody, /Fiscal 20\d\d so far \(\d+ months? from October\) · through (January|February|March|April|May|June|July|August|September|October|November|December) 20\d\d/, "the month is written out");
        match(obody, /Spent, (up|down) [\d.]+% from/); match(obody, /spending ran ahead of income by/); match(obody, /Social Security: \$[\d,.]+B/); match(obody, /Net Interest: /);
        match(obody, /Checked: the purposes add up/); match(obody, /does not say why any purpose rose or fell/); match(obody, /not a market signal or a forecast/);
        noMatch(obody, /\b20\d\d-\d\d-\d\d\b/, "no raw ISO dates on screen");
      }
      await page.locator(V("outlays-card")).scrollIntoViewIfNeeded().catch(() => undefined);
      await shot(page, "07m-outlays");
      const macroAll = await page.evaluate(() => { const el = document.querySelector('[data-testid="macro-brief"]'); return el ? el.innerText : ""; });          // the Macro screen only: screens stay mounted under the one on top
      assert(macroAll.length > 500, "the Macro screen text should be read in full");
      const rawDates = [...new Set(macroAll.match(/\b20\d\d-\d\d(-\d\d)?\b/g) || [])];
      const allLines = macroAll.split("\n");
      const rawLines = allLines.map((l, i) => (/\b20\d\d-\d\d(-\d\d)?\b/.test(l) ? `${(allLines[i - 1] || "").trim().slice(0, 40)} >> ${l.trim().slice(0, 60)}` : "")).filter(Boolean);
      assert(rawDates.length === 0, `the Macro screen must write dates in words, found raw dates in: ${rawLines.join(" || ")}`);
      await page.waitForSelector(V("debtrates-card"));
      await page.waitForSelector(V("debtrates-body") + ", " + V("debtrates-unavailable") + ", " + V("debtrates-error"), { timeout: 45000 });
      const dr = await text(page);
      match(dr, /Interest the Treasury pays/); match(dr, /US Treasury/); noMatch(dr, FORECASTS, "the debt-rates card makes no forecasts");
      if (await liveCard(page, "debtrates-body")) match(dr, /not a market signal or a forecast/, "the debt-rates caveat is shown");
      await page.locator(V("debtrates-card")).scrollIntoViewIfNeeded().catch(() => undefined);
      await shot(page, "07a-debtrates");
      await page.waitForSelector(V("debtmix-card"));
      await page.waitForSelector(V("debtmix-body") + ", " + V("debtmix-unavailable") + ", " + V("debtmix-error"), { timeout: 45000 });
      const dm = await text(page);
      match(dm, /What the US debt is made of/); match(dm, /US Treasury/); noMatch(dm, FORECASTS, "the debt-mix card makes no forecasts");
      if (await liveCard(page, "debtmix-body")) match(dm, /not a market signal or a forecast/, "the debt-mix caveat is shown");
      await page.waitForSelector(V("fedholdings-card"));
      await page.waitForSelector(V("fedholdings-body") + ", " + V("fedholdings-unavailable") + ", " + V("fedholdings-error"), { timeout: 60000 });
      const fh = await text(page);
      match(fh, /What the Fed holds/); match(fh, /New York Fed/); noMatch(fh, FORECASTS, "the Fed holdings card makes no forecasts");
      if (await liveCard(page, "fedholdings-body")) match(fh, /not a market signal or a forecast/, "the Fed holdings caveat is shown");
      await page.waitForSelector(V("fedrates-card"));
      await page.waitForSelector(V("fedrates-body") + ", " + V("fedrates-unavailable") + ", " + V("fedrates-error"), { timeout: 45000 });
      const fr = await text(page);
      match(fr, /Fed interest rate/); match(fr, /New York Fed/); noMatch(fr, FORECASTS, "the Fed rate card makes no forecasts");
      if (await liveCard(page, "fedrates-body")) match(fr, /not market signals or forecasts/, "the Fed rate caveat is shown");
      match(wt, /World economies/); noMatch(wt, FORECASTS, "the World Bank card makes no forecasts");
      if (await liveCard(page, "world-body")) match(wt, /revised later/, "the annual-data caveat is shown");
      match(fxText, /US dollar vs major currencies/); match(fxText, /ECB/); noMatch(fxText, FORECASTS, "the exchange-rate card makes no forecasts");
      match(t, /US Treasury/, "the Treasury card is on the Macro screen"); match(t, /Yield curve|Yield curve unavailable|Demo mode/i);
      match(t, /Key indicators/); noMatch(t, /What matters today/, "the rule-based notes section was removed on request"); match(t, /Upcoming/); match(t, /Headlines/);
      match(t, /Official indicators could not be loaded right now/, "missing indicators are said once, in plain words, not invented");
      assert(!/Unavailable: unavailable/i.test(t), "no 'Unavailable: unavailable (CODE)' wording");
      eq((t.match(/Unavailable:/g) || []).length, 0, "no wall of 'Unavailable:' rows; the one plain message replaces them");
      match(t, /Consensus forecasts .* not shown/, "the gaps are listed");
      noMatch(t, FORECASTS, "no forecasts");
      eq((await clickableNames(page)).filter((n) => TRADING_CONTROL.test(n)), [], "trading controls on Macro");
      await page.waitForSelector(V("calendar-body"), { timeout: 20000 });
      const cal = await inner(page, "calendar-card");
      match(cal, /CPI \(inflation\)/, "the CPI release is on the calendar");
      match(cal, /AAPL · Apple Inc\./, "a big company's earnings are listed");
      match(cal, /Estimate \$1\.25 \(30 analysts\)/, "the estimate and analyst count come from the source");
      match(cal, /unofficial/, "unofficial sources are labelled");
      match(cal, /official/);
      noMatch(cal, /TINY/, "the default Major scope leaves out small unknown companies");
      await page.click(V("cal-scope-all"));
      await page.waitForFunction(() => /TINY/.test(document.querySelector('[data-testid="calendar-card"]')?.innerText ?? ""), null, { timeout: 15000 });
      await page.click(V("cal-kind-economy"));
      await page.waitForFunction(() => !/AAPL/.test(document.querySelector('[data-testid="calendar-card"]')?.innerText ?? ""), null, { timeout: 15000 });
      match(await inner(page, "calendar-card"), /CPI \(inflation\)/, "the Economy filter keeps the CPI release");
      eq((await clickableNames(page)).filter((n) => TRADING_CONTROL.test(n)), [], "trading controls on the calendar");
      await shot(page, "13-macro");
    });

    await check("Stock deep-dive: collapsed by default, then filings status, valuation, earnings, rule-based points and the gaps are labelled", async () => {
      await toStocks(page);
      await page.waitForSelector(V("earnings-card"));
      await page.click(V("earnings-toggle"));
      await page.waitForSelector(V("earnings-empty"), { timeout: 30000 }).catch(() => page.waitForSelector(V("earn-row-AAPL"), { timeout: 5000 }));
      await openFromWatchlist(page, ID.aapl);
      await page.waitForSelector(V("stock-card"));
      assert(!(await present(page, "stock-body")), "the deep-dive must stay collapsed until asked for");
      await page.click(V("stock-toggle"));
      await page.waitForSelector(V("stock-body"), { timeout: 45000 });
      const t = await text(page);
      match(t, /Company deep-dive/); match(t, /Financials \(annual filings\)/); match(t, /Bull points/); match(t, /Bear points/);
      match(t, /Interpretation \(rule-based\)/); match(t, /Guidance and analyst consensus .* not available/i, "the gaps are listed");
      match(t, /SEC filings are off|No filing data loaded|Demo/i, "missing SEC contact is said plainly, not papered over");
      assert((t.match(/SEC filings are off/g) || []).length <= 1, "the missing SEC contact is explained once on the stock page, not repeated in every card");
      if (await present(page, "stock-sec-off")) { match(await inner(page, "stock-sec-off"), /steps are in the SEC filings card above/, "the deep-dive points to the one explanation"); noMatch(await inner(page, "stock-body"), /\$env:ATLAS_SEC_CONTACT/, "the setup line is not repeated inside the deep-dive"); }
      const points = (await page.$$eval("div", (els) => els.map((e) => e.innerText || "").filter((x) => x.startsWith("•")))).join(" ");
      noMatch(points, FORECASTS, "bull and bear points make no forecasts");       // (headlines are quoted third-party text and are checked separately)
      eq((await clickableNames(page)).filter((n) => TRADING_CONTROL.test(n)), [], "trading controls in the deep-dive");
      await shot(page, "14-stock-deep-dive");
      await page.getByText("Financials (annual filings)").first().scrollIntoViewIfNeeded().catch(() => undefined);
      await shot(page, "14b-stock-financials");
      await page.getByText("Interpretation (rule-based)").first().scrollIntoViewIfNeeded().catch(() => undefined);
      await shot(page, "14c-stock-bottom");
      await page.click(V("back"));
    });

    await check("What-if simulator: collapsed, then five labelled replays of the past, amount changes the answer, no trading controls", async () => {
      await openFromWatchlist(page, ID.aapl);
      await page.waitForSelector(V("whatif-card"));
      assert(!(await present(page, "whatif-body")), "the simulator must stay collapsed until asked for");
      await page.click(V("whatif-toggle"));
      await page.waitForSelector(V("whatif-body"), { timeout: 45000 });
      const t = await text(page);
      match(t, /What if I had bought AAPL\?/); match(t, /One purchase, held to today/); match(t, /The same amount every month/); match(t, /Whichever day you bought/);
      match(t, /With a rule for getting out/); match(t, /shuffled years/); match(t, /Simulation, not a forecast/); match(t, /Past results do not predict future results/);
      const first = await page.$eval(V("whatif-lump-0"), (e) => e.innerText);
      await page.click(V("whatif-amt-5000"));
      await page.waitForFunction(([id, before]) => { const e = document.querySelector(`[data-testid="${id}"]`); return !!e && e.innerText !== before; }, ["whatif-lump-0", first], { timeout: 30000 });
      match(await text(page), /\$5,000/, "the chosen amount is used");
      eq((await clickableNames(page)).filter((n) => TRADING_CONTROL.test(n)), [], "trading controls in the simulator");
      await shot(page, "15-what-if");
      await page.click(V("back"));
    });

    await check("SEC filings card on a stock page: filters, rows link to sec.gov or the missing SEC contact is said plainly, no trading controls", async () => {
      await openFromWatchlist(page, ID.aapl);
      await page.waitForSelector(V("filings-card"));
      await page.waitForSelector(V("filings-body") + ", " + V("filings-error"), { timeout: 45000 });
      const t = await text(page);
      match(t, /SEC filings/); match(t, /Reports/); match(t, /Insiders/); match(t, /Big holders/);
      match(t, /Filings are switched off|ATLAS_SEC_CONTACT|Demo mode|Tap a row to open it on sec\.gov/i, "either filings or the plain reason they are missing");
      await page.click(V("filings-group-insiders"));
      await page.waitForSelector(V("filings-body"), { timeout: 30000 });
      eq((await clickableNames(page)).filter((n) => TRADING_CONTROL.test(n)), [], "trading controls in the filings card");
      await page.click(V("back"));
    });

    await check("Fear & Greed card on the BTC page: shows its source and says it is not a signal, whether the index loads or not", async () => {
      await openFromWatchlist(page, ID.btc);
      await page.waitForSelector(V("sentiment-card"));
      await page.waitForSelector(V("sentiment-body") + ", " + V("sentiment-unavailable") + ", " + V("sentiment-error"), { timeout: 30000 });
      const t = await text(page);
      match(t, /Crypto Fear & Greed/); match(t, /not a forecast or a trading signal/i); match(t, /alternative\.me/);
      await page.waitForSelector(V("positioning-card"));
      await page.waitForSelector(V("positioning-body") + ", " + V("positioning-unavailable") + ", " + V("positioning-error"), { timeout: 45000 });
      const pt = await text(page);
      match(pt, /Bitcoin futures positioning/); match(pt, /CFTC/); noMatch(pt, FORECASTS, "positioning makes no forecasts");
      await page.waitForSelector(V("stablecoins-card"));
      await page.waitForSelector(V("stablecoins-body") + ", " + V("stablecoins-unavailable") + ", " + V("stablecoins-error"), { timeout: 60000 });
      const st = await text(page);
      await page.waitForSelector(V("market-card"));
      await page.waitForSelector(V("market-body") + ", " + V("market-unavailable") + ", " + V("market-error"), { timeout: 45000 });
      const mk = await text(page);
      match(mk, /Crypto market/); match(mk, /CoinGecko/); noMatch(mk, FORECASTS, "the crypto market card makes no forecasts");
      match(st, /Stablecoin supply/); noMatch(st, FORECASTS, "stablecoin card makes no forecasts");
      await page.waitForSelector(V("network-card"));
      await page.waitForSelector(V("network-body") + ", " + V("network-error"), { timeout: 60000 });
      const nt2 = await text(page);
      await page.waitForSelector(V("tracker-card"));
      await page.waitForSelector(V("tracker-body") + ", " + V("tracker-error"), { timeout: 60000 });
      const tk = await text(page);
      match(tk, /Strategy tracker/); match(tk, /Aroon trend/); match(tk, /Backtest \(frozen on/); match(tk, /Forward record/); match(tk, /Weak evidence|No reliable evidence|Moderate evidence/);
      noMatch(tk, FORECASTS, "the tracker makes no forecasts"); match(tk, /(too little to say anything|just started|Forward tracking needs real prices)/i, "a thin forward record is called thin");
      match(nt2, /Bitcoin network/); match(nt2, /Not a price signal: fees can be near zero/); noMatch(nt2, FORECASTS, "network card makes no forecasts");
      if (await liveCard(page, "network-pools")) {
        const pools = await inner(page, "network-pools");
        match(pools, /Who found the blocks \(last 1 month\)/); match(pools, /Miners the source could not name/); match(pools, /pools for a majority|no majority among named pools/); match(pools, /not who owns the machines/);
        match(pools, /1 week: largest/); match(pools, /1 month: largest/); match(pools, /3 months: largest/); noMatch(pools, FORECASTS, "the pool shares make no forecasts");
      }
      if (await liveCard(page, "network-revenue")) {
        const rev = await inner(page, "network-revenue");
        match(rev, /What miners were paid \(last 144 blocks, about a day\)/, "the window is named");
        match(rev, /In all\s+\d{3}\.\d{2} BTC/, "the total reward of about 144 blocks of 3.125 BTC"); match(rev, /Block subsidy \(3\.125 a block\)\s+450\.00 BTC/, "the subsidy is the checked schedule figure");
        match(rev, /Transaction fees\s+\d{1,3}\.\d{4} BTC/); match(rev, /Fees were \d{1,2}\.\d{2}% of what miners were paid\. [\d,]+ transactions were confirmed \(about [\d,]+ a block\), [\d,]+ sats on average in fees each\./, "the fee share and the size of an average fee");
        match(rev, /Next halving at block 1,050,000: [\d,]+ blocks away, about [\d,]+ days \([A-Z][a-z]{2} \d{1,2}, 20\d\d, an estimate\)\. The subsidy then falls to 1\.5625 BTC a block\./, "the halving is dated as an estimate");
        match(rev, /Blocks [\d,]+ to [\d,]+, as of this request\./); match(rev, /the reward minus the fees must equal the subsidy/); match(rev, /not a price signal/i); noMatch(rev, FORECASTS, "the miner revenue makes no forecasts");
        noMatch(rev, /\b20\d\d-\d\d-\d\d\b/, "no raw ISO dates on screen");
        await page.locator(V("network-revenue")).first().evaluate((el) => el.scrollIntoView({ block: "center" })).catch(() => undefined);
        await shot(page, "09p-network-revenue");
      }
      if (await liveCard(page, "stablecoins-body")) match(st, /not a price signal/, "the liquidity-gauge caveat is shown");
      if (await liveCard(page, "positioning-body")) match(pt, /Net short is not the same as bearish/, "the basis-trade caveat is shown");
      await page.waitForSelector(V("experiments-card"));
      await page.waitForSelector(V("experiments-body") + ", " + V("experiments-error"), { timeout: 30000 });
      const ex = await text(page);
      match(ex, /Experiments record/); match(ex, /7 tested, 0 passed the bar/); match(ex, /Bitcoin funding carry/); match(ex, /Bitcoin only while US net liquidity is rising/); match(ex, /Bitcoin only while miners are not capitulating/); match(ex, /Bitcoin only while US stocks are in an uptrend/); match(ex, /Did not pass/); match(ex, /None has passed yet/);
      noMatch(ex, /guaranteed|will make money|buy now/i, "the experiments record makes no promises");
      await page.locator(V("experiments-card")).scrollIntoViewIfNeeded().catch(() => undefined);
      await shot(page, "08x-experiments");
      await page.locator('[data-testid^="experiment-exp"]:visible').last().scrollIntoViewIfNeeded().catch(() => undefined);      // the newest entry, so every new experiment gets looked at too
      await shot(page, "08y-experiments-newest");
      eq((await clickableNames(page)).filter((n) => TRADING_CONTROL.test(n)), [], "trading controls in the sentiment card");
      await page.click(V("back"));
    });

    await check("no uncaught errors in the browser during the whole run", async () => { eq(S.pageErrors, [], "uncaught page errors"); eq(S.consoleErrors, [], "React warnings in the browser console"); });
  } finally {
    await S.ctx.close().catch(() => undefined);
    await be.stop();
  }
}

// ---------------------------------------------------------------------------------------------------------------- scenario 2: old prices
async function stale(browser) {
  const be = await startBackend(["--age", String(7 * 86400)]); // 7 days: stale at any time of week (3-day-old daily bars are the latest session on a Monday morning)
  const S = await phone(browser);
  const page = S.page;
  try {
    await addVia(be, ID.btc); await addVia(be, ID.aapl);
    await connectTo(page, be.url); await ready(page);
    await check("stale prices are flagged on the watchlist, with the count, instead of looking current", async () => {
      await waitRows(page, [ID.btc, ID.aapl]);
      await page.waitForSelector(V("stale-banner"));
      match(await inner(page, "stale-banner"), /2 stale/);
      for (const id of [ID.btc, ID.aapl]) match(await page.locator(T(`row-${id}`)).locator('[role="button"]').first().getAttribute("aria-label"), /Stale/, `row ${id}`);
      await shot(page, "01-watchlist-stale");
    });
    await check("the asset screen says the price is stale, how old it is, and who supplied it", async () => {
      await openFromWatchlist(page, ID.aapl);
      await page.waitForSelector(V("stale-banner"));
      match(await inner(page, "stale-banner"), /7 days ago|168 hours|7d/i, "how old");
      const f = await inner(page, "asset-freshness");
      match(f, /Stale/); match(f, /Yahoo Finance/);
      await shot(page, "02-asset-stale");
    });
    await check("the research is not presented as current: with old prices Technical gives no stance, says so first, and the briefing carries the warning", async () => {
      await waitAgents(page);
      match(await inner(page, "takeaway-technical"), /^Prices are out of date \(latest data \d+d ago\), so no current technical reading is given/);
      assert(!(await present(page, "stance-technical")), "no stance on stale prices");
      match(await inner(page, "briefing-risks"), /stale/i, "the briefing's risks lead with the stale prices");
      noMatch(await inner(page, "briefing-headline"), /Technicals (supportive|cautious|mixed)/, "the headline must not report a technical view");
      match(await expand(page, "technical"), /data as of/i);
    });
  } finally { await S.ctx.close().catch(() => undefined); await be.stop(); }
}

// ---------------------------------------------------------------------------------------------------------------- scenario 3: agents fail
async function partial(browser) {
  const be = await startBackend(["--news", "fail", "--fund", "fail"]);
  const S = await phone(browser);
  const page = S.page;
  try {
    await addVia(be, ID.aapl);
    await connectTo(page, be.url); await ready(page);
    await check("with News, Fundamentals and Macro failing, price, chart and Technical still work and the screen says so", async () => {
      await openFromWatchlist(page, ID.aapl);
      await waitAgents(page);
      assert(!(await present(page, "asset-error")), "the screen must not fail as a whole");
      await page.waitForSelector(T("price-chart"));
      match(await inner(page, "asset-price"), /^\$/);
      const cov = await inner(page, "briefing-coverage");
      match(cov, /Based on 1 of 4 agents/); match(cov, /News/); match(cov, /Macro/); match(cov, /Fundamentals/);
      match(await inner(page, "takeaway-technical"), /trend/i);
      assert(await present(page, "stance-technical"), "Technical still gives its stance");
      for (const a of ["news", "macro", "fundamentals"]) assert(!(await present(page, `stance-${a}`)), `${a} must not claim a stance without data`);
      await shot(page, "01-partial");
    });
    await check("each failed agent explains what is missing and why; refreshing is safe", async () => {
      for (const a of ["news", "fundamentals"]) {
        const t = await expand(page, a);
        match(t, /not available right now/i, a); match(t, /Reason:|Not available/i, a);
        noMatch(t, /Traceback|Exception|undefined|NaN|null/, `${a}: no raw errors`);
      }
      await page.click(T("refresh-news"));
      await page.waitForFunction(() => { const b = document.querySelector('[data-testid="refresh-news"]'); return b && !/Refreshing/.test(b.innerText); }, null, { timeout: 40000 });
      assert(await present(page, "agent-news"), "the row is still there after a refresh");
      assert(!(await present(page, "asset-error")), "the screen still works after a refresh");
      await shot(page, "02-partial-open");
    });
    await check("the Technical agent is unaffected by the other agents' failures (no disagreement is invented)", async () => {
      assert((await page.locator(T("briefing-disagreement")).count()) === 0, "no disagreement with a single agent");
      match(await inner(page, "briefing-supports"), /Technical/);
    });
  } finally { await S.ctx.close().catch(() => undefined); await be.stop(); }
}

// ---------------------------------------------------------------------------------------------------------------- scenario 4: no prices at all
async function missing(browser) {
  const be = await startBackend(["--quote", "fail", "--bars", "fail"]);
  const S = await phone(browser);
  const page = S.page;
  try {
    await addVia(be, ID.aapl); await addVia(be, ID.btc);
    await connectTo(page, be.url); await ready(page);
    await check("rows without a price say Unavailable and the banner counts them; nothing is shown as a price", async () => {
      await waitRows(page, [ID.aapl, ID.btc]);
      await page.waitForSelector(V("stale-banner"));
      match(await inner(page, "stale-banner"), /2 unavailable/);
      for (const id of [ID.aapl, ID.btc]) {
        const row = await page.locator(T(`row-${id}`)).innerText();
        match(row, /Unavailable/, id); noMatch(row, /\$\d/, `${id} must not show a price`);
      }
      await shot(page, "01-missing-watchlist");
    });
    await check("the asset screen says the price and chart are unavailable and still offers what research it can", async () => {
      await openFromWatchlist(page, ID.aapl);
      await page.waitForSelector(V("price-unavailable"));
      await page.waitForSelector(V("chart-error"));
      assert(!(await present(page, "asset-price")), "no price shown");
      assert(await present(page, "retry"), "a retry button for the chart");
      await waitAgents(page);
      const cov = await inner(page, "briefing-coverage");
      match(cov, /Technical/); match(cov, /unavailable/i);
      match(await expand(page, "technical"), /not available right now/i);
      await shot(page, "02-missing-asset");
    });
  } finally { await S.ctx.close().catch(() => undefined); await be.stop(); }
}

// ---------------------------------------------------------------------------------------------------------------- scenario 5: password
async function login(browser) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "signal-e2e-"));
  const db = path.join(dir, "signal.db");
  let be = await startBackend(["--db", db, "--password", "correct horse battery"]);
  const S = await phone(browser);
  const page = S.page;
  try {
    await check("without a login the API refuses every research and watchlist request", async () => {
      for (const p of ["/api/signal/watchlist", "/api/signal/search?q=btc", `/api/signal/research/${ID.btc}`]) eq((await api(be, p)).status, 401, p);
      eq((await api(be, "/api/signal/watchlist", { token: "not-a-real-token" })).status, 401, "a bad token");
    });
    await check("a wrong password is rejected with a readable message and does not enter the app", async () => {
      await connectTo(page, be.url, "wrong password");
      await page.waitForSelector(V("connect-error"));
      match(await inner(page, "connect-error"), /password|incorrect|wrong|invalid/i);
      assert(!(await present(page, "tab-stocks")), "must stay on the connect screen");
    });
    await check("the right password logs in, and the login survives a reload", async () => {
      await page.fill(T("server-password"), "correct horse battery");
      await page.click(T("connect-submit"));
      await page.waitForSelector(T("watchlist-empty"));
      await page.reload(); await ready(page);
      await page.waitForSelector(T("watchlist-empty"));
      const token = await page.evaluate(() => localStorage.getItem("signal.token.v1"));
      assert(token && token.length > 20, "a login token is kept on the device");
      assert(!(await page.evaluate(() => JSON.stringify(localStorage)).then((s) => s.includes("correct horse battery"))), "the password itself is never stored");
      eq((await api(be, "/api/signal/watchlist", { token })).status, 200, "the token works");
    });
    await check("logging out returns to the login screen and forgets the token", async () => {
      await page.click(T("profile-button"));
      await page.click(T("logout"));
      await page.waitForSelector(T("connect-title"));
      assert((await page.evaluate(() => localStorage.getItem("signal.token.v1"))) === null, "token removed");
      await page.reload();
      await page.waitForSelector(T("connect-title"));
    });
    await check("a login the server no longer accepts (password changed) sends the app back to the login screen", async () => {
      await connectTo(page, be.url, "correct horse battery"); await ready(page);
      await be.stop();
      be = await startBackend(["--db", db, "--password", "a different password"], { port: be.port });
      await page.reload();
      await page.waitForSelector(T("connect-title"), { timeout: 30000 });
      assert(!(await present(page, "tab-stocks")), "must not show the app with a rejected login");
    });
  } finally { await S.ctx.close().catch(() => undefined); await be.stop(); }
}

// ---------------------------------------------------------------------------------------------------------------- scenario 6: demo vs live
async function demo(browser) {
  const demoBe = await startBackend(["--demo"]);
  const liveBe = await startBackend([]);
  const S = await phone(browser);
  const page = S.page;
  try {
    await check("a demo server labels every screen as demo, including the data inside each agent", async () => {
      await connectTo(page, demoBe.url); await ready(page);
      await search(page, "bitcoin"); await addFromSearch(page, ID.btc);
      await search(page, "aapl"); await addFromSearch(page, ID.aapl);
      await toStocks(page);
      await waitRows(page, [ID.btc, ID.aapl]);
      await page.waitForSelector(V("demo-banner"));
      await shot(page, "01-demo-watchlist");
      await openFromWatchlist(page, ID.aapl);
      await page.waitForSelector(V("demo-banner"));
      match(await inner(page, "asset-freshness"), /Demo data/);
      await waitAgents(page);
      match(await expand(page, "news"), /\[DEMO\]/, "demo stories are prefixed");
      match(await inner(page, "agent-news"), /DEMO/);
      await shot(page, "02-demo-asset");
      await page.click(T("back"));
      await page.click(T("profile-button")); await page.waitForSelector(T("settings-title"));
      match(await text(page), /Demo mode/);
    });
    await check("BTC Strategy Lab on a demo server: collapsed, runs five strategies, labels the data as synthetic, says what it is not, never offers a trade", async () => {
      await page.goto(WEB_ORIGIN); await ready(page);
      await page.click(V("tab-btc"));
      await page.waitForSelector(V("lab-card"));
      assert(!(await present(page, "lab-run")), "the lab stays collapsed until asked for");
      await page.click(V("lab-toggle"));
      await page.route("**/api/btclab/run", async (route) => { await sleep(1500); await route.continue(); });      // slow it down so the waiting message can be seen
      await page.click(V("lab-run"));
      await page.waitForSelector(V("lab-busy"), { timeout: 5000 });
      match(await inner(page, "lab-busy"), /Running the comparison.*first run on real data downloads/s, "a waiting message explains the first-run download");
      await shot(page, "15a-lab-busy");
      await page.waitForSelector(V("lab-results"), { timeout: 60000 });
      await page.unroute("**/api/btclab/run");
      assert(!(await present(page, "lab-busy")), "the waiting message goes away when results arrive");
      const t = await inner(page, "lab-results");
      match(t, /synthetic/i, "demo prices are labelled synthetic");
      eq(await page.locator('[data-testid^="lab-row-"]:visible').count(), 5, "five strategies by default");
      match(t, /not a forecast|Past results do not predict/i);
      match(t, /(No reliable|Weak|Moderate) evidence/);
      await page.locator('[data-testid^="lab-row-"]:visible').first().click();
      match(await text(page), /Right now \(/, "current rule state is shown");
      match(await text(page), /Too few out-of-sample trades \(\d+; at least 15 are needed\) to run a luck check/, "a rule with too few trades is not given a misleading luck check");
      await shot(page, "15b-lab-results-expanded");
      noMatch(await text(page), FORECASTS, "no forecasts");
      await page.click(V("lab-perp")); await page.click(V("lab-lev-3")); await page.click(V("lab-run"));
      await page.waitForFunction(() => /perp/i.test(document.body.innerText) || /funding/i.test(document.body.innerText), null, { timeout: 60000 });
      eq((await clickableNames(page)).filter((n) => TRADING_CONTROL.test(n)), [], "trading controls in the lab");
      await shot(page, "15-strategy-lab");
      await toStocks(page); await page.click(V("profile-button")); await page.waitForSelector(T("settings-title"));      // leave the app where the next check expects it
    });
    await check("Discover on a demo server: five picks with reasons, risks, evidence and dates, a visible method, save to watchlist, no trade buttons", async () => {
      await page.goto(WEB_ORIGIN); await ready(page);
      await page.click(V("tab-discover"));
      await page.waitForSelector(V("discover-body"), { timeout: 90000 });
      await page.waitForSelector(V("discover-demo"));
      await page.waitForSelector(V("narrative-card"));
      await page.waitForSelector(V("narrative-body") + ", " + V("narrative-none") + ", " + V("narrative-error"), { timeout: 90000 });
      const nt = await text(page);
      match(nt, /Narrative of the day/);
      if (await liveCard(page, "narrative-body")) { match(nt, /Why it is in focus/); match(nt, /Risks to weigh/); match(nt, /Demo data/, "demo narrative is labelled"); match(nt, /Not a recommendation, rating or prediction/i); noMatch(nt, FORECASTS, "narrative makes no forecasts"); }
      const picks = await page.$$eval('[data-testid^="pick-"]:not([data-testid^="pick-more"]):not([data-testid^="pick-save"])', (els) => els.map((e) => e.getAttribute("data-testid")));
      assert(picks.length >= 1 && picks.length <= 5, `between one and five picks (got ${picks.length})`);
      const t = await text(page);
      match(t, /Why it ranks well/); match(t, /Risks to weigh/); match(t, /Not a recommendation, rating or forecast/);
      match(t, /Not included:/); match(t, /Earnings surprises, IPO calendars/);
      noMatch(t, FORECASTS, "no forecasts");
      const sym = picks[0].slice(5);
      await page.click(V(`pick-more-${sym}`));
      match(await text(page), /Score breakdown/); match(await text(page), /as of \d{4}-\d{2}-\d{2}/, "evidence carries dates");
      await page.click(V("discover-how"));
      await page.waitForSelector(V("discover-method"));
      match(await inner(page, "discover-method"), /Growth .* 25%/s, "weights are shown");
      await page.click(V(`pick-save-${sym}`));
      await page.waitForFunction((s2) => /On your watchlist/.test(document.querySelector(`[data-testid="pick-save-${s2}"]`)?.innerText ?? ""), sym, { timeout: 15000 });
      eq((await clickableNames(page)).filter((n) => TRADING_CONTROL.test(n)), [], "trading controls in Discover");
      await shot(page, "16-discover");
      await toStocks(page); await page.click(V("profile-button")); await page.waitForSelector(T("settings-title"));
    });

    await check("switching to a live server drops the demo list and every demo label; nothing carries over", async () => {
      await page.fill(T("server-url"), liveBe.url);
      await page.click(T("connect-submit"));
      await page.waitForFunction((u) => document.querySelector('[data-testid="settings-server"]')?.innerText === u, liveBe.url);
      await page.waitForFunction(() => /Live mode/.test(document.body.innerText), null, { timeout: 20000 });
      noMatch(await text(page), /Demo mode/);
      await page.click(T("settings-close"));
      await page.waitForSelector(T("watchlist-empty"));
      assert(!(await present(page, "demo-banner")), "no demo banner on the live server");
      await search(page, "btc");
      assert(await present(page, `result-${ID.btcEtf}`), "the live directory is in use (the ETF exists only there)");
      noMatch(await text(page), /demo/i);
    });
    await check("a saved copy that belongs to another server is never shown, even when the live server is unreachable", async () => {
      const fake = JSON.stringify({ baseUrl: demoBe.url, savedAt: Date.now(), data: { items: [{ asset: { id: ID.btc, symbol: "BTC", name: "Bitcoin (from the demo server)", type: "crypto", venue: "Coinbase spot (USD)", support: "supported", note: null }, quote: null, spark: null, takeaway: null, error: null }], count: 1, demo: true, as_of: new Date().toISOString() } });
      await S.ctx.addInitScript((v) => { try { localStorage.setItem("signal.watchlist.cache.v2", v); } catch { /* ignore */ } }, fake);
      await liveBe.stop();
      await page.goto(WEB_ORIGIN); await ready(page);
      await page.waitForSelector(V("watchlist-error"), { timeout: 30000 });
      noMatch(await text(page), /from the demo server/);
      assert(!(await present(page, "demo-banner")), "no demo label");
    });
  } finally { await S.ctx.close().catch(() => undefined); await demoBe.stop(); await liveBe.stop(); }
}

// ---------------------------------------------------------------------------------------------------------------- main
// ---------------------------------------------------------------------------------------------------------------- scenario 7: accessibility
// axe-core (free, runs inside the page, no network) with the WCAG 2.x level A and AA rules, plus a rule of our own for tap targets of at least 44 x 44 points (what Apple recommends; WCAG's own minimum is the smaller 24).
// Everything tappable has to be 44 x 44, with no exceptions: the one-line "Source: ..." links that end the cards use `SourceLink` (components/ui.tsx), whose touch target reaches 15 points above and below its text without moving anything.
const AXE_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];
async function a11yProbe(page) {
  if (!(await page.evaluate(() => !!window.axe))) await page.addScriptTag({ path: require.resolve("axe-core") });
  return page.evaluate(async (tags) => {
    // axe's own "label in name" rule (label-content-name-mismatch) glues the text of separate blocks together without spaces ("BTCCryptoBitcoin..."), and react-native-web draws every Text as its own block, so it flags a label that does contain every visible word. It is switched off and replaced by the check below, which compares words.
    const res = await window.axe.run(document, { runOnly: { type: "tag", values: tags }, rules: { "label-content-name-mismatch": { enabled: false } }, resultTypes: ["violations", "incomplete"], elementRef: true });
    const unjudged = res.incomplete.filter((v) => v.id === "color-contrast").reduce((n, v) => n + v.nodes.filter((x) => !(x.element && x.element.closest('[aria-hidden="true"]'))).length, 0);      // text on this screen that axe could not measure (over a gradient or an image): not counted as a pass
    window.axe.utils.getFlattenedTree(document.documentElement);
    const violations = res.violations.map((v) => ({ id: v.id, impact: v.impact, count: v.nodes.length, sample: v.nodes.slice(0, 3).map((n) => ({ target: n.target.join(" ").slice(0, 120), html: n.html.slice(0, 170), why: String((n.any[0] || n.all[0] || n.none[0] || {}).message || "").slice(0, 170), id: n.element ? n.element.getAttribute("data-testid") || "" : "", label: n.element ? String(n.element.getAttribute("aria-label") || "").slice(0, 110) : "", text: n.element ? String(n.element.innerText || "").replace(/\s+/g, " ").slice(0, 110) : "", spoken: (() => { try { return n.element ? String(window.axe.commons.text.accessibleText(n.element)).slice(0, 110) : ""; } catch (e) { return "?"; } })(), seen: (() => { try { return n.element ? String(window.axe.commons.text.visibleVirtual(window.axe.utils.getNodeFromTree(n.element), false, false)).replace(/\s+/g, " ").slice(0, 110) : ""; } catch (e) { return "?" + e.message; } })() })) }));
    const words = (t) => String(t || "").normalize("NFKD").toLowerCase().replace(/[^\p{L}\p{N}]+/gu, " ").trim().split(" ").filter(Boolean);
    const within = (hay, needle) => { for (let i = 0; i + needle.length <= hay.length; i++) if (needle.every((w, j) => hay[i + j] === w)) return true; return false; };
    const unlike = [];                                     // WCAG 2.5.3: the spoken name of a control contains the words it shows, in order
    for (const el of document.querySelectorAll('button, [role="button"], a[href], [role="link"], [role="tab"]')) {
      const label = el.getAttribute("aria-label");
      if (!label || el.closest('[aria-hidden="true"]')) continue;
      const seen = words(el.innerText);
      if (seen.length && !within(words(label), seen)) unlike.push({ target: el.getAttribute("data-testid") || el.tagName, html: el.outerHTML.slice(0, 120), why: "the accessible name does not contain the visible words in order", id: el.getAttribute("data-testid") || "", label: label.slice(0, 110), text: String(el.innerText).replace(/\s+/g, " ").slice(0, 110), spoken: "", seen: "" });
    }
    if (unlike.length) violations.push({ id: "label-in-name", impact: "serious", count: unlike.length, sample: unlike.slice(0, 3) });
    const small = [];
    for (const el of document.querySelectorAll('button, [role="button"], a[href], input, select, textarea, [role="link"], [role="tab"], [role="switch"], [role="checkbox"]')) {
      const r = el.getBoundingClientRect();
      const cs = getComputedStyle(el);
      if (r.width === 0 || r.height === 0 || cs.visibility === "hidden" || cs.display === "none" || el.closest('[aria-hidden="true"]')) continue;      // the tabs you are not on stay mounted and marked aria-hidden
      if (r.width < 44 || r.height < 44) small.push({ name: String(el.getAttribute("aria-label") || el.innerText || el.getAttribute("placeholder") || el.getAttribute("data-testid") || el.tagName).replace(/\s+/g, " ").trim().slice(0, 40), id: el.getAttribute("data-testid") || "", w: Math.round(r.width), h: Math.round(r.height) });
    }
    let sources = 0, sourcesMin = 0;                                       // the one-line "Source: ..." links of the cards on screen: they are measured like everything else, and counted so that a clean result is known to include them
    for (const el of document.querySelectorAll('[role="link"]')) { const r = el.getBoundingClientRect(); if (r.width && r.height && !el.closest('[aria-hidden="true"]') && /^(Source: |Data provided by )/.test(String(el.innerText).trim())) { sources++; sourcesMin = sourcesMin ? Math.min(sourcesMin, Math.round(r.height)) : Math.round(r.height); } }
    return { violations, small, unjudged, sources, sourcesMin };
  }, AXE_TAGS);
}
async function a11y(browser) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "signal-e2e-"));
  const be = await startBackend(["--db", path.join(dir, "signal.db")]);
  const S = await phone(browser);
  const page = S.page;
  try {
    await addVia(be, ID.btc);
    await addVia(be, ID.aapl);
    const settleSourceLinks = async () => {                 // the Macro screen loads about thirty cards from live sources, each with a source link once it has data: wait until the number of links stops growing (three polls of 2 seconds in a row, at most 60 seconds), so that the gate measures them and not an empty screen
      let last = -1, same = 0;
      for (let i = 0; i < 30 && same < 3; i++) {
        await sleep(2000);
        const n = await page.evaluate(() => [...document.querySelectorAll('[role="link"]')].filter((el) => /^(Source: |Data provided by )/.test(String(el.innerText).trim())).length);
        same = n === last ? same + 1 : 0; last = n;
      }
    };
    const probeScreen = async (name, settle = false) => {
      if (settle) await settleSourceLinks();
      await sleep(2500);                                    // let the cards load and the sparklines draw
      await shot(page, `a11y-${name.replace(/[^a-z0-9]+/gi, "-").toLowerCase()}`);
      const r = await a11yProbe(page);
      assert(!/Source: \.(\s|$)/.test(await text(page)), `${name}: a card prints an empty source line ("Source: .")`);      // found 2026-11-17: the new listings card printed it while its feed was still loading
      const kinds = new Map();
      for (const s of r.small) { const k = s.id.replace(/-[A-Z]+:.*$/, "-*").replace(/^(row|toggle)-.*$/, "$1-*") || s.name; kinds.set(k, `${s.w}x${s.h}`); }
      console.log(`    ${name}: ${r.violations.length ? r.violations.map((v) => `${v.id} x${v.count} (${v.impact})`).join(", ") : "no axe violations"}; ${r.small.length} tap targets under 44 x 44${kinds.size ? `: ${[...kinds].map(([k, v]) => `${k} ${v}`).join(", ")}` : ""}; ${r.sources} card source links measured${r.sources ? ` (the smallest ${r.sourcesMin} points high)` : ""}; text axe could not measure: ${r.unjudged}`);
      for (const v of r.violations) for (const s of v.sample.slice(0, 2)) console.log(`      - ${v.id}: ${s.why} | id=${s.id} | label="${s.label}" | text="${s.text}" | ${s.target}`);
      // The gate: no rule may be broken, and every tappable element is 44 x 44.
      assert(r.violations.length === 0, `${name}: ${r.violations.map((v) => `${v.id} x${v.count} (${v.sample.map((x) => x.id || x.target).join(", ")})`).join("; ")}`);
      assert(r.small.length === 0, `${name}: tap targets under 44 x 44: ${r.small.map((x) => `${x.name} (${x.id}) ${x.w}x${x.h}`).join("; ")}`);
      return r;
    };
    await check("accessibility probe: the connect screen", async () => {
      await page.goto(WEB_ORIGIN);
      await page.waitForSelector(T("connect-title"));
      await probeScreen("the connect screen");
    });
    await check("the probe itself notices a bad button, so a clean result means something", async () => {
      await page.evaluate(() => {
        const mk = (css, label, text) => { const b = document.createElement("button"); b.setAttribute("data-bad", "1"); b.style.cssText = `position:fixed;left:0;top:0;z-index:9;${css}`; if (label) b.setAttribute("aria-label", label); if (text) b.textContent = text; document.body.appendChild(b); };
        mk("width:20px;height:20px;", "Save", "Remove");                  // small, and its name does not hold the words it shows
        mk("left:60px;width:60px;height:60px;", "", "");                   // no name at all
        const a = document.createElement("a"); a.setAttribute("data-bad", "1"); a.setAttribute("href", "https://example.org/"); a.style.cssText = "position:fixed;left:140px;top:0;z-index:9;display:block;width:200px;height:15px;"; a.textContent = "Source: Example, via Test"; document.body.appendChild(a);   // a card's source link at its old 15 points: no longer excused
      });
      const r = await a11yProbe(page);
      await page.evaluate(() => document.querySelectorAll("[data-bad]").forEach((e) => e.remove()));
      assert(r.small.some((x) => x.name === "Save" && x.w === 20), "a 20 x 20 button was not reported as too small");
      assert(r.small.some((x) => x.name.startsWith("Source: Example") && x.h === 15), "a 15 point high Source link was not reported as too small");
      assert(r.violations.some((v) => v.id === "label-in-name"), "a button labelled Save that shows Remove was not reported");
      assert(r.violations.some((v) => v.id === "button-name"), "a button with no name was not reported");
    });
    await check("the app connects and has something on the watchlist", async () => {
      await page.fill(T("server-url"), be.url);
      await page.click(T("connect-submit"));
      await ready(page);
      await toStocks(page);
      await waitRows(page, [ID.btc, ID.aapl]);
    });
    // The asset page is opened before any other tab is visited: a tab you have been to stays mounted under the screen on top, and both would carry the same test ids.
    const screens = [
      ["the watchlist", async () => { await toStocks(page); }],
      ["an asset page", async () => { await openFromWatchlist(page, ID.aapl); }],
      ["Settings", async () => { await page.click(V("back")); await page.click(V("profile-button")); await page.waitForSelector(T("settings-title")); }],
      ["BTC", async () => { await page.click(V("settings-close")); await page.click(V("tab-btc")); }],
      ["Journey", async () => { await page.click(V("tab-journey")); }],
      ["Macro", async () => { await page.click(V("tab-macro")); }],
      ["Discover", async () => { await page.click(V("tab-discover")); }],
      ["Journal", async () => { await page.click(V("tab-journal")); }],
      ["search", async () => { await gotoSearch(page); }],
      ["search results", async () => { await search(page, "apple"); await page.waitForSelector(T(`result-${ID.aapl}`)); }],
    ];
    for (const [name, go] of screens) {
      await check(`accessibility probe: ${name}`, async () => {
        await go();
        await probeScreen(name, name === "Macro");
      });
    }
  } finally {
    await S.ctx.close().catch(() => undefined);
    await be.stop();
  }
}

const SCENARIOS = { healthy, a11y, stale, partial, missing, login, demo };
(async () => {
  if (!fs.existsSync(path.join(DIST, "index.html"))) { console.error("dist/ is missing: run `npm run export:web` first"); process.exit(2); }
  const wanted = process.argv.slice(2).length ? process.argv.slice(2) : Object.keys(SCENARIOS);
  for (const w of wanted) if (!SCENARIOS[w]) { console.error(`unknown scenario "${w}" (have: ${Object.keys(SCENARIOS).join(", ")})`); process.exit(2); }
  const web = await startStatic();
  const browser = await chromium.launch();
  try {
    for (const name of wanted) {
      scenarioName = name;
      console.log(`\n${name}`);
      try { await SCENARIOS[name](browser); } catch (e) { results.push({ scenario: name, name: "scenario setup", ok: false, err: e }); console.log(`  ✗ scenario setup\n    ${String(e.message || e).split("\n").join("\n    ")}`); }
    }
  } finally { await browser.close(); web.close(); }
  const failed = results.filter((r) => !r.ok);
  console.log(`\n${results.length - failed.length} of ${results.length} checks passed${failed.length ? `, ${failed.length} failed:` : "."}`);
  for (const f of failed) console.log(`  ✗ [${f.scenario}] ${f.name}`);
  if (SKIPPED.size) console.log(`Not checked this run (the live card was unavailable, so its content checks were skipped): ${[...SKIPPED].join(", ")}.`);
  else if (wanted.includes("healthy")) console.log("Every live card had data this run, so every content check ran.");
  process.exit(failed.length ? 1 : 0);
})();
