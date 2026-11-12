// Compare overlay + multi-timeframe e2e. Needs the DEMO backend on :8000 and `npm run dev` on :5173.
const { chromium } = require('playwright');
const fs = require('fs');
const S = process.argv[2] || './e2e-out';
fs.mkdirSync(S, { recursive: true });
(async () => {
  const b = await chromium.launch();
  const pg = await b.newPage({ viewport: { width: 1680, height: 1250 } });
  const errors = [], httpErrors = [];
  pg.on('pageerror', e => errors.push(e.message));
  pg.on('console', m => { if (m.type() === 'error' && !/Failed to load resource/.test(m.text())) errors.push(m.text()); });
  pg.on('response', r => { if (r.status() >= 400) httpErrors.push(`${r.status()} ${new URL(r.url()).pathname}`); });
  await pg.goto('http://127.0.0.1:5173');
  await pg.waitForSelector('.topbar .cell');

  // 1. COMPARE command -> overlay with calendar-aligned stats
  await pg.keyboard.press('/'); await pg.keyboard.type('COMPARE BTC QQQ'); await pg.keyboard.press('Enter');
  await pg.waitForSelector('.cmpstats table', { timeout: 15000 });
  const note = await pg.locator('.cmpstats .note').first().innerText();
  console.log('aligned note:', note);
  if (!/aligned bars/.test(note)) throw new Error('aligned-bar disclosure missing');
  const head = await pg.locator('.cmpstats thead').innerText();
  if (!/ρ 20/.test(head) || !/ρ 180/.test(head) || !/ρ60 range/.test(head)) throw new Error('correlation windows missing');
  const row = (await pg.locator('.cmpstats tbody tr').first().innerText()).replace(/\s+/g, ' ');
  console.log('stats row:', row);
  const legend = await pg.locator('.legend').allInnerTexts();
  console.log('legend:', legend.join(' | '));
  if (legend.length !== 2) throw new Error('expected 2 legend entries');
  if ((await pg.locator('.compare canvas').count()) < 1) throw new Error('compare chart did not render');
  console.log('chart title:', await pg.locator('.panel-t', { hasText: 'CHART' }).first().innerText());
  await pg.screenshot({ path: S + '/compare.png' });

  // 2. add a third series from the toolbar, then remove one
  await pg.locator('.toolbar .mini', { hasText: /^Indicators/ }).first().click();             // the compare box sits behind the Indicators button
  await pg.locator('input[aria-label="Compare symbol"]').first().fill('SPY');
  await pg.keyboard.press('Enter');
  await pg.waitForFunction(() => document.querySelectorAll('.legend').length === 3, null, { timeout: 10000 });
  console.log('third series added: legend', (await pg.locator('.legend').count()));
  await pg.locator('button', { hasText: /^SPY ✕$/ }).first().click();
  await pg.waitForFunction(() => document.querySelectorAll('.legend').length === 2, null, { timeout: 10000 });
  await pg.locator('button', { hasText: /^QQQ ✕$/ }).first().click();
  await pg.waitForFunction(() => document.querySelectorAll('.compare').length === 0, null, { timeout: 10000 });
  console.log('compare cleared: normal chart restored');

  // 3. multi-timeframe for an equity: 5 rows, verdict, numeric score, SPY benchmark used
  await pg.keyboard.press('/'); await pg.keyboard.type('NVDA MTF'); await pg.keyboard.press('Enter');
  await pg.waitForSelector('.mtf-top', { timeout: 20000 });
  await pg.waitForSelector('.scorenum');
  const tfRows = await pg.locator('.panel:has(.mtf-top) table').first().locator('tbody tr').count();
  const verdict = (await pg.locator('.verdict').innerText()).replace(/\n/g, ' - ');
  const score = parseFloat(await pg.locator('.scorenum').innerText());
  console.log('mtf rows:', tfRows, '| verdict:', verdict, '| score:', score);
  if (tfRows !== 5) throw new Error('expected 5 timeframes');
  if (!(score >= 0 && score <= 100)) throw new Error('score out of range');
  const rsRow = (await pg.locator('tr', { hasText: 'Relative strength' }).first().innerText()).replace(/\s+/g, ' ');
  console.log('relative strength row (auto benchmark):', rsRow);
  if (/excluded/.test(rsRow)) throw new Error('RS should be available for an equity with the SPY auto-benchmark');
  // benchmark -> none: factor excluded, weights renormalised (the "Used" column of the others sums to 1)
  await pg.locator('select[aria-label="Benchmark"]').selectOption('none');
  await pg.waitForFunction(() => /excluded/.test([...document.querySelectorAll('tr')].find(r => /Relative strength/.test(r.textContent))?.textContent || ''), null, { timeout: 20000 });
  const used = await pg.locator('.panel:has(.mtf-top) table').nth(1).locator('tbody tr').evaluateAll(rows =>
    rows.map(r => parseFloat(r.children[3].textContent)).filter(x => !Number.isNaN(x)));
  const sum = used.reduce((a, c) => a + c, 0);
  console.log('effective weights without benchmark:', used.join(', '), '= sum', sum.toFixed(2));
  if (Math.abs(sum - 1) > 0.02) throw new Error('weights not renormalised to 1');
  await pg.screenshot({ path: S + '/mtf.png' });

  // 4. BTC: no automatic benchmark
  await pg.keyboard.press('/'); await pg.keyboard.type('BTC MTF'); await pg.keyboard.press('Enter');
  await pg.waitForSelector('.mtf-top', { timeout: 20000 });
  await pg.waitForTimeout(1500);
  const btcRs = (await pg.locator('tr', { hasText: 'Relative strength' }).first().innerText()).replace(/\s+/g, ' ');
  console.log('BTC relative strength (no auto benchmark):', btcRs);
  if (!/excluded/.test(btcRs)) throw new Error('BTC should have no automatic benchmark');

  console.log('HTTP errors:', JSON.stringify(httpErrors));
  if (httpErrors.length) throw new Error('unexpected HTTP errors');
  console.log('JS errors:', errors.length ? errors.join('\n') : 'none');
  if (errors.length) throw new Error('JS errors');
  await b.close();
})().catch(e => { console.error('E2E FAIL', e.message); process.exit(1); });
