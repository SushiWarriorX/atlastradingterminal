// Hyperliquid journal sync e2e. Needs: `python e2e/fake_hyperliquid.py 8099 $HL_LOG`, the DEMO backend started with
//   HYPERLIQUID_API_BASE=http://127.0.0.1:8099 ATLAS_DEMO=1 on a throwaway ATLAS_DB, plus `npm run dev`.
const { chromium } = require('playwright');
const fs = require('fs');
const S = process.argv[2] || './e2e-out';
const HL_LOG = process.env.HL_LOG;
fs.mkdirSync(S, { recursive: true });
const ADDR = '0x' + 'ab'.repeat(20), KEY = '0x' + '1f'.repeat(32);
const reqs = () => (fs.existsSync(HL_LOG) ? fs.readFileSync(HL_LOG, 'utf8').trim().split('\n').filter(Boolean).map(JSON.parse) : []);
(async () => {
  const b = await chromium.launch();
  const pg = await b.newPage({ viewport: { width: 1680, height: 1300 } });
  const errors = [], httpErrors = [];
  pg.on('pageerror', e => errors.push('pageerror: ' + e.message));
  pg.on('console', m => { if (m.type() === 'error' && !/Failed to load resource/.test(m.text())) errors.push('console: ' + m.text()); });
  pg.on('response', r => { if (r.status() >= 400) httpErrors.push(`${r.status()} ${r.request().method()} ${new URL(r.url()).pathname}`); });
  await pg.goto('http://127.0.0.1:5173'); await pg.waitForSelector('.topbar .cell');
  await pg.keyboard.press('/'); await pg.keyboard.type('JOURNAL'); await pg.keyboard.press('Enter');
  await pg.waitForSelector('#hl-box', { timeout: 15000 });
  const box = pg.locator('#hl-box');

  // 1. a private key is refused with no network call at all
  await box.locator('input[aria-label="Hyperliquid address"]').fill(KEY);
  await box.locator('button', { hasText: 'Sync' }).click();
  await pg.waitForSelector('.note.warn:has-text("PRIVATE KEY")', { timeout: 10000 });
  console.log('key refused:', (await pg.locator('.note.warn:has-text("PRIVATE KEY")').first().innerText()).slice(0, 100));
  if (reqs().length) throw new Error('a request reached Hyperliquid for a key-shaped value');
  if ((await pg.content()).includes(KEY.slice(2)) && !(await box.locator('input').inputValue()).includes(KEY.slice(2))) throw new Error('key echoed outside the input');

  // 2. public address syncs: fills, funding, reported P&L, no secret in any request
  await box.locator('input[aria-label="Hyperliquid address"]').fill(ADDR);
  await box.locator('button', { hasText: 'Sync' }).click();
  await box.locator('[role=status]').waitFor({ timeout: 15000 });
  const res = (await box.locator('[role=status]').innerText()).replace(/\n/g, ' ');
  console.log('sync:', res.slice(0, 230));
  if (!/3 new fills/.test(res) || !/1 funding/.test(res) || !/100\.0/.test(res)) throw new Error('sync summary wrong: ' + res);
  const sent = reqs();
  console.log('requests to HL:', sent.map(r => r.type).join(','));
  if (!sent.every(r => Object.keys(r).sort().join() === 'startTime,type,user')) throw new Error('unexpected fields sent to Hyperliquid: ' + JSON.stringify(sent[0]));

  // 3. the source and the derived trade appear; fees and funding are in the net P&L
  await pg.waitForSelector('td:has-text("hyperliquid:0xabab")', { timeout: 10000 });
  const trades = await pg.locator('.panel:has-text("TRADE JOURNAL") tbody tr, .panel:has(.tbl) tbody tr:has-text("BTC-PERP")').first().innerText().catch(() => '');
  const api = await (await fetch('http://127.0.0.1:8000/api/journal/trades')).json();
  const t = api.data.trades.find(x => x.symbol === 'BTC-PERP');
  console.log('BTC-PERP trade:', t.status, 'gross', t.gross_pnl, 'fees', t.fees, 'funding', t.funding, 'net', t.net_pnl);
  if (t.status !== 'closed' || Math.abs(parseFloat(t.net_pnl) - 98.54) > 1e-6) throw new Error('net P&L should be 100 - 1.21 fees - 0.25 funding = 98.54');
  const eth = api.data.trades.find(x => x.symbol === 'ETH-PERP');
  if (!eth || eth.status !== 'open') throw new Error('ETH-PERP should be an open trade');

  // 4. re-sync is idempotent; the address is remembered in the input after reload
  await box.locator('button', { hasText: 'Sync' }).click();
  await pg.waitForFunction(() => /0 new fills \(3 already known\)/.test(document.querySelector('#hl-box [role=status]')?.textContent || ''), null, { timeout: 15000 });
  console.log('re-sync adds nothing: ok');
  await pg.reload(); await pg.waitForSelector('.topbar'); await pg.keyboard.press('/'); await pg.keyboard.type('JOURNAL'); await pg.keyboard.press('Enter');
  await pg.waitForSelector('#hl-box');
  if ((await pg.locator('#hl-box input[aria-label="Hyperliquid address"]').inputValue()) !== ADDR) throw new Error('address not remembered');
  await pg.screenshot({ path: S + '/hyperliquid.png' });

  console.log('HTTP errors:', JSON.stringify(httpErrors));
  if (httpErrors.length !== 1 || httpErrors[0] !== '422 POST /api/journal/hyperliquid/sync') throw new Error('unexpected HTTP errors (only the deliberate key refusal is allowed)');
  console.log('JS errors:', errors.length ? errors.join('\n') : 'none');
  if (errors.length) throw new Error('JS errors');
  await b.close();
})().catch(e => { console.error('E2E FAIL', e.message); process.exit(1); });
