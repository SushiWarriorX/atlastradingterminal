// Treasury panels on the Macro desk, against a NON-demo backend (mobile/e2e/fake_backend.py --port 8000) so the panels show the real layout, and `npm run dev` on :5173.
// Interest on the debt, Treasury buybacks and Treasury bill auctions each show their source, say plainly when they are unavailable or overdue, write dates in words, and make no forecasts.
// Usage: node e2e/treasury.cjs [screenshot-folder]   (the live Treasury source answers from this machine; when it does not, the panels must say so instead of showing numbers)
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const S = process.argv[2] || '';
if (S) fs.mkdirSync(S, { recursive: true });
const fail = (m) => { throw new Error(m); };
const FORECASTS = /\b(will (rise|fall|double)|forecast to|predict(s|ed)|price target|guaranteed|buy now|sell now)\b/i;
const OWN_CAVEAT = /not (a|market) (market )?signals? or (a )?forecasts?/gi;
(async () => {
  const b = await chromium.launch();
  const pg = await b.newPage({ viewport: { width: 1680, height: 1500 } });
  const errors = [];
  pg.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
  pg.on('console', (m) => { if (m.type() === 'error' && !/Failed to load resource/.test(m.text())) errors.push('console: ' + m.text()); });
  await pg.goto('http://127.0.0.1:5173'); await pg.waitForSelector('.topbar .cell');
  await pg.keyboard.press('Control+4');                                                              // Macro desk
  await pg.waitForTimeout(800);
  for (const [id, title, shot] of [['interest', /INTEREST ON THE DEBT/, 'interest'], ['buybacks', /TREASURY BUYBACKS/, 'buybacks'], ['bills', /TREASURY BILL AUCTIONS/, 'bills'], ['borrowing', /TREASURY BORROWING/, 'borrowing']]) {
    const loc = pg.locator(`[data-testid="${id}"]`);
    await loc.waitFor({ timeout: 60000 });
    await loc.scrollIntoViewIfNeeded();
    await pg.waitForTimeout(400);
    const panel = pg.locator('.panel', { has: loc });
    const all = (await panel.innerText()).replace(/\s+/g, ' ');
    if (!title.test(all)) fail(`${id}: panel title missing: ${all.slice(0, 80)}`);
    if (!/US Treasury|Treasury FiscalData/.test(all)) fail(`${id}: the source is not named`);
    const stripped = all.replace(OWN_CAVEAT, '');
    if (FORECASTS.test(stripped)) fail(`${id}: forecast-like wording: ${stripped.match(FORECASTS)[0]}`);
    if (/\b20\d\d-\d\d-\d\d\b/.test(all.replace(/https?:\S+/g, ''))) fail(`${id}: a raw ISO date is on screen`);
    const live = !/could not be read|Demo mode|unavailable/i.test(all);
    if (live) {
      if (!/what already happened|already happened|not (a )?market signals? or (a )?forecasts?/i.test(all)) fail(`${id}: the plain-words caveat is missing`);
      if (id === 'interest' && !(/(January|February|March|April|May|June|July|August|September|October|November|December) 20\d\d/.test(all) && /Treasury bills/.test(all) && /from a year earlier/.test(all))) fail('interest: month in words, bills line and year-ago comparison expected');
      if (id === 'interest' && !/Bars: interest for each of the last \d+ months, oldest on the left, drawn from zero\. Lowest \$[\d.,]+B, highest \$[\d.,]+B, latest \$[\d.,]+B\./.test(all)) fail('interest: the bar strip needs its caption (what the bars are, their order, the baseline and the range)');
      if (id === 'buybacks' && !(/Latest operation/.test(all) && /LAST 90 DAYS/.test(all) && /LAST 12 MONTHS/.test(all) && /RECENT OPERATIONS/.test(all))) fail('buybacks: latest operation, both windows and recent list expected');
      if (id === 'bills' && !(/4-week/.test(all) && /13-week/.test(all) && /26-week/.test(all) && /Bid-to-cover/.test(all))) fail('bills: terms and bid-to-cover expected');
      if (id === 'borrowing' && !(/SO FAR \(through [A-Z][a-z]{2} \d{1,2}, 20\d\d\)/.test(all) && /FISCAL 20\d\d SO FAR/.test(all) && /Net new borrowing/.test(all) && /Treasury bills/.test(all) && /Same point a year earlier/.test(all))) fail('borrowing: month, fiscal year, net borrowing, types and the year-ago comparison expected');
      if (id === 'borrowing' && /DOES NOT MATCH/.test(all)) fail('borrowing: the self-check against the source failed');
    }
    console.log(`${id}: ${live ? 'live data' : 'unavailable, said so'}: ok`);
    if (S) await panel.screenshot({ path: path.join(S, `terminal-${shot}.png`) }).catch(() => undefined);
  }
  if (errors.length) fail('browser errors: ' + errors.slice(0, 3).join(' | '));
  await b.close();
  console.log('TREASURY PANELS OK');
})().catch((e) => { console.error('FAIL: ' + e.message); process.exit(1); });
