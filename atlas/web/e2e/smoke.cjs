// Browser smoke test. Needs: backend with ATLAS_DEMO=1 on :8000, `npm run dev` on :5173, and playwright installed.
// Mutates the demo DB (adds AMD to the watchlist), so run it against a throwaway ATLAS_DB.
const { chromium } = require('playwright');
const fs = require('fs');
const S = process.argv[2] || './e2e-out';
fs.mkdirSync(S, { recursive: true });
(async () => {
  const b = await chromium.launch();
  const pg = await b.newPage({ viewport: { width: 1680, height: 1000 } });
  const errors = [];
  pg.on('pageerror', e => errors.push('pageerror: ' + e.message));
  pg.on('console', m => { if (m.type() === 'error') errors.push('console: ' + m.text()); });
  await pg.goto('http://127.0.0.1:5173');
  await pg.waitForSelector('.chart-host canvas', { timeout: 15000 });
  await pg.waitForTimeout(2500);
  await pg.screenshot({ path: S + '/01-overview.png' });

  // command bar: symbol + function
  await pg.keyboard.press('/');
  await pg.keyboard.type('NVDA TECH');
  await pg.keyboard.press('Enter');
  await pg.waitForTimeout(1500);
  console.log('after NVDA TECH, title:', await pg.locator('.panel-t').first().innerText());
  // bad command + suggestion
  await pg.keyboard.press('Control+k');
  await pg.keyboard.type('MACROO');
  await pg.keyboard.press('Enter');
  await pg.waitForTimeout(600);
  console.log('notice:', await pg.locator('.notice').innerText());
  // not-built module
  await pg.keyboard.press('Escape');
  await pg.keyboard.press('/');
  await pg.keyboard.type('IDEAS');
  await pg.keyboard.press('Enter');
  await pg.waitForTimeout(800);
  console.log('IDEAS ->', await pg.locator('.notice').innerText(), '|', (await pg.locator('.unavail .big').allInnerTexts()).join(' / '));
  await pg.screenshot({ path: S + '/02-ideas-unbuilt.png' });
  // BTC desk
  await pg.keyboard.press('Control+2');
  await pg.waitForTimeout(2500);
  await pg.screenshot({ path: S + '/03-btc.png' });
  // interval switch + indicator toggle
  await pg.locator('.toolbar .mini', { hasText: /^4h$/ }).first().click();
  await pg.locator('.toolbar .mini', { hasText: 'BB(20,2)' }).first().click();
  await pg.waitForTimeout(1500);
  // AI without key
  await pg.keyboard.press('Control+7');
  await pg.waitForTimeout(1200);
  console.log('AI warning:', await pg.locator('.note.warn').first().innerText());
  // watchlist add + persistence across reload
  await pg.keyboard.press('Control+3');
  await pg.waitForTimeout(1500);
  await pg.fill('input[aria-label="Add symbol to watchlist"]', 'amd');
  await pg.waitForTimeout(600);
  await pg.locator('.dropdown .opt', { hasText: 'AMD' }).first().click();
  await pg.waitForTimeout(800);
  // theme
  await pg.keyboard.press('/'); await pg.keyboard.type('HELP'); await pg.keyboard.press('Enter');
  await pg.waitForTimeout(400);
  await pg.screenshot({ path: S + '/04-help.png' });
  await pg.keyboard.press('Escape');
  await pg.reload();
  await pg.waitForSelector('.chart-host canvas');
  await pg.waitForTimeout(2000);
  const rows = await pg.locator('.panel:has(.panel-t:text-is("WATCHLIST")) table.tbl tbody tr td:first-child b').allInnerTexts();
  console.log('watchlist after reload:', rows.join(','));
  console.log('workspace restored:', await pg.locator('.ws-bar span').first().innerText());
  await pg.screenshot({ path: S + '/05-equities-reload.png' });
  console.log('JS errors:', errors.length ? errors.join('\n') : 'none');
  await b.close();
})().catch(e => { console.error('E2E FAIL', e); process.exit(1); });
