// Fundamental research and discovery e2e (DEMO backend on :8000, `npm run dev` on :5173). The research, listings and candidates responses are served from fixtures that were produced by the real
// backend code from SYNTHETIC companies (backend/tests/make_ui_fixtures.py), so the browser check covers five company types without real filings.
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const FX = path.join(__dirname, 'fixtures');
const SHOTS = process.env.RESEARCH_SHOTS || '';                                          // set to a folder to save screenshots
if (SHOTS) fs.mkdirSync(SHOTS, { recursive: true });
const load = n => JSON.parse(fs.readFileSync(path.join(FX, n), 'utf8'));
const KIND = { AAPL: 'mature', MSFT: 'software', NVDA: 'recent_ipo', TSLA: 'loss_making', AMZN: 'bank' };
const FORBIDDEN = /\b(buy now|sell now|price target|will (rise|fall|double)|guaranteed|strong buy|place order)\b/i;
const DISCLAIMER = /not a forecast, price target or advice/gi;                      // the app's own disclaimer names these things in order to deny them
const advice = s => (s || '').replace(DISCLAIMER, '');
(async () => {
  const b = await chromium.launch();
  const pg = await b.newPage({ viewport: { width: 1680, height: 1400 } });
  const errors = [];
  const writes = [];
  pg.on('pageerror', e => errors.push('pageerror: ' + e.message));
  pg.on('console', m => { if (m.type() === 'error' && !/Failed to load resource/.test(m.text())) errors.push('console: ' + m.text()); });
  const json = (route, data) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, data }) });
  await pg.route('**/api/research/**', route => {
    const u = new URL(route.request().url()); const m = route.request().method();
    if (m !== 'GET') { writes.push(m + ' ' + u.pathname); return json(route, u.pathname.endsWith('/notes') ? { id: 1 } : { snapshot: {} }); }
    const parts = u.pathname.split('/').filter(Boolean);                               // api research SYMBOL [changes]
    if (parts[3] === 'changes') return json(route, { available: true, has_review: false, note: 'You have not marked this company as reviewed yet, so there is nothing to compare with.' });
    const k = KIND[parts[2]] || 'software';
    const d = load(`research_${k}.json`); d.symbol = parts[2];
    return json(route, d);
  });
  await pg.route('**/api/discover/listings**', route => json(route, load('listings.json')));
  await pg.route('**/api/discover/candidates**', route => json(route, load('candidates.json')));
  await pg.route('**/api/discover/state', route => { writes.push('POST /api/discover/state'); return json(route, {}); });
  await pg.goto('http://127.0.0.1:5173'); await pg.waitForSelector('.topbar .cell');
  const cmd = async t => { await pg.evaluate(() => document.activeElement && document.activeElement.blur()); await pg.keyboard.press('/'); await pg.keyboard.type(t); await pg.keyboard.press('Enter'); await pg.waitForTimeout(900); };
  const fail = m => { throw new Error(m); };
  const text = async sel => { const l = pg.locator(sel).first(); await l.waitFor({ timeout: 30000 }); await l.scrollIntoViewIfNeeded(); return (await l.innerText()).replace(/\s+/g, ' '); };

  // ---- Discover desk: new listings and new-to-me come first ----
  await pg.keyboard.press('Control+5');
  await pg.waitForTimeout(800);
  const titles = async () => (await pg.locator('.panel-t').allInnerTexts()).map(t => t.replace(/\s+/g, ' ').trim());
  let t = await titles();
  if (!/NEW LISTINGS/.test(t[0] || '') || !/NEW TO ME/.test(t[1] || '')) fail('Discover desk should start with NEW LISTINGS then NEW TO ME: ' + t.slice(0, 3).join(' | '));
  const ls = await text('[data-testid="new-listings"]');
  if (!/UPCOMING LISTINGS/.test(ls) || !/RECENT LISTINGS/.test(ls)) fail('upcoming and recent listings are not separated');
  if (!/No new listings are reported for today/.test(ls)) fail('a quiet day must say so');
  if (!/RZRA/.test(ls) || !/not trading yet/i.test(ls)) fail('an upcoming deal must say it is not trading yet');
  if (!/confirmed trading/.test(ls) || !/NARA/.test(ls) || !/SEC check/.test(ls)) fail('a confirmed and SEC-checked debut must be marked');
  if (!/priced, not yet confirmed/.test(ls)) fail('a priced deal without independent confirmation must say so');
  if (!/IPOs only/.test(ls) || !/Direct listings/.test(ls)) fail('the coverage limit must be stated');
  if (!/SPAC IPO/.test(ls) || !/blank-check company/.test(ls) || !/no revenue to research/.test(ls)) fail('a blank-check company must be labelled as a SPAC with no revenue to research');
  if ((await pg.locator('[data-testid="listing-BHAIU"] button').count()) !== 0) fail('a SPAC IPO must not offer a revenue research button');
  if ((await pg.locator('[data-testid="listing-BBTX"] button').count()) !== 1) fail('an operating company IPO should offer a research button');
  if (SHOTS) await pg.locator('[data-testid="new-listings"]').screenshot({ path: path.join(SHOTS, 'listings.png') });
  console.log('Discover desk new listings: ok');
  const nm = await text('[data-testid="new-to-me"]');
  if (!/Showing 3 of a target of 5/.test(nm) || !/fewer are shown when evidence is weak/.test(nm)) fail('the candidate list must say it shows fewer when evidence is weak');
  for (const s of ['CLDX', 'DATA', 'MATU']) if (!(await pg.locator(`[data-testid="cand-${s}"]`).count())) fail('missing candidate ' + s);
  const card = await text('[data-testid="cand-CLDX"]');
  for (const re of [/Why it surfaced/, /Main opportunity/, /Main risk/, /Rule of 40/, /Valuation under stated assumptions/, /evidence:/, /filings to/, /Research this company/, /Classification/]) if (!re.test(card)) fail('candidate card lacks ' + re);
  if (FORBIDDEN.test(advice(nm + ls))) fail('discovery text contains advice or prediction language');
  if (SHOTS) await pg.locator('[data-testid="cand-CLDX"]').screenshot({ path: path.join(SHOTS, 'candidate.png') });
  console.log('Discover desk new to me: ok');
  await pg.locator('[data-testid="cand-research-MATU"]').click();                     // opens the Equities desk on that company
  await pg.waitForTimeout(800);
  if (!writes.some(w => w === 'POST /api/discover/state')) fail('opening a candidate should be recorded');

  // ---- research page for five company types ----
  const check = async (sym, kind, asserts) => {
    await cmd(sym);
    const r = await text('[data-testid="fundamental-research"]');
    await asserts(r);
    if (FORBIDDEN.test(advice(r))) fail(`${kind}: research text contains advice or prediction language: ` + (advice(r).match(FORBIDDEN) || [])[0]);
    if (SHOTS) await pg.locator('[data-testid="fundamental-research"]').screenshot({ path: path.join(SHOTS, `research-${sym}.png`) });
    console.log(`research page ${kind}: ok`);
  };
  await check('MSFT', 'software company', r => {
    for (const re of [/Trailing twelve months to 2025-12-31/, /FIVE FISCAL YEARS/, /EIGHT QUARTERS/, /reported \(three-month figure\)/, /derived: 12-month total minus 9-month total/, /Rule of 40 \(FCF basis\)/, /= 43\.0 points/, /reaches 40/,
      /Separate measure, not the default/, /Within estimated fair-value range/, /bear/, /base/, /bull/, /What the price implies/, /What needs to be true/, /What evidence would disprove it/, /What should I research next/, /Not in structured SEC data/i])
      if (!re.test(r)) fail('software page lacks ' + re);
  });
  await check('AAPL', 'mature company', r => {
    if (!/Not applicable/.test(r) || !/software/.test(r)) fail('a mature company must show the Rule of 40 as not applicable');
    if (!/Potentially undervalued under these assumptions/.test(r)) fail('mature company should show its valuation label');
    if (!/FIVE FISCAL YEARS/.test(r) || !/n\/a/.test(r)) fail('first year growth must be n/a');
  });
  await check('NVDA', 'recent listing', async r => {
    if (!/Insufficient evidence/.test(r) || !/Missing, not guessed/.test(r) || !/four consecutive quarters/.test(r)) fail('a recent listing must say what is missing');
    if (!/N\/A/.test(r) || !/eight consecutive quarters/.test(r)) fail('Rule of 40 must be N/A with the reason');
    if (!/post-listing|short filing history/.test(r)) fail('the share-count caution for new listings must show');
    if (!(await pg.locator('[data-testid="fr-annual-empty"]').count())) fail('an empty fiscal-year table must say that no full year has been filed');
    if (!(await pg.locator('[data-testid="fr-warning"]').count())) fail('the share-count warning must be visible, not buried');
    if ((r.match(/short filing history/g) || []).length !== 1) fail('the share-count warning should appear once, not repeated');
    if (/-\d+ days ago/.test(r)) fail('a negative age must never be shown');
  });
  await check('TSLA', 'loss-making company', r => {
    if (!/below 40/.test(r) || !/30\.0 points/.test(r)) fail('loss-making company should show a Rule of 40 below 40');
    if (!/Insufficient evidence/.test(r) || !/not positive/.test(r)) fail('no DCF verdict without positive free cash flow');
    if (!/not meaningful/.test(r)) fail('earnings multiples must be marked not meaningful');
  });
  await check('AMZN', 'sector-specific company', r => {
    if (!/bank/.test(r) || !/net interest margin/.test(r)) fail('a bank must be pointed to sector-specific measures');
    if (!/Not applicable/.test(r) || !/Insufficient evidence/.test(r)) fail('a bank gets no company-style Rule of 40 or verdict');
  });

  // ---- my notes and review on the software company ----
  await cmd('MSFT');
  await pg.locator('textarea[aria-label="Research note"]').fill('Check segment margins in the 10-K.');
  await pg.locator('[data-testid="fr-note-add"]').click();
  await pg.locator('[data-testid="fr-review"]').click();
  await pg.locator('[data-testid="fr-save"]').click();
  await pg.waitForTimeout(500);
  for (const w of ['POST /api/research/MSFT/notes', 'POST /api/research/MSFT/review', 'POST /api/discover/state'])
    if (!writes.includes(w)) fail('expected request not sent: ' + w + ' (sent: ' + writes.join(', ') + ')');
  console.log('notes, review and save: ok');

  const bad = await pg.locator('button').evaluateAll(bs => bs.map(x => (x.innerText || '').trim()).filter(x => /\b(buy|sell|place order|submit order)\b/i.test(x)));
  if (bad.length) fail('trading controls found: ' + bad.join(', '));
  if (errors.length) fail('browser errors: ' + errors.join(' | '));
  console.log('PASS');
  await b.close();
})().catch(e => { console.error('FAIL', e.message); process.exit(1); });
