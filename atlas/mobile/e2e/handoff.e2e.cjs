#!/usr/bin/env node
"use strict";
/*
 * "Ask ChatGPT" handoff on a PHONE-sized screen: the real exported app talking to the real backend (e2e/fake_backend.py --research software: real routes and brief builder, SYNTHETIC company data).
 *   npm run export:web && node e2e/handoff.e2e.cjs          (SIGNAL_E2E_PYTHON=/path/to/python if the backend is installed elsewhere; HANDOFF_SHOTS=<dir> saves screenshots)
 */
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const http = require("node:http");
const net = require("node:net");
const path = require("node:path");
const { chromium } = require("playwright");

const ROOT = path.resolve(__dirname, "..");
const DIST = path.join(ROOT, "dist");
const PY = process.env.SIGNAL_E2E_PYTHON || "python3";
const SHOTS = process.env.HANDOFF_SHOTS || "";
if (SHOTS) fs.mkdirSync(SHOTS, { recursive: true });
const T = (id) => `[data-testid="${id}"]`;
const INTRO_START = "I am researching this company. The following context is exported from my stock research app and may contain stale data or errors.";
const DEFAULT_Q = "What should I investigate next about this company's revenue quality, financial health, and valuation? What evidence would strengthen or weaken the investment thesis?";
const COPIED = "Context copied. Paste it into ChatGPT and ask your question.";
const NOTE = "PRIVATE-NOTE-4417";
const fail = (m) => { throw new Error(m); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const freePort = () => new Promise((ok, no) => { const s = net.createServer(); s.on("error", no); s.listen(0, "127.0.0.1", () => { const p = s.address().port; s.close(() => ok(p)); }); });
const TYPES = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".png": "image/png", ".ico": "image/x-icon", ".ttf": "font/ttf", ".svg": "image/svg+xml" };

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
  return { srv, origin: `http://localhost:${port}` };
}
async function startBackend(origin) {
  const port = await freePort();
  const proc = spawn(PY, [path.join(__dirname, "fake_backend.py"), "--port", String(port), "--research", "software"], { env: { ...process.env, ATLAS_CORS_ORIGINS: origin, PYTHONUNBUFFERED: "1" }, stdio: ["ignore", "pipe", "pipe"] });
  let log = ""; proc.stdout.on("data", (d) => (log += d)); proc.stderr.on("data", (d) => (log += d));
  const url = `http://localhost:${port}`;
  for (let i = 0; i < 200; i++) {
    if (proc.exitCode !== null) fail("the scripted backend exited:\n" + log.slice(-1200));
    try { if ((await fetch(`${url}/api/auth/status`)).ok) return { url, proc }; } catch { /* not up yet */ }
    await sleep(300);
  }
  fail("the scripted backend did not start:\n" + log.slice(-1200));
}
const post = async (url, p, body) => (await (await fetch(url + p, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) })).json());

async function phonePage(browser, origin, url, { clipboard = "ok", popup = "ok" } = {}) {
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true, locale: "en-US", timezoneId: "UTC", acceptDownloads: true,
    permissions: clipboard === "ok" ? ["clipboard-read", "clipboard-write"] : [] });
  await ctx.addInitScript(({ clipboard, popup }) => {
    window.__opened = [];
    window.open = (u, t) => { window.__opened.push([String(u), String(t)]); return popup === "blocked" ? null : { opener: "page" }; };
    if (clipboard === "denied") {
      Object.defineProperty(navigator, "clipboard", { value: { writeText: () => Promise.reject(new Error("denied")), readText: () => Promise.reject(new Error("denied")) }, configurable: true });
      document.execCommand = () => false;
    }
  }, { clipboard, popup });
  const page = await ctx.newPage();
  page.setDefaultTimeout(25000);
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e).slice(0, 300)));
  page.on("console", (m) => { if (m.type() === "error" && /React does not recognize|Warning:|Invalid DOM property|unique "key"|validateDOMNesting/.test(m.text())) errors.push(m.text().slice(0, 300)); });
  await page.goto(origin);
  await page.waitForSelector(T("server-url"));
  await page.fill(T("server-url"), url);
  await page.click(T("connect-submit"));
  await page.waitForSelector(T("tab-stocks"));
  await page.locator(T("row-EQUITY:NASDAQ:AAPL")).locator('[role="button"]').first().click();
  await page.waitForSelector(T("asset-name"));
  await page.locator(`${T("fr-toggle")}:visible`).first().click();
  await page.waitForSelector(`${T("fr-body")}:visible`, { timeout: 40000 });
  return { ctx, page, errors };
}
const vis = (page, id) => `${T(id)}:visible`;
async function openPanel(page, where = "research") {
  const btn = page.locator(`${T(`ask-${where}`)}:visible ${T("ask-chatgpt-button")}`).first();
  await btn.scrollIntoViewIfNeeded(); await btn.click();
  await page.waitForSelector(vis(page, "ask-preview"));
  await page.waitForFunction(() => { const e = [...document.querySelectorAll('[data-testid="ask-preview"]')].find((x) => x.offsetParent); return e && e.value.length > 200; });
}
const preview = async (page) => { await page.waitForFunction(() => !document.querySelector('[data-testid="ask-updating"]')); return page.locator(vis(page, "ask-preview")).inputValue(); };
const status = (page) => page.locator(vis(page, "ask-status")).innerText();

(async () => {
  const browser = await chromium.launch();
  const { srv, origin } = await startStatic();
  const be = await startBackend(origin);
  try {
    await post(be.url, "/api/signal/watchlist", { id: "EQUITY:NASDAQ:AAPL" });
    let { ctx, page, errors } = await phonePage(browser, origin, be.url);
    await openPanel(page);
    const panel = (await page.locator(vis(page, "ask-panel")).innerText()).replace(/\s+/g, " ");
    for (const re of [/What would you like to research\?/, /Concise brief/, /Detailed brief/, /Include my private notes/, /Include my holdings \(shares and buy price\)/, /Copy context & open ChatGPT/, /Copy context only/, /Download context as Markdown/,
      /This handoff makes no AI API calls from this app\. ChatGPT usage is subject to your own account's plan and limits\./, /Preview of the context that will be copied/, /private notes not included/, /holdings not included/]) if (!re.test(panel)) fail("panel lacks " + re);
    const t0 = await preview(page);
    const server = (await post(be.url, "/api/research/AAPL/brief", { detail: "concise", include_notes: false, include_position: false })).data;
    if (t0 !== server.markdown) fail("the preview must be exactly the brief the server built");
    if (!t0.startsWith(INTRO_START) || !t0.endsWith(DEFAULT_Q)) fail("the brief must start with the required opening and end with the default question");
    if (!t0.includes("(AAPL): research brief") || !t0.includes("https://www.sec.gov/Archives/edgar/data/")) fail("company name and source links are missing");
    console.log("  ✓ phone panel and exact brief");

    // mobile usability: nothing wider than the screen, tap targets tall enough, the brief readable and selectable
    const layout = await page.evaluate(() => {
      const w = window.innerWidth;
      const els = [...document.querySelectorAll('[data-testid="ask-panel"] [role="button"], [data-testid="ask-panel"] [role="link"], [data-testid="ask-panel"] textarea, [data-testid="ask-panel"] input')].filter((e) => e.offsetParent);
      return { overflow: document.documentElement.scrollWidth - w, small: els.filter((e) => e.getBoundingClientRect().height < 40).map((e) => (e.getAttribute("data-testid") || e.getAttribute("aria-label") || e.tagName) + ":" + Math.round(e.getBoundingClientRect().height)),
        outside: els.filter((e) => { const r = e.getBoundingClientRect(); return r.left < -1 || r.right > w + 1; }).map((e) => e.getAttribute("data-testid") || e.tagName), count: els.length };
    });
    if (layout.overflow > 1) fail("the page scrolls sideways by " + layout.overflow + "px");
    if (layout.outside.length) fail("controls outside the screen: " + layout.outside.join(", "));
    if (layout.small.length) fail("tap targets under 40px: " + layout.small.join(", "));
    if (layout.count < 8) fail("expected the panel's controls, found " + layout.count);
    if (SHOTS) { await page.locator(vis(page, "ask-panel")).screenshot({ path: path.join(SHOTS, "phone-panel.png") }); await page.screenshot({ path: path.join(SHOTS, "phone-screen.png") }); }
    console.log("  ✓ phone layout: no sideways scroll, controls on screen, tap targets 40px or more");

    // valuation view button
    if (!(await page.locator(`${T("ask-valuation")}:visible ${T("ask-chatgpt-button")}`).count())) fail("the valuation view needs an Ask ChatGPT button");
    console.log("  ✓ valuation button");

    // privacy defaults and toggles
    await post(be.url, "/api/research/AAPL/notes", { body: NOTE });
    await ctx.close();
    ({ ctx, page, errors } = await phonePage(browser, origin, be.url));                       // a fresh page, so the stored note is part of the research
    await openPanel(page);
    if ((await preview(page)).includes(NOTE)) fail("a private note must not be in the default brief");
    await page.locator(vis(page, "ask-include-notes")).click();
    await page.waitForFunction((n) => [...document.querySelectorAll('[data-testid="ask-preview"]')].some((e) => e.offsetParent && e.value.includes(n)), NOTE);
    if (!(await preview(page)).endsWith(DEFAULT_Q)) fail("the question must stay last");
    await page.locator(vis(page, "ask-include-notes")).click();
    await page.waitForFunction((n) => [...document.querySelectorAll('[data-testid="ask-preview"]')].every((e) => !e.offsetParent || !e.value.includes(n)), NOTE);
    await page.locator(vis(page, "ask-include-position")).click();
    await page.fill(vis(page, "ask-shares"), "100"); await page.fill(vis(page, "ask-buy"), "30");
    await page.waitForFunction(() => [...document.querySelectorAll('[data-testid="ask-preview"]')].some((e) => e.offsetParent && e.value.includes("My position (included at my request)")));
    if (!/Shares: 100 · buy price: \$30\.00/.test(await preview(page))) fail("position lines are wrong");
    await page.locator(vis(page, "ask-include-position")).click();
    await page.waitForFunction(() => [...document.querySelectorAll('[data-testid="ask-preview"]')].every((e) => !e.offsetParent || !e.value.includes("My position")));
    console.log("  ✓ privacy defaults and toggles");

    // question
    await page.fill(vis(page, "ask-question"), "How durable is the recurring revenue? Reach me at me@example.com");
    await page.waitForFunction(() => [...document.querySelectorAll('[data-testid="ask-preview"]')].some((e) => e.offsetParent && e.value.includes("How durable")));
    const q = await preview(page);
    if (!/## My question\nHow durable is the recurring revenue\? Reach me at \[email removed\]$/.test(q)) fail("the question must end the brief with secrets removed: " + q.slice(-120));
    await page.fill(vis(page, "ask-question"), "");
    await page.waitForFunction(() => [...document.querySelectorAll('[data-testid="ask-preview"]')].some((e) => e.offsetParent && e.value.endsWith("investment thesis?")));
    console.log("  ✓ question and default question");

    // clipboard success, open ChatGPT, download
    const want = await preview(page);
    await page.locator(vis(page, "ask-copy")).click();
    await page.waitForSelector(vis(page, "ask-status"));
    if ((await status(page)) !== COPIED) fail("copy-only status wrong: " + (await status(page)));
    if ((await page.evaluate(() => navigator.clipboard.readText())) !== want) fail("the clipboard must hold exactly the preview");
    await page.evaluate(() => navigator.clipboard.writeText("overwritten"));
    await page.locator(vis(page, "ask-copy-open")).click();
    await page.waitForFunction(() => window.__opened.length >= 1);
    const opened = await page.evaluate(() => window.__opened);
    if (opened[0][0] !== "https://chatgpt.com/" || opened[0][1] !== "_blank" || new URL(opened[0][0]).search) fail("ChatGPT must open with the plain address: " + JSON.stringify(opened));
    await page.waitForFunction(() => [...document.querySelectorAll('[data-testid="ask-status"]')].some((e) => e.offsetParent && e.innerText.startsWith("Context copied")));
    if ((await page.evaluate(() => navigator.clipboard.readText())) !== want) fail("copy & open must put the brief on the clipboard");
    const [dl] = await Promise.all([page.waitForEvent("download"), page.locator(vis(page, "ask-download")).click()]);
    if (!/^AAPL-research-brief-\d{8}\.md$/.test(dl.suggestedFilename())) fail("download name: " + dl.suggestedFilename());
    if (fs.readFileSync(await dl.path(), "utf8") !== want) fail("the downloaded Markdown must equal the preview");
    console.log("  ✓ clipboard, open ChatGPT with a plain address, download");
    if (errors.length) fail("browser errors: " + errors.join(" | "));
    await ctx.close();

    // clipboard refused: never says copied, the text is selected for a manual copy
    ({ ctx, page, errors } = await phonePage(browser, origin, be.url, { clipboard: "denied" }));
    await openPanel(page);
    await page.locator(vis(page, "ask-copy")).click();
    await page.waitForSelector(vis(page, "ask-status"));
    let st = await status(page);
    if (/Context copied/.test(st) || !/Could not copy automatically/.test(st)) fail("a failed copy must not say copied: " + st);
    const sel = await page.evaluate(() => { const e = [...document.querySelectorAll('[data-testid="ask-preview"]')].find((x) => x.offsetParent); return [document.activeElement === e, e.selectionStart, e.selectionEnd, e.value.length]; });
    if (!sel[0] || sel[1] !== 0 || sel[2] !== sel[3]) fail("the whole context should be selected for manual copy: " + sel);
    console.log("  ✓ clipboard refused: warning, text selected for a manual copy");
    if (SHOTS) await page.screenshot({ path: path.join(SHOTS, "phone-clipboard-refused.png") });
    await ctx.close();

    // blocked new tab
    ({ ctx, page, errors } = await phonePage(browser, origin, be.url, { popup: "blocked" }));
    await openPanel(page);
    await page.locator(vis(page, "ask-copy-open")).click();
    await page.waitForSelector(vis(page, "ask-blocked"));
    st = await status(page);
    if (!/^Context copied\./.test(st) || !/blocked the new tab/.test(st)) fail("blocked tab notice wrong: " + st);
    if (!(await page.locator(vis(page, "ask-open-link")).isVisible())) fail("a visible Open ChatGPT link must remain");
    console.log("  ✓ blocked new tab: copied, notice shown, link stays visible");
    await ctx.close();
    console.log("\nALL ASK-CHATGPT PHONE CHECKS PASSED");
  } catch (e) {
    console.error("\nFAIL", e.message);
    process.exitCode = 1;
  } finally {
    await browser.close(); srv.close(); be.proc.kill("SIGTERM");
  }
})();
