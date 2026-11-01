// Desk rules e2e (DEMO backend on :8000, `npm run dev` on :5173): BTC desk is BTC only, Equities desk is stocks/ETFs only, Charts lets each chart change asset.
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
  pg.on('response', r => { if (r.status() >= 400) httpErrors.push(`${r.status()} ${new URL(r.url()).pathname}`); });
  await pg.goto('http://127.0.0.1:5173'); await pg.waitForSelector('.topbar .cell');
  const cmd = async t => { await pg.evaluate(() => document.activeElement && document.activeElement.blur()); await pg.keyboard.press('/'); await pg.keyboard.type(t); await pg.keyboard.press('Enter'); await pg.waitForTimeout(700); };
  const titles = async () => (await pg.locator('.panel-t').allInnerTexts()).map(t => t.replace(/\s+/g, ' ').trim());
  const nav = async () => (await pg.locator('.side .nav > span:first-child').allInnerTexts()).map(t => t.trim());

  // 1. sidebar: Markets and Fundamentals are gone; Ctrl+2 still opens the BTC desk
  const items = await nav();
  console.log('nav:', items.join(' | '));
  if (items.some(x => /MARKETS|FUNDAMENTALS/.test(x))) throw new Error('removed sections still in the sidebar');
  if (items[0] !== 'OVERVIEW' || items[1] !== 'BTC INTELLIGENCE' || items[2] !== 'EQUITIES' || items[3] !== 'CHARTS') throw new Error('unexpected nav order');
  await pg.keyboard.press('Control+2'); await pg.waitForTimeout(800);
  if (!(await titles()).some(t => /CHART BTC-USD/.test(t))) throw new Error('Ctrl+2 did not open the BTC desk');

  // 2. BTC desk: every panel is Bitcoin, nothing offers to change the asset, and picking a stock elsewhere does not change it
  let t = await titles();
  console.log('BTC desk panels:', t.join(' | '));
  if (await pg.locator('input[aria-label="Chart symbol"]').count()) throw new Error('BTC desk must not offer a symbol box');
  for (const p of t.filter(x => /^(CHART|TECHNICAL|MULTI-TIMEFRAME|QUOTE)/.test(x))) if (!/BTC/.test(p)) throw new Error('non-BTC panel on the BTC desk: ' + p);
  await cmd('AAPL');                                         // routes to the Equities desk
  if (!(await titles()).some(x => /CHART AAPL/.test(x))) throw new Error('AAPL should open on the Equities desk');
  await pg.locator('.side .nav', { hasText: 'BTC INTELLIGENCE' }).click(); await pg.waitForTimeout(800);
  t = await titles();
  if (t.some(x => /AAPL/.test(x))) throw new Error('BTC desk changed to AAPL: ' + t.join(' | '));
  if (!t.some(x => /CHART BTC-USD/.test(x))) throw new Error('BTC desk lost its BTC chart');
  console.log('BTC desk stays BTC after selecting AAPL: ok');

  // 3. Equities desk: stocks/ETFs only (watchlist filtered, picker refuses BTC), remembers the last stock
  await pg.locator('.side .nav', { hasText: 'EQUITIES' }).click(); await pg.waitForTimeout(800);
  const rows = (await pg.locator('.panel:has(.panel-t:text("WATCHLIST")) tbody tr td:first-child b').allInnerTexts());
  console.log('equities watchlist:', rows.join(','));
  if (rows.some(r => /BTC|SPX|NDX|VIX|US10Y/.test(r)) || !rows.length) throw new Error('equities watchlist must hold stocks/ETFs only');
  await cmd('BTC');                                           // BTC desk; then back to equities: must still be AAPL, never BTC
  await pg.locator('.side .nav', { hasText: 'EQUITIES' }).click(); await pg.waitForTimeout(800);
  if (!(await titles()).some(x => /CHART AAPL/.test(x))) throw new Error('equities desk should remember AAPL, not follow BTC');
  const box = pg.locator('input[aria-label="Chart symbol"]').first();
  await box.fill('NVDA'); await box.press('Enter'); await pg.waitForTimeout(900);
  if (!(await titles()).some(x => /CHART NVDA/.test(x))) throw new Error('equities chart picker did not switch to NVDA');
  await box.fill('BITCOIN'); await box.press('Enter');
  await pg.waitForSelector('text=No stock or ETF matches', { timeout: 5000 });
  if (!(await titles()).some(x => /CHART NVDA/.test(x))) throw new Error('equities chart must refuse a crypto symbol');
  console.log('equities picker accepts NVDA and refuses BTC: ok');
  await pg.screenshot({ path: S + '/desk-equities.png' });

  // 4. indices are not stocks: SPX opens on Charts, not Equities
  await cmd('SPX');
  await pg.waitForSelector('.panel-t:text("CHART SPX")', { timeout: 10000 });
  if ((await pg.locator('.ws-bar span').first().innerText()) !== 'Multi-chart') throw new Error('SPX should open the Charts desk');

  // 5. Charts: each chart changes asset independently, survives a reload, and can return to following the selection
  const boxes = pg.locator('input[aria-label="Chart symbol"]');
  if ((await boxes.count()) !== 4) throw new Error('expected a symbol box on each of the 4 charts');
  await boxes.nth(0).fill('SPY'); await boxes.nth(0).press('Enter'); await pg.waitForSelector('.panel-t:text("CHART SPY 1d")', { timeout: 10000 });
  await boxes.nth(1).fill('NVDA'); await boxes.nth(1).press('Enter'); await pg.waitForSelector('.panel-t:text("CHART NVDA 1h")', { timeout: 10000 });
  t = await titles();
  console.log('charts:', t.filter(x => /^CHART/.test(x)).join(' | '));
  if (!t.some(x => /CHART SPY 1d/.test(x)) || !t.some(x => /CHART NVDA 1h/.test(x)) || !t.some(x => /CHART SPX 15m/.test(x))) throw new Error('charts did not change independently');
  await pg.screenshot({ path: S + '/desk-charts.png' });
  await pg.reload(); await pg.waitForSelector('.topbar .cell'); await pg.waitForSelector('.panel-t:text("CHART SPY 1d")', { timeout: 10000 });
  t = await titles();
  if (!t.some(x => /CHART SPY 1d/.test(x)) || !t.some(x => /CHART NVDA 1h/.test(x))) throw new Error('chart assets were not remembered after reload');
  await pg.locator('button', { hasText: 'follow selection' }).first().click(); await pg.waitForSelector('.panel-t:text("CHART SPX 1d")', { timeout: 10000 });
  if (!(await titles()).some(x => /CHART SPX 1d/.test(x))) throw new Error('"follow selection" did not return the chart to the selected instrument');

  console.log('HTTP errors:', JSON.stringify(httpErrors));
  if (httpErrors.length) throw new Error('unexpected HTTP errors');
  console.log('JS errors:', errors.length ? errors.join('\n') : 'none');
  if (errors.length) throw new Error('JS errors');
  await b.close();
})().catch(e => { console.error('E2E FAIL', e.message); process.exit(1); });
