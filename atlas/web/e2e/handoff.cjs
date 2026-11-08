// "Ask ChatGPT" handoff e2e. Needs: the scripted backend with SYNTHETIC research on :8000
//   python3 ../mobile/e2e/fake_backend.py --port 8000 --demo --research software        and `npm run dev` on :5173.
// The brief comes from the REAL /api/research/{symbol}/brief route and the real privacy toggles; only the company data is synthetic.
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const API = 'http://127.0.0.1:8000';
const APP = 'http://127.0.0.1:5173';
const INTRO_START = 'I am researching this company. The following context is exported from my stock research app and may contain stale data or errors.';
const DEFAULT_Q = "What should I investigate next about this company's revenue quality, financial health, and valuation? What evidence would strengthen or weaken the investment thesis?";
const COPIED = 'Context copied. Paste it into ChatGPT and ask your question.';
const SECRET_NOTE = 'PRIVATE-NOTE-7731';
const fail = m => { throw new Error(m); };
const SHOTS = process.env.HANDOFF_SHOTS || '';
if (SHOTS) fs.mkdirSync(SHOTS, { recursive: true });

async function page(b, { clipboard = 'ok', popup = 'ok' } = {}) {
  const ctx = await b.newContext({ viewport: { width: 1680, height: 1400 }, permissions: clipboard === 'ok' ? ['clipboard-read', 'clipboard-write'] : [], acceptDownloads: true });
  await ctx.addInitScript(({ clipboard, popup }) => {
    window.__opened = [];
    const real = window.open.bind(window);
    window.open = (u, t) => { window.__opened.push([String(u), String(t)]); return popup === 'blocked' ? null : { opener: 'page' }; };
    if (clipboard === 'denied') {                                                       // a browser that refuses every copy
      Object.defineProperty(navigator, 'clipboard', { value: { writeText: () => Promise.reject(new Error('denied')), readText: () => Promise.reject(new Error('denied')) }, configurable: true });
      document.execCommand = () => false;
    }
    window.__realOpen = real;
  }, { clipboard, popup });
  const pg = await ctx.newPage();
  pg.__errors = []; pg.__requests = [];
  pg.on('pageerror', e => pg.__errors.push('pageerror: ' + e.message));
  pg.on('console', m => { if (m.type() === 'error' && !/Failed to load resource/.test(m.text())) pg.__errors.push('console: ' + m.text()); });
  pg.on('request', r => pg.__requests.push(r.method() + ' ' + r.url()));
  await pg.goto(APP); await pg.waitForSelector('.topbar .cell');
  return { ctx, pg };
}
const cmd = async (pg, t) => { await pg.evaluate(() => document.activeElement && document.activeElement.blur()); await pg.keyboard.press('/'); await pg.keyboard.type(t); await pg.keyboard.press('Enter'); await pg.waitForTimeout(900); };
const openPanel = async (pg, where = 'research') => {
  await cmd(pg, 'MSFT');
  await pg.locator('[data-testid="fundamental-research"]').waitFor({ timeout: 30000 });
  const btn = pg.locator(`[data-testid="ask-${where}"] [data-testid="ask-chatgpt-button"]`);
  await btn.scrollIntoViewIfNeeded(); await btn.click();
  await pg.locator('[data-testid="ask-preview"]').waitFor({ timeout: 20000 });
  await pg.waitForFunction(() => document.querySelector('[data-testid="ask-preview"]').value.length > 200);
};
const settled = pg => pg.waitForFunction(() => !document.querySelector('[data-testid="ask-updating"]') && document.querySelector('[data-testid="ask-copy"]') && !document.querySelector('[data-testid="ask-copy"]').disabled);
const preview = async pg => { await settled(pg); return pg.locator('[data-testid="ask-preview"]').inputValue(); };
const apiBrief = async body => (await (await fetch(API + '/api/research/MSFT/brief', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) })).json()).data;

(async () => {
  const b = await chromium.launch();
  try {
    // ---- the panel, its wording and its defaults
    let { ctx, pg } = await page(b);
    await openPanel(pg);
    const panel = (await pg.locator('[data-testid="ask-panel"]').innerText()).replace(/\s+/g, ' ');
    for (const re of [/What would you like to research\?/, /Concise brief/, /Detailed brief/, /Include my private notes/, /Include my holdings \(shares and buy price\)/, /Copy context & open ChatGPT/, /Copy context only/, /Download context as Markdown/,
      /This handoff makes no AI API calls from this app\. ChatGPT usage is subject to your own account's plan and limits\./, /Preview of the context that will be copied/, /private notes not included/, /holdings not included/]) if (!re.test(panel)) fail('panel lacks ' + re);
    const t0 = await preview(pg);
    const server = await apiBrief({ detail: 'concise', include_notes: false, include_position: false });
    if (t0 !== server.markdown) fail('the preview must be exactly the brief the server built');
    if (!t0.startsWith(INTRO_START) || !t0.endsWith(DEFAULT_Q)) fail('the brief must start with the required opening and end with the default question');
    for (const need of ['Cloud Software Inc', 'Trailing twelve months to 2025-12-31', '= 43.0 points', 'Within estimated fair-value range', '[REPORTED]', '[CALCULATED', '[ESTIMATE]', 'https://www.sec.gov/Archives/edgar/data/', 'Original sources', 'Missing information and unresolved questions'])
      if (!t0.includes(need)) fail('brief lacks ' + need);
    if (/@|sk-[A-Za-z0-9]{16}|api[_-]?key|Bearer /i.test(t0)) fail('the brief must not contain emails, keys or tokens');
    console.log('panel, wording and exact brief: ok');
    if (SHOTS) await pg.locator('[data-testid="ask-panel"]').screenshot({ path: path.join(SHOTS, 'panel.png') });

    // ---- the valuation view has its own button
    if (!(await pg.locator('[data-testid="ask-valuation"] [data-testid="ask-chatgpt-button"]').count())) fail('the valuation view needs an Ask ChatGPT button');
    console.log('valuation button: ok');

    // ---- privacy defaults and explicit toggles
    await fetch(API + '/api/research/MSFT/notes', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ body: SECRET_NOTE }) });
    await pg.reload(); await pg.waitForSelector('.topbar .cell'); await openPanel(pg);
    if ((await preview(pg)).includes(SECRET_NOTE)) fail('a private note must not be in the default brief');
    await pg.locator('[data-testid="ask-include-notes"]').check();
    await pg.waitForFunction(n => document.querySelector('[data-testid="ask-preview"]').value.includes(n), SECRET_NOTE);
    let t = await preview(pg);
    if (!/My private notes \(included at my request\)/.test(t) || !/private notes INCLUDED/.test(await pg.locator('[data-testid="ask-meta"]').innerText())) fail('notes must be labelled when included');
    if (!t.endsWith(DEFAULT_Q)) fail('the question must still come last');
    await pg.locator('[data-testid="ask-include-notes"]').uncheck();
    await pg.waitForFunction(n => !document.querySelector('[data-testid="ask-preview"]').value.includes(n), SECRET_NOTE);
    await pg.locator('[data-testid="ask-include-position"]').check();
    await pg.locator('[data-testid="ask-shares"]').fill('100'); await pg.locator('[data-testid="ask-buy"]').fill('30');
    await pg.waitForFunction(() => document.querySelector('[data-testid="ask-preview"]').value.includes('My position (included at my request)'));
    t = await preview(pg);
    if (!/Shares: 100 · buy price: \$30\.00/.test(t) || !/unrealised \+\$1\.0K \(\+33\.3%\)/.test(t)) fail('position lines are wrong: ' + (t.match(/## My position[\s\S]{0,300}/) || [''])[0]);
    await pg.locator('[data-testid="ask-include-position"]').uncheck();
    await pg.waitForFunction(() => !document.querySelector('[data-testid="ask-preview"]').value.includes('My position'));
    console.log('privacy defaults and toggles: ok');

    // ---- question, concise versus detailed
    await pg.locator('[data-testid="ask-question"]').fill('How durable is the recurring revenue? My email is me@example.com');
    await pg.waitForFunction(() => document.querySelector('[data-testid="ask-preview"]').value.includes('How durable'));
    t = await preview(pg);
    if (t.includes(DEFAULT_Q) || !/## My question\nHow durable is the recurring revenue\? My email is \[email removed\]$/.test(t)) fail('the question must end the brief with secrets removed: ' + t.slice(-160));
    if (!/removed/.test(await pg.locator('[data-testid="ask-meta"]').innerText())) fail('the meta line should say that items were removed');
    const concise = t.length;
    await pg.locator('[data-testid="ask-detailed"]').check();
    await pg.waitForFunction(n => document.querySelector('[data-testid="ask-preview"]').value.length > n, concise);
    if (!/Sensitivity:/.test(await preview(pg))) fail('the detailed brief should add the sensitivity lines');
    console.log('question and detail levels: ok');

    // ---- clipboard success and the browser handoff
    await pg.locator('[data-testid="ask-question"]').fill('');
    await pg.locator('[data-testid="ask-concise"]').check();
    await pg.waitForFunction(() => document.querySelector('[data-testid="ask-preview"]').value.endsWith("investment thesis?"));
    const want = await preview(pg);
    await pg.locator('[data-testid="ask-copy"]').click();
    await pg.waitForFunction(() => document.querySelector('[data-testid="ask-status"]'));
    let st = await pg.locator('[data-testid="ask-status"]').innerText();
    if (st !== COPIED) fail('copy-only status should be the required message, got: ' + st);
    if ((await pg.evaluate(() => navigator.clipboard.readText())) !== want) fail('the clipboard must hold exactly the preview');
    if ((await pg.evaluate(() => window.__opened)).length) fail('copy-only must not open anything');
    await pg.evaluate(() => navigator.clipboard.writeText('overwritten'));
    await pg.locator('[data-testid="ask-copy-open"]').click();
    await pg.waitForFunction(() => window.__opened.length === 1);
    const opened = await pg.evaluate(() => window.__opened);
    if (opened[0][0] !== 'https://chatgpt.com/' || opened[0][1] !== '_blank') fail('ChatGPT must be opened with the plain address in a new tab: ' + JSON.stringify(opened));
    if (new URL(opened[0][0]).search || new URL(opened[0][0]).hash) fail('no context may be placed in the address');
    await pg.waitForFunction(() => document.querySelector('[data-testid="ask-status"]').innerText.startsWith('Context copied'));
    if ((await pg.locator('[data-testid="ask-status"]').innerText()) !== COPIED) fail('copy & open status wrong');
    if ((await pg.evaluate(() => navigator.clipboard.readText())) !== want) fail('copy & open must put the brief on the clipboard');
    if (await pg.locator('[data-testid="ask-blocked"]').count()) fail('no blocked-tab notice when the tab opened');
    const link = pg.locator('[data-testid="ask-open-link"]');
    if ((await link.getAttribute('href')) !== 'https://chatgpt.com/' || (await link.getAttribute('target')) !== '_blank' || !/noopener/.test(await link.getAttribute('rel'))) fail('the visible Open ChatGPT link is wrong');
    console.log('clipboard success and open ChatGPT: ok');

    // ---- download
    const [dl] = await Promise.all([pg.waitForEvent('download'), pg.locator('[data-testid="ask-download"]').click()]);
    if (!/^MSFT-research-brief-\d{8}\.md$/.test(dl.suggestedFilename())) fail('download name: ' + dl.suggestedFilename());
    const saved = fs.readFileSync(await dl.path(), 'utf8');
    if (saved !== want) fail('the downloaded Markdown must equal the preview');
    console.log('download: ok');

    // ---- nothing is sent to OpenAI or ChatGPT; only this app's own brief route is used
    const outside = pg.__requests.filter(r => { try { return /(^|\.)(openai|chatgpt)\.com$/i.test(new URL(r.split(' ')[1]).hostname); } catch { return false; } });      // by host name, not by file name
    if (outside.length) fail('the app must make no request to OpenAI or ChatGPT: ' + outside.join(', '));
    if (!pg.__requests.some(r => /POST .*\/api\/research\/MSFT\/brief/.test(r))) fail('the brief should come from the local route');
    if (pg.__errors.length) fail('browser errors: ' + pg.__errors.join(' | '));
    await ctx.close();

    // ---- a browser that refuses the clipboard: nothing says "Copied", the text is selected for manual copy
    ({ ctx, pg } = await page(b, { clipboard: 'denied' }));
    await openPanel(pg);
    await pg.locator('[data-testid="ask-copy"]').click();
    await pg.waitForFunction(() => document.querySelector('[data-testid="ask-status"]'));
    st = await pg.locator('[data-testid="ask-status"]').innerText();
    if (/Context copied/.test(st) || !/Could not copy automatically/.test(st)) fail('a failed copy must not say copied: ' + st);
    if ((await pg.locator('[data-testid="ask-status"]').getAttribute('data-kind')) !== 'warn') fail('a failed copy is a warning');
    const sel = await pg.evaluate(() => { const e = document.querySelector('[data-testid="ask-preview"]'); return [document.activeElement === e, e.selectionStart, e.selectionEnd, e.value.length]; });
    if (!sel[0] || sel[1] !== 0 || sel[2] !== sel[3]) fail('the whole context should be selected for manual copy: ' + sel);
    await pg.locator('[data-testid="ask-copy-open"]').click();
    await pg.waitForFunction(() => window.__opened.length === 1);
    st = await pg.locator('[data-testid="ask-status"]').innerText();
    if (/Context copied/.test(st) || !/Could not copy automatically/.test(st)) fail('copy & open with a refused clipboard must say so: ' + st);
    console.log('clipboard refused: ok');
    if (SHOTS) await pg.locator('[data-testid="ask-panel"]').screenshot({ path: path.join(SHOTS, 'clipboard-refused.png') });
    await ctx.close();

    // ---- a browser that blocks the new tab
    ({ ctx, pg } = await page(b, { popup: 'blocked' }));
    await openPanel(pg);
    await pg.locator('[data-testid="ask-copy-open"]').click();
    await pg.locator('[data-testid="ask-blocked"]').waitFor();
    st = await pg.locator('[data-testid="ask-status"]').innerText();
    if (!/^Context copied\./.test(st) || !/blocked the new tab/.test(st)) fail('blocked tab: the copy still succeeded, and the notice must say the tab was blocked: ' + st);
    if (!(await pg.locator('[data-testid="ask-open-link"]').isVisible())) fail('a visible Open ChatGPT link must remain');
    console.log('popup blocked: ok');
    await ctx.close();
    console.log('PASS');
  } finally { await b.close(); }
})().catch(e => { console.error('FAIL', e.message); process.exit(1); });
