// Fundamentals e2e (DEMO backend on :8000, `npm run dev` on :5173).
const { chromium } = require('playwright');
const fs = require('fs');
const S = process.argv[2] || './e2e-out';
fs.mkdirSync(S, { recursive: true });
(async () => {
  const b = await chromium.launch();
  const pg = await b.newPage({ viewport: { width: 1680, height: 1200 } });
  const errors = [], httpErrors = [];
  pg.on('pageerror', e => errors.push('pageerror: ' + e.message));
  pg.on('console', m => { if (m.type() === 'error' && !/Failed to load resource/.test(m.text())) errors.push('console: ' + m.text()); });
  pg.on('response', r => { if (r.status() >= 400) httpErrors.push(`${r.status()} ${new URL(r.url()).pathname}`); });
  await pg.goto('http://127.0.0.1:5173'); await pg.waitForSelector('.topbar .cell');

  // 1. AAPL FA opens the fundamentals workspace (no "not built" placeholder), labelled as synthetic demo data
  await pg.keyboard.press('/'); await pg.keyboard.type('AAPL FA'); await pg.keyboard.press('Enter');
  await pg.waitForSelector('.fa-grid', { timeout: 15000 });
  if (await pg.locator('.unavail').count()) throw new Error('fundamentals still shows the unbuilt placeholder');
  const head = await pg.locator('.panel.fa .panel-r').innerText();
  console.log('provenance:', head.replace(/\n/g, ' '));
  if (!/DEMO/.test(head)) throw new Error('demo fundamentals not labelled DEMO');
  if (!/Synthetic demo data/.test(await pg.locator('.panel.fa').innerText())) throw new Error('missing synthetic-data warning');

  // 2. the five groups render with computed ratios; every row explains its basis on hover
  const groups = await pg.locator('.fa-group b').allInnerTexts();
  console.log('groups:', groups.join(' | '));
  if (groups.length !== 5) throw new Error('expected 5 groups');
  const pe = pg.locator('.fa-group tr', { hasText: 'P/E (trailing)' });
  console.log('P/E row:', (await pe.innerText()).replace(/\s+/g, ' '), '| basis:', await pe.getAttribute('title'));
  if (!/price \/ trailing EPS/.test(await pe.getAttribute('title'))) throw new Error('row basis tooltip missing');
  if (!/^\d+\.\d\dx$/.test((await pe.locator('td').nth(1).innerText()).trim())) throw new Error('P/E not shown as a ratio');
  await pg.screenshot({ path: S + '/fundamentals.png' });

  // 3. refresh re-fetches without error
  await pg.locator('.panel.fa button', { hasText: 'refresh' }).click(); await pg.waitForTimeout(800);

  // 4. crypto is refused with the reason, not an empty table
  await pg.keyboard.press('/'); await pg.keyboard.type('BTC'); await pg.keyboard.press('Enter'); await pg.waitForTimeout(500);
  await pg.keyboard.press('/'); await pg.keyboard.type('FA'); await pg.keyboard.press('Enter');
  await pg.waitForSelector('.panel.fa .errbox', { timeout: 10000 });
  console.log('crypto:', (await pg.locator('.panel.fa .errbox').innerText()).replace(/\n/g, ' ').slice(0, 120));
  if (!/not available for crypto/.test(await pg.locator('.panel.fa .errbox').innerText())) throw new Error('crypto refusal reason missing');

  console.log('HTTP errors:', JSON.stringify(httpErrors));
  if (httpErrors.length !== 1 || !/^503 \/api\/fundamentals/.test(httpErrors[0])) throw new Error('only the deliberate crypto 503 is allowed');
  console.log('JS errors:', errors.length ? errors.join('\n') : 'none');
  if (errors.length) throw new Error('JS errors');
  await b.close();
})().catch(e => { console.error('E2E FAIL', e.message); process.exit(1); });
