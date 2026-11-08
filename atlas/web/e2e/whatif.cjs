// What-if panel e2e (DEMO backend on :8000, `npm run dev` on :5173): it shows on the Equities and BTC desks, labels demo data, changes with the amount, and offers no trading controls.
const { chromium } = require('playwright');
const fs = require('fs');
const S = process.argv[2] || './e2e-out';
fs.mkdirSync(S, { recursive: true });
(async () => {
  const b = await chromium.launch();
  const pg = await b.newPage({ viewport: { width: 1680, height: 1300 } });
  const errors = [];
  pg.on('pageerror', e => errors.push('pageerror: ' + e.message));
  pg.on('console', m => { if (m.type() === 'error' && !/Failed to load resource/.test(m.text())) errors.push('console: ' + m.text()); });
  await pg.goto('http://127.0.0.1:5173'); await pg.waitForSelector('.topbar .cell');
  const cmd = async t => { await pg.evaluate(() => document.activeElement && document.activeElement.blur()); await pg.keyboard.press('/'); await pg.keyboard.type(t); await pg.keyboard.press('Enter'); await pg.waitForTimeout(600); };
  const titles = async () => (await pg.locator('.panel-t').allInnerTexts()).map(t => t.replace(/\s+/g, ' ').trim());
  const fail = m => { throw new Error(m); };

  await cmd('AAPL');                                     // opens the Equities desk
  let t = await titles();
  if (!t.some(x => /WHAT IF I HAD BOUGHT AAPL/.test(x))) fail('Equities desk has no what-if panel: ' + t.join(' | '));
  const box = pg.locator('[data-testid="whatif"]');
  await box.waitFor({ timeout: 45000 });
  await box.scrollIntoViewIfNeeded();
  const first = await pg.locator('[data-testid="whatif-lump"]').first().innerText();
  const body = await box.innerText();
  for (const re of [/ONE PURCHASE OF \$1,000/, /EVERY MONTH/, /WHICHEVER DAY YOU BOUGHT/, /WITH A RULE FOR GETTING OUT/, /SHUFFLED YEARS/, /Simulation, not a forecast/, /Past results do not predict/, /Demo data/]) {
    if (!re.test(body)) fail('missing in the what-if panel: ' + re);
  }
  await pg.click('[data-testid="whatif-amt-5000"]');
  await pg.waitForFunction(([before]) => { const e = document.querySelector('[data-testid="whatif-lump"]'); return !!e && e.innerText !== before; }, [first], { timeout: 30000 });
  if (!/ONE PURCHASE OF \$5,000/.test(await box.innerText())) fail('the chosen amount is not used');
  const buttons = (await pg.locator('[data-testid="whatif"] button, [data-testid="whatif-controls"] button').allInnerTexts()).join(' | ');
  if (/\b(buy|sell|order|trade)\b/i.test(buttons)) fail('trading control in the what-if panel: ' + buttons);
  await pg.screenshot({ path: S + '/whatif-equities.png' });
  console.log('Equities desk what-if: ok');
  t = await titles();
  if (!t.some(x => /SEC FILINGS AAPL/.test(x))) fail('Equities desk has no SEC filings panel: ' + t.join(' | '));
  const sec = pg.locator('[data-testid="sec-filings"]');
  await sec.waitFor({ timeout: 45000 });
  const secText = await sec.innerText();
  if (!/Demo mode|ATLAS_SEC_CONTACT|open on sec\.gov/.test(secText)) fail('SEC filings panel shows neither filings nor the reason: ' + secText.slice(0, 200));
  await pg.click('[data-testid="filings-group-insiders"]');
  await pg.click('[data-testid="filings-scope-watchlist"]');
  await pg.waitForTimeout(500);
  console.log('Equities desk SEC filings: ok');

  await pg.keyboard.press('Control+2');                  // BTC desk
  await pg.waitForTimeout(800);
  t = await titles();
  if (!t.some(x => /WHAT IF I HAD BOUGHT BTC/.test(x))) fail('BTC desk has no what-if panel: ' + t.join(' | '));
  await pg.locator('[data-testid="whatif"]').waitFor({ timeout: 45000 });
  console.log('BTC desk what-if: ok');
  t = await titles();
  if (!t.some(x => /CRYPTO FEAR & GREED/.test(x))) fail('BTC desk has no Fear & Greed panel: ' + t.join(' | '));
  const fng = await pg.locator('[data-testid="sentiment"]').innerText();
  if (!/alternative\.me/.test(fng) || !/not a forecast/i.test(fng)) fail('Fear & Greed panel lacks its source or its caveat');
  console.log('BTC desk Fear & Greed: ok');

  if (errors.length) fail('browser errors: ' + errors.join(' ; '));
  console.log('PASS');
  await b.close();
})().catch(e => { console.error('FAIL', e.message); process.exit(1); });
