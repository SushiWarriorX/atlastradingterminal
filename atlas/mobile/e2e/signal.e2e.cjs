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

    await check("connects and shows an honest empty watchlist under five tabs and a profile icon", async () => {
      await page.fill(T("server-url"), be.url);
      await page.click(T("connect-submit"));
      await page.waitForSelector(T("tab-stocks"));
      await toStocks(page);
      await page.waitForSelector(T("watchlist-empty"));
      const tabs = await page.$$eval('[data-testid^="tab-"]', (els) => els.map((e) => e.innerText.replace(/[^A-Za-z]+/g, "")));
      eq(tabs, ["BTC", "Stocks", "Macro", "Discover", "Journal"], "the only tabs");
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
        for (const d of ["btc", "stocks", "macro", "discover", "journal"]) assert(await present(w, `nav-${d}`), `top navigation must offer ${d}`);
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

    await check("Macro: what matters today, indicators and headlines are labelled, gaps are listed, and a missing FRED key is said plainly", async () => {
      await page.click(T("tab-macro"));
      await page.waitForSelector(V("macro-brief"));
      const t = await text(page);
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
      const points = (await page.$$eval("div", (els) => els.map((e) => e.innerText || "").filter((x) => x.startsWith("•")))).join(" ");
      noMatch(points, FORECASTS, "bull and bear points make no forecasts");       // (headlines are quoted third-party text and are checked separately)
      eq((await clickableNames(page)).filter((n) => TRADING_CONTROL.test(n)), [], "trading controls in the deep-dive");
      await shot(page, "14-stock-deep-dive");
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
  const be = await startBackend(["--age", String(3 * 86400)]);
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
      match(await inner(page, "stale-banner"), /3 days ago|72 hours|3d/i, "how old");
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
      if (await present(page, "narrative-body")) { match(nt, /Why it is in focus/); match(nt, /Risks to weigh/); match(nt, /Demo data/, "demo narrative is labelled"); match(nt, /Not a recommendation, rating or prediction/i); noMatch(nt, FORECASTS, "narrative makes no forecasts"); }
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
const SCENARIOS = { healthy, stale, partial, missing, login, demo };
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
  process.exit(failed.length ? 1 : 0);
})();
