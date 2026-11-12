// Journal / import / performance e2e. Needs the DEMO backend (fresh DB) on :8000 and `npm run dev` on :5173.
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const S = process.argv[2] || './e2e-out';
fs.mkdirSync(S, { recursive: true });
const api = (p, o) => fetch('http://127.0.0.1:8000' + p, o).then(r => r.json());
const ensure = (c, m) => { if (!c) throw new Error(m); };

const VARIATIONAL = `Trade ID,Created At,Side,Underlying,Price,Quantity,Trade Type,Status
t1,2026-03-01 10:00:00,Buy,BTC-PERP,"70,000.50",0.5,trade,filled
t2,2026-03-02 11:00:00,Sell,BTC-PERP,71000,0.5,trade,filled
t3,2026-03-03 12:00:00,Buy,ETH-PERP,3500,2,trade,pending
t4,2026-03-04 13:00:00,Sell,ETH/USDC,3400,1,liquidation,completed
t5,2026-03-05 14:00:00,Buy,SOL-PERP,150,10,rebalance,filled`;
const FUNDING = `timestamp,underlying,type,amount,funding_rate
2026-03-01 18:00:00,BTC-PERP,Funding,-0.40,0.0001
2026-03-02 02:00:00,BTC-PERP,funding,0.10,-0.00005
2026-03-02 09:00:00,,Transfer,500,
2026-03-02 10:00:00,BTC-PERP,Realized PnL,500,`;
function bulk(n) {   // n closed round trips: even index wins +10, odd loses -5
  const rows = ['timestamp,symbol,side,quantity,price,fee,trade_id'];
  let t = Date.UTC(2026, 0, 5, 9, 30);
  for (let i = 0; i < n; i++) {
    rows.push(`${new Date(t).toISOString()},BULK,buy,1,100,0,b${i}`);
    rows.push(`${new Date(t + 2 * 3600e3).toISOString()},BULK,sell,1,${i % 2 === 0 ? 110 : 95},0,s${i}`);
    t += 86400e3;
  }
  return rows.join('\n');
}
(async () => {
  const b = await chromium.launch();
  const pg = await b.newPage({ viewport: { width: 1680, height: 1500 } });
  const errors = [], httpErrors = [];
  pg.on('pageerror', e => errors.push(e.message));
  pg.on('console', m => { if (m.type() === 'error' && !/Failed to load resource/.test(m.text())) errors.push(m.text()); });
  pg.on('response', r => { if (r.status() >= 400) httpErrors.push(`${r.status()} ${r.request().method()} ${new URL(r.url()).pathname}`); });
  const cmd = async t => { await pg.keyboard.press('/'); await pg.keyboard.type(t); await pg.keyboard.press('Enter'); };
  const panel = t => pg.locator('.panel', { has: pg.locator('.panel-t', { hasText: t }) });
  await pg.goto('http://127.0.0.1:5173');
  await pg.waitForSelector('.topbar .cell');

  // 1. JOURNAL workspace; the unverified Variational preset is flagged honestly
  await cmd('JOURNAL');
  await pg.locator('button', { hasText: 'imports and detailed analytics' }).first().click();       // imports and analytics moved to their own workspace
  await pg.waitForSelector('textarea[aria-label="CSV text"]');
  const warn = await panel('IMPORT TRADES').locator('.note.warn').first().innerText();
  console.log('preset warning:', warn.slice(0, 110));
  ensure(/could not be reached/.test(warn), 'unverified preset must be flagged');

  // 2. preview saves nothing and shows what was understood; the timezone changes parsed times
  await pg.fill('textarea[aria-label="CSV text"]', VARIATIONAL);
  await pg.locator('button', { hasText: 'Preview (nothing is saved)' }).click();
  await pg.waitForSelector('.pvbox');
  const pv = (await panel('IMPORT TRADES').locator('.pvbox').innerText()).replace(/\s+/g, ' ');
  console.log('preview:', pv.slice(0, 150));
  ensure(/4 of 5 rows parsed/.test(pv) && /skipped 1: status=pending/.test(pv) && /rebalance/.test(pv) && /assumed UTC/.test(pv), 'preview summary wrong');
  ensure((await panel('IMPORT TRADES').locator('select[aria-label="Map symbol"]').inputValue()) === 'Underlying', 'symbol column not detected');
  ensure(/2026-03-01 10:00:00 UTC/.test(pv), 'first row should read 10:00 UTC before the timezone change');
  ensure((await api('/api/journal/sources')).data.sources.length === 0, 'preview wrote to the database');
  await pg.locator('select[aria-label="Timestamp timezone"]').selectOption('America/New_York');
  await pg.locator('button', { hasText: 'Preview (nothing is saved)' }).click();
  await pg.waitForFunction(() => /2026-03-01 15:00:00 UTC/.test(document.querySelector('.pvbox')?.textContent || ''), null, { timeout: 10000 });
  console.log('timezone applied: 10:00 New York -> 15:00 UTC');

  // 3. confirm the import; trades appear with FIFO P&L
  await panel('IMPORT TRADES').locator('.confirm').click();
  await pg.waitForSelector('.note:has-text("Imported 4 new rows")');
  await pg.waitForSelector('td b:has-text("BTC")');
  const btc = (await panel('TRADES').locator('tr', { hasText: 'BTC' }).first().innerText()).replace(/\s+/g, ' ');
  console.log('BTC trade:', btc);
  ensure(/long/.test(btc) && /\+499\.75/.test(btc), 'BTC trade P&L wrong (expected +499.75)');
  const eth = (await panel('TRADES').locator('tr', { hasText: 'ETH' }).first().innerText()).replace(/\s+/g, ' ');
  ensure(/short/.test(eth) && /open/.test(eth) && /⚡/.test(await panel('TRADES').locator('tr', { hasText: 'ETH' }).first().innerHTML().then(h => h.includes('⚡') ? '⚡' : '')), 'liquidated short should be flagged');
  // re-previewing the same file recognises it
  await pg.fill('textarea[aria-label="CSV text"]', VARIATIONAL);
  await pg.locator('button', { hasText: 'Preview (nothing is saved)' }).click();
  await pg.waitForSelector('.pvbox');
  ensure(/4 already imported/.test((await panel('IMPORT TRADES').locator('.pvbox').innerText()).replace(/\s+/g, ' ')), 'duplicates not recognised');
  ensure((await panel('IMPORT TRADES').locator('.confirm').isDisabled()), 'nothing new: import button must be disabled');

  // 4. funding file attaches to the open trade; transfers/realized P&L are not double counted
  await pg.locator('select[aria-label="File kind"]').selectOption('flows');
  await pg.fill('textarea[aria-label="CSV text"]', FUNDING);
  await pg.locator('button', { hasText: 'Preview (nothing is saved)' }).click();
  await pg.waitForFunction(() => /3 of 4 rows parsed/.test(document.querySelector('.pvbox')?.textContent || ''), null, { timeout: 10000 });
  const fp = (await panel('IMPORT TRADES').locator('.pvbox').innerText()).replace(/\s+/g, ' ');
  ensure(/exchange-reported/.test(fp) && /POSITIVE amount/.test(fp), 'funding preview should explain skips and sign');
  await panel('IMPORT TRADES').locator('.confirm').click();
  await pg.waitForSelector('.note:has-text("Imported 3 new rows")');
  await pg.waitForFunction(() => /\+499\.45/.test([...document.querySelectorAll('tr')].find(r => /BTC/.test(r.textContent) && /long/.test(r.textContent))?.textContent || ''), null, { timeout: 15000 });
  console.log('funding attached: BTC net now +499.45');

  // 5. notes: setup, planned stop (-> R), mistakes, tags, screenshot
  await panel('TRADES').locator('tr', { hasText: 'BTC' }).first().click();
  await pg.waitForSelector('input[aria-label="Planned stop"]');
  await pg.fill('input[aria-label="Setup"]', 'breakout');
  await pg.fill('textarea[aria-label="Thesis"]', 'range break with volume');
  await pg.fill('input[aria-label="Planned stop"]', '69000');
  await pg.fill('input[aria-label="Mistakes"]', 'late entry');
  await pg.fill('input[aria-label="Tags"]', 'A+');
  fs.writeFileSync(S + '/dot.png', Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==', 'base64'));
  await pg.locator('input[aria-label="Attach screenshot"]').setInputFiles(S + '/dot.png');
  await pg.waitForSelector('img.shot');
  await pg.locator('button', { hasText: 'Save notes' }).click();
  await pg.waitForSelector('.note:has-text("Saved.")', { timeout: 8000 }).catch(async () => {
    throw new Error('notes did not save; editor says: ' + (await panel('TRADE NOTES').locator('.note').allInnerTexts()).join(' | ') + ' | form: ' + JSON.stringify(await panel('TRADE NOTES').locator('input,textarea').evaluateAll(e => e.map(x => x.value).filter(Boolean))));
  });
  await pg.waitForFunction(() => /breakout/.test([...document.querySelectorAll('tr')].find(r => /BTC/.test(r.textContent) && /long/.test(r.textContent))?.textContent || ''), null, { timeout: 10000 });
  const row = (await panel('TRADES').locator('tr', { hasText: 'BTC' }).first().innerText()).replace(/\s+/g, ' ');
  console.log('after notes:', row);
  ensure(/\+1\.00|\+0\.99/.test(row), 'R multiple missing: ' + row);         // 499.45 / (0.5 * |70000.5 - 69000|) = 0.998
  ensure((await api('/api/journal/trades')).data.trades.find(t => t.symbol === 'BTC').has_screenshot === true, 'screenshot not stored');
  const bad = await api('/api/journal/notes?key=' + encodeURIComponent((await api('/api/journal/trades')).data.trades[0].key), { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ screenshot: 'http://x/y.png' }) });
  ensure(bad.error.code === 'INVALID_NOTE', 'server must reject a non-data-URL screenshot');

  // 6. performance with a tiny sample refuses to look conclusive
  const perf = panel('PERFORMANCE ANALYSIS');
  await perf.locator('.note.warn[role="alert"]').waitFor();
  const small = (await perf.innerText()).replace(/\s+/g, ' ');
  console.log('small sample:', small.slice(0, 160));
  ensure(/only 1 trade\b/.test(small) && !/only 1 trades/.test(small) && /need 30\+/.test(small) && /anecdotal/.test(small), 'small-sample warning missing');   // singular for one trade; the minimum sample is 30
  ensure(!/95% interval/.test(await perf.innerHTML()) || /n<30/.test(small), 'no interval should be claimed from 1 trade');

  // 7. enough trades: the warning clears, intervals and reliable groups appear
  const r = await api('/api/journal/import', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ source: 'bulk', text: bulk(40), preset: 'generic', confirm: true }) });
  ensure(r.data.inserted === 80, 'bulk import failed');
  await pg.reload(); await pg.waitForSelector('.topbar');
  await cmd('JOURNAL');
  await pg.locator('button', { hasText: 'imports and detailed analytics' }).first().click();       // the PERF command was removed: analytics live in the advanced workspace
  await perf.locator('.stats').waitFor();
  await pg.waitForFunction(() => !document.querySelector('.note.warn[role="alert"]'), null, { timeout: 15000 });
  const big = (await perf.innerText()).replace(/\s+/g, ' ');
  console.log('reliable sample:', big.slice(0, 220));
  ensure(/TRADES 41/.test(big) && /WIN RATE/.test(big) && /EXPECTANCY/.test(big), 'stats missing');
  await perf.locator('button', { hasText: /^Setup$/ }).click();
  const groups = (await perf.locator('table.tbl').last().innerText()).replace(/\s+/g, ' ');
  console.log('setup groups:', groups.slice(0, 160));
  ensure(/\(no setup\)/.test(groups) && /breakout/.test(groups) && /⚠ n<30/.test(groups), 'group reliability flags missing');
  ensure(groups.indexOf('(no setup)') < groups.indexOf('breakout'), 'an unreliable group must not outrank a reliable one');

  // 8. manual execution + source deletion (with confirmation)
  await panel('JOURNAL SOURCES').locator('input[aria-label="Manual symbol"]').fill('NVDA');
  await panel('JOURNAL SOURCES').locator('input[aria-label="Manual quantity"]').fill('10');
  await panel('JOURNAL SOURCES').locator('input[aria-label="Manual price"]').fill('100');
  await panel('JOURNAL SOURCES').locator('input[aria-label="Manual time"]').fill('2026-03-10 14:30');
  await panel('JOURNAL SOURCES').locator('button', { hasText: /^Add$/ }).click();
  await pg.waitForSelector('.note:has-text("Execution added")');
  ensure((await api('/api/journal/sources')).data.sources.some(s => s.source === 'manual'), 'manual execution missing');
  pg.once('dialog', d => d.accept());
  await panel('JOURNAL SOURCES').locator('tr', { hasText: 'bulk' }).locator('button', { hasText: 'delete' }).click();
  await pg.waitForSelector('.note:has-text("Deleted 80 executions")');
  ensure(!(await api('/api/journal/sources')).data.sources.some(s => s.source === 'bulk'), 'source not deleted');
  ensure(/not connected/.test(JSON.stringify((await api('/api/journal/sync', { method: 'POST' })).data)), 'sync should say IBKR is not connected');

  // 9. persistence + IBKR panel in Settings + ask-the-desk
  await pg.reload(); await pg.waitForSelector('.topbar');
  ensure((await api('/api/journal/trades')).data.trades.find(t => t.symbol === 'BTC').setup === 'breakout', 'notes lost after reload');
  await cmd('SETTINGS');
  await pg.waitForSelector('.tgbox:has-text("INTERACTIVE BROKERS")');
  const ib = (await pg.locator('.tgbox:has-text("INTERACTIVE BROKERS")').innerText()).replace(/\s+/g, ' ');
  console.log('IBKR settings:', ib.slice(0, 150));
  ensure(/Not configured/.test(ib) && /IBKR_MODE/.test(ib), 'IBKR help missing');
  await cmd('JOURNAL');
  await pg.locator('button', { hasText: 'imports and detailed analytics' }).first().click();
  await pg.locator('button', { hasText: 'Ask desk: best setups' }).click();
  await pg.waitForSelector('.nav.on:has(span:text-is("BTC"))');
  await pg.waitForSelector('.panel.ai');
  const said = await pg.locator('.notice').innerText();
  ensure(/AI research desk on the BTC page|AI is not configured/.test(said), 'the user is not told what happened to the question');      // without an AI key the AI panel replaces the first notice with its own
  console.log('ask-the-desk opened the AI panel on the BTC page and said so');
  await pg.screenshot({ path: S + '/journal.png' });
  httpErrors.splice(0, httpErrors.length, ...httpErrors.filter(e => !/PUT \/api\/journal\/notes/.test(e)));
  console.log('HTTP errors (excluding the deliberate bad-screenshot probe):', JSON.stringify(httpErrors));
  ensure(!httpErrors.length, 'unexpected HTTP errors');
  console.log('JS errors:', errors.length ? errors.join('\n') : 'none');
  ensure(!errors.length, 'JS errors');
  await b.close();
})().catch(e => { console.error('E2E FAIL', e.message); process.exit(1); });
