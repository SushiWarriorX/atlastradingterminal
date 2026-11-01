// BTC derivatives e2e on DEMO data (backend with ATLAS_DEMO=1 on :8000, `npm run dev` on :5173).
const { chromium } = require('playwright');
const fs = require('fs');
const S = process.argv[2] || './e2e-out';
fs.mkdirSync(S, { recursive: true });
(async () => {
  const b = await chromium.launch();
  const pg = await b.newPage({ viewport: { width: 1680, height: 1500 } });
  const errors = [], httpErrors = [];
  pg.on('pageerror', e => errors.push('pageerror: ' + e.message));
  pg.on('console', m => { if (m.type() === 'error' && !/Failed to load resource/.test(m.text())) errors.push('console: ' + m.text()); });
  pg.on('response', r => { if (r.status() >= 400) httpErrors.push(`${r.status()} ${new URL(r.url()).pathname}`); });
  await pg.goto('http://127.0.0.1:5173'); await pg.waitForSelector('.topbar .cell');

  // BTC OI opens the BTC desk (no "needs a provider" placeholder) with the derivatives panel
  await pg.keyboard.press('/'); await pg.keyboard.type('BTC OI'); await pg.keyboard.press('Enter');
  await pg.waitForSelector('.panel.deriv table tbody tr', { timeout: 20000 });
  if (await pg.locator('.unavail').count()) throw new Error('derivatives still shows the unbuilt placeholder');
  const rows = await pg.locator('.panel.deriv tbody tr').allInnerTexts();
  console.log('rows:', rows.length, '|', rows.map(r => r.split('\t')[0].trim()).join(' / '));
  if (rows.length !== 5) throw new Error('expected 4 venues plus the aggregate row');
  for (const name of ['Hyperliquid', 'Binance', 'Bybit', 'OKX', 'All answering venues']) if (!rows.some(r => r.includes(name))) throw new Error('missing row: ' + name);
  const text = await pg.locator('.panel.deriv').innerText();
  if (!/DEMO/.test(text) || !/Synthetic demo data/.test(text)) throw new Error('demo data not labelled');
  if (!/Liquidations, ETF flows and on-chain data are not included \(no reliable free source\)/.test(text)) throw new Error('unavailable data not disclosed');
  if (!/not enough history yet/.test(text)) throw new Error('missing-history state not shown');
  const hl = (await pg.locator('.panel.deriv tbody tr', { hasText: 'Hyperliquid' }).innerText()).replace(/\s+/g, ' ');
  console.log('Hyperliquid row:', hl);
  if (!/%/.test(hl) || !/DEMO/.test(hl)) throw new Error('row incomplete');
  await pg.locator('.panel.deriv button', { hasText: 'refresh now' }).click(); await pg.waitForTimeout(800);
  await pg.screenshot({ path: S + '/derivatives.png', fullPage: true });
  console.log('HTTP errors:', JSON.stringify(httpErrors));
  if (httpErrors.length) throw new Error('unexpected HTTP errors');
  console.log('JS errors:', errors.length ? errors.join('\n') : 'none');
  if (errors.length) throw new Error('JS errors');
  await b.close();
})().catch(e => { console.error('E2E FAIL', e.message); process.exit(1); });
