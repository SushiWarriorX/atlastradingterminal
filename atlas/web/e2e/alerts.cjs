// Alerts browser test. Needs the DEMO backend with a fast loop (ATLAS_ALERT_SECONDS=2) on :8000 and `npm run dev` on :5173.
// Demo BTC quotes oscillate +/-1% (period ~25 s). The test samples one period (see lib.cjs) and picks a level that is crossed every cycle.
// Mutates the demo DB, so run it against a throwaway ATLAS_DB.
const { chromium } = require('playwright');
const fs = require('fs');
const { demoCrossLevel } = require('./lib.cjs');
const S = process.argv[2] || './e2e-out';
fs.mkdirSync(S, { recursive: true });
(async () => {
  const b = await chromium.launch();
  const pg = await b.newPage({ viewport: { width: 1680, height: 1100 } });
  const errors = [];
  pg.on('pageerror', e => errors.push('pageerror: ' + e.message));
  pg.on('console', m => { if (m.type() === 'error' && !/Failed to load resource/.test(m.text())) errors.push('console: ' + m.text()); });
  const httpErrors = [];
  pg.on('response', r => { if (r.status() >= 400) httpErrors.push(`${r.status()} ${r.request().method()} ${new URL(r.url()).pathname}`); });
  const posts = [];
  pg.on('request', r => { if (r.method() === 'POST') posts.push(new URL(r.url()).pathname); });
  await pg.goto('http://127.0.0.1:5173');
  await pg.waitForSelector('.topbar .cell');
  await pg.waitForTimeout(1500);

  // 1. ALERT command creates a DRAFT only (nothing exists until the user presses Create)
  const level = await demoCrossLevel();
  console.log('level (centre + half amplitude of the demo oscillation):', level);
  await pg.keyboard.press('/'); await pg.keyboard.type(`ALERT BTC ABOVE ${level}`); await pg.keyboard.press('Enter');
  await pg.waitForSelector('.aform-h');
  console.log('form header:', await pg.locator('.aform-h').innerText());
  const before = await fetch('http://127.0.0.1:8000/api/alerts').then(r => r.json());
  if (before.data.length !== 0) throw new Error('alert was created before confirmation');
  await pg.locator('button', { hasText: /^Create$/ }).click();
  await pg.waitForSelector('.tbl tbody tr');
  console.log('created:', (await pg.locator('.tbl tbody tr').first().locator('td').nth(1).innerText()).split('\n')[0]);

  // 1b. regression guard: buttons inside a panel header (the drag handle) must still receive clicks
  posts.length = 0;
  await pg.locator('button', { hasText: 'check now' }).click();
  await pg.waitForTimeout(600);
  if (!posts.includes('/api/alerts/evaluate')) throw new Error('header button "check now" did not fire (drag handle swallowing clicks?)');
  console.log('header button click reached the server: ok');

  // 2. validation error is shown, nothing created
  await pg.locator('select[aria-label="Alert type"]').selectOption('price');
  await pg.locator('input[aria-label="Symbol"]').fill('NOPE123456');
  await pg.locator('input[aria-label="Level"]').fill('5');
  await pg.locator('button', { hasText: /^Create$/ }).click();
  await pg.waitForSelector('.note.warn');
  console.log('validation:', await pg.locator('.aform .note.warn').first().innerText());

  // 3. wait for the background loop to fire the alert (edge: the demo price must cross the level)
  const t0 = Date.now();
  await pg.waitForSelector('.event:not(.sup)', { timeout: 90000 });
  console.log('fired after', Math.round((Date.now() - t0) / 1000), 's:', (await pg.locator('.event').first().locator('.event-m').innerText()));
  console.log('event meta:', await pg.locator('.event').first().locator('.meta').innerText());
  const bell = await pg.locator('.bell').innerText();
  console.log('bell:', bell.trim());
  if (!/DEMO/.test(await pg.locator('.event').first().innerText())) throw new Error('event not labelled DEMO');
  // 4. mark read clears the bell
  await pg.locator('button', { hasText: 'mark all read' }).click();
  await pg.waitForTimeout(1200);
  const after = (await pg.locator('.bell').innerText()).trim();
  console.log('bell after read:', after);
  if (!/ 0$/.test(after)) throw new Error('bell did not clear after mark all read');

  // 5. scan -> "Alert on new matches" drafts a scan alert
  await pg.keyboard.press('/'); await pg.keyboard.type('SCAN RVOL'); await pg.keyboard.press('Enter');
  await pg.waitForSelector('.scanmeta', { timeout: 30000 });
  await pg.locator('button', { hasText: 'Alert on new matches' }).click();
  await pg.waitForSelector('.aform-h');
  console.log('scan draft:', await pg.locator('.aform-h').innerText(), '| type:', await pg.locator('select[aria-label="Alert type"]').inputValue());
  await pg.locator('button', { hasText: /^Create$/ }).click();
  await pg.waitForTimeout(1000);
  const list = (await fetch('http://127.0.0.1:8000/api/alerts').then(r => r.json())).data;
  console.log('alerts on server:', list.map(a => a.kind).join(','));
  if (!list.some(a => a.kind === 'scan')) throw new Error('scan alert was not created');
  // 6. disable + persistence across reload
  await pg.locator('input[aria-label^="Enable"]').first().click();
  await pg.waitForFunction(() => !document.querySelector('input[aria-label^="Enable"]').checked, null, { timeout: 2000 })
    .catch(() => { throw new Error('enable checkbox did not flip (optimistic update broken?)'); });
  await pg.waitForTimeout(800);
  await pg.reload(); await pg.waitForSelector('.topbar'); await pg.waitForTimeout(1500);
  const rows = await pg.locator('.tbl tbody tr').count();
  const enabled = await pg.locator('input[aria-label^="Enable"]').evaluateAll(els => els.map(e => e.checked));
  console.log('after reload rows:', rows, 'enabled flags:', JSON.stringify(enabled), 'events:', await pg.locator('.event').count());
  await pg.screenshot({ path: S + '/alerts.png' });
  if (!enabled.includes(false)) throw new Error('disabled state did not persist across reload');
  console.log('HTTP errors:', JSON.stringify(httpErrors));
  if (httpErrors.length !== 1 || httpErrors[0] !== '404 POST /api/alerts') throw new Error('unexpected HTTP errors (only the deliberate unknown-symbol 404 is allowed)');
  console.log('JS errors:', errors.length ? errors.join('\n') : 'none');
  await b.close();
})().catch(e => { console.error('E2E FAIL', e.message); process.exit(1); });
