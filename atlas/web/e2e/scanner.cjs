// Scanner browser test. Needs the demo backend on :8000 and `npm run dev` on :5173 (see smoke.cjs).
// Mutates the demo DB (saves a scan), so run it against a throwaway ATLAS_DB.
const { chromium } = require('playwright');
const fs = require('fs');
const S = process.argv[2] || './e2e-out';
fs.mkdirSync(S, { recursive: true });
(async () => {
  const b = await chromium.launch();
  const pg = await b.newPage({ viewport: { width: 1680, height: 1100 } });
  const errors = [];
  pg.on('pageerror', e => errors.push('pageerror: ' + e.message));
  pg.on('console', m => { if (m.type() === 'error') errors.push('console: ' + m.text()); });
  await pg.goto('http://127.0.0.1:5173');
  await pg.waitForSelector('.topbar');
  // 1. command bar -> preset runs and renders a results table with metadata
  await pg.keyboard.press('/'); await pg.keyboard.type('SCAN RVOL'); await pg.keyboard.press('Enter');
  await pg.waitForSelector('.scanmeta', { timeout: 30000 });
  const meta = await pg.locator('.scanmeta').innerText();
  console.log('meta:', meta.replace(/\n/g, ' | '));
  console.log('rows:', await pg.locator('.results tbody tr').count());
  if (!/DEMO/.test(meta)) throw new Error('results not labelled DEMO');
  // 2. sorting
  await pg.locator('.results th', { hasText: 'RVOL' }).click();
  console.log('top RVOL after sort:', await pg.locator('.results tbody tr').first().locator('td').nth(3).innerText());
  // 3. row click selects the instrument -> chart title changes
  const sym = await pg.locator('.results tbody tr').first().locator('td').first().innerText();
  await pg.locator('.results tbody tr').first().click();
  await pg.waitForTimeout(1500);
  console.log('clicked', sym, '-> chart title:', await pg.locator('.panel-t', { hasText: 'CHART' }).first().innerText());
  // 4. natural language -> visible, editable rules, unsupported parts reported
  await pg.fill('input[aria-label="Describe a scan in plain English"]', 'profitable technology stocks above their 50-day moving average with relative volume above 2');
  await pg.locator('button', { hasText: 'Interpret' }).click();
  await pg.waitForSelector('.frow');
  console.log('rules:', await pg.locator('.frow').count(), '| warning:', await pg.locator('.note.warn').first().innerText());
  await pg.locator('.frow .fval[value="2"]').fill('1'); // edit the RVOL >= 2 rule (bool rules have no text input), then run it
  await pg.locator('button', { hasText: /^Run$/ }).click();
  await pg.waitForTimeout(3000);
  console.log('custom scan matches:', await pg.locator('.scanmeta b').first().innerText());
  // 5. save + persistence across reload
  pg.once('dialog', d => d.accept('E2E scan'));
  await pg.locator('button', { hasText: /^Save$/ }).click();
  await pg.waitForTimeout(800);
  await pg.reload(); await pg.waitForSelector('.topbar'); await pg.waitForTimeout(1500);
  const chips = await pg.locator('.savedchip').allInnerTexts();
  console.log('saved after reload:', chips);
  if (!chips.some(c => c.includes('E2E scan'))) throw new Error('saved scan not shown after reload');
  await pg.locator('.savedchip .mini').first().click(); await pg.waitForSelector('.scanmeta', { timeout: 20000 });
  console.log('re-run saved scan matches:', await pg.locator('.scanmeta b').first().innerText());
  await pg.screenshot({ path: S + '/scanner.png' });
  console.log('JS errors:', errors.length ? errors.join('\n') : 'none');
  await b.close();
})().catch(e => { console.error('E2E FAIL', e.message); process.exit(1); });
