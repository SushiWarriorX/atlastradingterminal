// AI desk (specialists + chief) e2e. Needs the backend started by e2e/serve_fake_llm.py (scripted LLM, DEMO data) on :8000 and `npm run dev`.
const { chromium } = require('playwright');
const fs = require('fs');
const S = process.argv[2] || './e2e-out';
fs.mkdirSync(S, { recursive: true });
(async () => {
  const b = await chromium.launch();
  const pg = await b.newPage({ viewport: { width: 1680, height: 1250 } });
  const errors = [], httpErrors = [];
  pg.on('pageerror', e => errors.push('pageerror: ' + e.message));
  pg.on('console', m => { if (m.type() === 'error' && !/Failed to load resource/.test(m.text())) errors.push('console: ' + m.text()); });
  pg.on('response', r => { if (r.status() >= 400) httpErrors.push(`${r.status()} ${r.request().method()} ${new URL(r.url()).pathname}`); });
  await pg.goto('http://127.0.0.1:5173'); await pg.waitForSelector('.topbar .cell');
  const cmd = async t => { await pg.keyboard.press('/'); await pg.keyboard.type(t); await pg.keyboard.press('Enter'); };

  // 1. full desk on an equity: the server computes the conflict between agents and the chief must address it
  await cmd('AAPL'); await pg.waitForTimeout(500); await cmd('AI'); await pg.waitForSelector('.panel.ai .toolbar');
  const desk = pg.locator('button', { hasText: /^Full desk: AAPL$/ });
  await desk.click();
  await pg.waitForSelector('.card:has-text("FULL DESK")', { timeout: 60000 });
  const card = pg.locator('.card:has-text("FULL DESK")');
  const text = (await card.innerText()).replace(/\n/g, ' | ');
  console.log('desk card:', text.slice(0, 420));
  if (!/CAUTIOUS/.test(text)) throw new Error('chief stance missing');
  if (!/Conflicts \(computed in code\)/.test(text) || !/fundamental reads 'adverse' while technical reads 'bullish'/.test(text)) throw new Error('computed conflict not shown');
  if (!/How the chief weighs them/.test(text) || !/Weighing: fundamental reads/.test(text)) throw new Error('chief did not address the conflict');
  for (const n of ['technical', 'fundamental', 'macro', 'risk']) if (!new RegExp(n + ':').test(text)) throw new Error('specialist missing: ' + n);
  if (!/risk: no data/.test(text) || !/PARTIAL/.test(text)) throw new Error('empty portfolio must show risk as no data and the result as PARTIAL');
  if (!/no agent can place or authorise an order/.test(text)) throw new Error('safety footer missing');
  await pg.screenshot({ path: S + '/agents-desk.png' });

  // 2. single specialists: cited numbers are server-resolved values; macro shows the computed reference tilt
  await pg.locator('.toolbar button', { hasText: /^fundamental$/ }).click();
  await pg.waitForSelector('.card:has-text("FUNDAMENTAL")', { timeout: 30000 });
  const f = (await pg.locator('.card:has-text("AAPL · FUNDAMENTAL")').innerText()).replace(/\n/g, ' | ');
  console.log('fundamental:', f.slice(0, 300));
  if (!/pe = \d/.test(f) || !/not written by the model/.test(f)) throw new Error('cited value not shown with provenance');
  await pg.locator('.toolbar button', { hasText: /^macro$/ }).click();
  await pg.waitForSelector('.card:has-text("Reference tilt (computed)")', { timeout: 30000 });
  console.log('macro tilt:', (await pg.locator('.card:has-text("Reference tilt")').locator('.small').first().innerText()).replace(/\n/g, ' ').slice(0, 200));
  await pg.locator('.toolbar button', { hasText: /^risk$/ }).click();
  await pg.waitForSelector('.msg.sys:has-text("risk analysis no_data")', { timeout: 30000 });
  console.log('risk (empty portfolio):', (await pg.locator('.msg.sys:has-text("risk analysis")').first().innerText()).replace(/\n/g, ' ').slice(0, 160));

  // 3. crypto: fundamentals are not applicable (not a failure) and the chief still answers from the rest
  await cmd('BTC'); await pg.waitForTimeout(500); await cmd('AI'); await pg.waitForSelector('.toolbar button');
  await pg.locator('button', { hasText: /^Full desk: BTC/ }).click();
  await pg.waitForSelector('.card:has-text("FULL DESK")', { timeout: 60000 });
  const c2 = (await pg.locator('.card:has-text("FULL DESK")').innerText()).replace(/\n/g, ' | ');
  console.log('BTC desk:', c2.slice(0, 260));
  if (/fundamental: (failed|unavailable)/.test(c2)) throw new Error('fundamentals for crypto should be not-applicable, not a failure');

  console.log('HTTP errors:', JSON.stringify(httpErrors));
  if (httpErrors.length) throw new Error('unexpected HTTP errors');
  console.log('JS errors:', errors.length ? errors.join('\n') : 'none');
  if (errors.length) throw new Error('JS errors');
  await b.close();
})().catch(e => { console.error('E2E FAIL', e.message); process.exit(1); });
