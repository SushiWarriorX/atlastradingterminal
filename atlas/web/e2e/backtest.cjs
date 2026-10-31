// Backtester browser test. Needs the DEMO backend on :8000 and `npm run dev` on :5173. Writes a saved run to the demo DB: use a throwaway ATLAS_DB.
const { chromium } = require('playwright');
const fs = require('fs');
const S = process.argv[2] || './e2e-out';
fs.mkdirSync(S, { recursive: true });
(async () => {
  const b = await chromium.launch();
  const pg = await b.newPage({ viewport: { width: 1680, height: 1300 } });
  const errors = [], httpErrors = [];
  pg.on('pageerror', e => errors.push('pageerror: ' + e.message));
  pg.on('console', m => { if (m.type() === 'error' && !/Failed to load resource/.test(m.text())) errors.push('console: ' + m.text()); });
  pg.on('response', r => { if (r.status() >= 400) httpErrors.push(`${r.status()} ${r.request().method()} ${new URL(r.url()).pathname}`); });
  await pg.goto('http://127.0.0.1:5173'); await pg.waitForSelector('.topbar .cell');

  // 1. command opens the backtester with the preset loaded but NOT run
  await pg.keyboard.press('/'); await pg.keyboard.type('BACKTEST BREAKOUT'); await pg.keyboard.press('Enter');
  await pg.waitForSelector('.bt-form', { timeout: 15000 });
  console.log('rules:', (await pg.locator('.rules .note').first().innerText()).slice(0, 140));
  if (await pg.locator('.bt-stats').count()) throw new Error('backtest ran before the user pressed Run');
  if (!/Momentum Breakout/.test(await pg.locator('.rules-h').innerText())) throw new Error('preset not loaded');

  // 2. a target without a stop is rejected up front (client warning) and by the server
  await pg.locator('input[aria-label="stop (ATR×)"]').fill('');
  await pg.locator('input[aria-label="target (R)"]').fill('2');
  await pg.waitForSelector('.note.warn:has-text("target needs a stop")');
  await pg.locator('button', { hasText: 'Run backtest' }).click();
  await pg.waitForSelector('.errbox', { timeout: 10000 });
  console.log('server rejection shown:', (await pg.locator('.errbox').innerText()).replace(/\n/g, ' ').slice(0, 120));
  await pg.locator('input[aria-label="stop (ATR×)"]').fill('2');
  await pg.locator('input[aria-label="symbols"]').fill('20');

  // 3. run it: progress, then results
  await pg.locator('button', { hasText: 'Run backtest' }).click();
  await pg.waitForSelector('.progress', { timeout: 10000 });
  await pg.waitForSelector('.bt-stats', { timeout: 180000 });
  const meta = (await pg.locator('.scanmeta').innerText()).replace(/\n/g, ' | ');
  console.log('meta:', meta);
  if (!/DEMO/.test(meta) || !/nothing about any market|say nothing about any market/.test(meta)) throw new Error('demo results not labelled as synthetic');
  const stats = (await pg.locator('.bt-stat').allInnerTexts()).map(x => x.replace(/\n/g, ' '));
  console.log('stats:', stats.join(' | '));
  const trades = parseInt(stats[0].replace(/\D+/g, ''), 10);
  if (!(trades > 0)) throw new Error('no trades in the demo backtest');
  if ((await pg.locator('.bt-chart canvas').count()) < 1) throw new Error('equity chart did not render');
  const rows = await pg.locator('.bt-trades tbody tr').count();
  console.log('trade rows:', rows, '| split rows:', await pg.locator('.bt-two table').first().locator('tbody tr').count());
  if (rows < 1) throw new Error('trade table empty');
  const split = (await pg.locator('.bt-two table').first().innerText()).replace(/\s+/g, ' ');
  if (!/In-sample/.test(split) || !/Hold-out/.test(split)) throw new Error('in-sample / hold-out table missing');
  await pg.locator('.bt-cav summary').click();
  if (!/survivorship/i.test(await pg.locator('.bt-cav').innerText())) throw new Error('caveats missing');
  await pg.screenshot({ path: S + '/backtest.png' });

  // 4. trade row selects the instrument -> chart title changes
  const sym = await pg.locator('.bt-trades tbody tr').first().locator('td').first().innerText();
  await pg.locator('.bt-trades tbody tr').first().click(); await pg.waitForTimeout(1500);
  console.log('clicked', sym, '-> chart title:', await pg.locator('.panel-t', { hasText: 'CHART' }).first().innerText());

  // 5. the run was saved: survives a reload and reopens without recomputing
  await pg.reload(); await pg.waitForSelector('.topbar'); await pg.keyboard.press('/'); await pg.keyboard.type('BACKTEST'); await pg.keyboard.press('Enter');
  await pg.waitForSelector('.savedchip', { timeout: 15000 });
  const posts = []; pg.on('request', r => { if (r.method() === 'POST') posts.push(new URL(r.url()).pathname); });
  await pg.locator('.savedchip .mini').first().click();
  await pg.waitForSelector('.bt-stats', { timeout: 15000 });
  const again = (await pg.locator('.bt-stat').first().innerText()).replace(/\n/g, ' ');
  console.log('reopened saved run:', again);
  if (posts.includes('/api/backtest/run')) throw new Error('reopening recomputed instead of loading');
  if (parseInt(again.replace(/\D+/g, ''), 10) !== trades) throw new Error('saved run differs from the original');

  // 6. unknown preset is a clean command error
  await pg.keyboard.press('/'); await pg.keyboard.type('BACKTEST NOPE'); await pg.keyboard.press('Enter');
  await pg.waitForSelector('.notice');
  console.log('bad preset:', await pg.locator('.notice').innerText());

  console.log('HTTP errors:', JSON.stringify(httpErrors));
  if (httpErrors.length !== 1 || httpErrors[0] !== '422 POST /api/backtest/run') throw new Error('unexpected HTTP errors (only the deliberate invalid-spec 422 is allowed)');
  console.log('JS errors:', errors.length ? errors.join('\n') : 'none');
  if (errors.length) throw new Error('JS errors');
  await b.close();
})().catch(e => { console.error('E2E FAIL', e.message); process.exit(1); });
