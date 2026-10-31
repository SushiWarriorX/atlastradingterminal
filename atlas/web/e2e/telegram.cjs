// Telegram e2e. Needs: e2e/fake_telegram.py on :9999 logging to $TG_LOG, and the DEMO backend started with
//   TELEGRAM_BOT_TOKEN=$TG_TOKEN TELEGRAM_CHAT_ID=987654321 TELEGRAM_API_BASE=http://127.0.0.1:9999
//   ATLAS_TELEGRAM_ALLOW_DEMO=1 ATLAS_ALERT_SECONDS=2 ATLAS_DEMO=1   (backend log at $API_LOG), plus `npm run dev`.
const { chromium } = require('playwright');
const fs = require('fs');
const { demoCrossLevel } = require('./lib.cjs');
const S = process.argv[2] || './e2e-out';
const TOKEN = process.env.TG_TOKEN, TG_LOG = process.env.TG_LOG, API_LOG = process.env.API_LOG;
fs.mkdirSync(S, { recursive: true });
const sent = () => (fs.existsSync(TG_LOG) ? fs.readFileSync(TG_LOG, 'utf8').trim().split('\n').filter(Boolean).map(JSON.parse) : []);
(async () => {
  const b = await chromium.launch();
  const pg = await b.newPage({ viewport: { width: 1680, height: 1100 } });
  const errors = [], bodies = [], httpErrors = [];
  pg.on('pageerror', e => errors.push(e.message));
  pg.on('response', async r => {
    if (r.url().includes('/api/')) { try { bodies.push(await r.text()); } catch {} }
    if (r.status() >= 400) httpErrors.push(`${r.status()} ${r.request().method()} ${new URL(r.url()).pathname}`);
  });
  await pg.goto('http://127.0.0.1:5173');
  await pg.waitForSelector('.topbar .cell');

  // 1. Settings shows the verified bot and a MASKED chat id
  await pg.locator('.nav', { hasText: 'SETTINGS' }).click();
  await pg.waitForSelector('.tgbox:has-text("TELEGRAM ALERT DELIVERY") table');
  const box = await pg.locator('.tgbox:has-text("TELEGRAM ALERT DELIVERY")').innerText();
  console.log('settings:', box.replace(/\s+/g, ' ').slice(0, 160));
  if (!box.includes('@fake_atlas_bot') || !box.includes('…4321')) throw new Error('bot/chat not shown as expected');
  if (box.includes('987654321')) throw new Error('full chat id leaked to the UI');

  // 2. test message reaches the (fake) Telegram API
  await pg.locator('button', { hasText: 'Send test message' }).click();
  await pg.waitForSelector('.tgbox:has-text("TELEGRAM ALERT DELIVERY") .note:has-text("Test message sent")');
  if (!sent().some(m => m.text.includes('ATLAS test message') && m.chat_id === '987654321')) throw new Error('test message not received');
  console.log('test message received by Telegram API: ok');

  // 3. minimum severity -> critical
  await pg.locator('select[aria-label="Minimum severity"]').selectOption('critical');
  await pg.waitForTimeout(800);

  // 4. two alerts that cross at the same time: one info, one critical
  await pg.locator('.nav', { hasText: 'ALERTS' }).click();
  await pg.waitForSelector('.aform');
  const level = String(await demoCrossLevel());
  for (const [name, sev] of [['INFO alert', 'info'], ['CRIT alert', 'critical']]) {
    await pg.locator('select[aria-label="Alert type"]').selectOption('price');
    await pg.locator('input[aria-label="Symbol"]').fill('BTC-USD');
    await pg.locator('input[aria-label="Level"]').fill(level);
    await pg.locator('select[aria-label="Severity"]').selectOption(sev);
    await pg.locator('input[aria-label="Alert name"]').fill(name);
    await pg.locator('button', { hasText: /^Create$/ }).click();
    await pg.waitForTimeout(700);
  }
  await pg.waitForFunction(() => document.querySelectorAll('.event:not(.sup)').length >= 2, null, { timeout: 90000 });
  await pg.waitForTimeout(1000);
  const metas = await pg.locator('.event').evaluateAll(els => els.map(e => ({ msg: e.querySelector('.event-m').innerText, meta: e.querySelector('.meta').innerText })));
  for (const m of metas) console.log(' event:', m.msg.slice(0, 40), '|', m.meta);
  const info = metas.find(m => m.msg.startsWith('INFO alert')), crit = metas.find(m => m.msg.startsWith('CRIT alert'));
  if (!info.meta.includes('telegram:skipped_severity')) throw new Error('info alert should be filtered by min severity');
  if (!crit.meta.includes('telegram:delivered')) throw new Error('critical alert should be delivered');
  const alertMsgs = sent().filter(m => m.text.includes('ATLAS ·'));
  console.log('messages at Telegram API:', alertMsgs.length, '|', alertMsgs.map(m => m.text.split('\n')[0]).join(' / '));
  if (alertMsgs.length !== 1 || !alertMsgs[0].text.includes('CRITICAL') || !alertMsgs[0].text.includes('CRIT alert')) throw new Error('exactly one critical message expected');
  if (!alertMsgs[0].text.includes('data DEMO')) throw new Error('message must state the data status');

  // 5. the token appears nowhere the browser or the logs can see
  const leaked = bodies.filter(t => t.includes(TOKEN) || t.includes('987654321'));
  if (leaked.length) throw new Error('secret found in an API response');
  const log = fs.readFileSync(API_LOG, 'utf8');
  if (log.includes(TOKEN) || log.includes(TOKEN.split(':')[1])) throw new Error('TOKEN LEAKED INTO BACKEND LOG');
  console.log(`token absent from ${bodies.length} API responses and the backend log (${log.split('\n').length} lines): ok`);
  await pg.screenshot({ path: S + '/telegram.png' });
  console.log('HTTP errors:', JSON.stringify(httpErrors), '| JS errors:', errors.length ? errors.join('\n') : 'none');
  await b.close();
})().catch(e => { console.error('E2E FAIL', e.message); process.exit(1); });
