// Portfolio / paper trading / risk e2e. Needs the DEMO backend (fresh DB, fast loops) on :8000 and `npm run dev` on :5173:
//   ATLAS_DEMO=1 ATLAS_ALERT_SECONDS=2 ATLAS_PAPER_SECONDS=2 python -m atlas_api
// Mutates the demo DB, so use a throwaway ATLAS_DB.
const { chromium } = require('playwright');
const fs = require('fs');
const S = process.argv[2] || './e2e-out';
fs.mkdirSync(S, { recursive: true });
const api = (p, o) => fetch('http://127.0.0.1:8000' + p, o).then(r => r.json());
const ensure = (c, m) => { if (!c) throw new Error(m); };
(async () => {
  const b = await chromium.launch();
  const pg = await b.newPage({ viewport: { width: 1680, height: 1300 } });
  const errors = [], httpErrors = [];
  pg.on('pageerror', e => errors.push(e.message));
  pg.on('console', m => { if (m.type() === 'error' && !/Failed to load resource/.test(m.text())) errors.push(m.text()); });
  pg.on('response', r => { if (r.status() >= 400) httpErrors.push(`${r.status()} ${r.request().method()} ${new URL(r.url()).pathname}`); });
  const cmd = async t => { await pg.keyboard.press('/'); await pg.keyboard.type(t); await pg.keyboard.press('Enter'); };
  const btcPrice = async () => parseFloat((await pg.locator('.topbar .cell', { hasText: 'BTC-USD' }).innerText()).replace(/,/g, '').match(/(\d+\.\d+)/)[1]);
  const preview = async () => { await pg.locator('button', { hasText: 'Preview + risk check' }).click(); await pg.waitForSelector('.pvbox'); };
  await pg.goto('http://127.0.0.1:5173');
  await pg.waitForSelector('.topbar .cell');

  // 1. portfolio opens with the paper account
  await cmd('PORT');
  await pg.waitForSelector('.stats');
  const stats = (await pg.locator('.stats').first().innerText()).replace(/\s+/g, ' ');
  console.log('empty account:', stats);
  ensure(/EQUITY 100,000.00/.test(stats) && /CASH 100,000.00/.test(stats), 'unexpected starting account');
  ensure((await pg.locator('.env-tag', { hasText: 'PAPER ACCOUNT' }).count()) === 1, 'paper label missing');

  // 2. BUY command only DRAFTS; confirm stays disabled until a preview approves
  const p0 = await btcPrice();
  const stop = (p0 * 0.98).toFixed(2);
  await cmd(`BUY BTC 0.1 SL ${stop}`);
  await pg.waitForSelector('input[aria-label="Order quantity"]');
  ensure((await pg.locator('input[aria-label="Order quantity"]').inputValue()) === '0.1', 'draft qty not filled');
  ensure((await pg.locator('input[aria-label="Planned stop"]').inputValue()) === stop, 'draft stop not filled');
  ensure((await api('/api/orders')).data.length === 0, 'an order was created by the draft command');
  ensure((await pg.locator('.confirm').count()) === 0, 'confirm button visible before preview');
  await preview();
  const verdict = await pg.locator('.pv-h b').innerText();
  const checks = await pg.locator('.pvbox .checks').innerText();
  console.log('verdict:', verdict, '| checks include data warning:', /SYNTHETIC/.test(checks));
  ensure(/APPROVED FOR PAPER REVIEW/.test(verdict), 'expected approval: ' + verdict + '\n' + checks);
  ensure(/environment/.test(checks) && /kill switch/.test(checks) && /event risk/.test(checks) && /not authorization|disclaimer|paper/i.test(await pg.locator('.pvbox').innerText()), 'checks incomplete');
  ensure((await api('/api/orders')).data.length === 0, 'preview created an order');

  // 3. editing the ticket invalidates the preview (no stale approval can be confirmed)
  await pg.locator('input[aria-label="Order quantity"]').fill('0.11');
  ensure((await pg.locator('.pvbox').count()) === 0, 'preview survived an edit');
  await pg.locator('input[aria-label="Order quantity"]').fill('0.1');
  await preview();

  // 4. confirm -> paper fill; account, positions, orders and fills all agree
  await pg.locator('.confirm').click();
  await pg.waitForSelector('.note:has-text("Paper order #1 filled")', { timeout: 15000 });
  console.log('submit result:', await pg.locator('.note:has-text("Paper order #1")').first().innerText());
  await pg.waitForFunction(() => /BTC-USD/.test(document.querySelector('.panel')?.innerText || '') && /EQUITY/.test(document.body.innerText), null, { timeout: 10000 });
  await pg.waitForTimeout(1500);
  const portfolioText = await pg.locator('.panel:has(.stats) table.tbl').first().innerText();
  console.log('positions:', portfolioText.replace(/\s+/g, ' ').slice(0, 140));
  ensure(/BTC-USD/.test(portfolioText) && /0\.1/.test(portfolioText), 'position missing');
  const acct = (await api('/api/portfolio')).data;
  ensure(Number(acct.cash) < 100000 && acct.positions.length === 1 && acct.positions[0].planned_stop === String(Number(stop)), 'account state wrong');
  ensure((await api('/api/portfolio/reconcile')).data.consistent === true, 'ledger inconsistent');
  await pg.locator('button', { hasText: 'fills' }).click();
  await pg.waitForSelector('td:has-text("market fill")');
  console.log('fill note:', (await pg.locator('td:has-text("market fill")').first().innerText()).slice(0, 80));

  // 5. an oversized order is REJECTED and cannot be confirmed
  await pg.locator('input[aria-label="Order quantity"]').fill('5');
  await pg.locator('input[aria-label="Planned stop"]').fill(stop);
  await preview();
  const v2 = await pg.locator('.pv-h b').innerText();
  console.log('oversized:', v2, '| confirm enabled:', await pg.locator('.confirm').isEnabled());
  ensure(/REJECTED/.test(v2) && !(await pg.locator('.confirm').isEnabled()), 'oversized order should be rejected and unconfirmable');
  ensure(/position cap|buying power/.test(await pg.locator('.pvbox .checks').innerText()), 'expected a limit failure');

  // 6. passive limit order: working, shown in open orders, cancellable
  await pg.locator('input[aria-label="Order quantity"]').fill('0.02');   // existing 0.1 BTC is ~7% of equity: keep the total under the 10% cap
  await pg.locator('select[aria-label="Order type"]').selectOption('limit');
  await pg.locator('input[aria-label="Limit price"]').fill((p0 * 0.9).toFixed(2));
  await pg.locator('input[aria-label="Planned stop"]').fill((p0 * 0.85).toFixed(2));
  await preview();
  ensure(/APPROVED/.test(await pg.locator('.pv-h b').innerText()), 'limit order should be approved');
  await pg.locator('.confirm').click();
  await pg.waitForSelector('.note:has-text("Paper order #2 working")', { timeout: 15000 });
  await pg.locator('button', { hasText: 'open orders' }).click();
  await pg.waitForSelector('tr:has-text("working")');
  console.log('open order:', (await pg.locator('tr:has-text("working")').first().innerText()).replace(/\s+/g, ' '));
  await pg.locator('tr:has-text("working") button', { hasText: 'cancel' }).click();
  await pg.waitForFunction(() => !/working/.test([...document.querySelectorAll('tr')].map(r => r.textContent).join('|')), null, { timeout: 10000 });
  ensure((await api('/api/orders')).data.find(o => o.id === 2).state === 'cancelled', 'order not cancelled');
  console.log('limit order cancelled: ok');
  await pg.screenshot({ path: S + '/trading.png' });

  // 7. risk workspace: limits are enforced, kill switch halts
  await cmd('RISK');
  await pg.waitForSelector('input[aria-label="Max single position (% equity)"]');
  await pg.locator('input[aria-label="Max single position (% equity)"]').fill('1');
  await pg.locator('button', { hasText: 'Save limits' }).click();
  await pg.waitForSelector('.note:has-text("Limits saved")');
  const pvTight = (await api('/api/orders/preview', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ instrument_id: 'BTC-USD', side: 'buy', qty: '0.01', type: 'market', planned_stop: stop }) })).data;
  ensure(pvTight.verdict === 'REJECT' && pvTight.checks.find(c => c.name === 'position_cap').status === 'fail', 'tightened cap not enforced');
  console.log('tightened position cap enforced by backend: ok');
  await pg.locator('input[aria-label="Max single position (% equity)"]').fill('10');
  await pg.locator('button', { hasText: 'Save limits' }).click();
  await pg.waitForSelector('.note:has-text("Limits saved")');
  const bad = await api('/api/risk/limits', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ max_position_pct: 0 }) });
  ensure(bad.ok === false && bad.error.code === 'INVALID_LIMITS', 'invalid limit accepted');
  pg.once('dialog', d => d.accept());
  await pg.locator('button', { hasText: 'HALT TRADING' }).click();
  await pg.waitForSelector('.chip.halted');
  const hv = (await api('/api/orders/preview', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ instrument_id: 'BTC-USD', side: 'buy', qty: '0.01', type: 'market', planned_stop: stop }) })).data;
  ensure(hv.verdict === 'REJECT' && hv.checks.find(c => c.name === 'kill_switch').status === 'fail', 'kill switch did not block');
  console.log('kill switch: HALTED chip shown, new orders rejected');
  await pg.locator('button', { hasText: 'Resume trading' }).click();
  await pg.waitForFunction(() => !document.querySelector('.chip.halted'), null, { timeout: 10000 });

  // 8. analytics and scenarios
  await pg.waitForSelector('.panel:has-text("PORTFOLIO RISK") .stats', { timeout: 30000 });
  const rtext = (await pg.locator('.panel:has-text("PORTFOLIO RISK") .stats').first().innerText()).replace(/\s+/g, ' ');
  console.log('risk stats:', rtext);
  ensure(/VaR 95% 1d [\d.]+%/.test(rtext) && /VOL \(ann\.\) [\d.]+%/.test(rtext), 'risk stats missing');
  await pg.locator('input[aria-label="Shock BTC-USD"]').fill('-10');
  await pg.locator('button', { hasText: 'Run scenario' }).click();
  await pg.waitForSelector('.panel:has-text("SCENARIO LAB") .stats');
  const posVal = Number((await api('/api/portfolio')).data.positions[0].value);
  const pnl = parseFloat((await pg.locator('.panel:has-text("SCENARIO LAB") .stats b').first().innerText()).replace(/,/g, ''));
  console.log('scenario BTC -10%:', pnl, 'expected', (-posVal * 0.1).toFixed(2));
  ensure(Math.abs(pnl - -posVal * 0.1) < 0.02, 'scenario P&L wrong');
  await pg.locator('button', { hasText: 'reconcile ledger' }).click();
  await pg.waitForSelector('.note:has-text("reconciles")');
  await pg.screenshot({ path: S + '/risk.png' });

  // 9. manual portfolio: user-entered holdings, cannot trade
  await cmd('PORT');
  await pg.waitForSelector('.stats');
  const answers = [d => d.accept('Holdings'),          // name
                   d => d.dismiss(),                   // confirm: Cancel = manual holdings
                   d => d.accept('5000')];             // starting cash
  const onDialog = d => { const a = answers.shift(); if (a) a(d); else d.dismiss(); };   // dialogs arrive one at a time, in order
  pg.on('dialog', onDialog);
  await pg.locator('button', { hasText: '+ portfolio' }).click();
  await pg.waitForSelector('.env-tag:has-text("MANUAL HOLDINGS")', { timeout: 10000 });
  pg.off('dialog', onDialog);
  await pg.locator('input[aria-label="Holding symbol"]').fill('AAPL');
  await pg.locator('input[aria-label="Holding quantity"]').fill('10');
  await pg.locator('input[aria-label="Holding average cost"]').fill('150');
  await pg.locator('button', { hasText: 'Save holding' }).click();
  await pg.waitForSelector('td b:has-text("AAPL")');
  ensure(/Manual portfolios cannot trade/.test(await pg.locator('.panel:has-text("ORDER TICKET")').innerText()), 'ticket should refuse manual portfolios');
  console.log('manual portfolio: holdings saved, ticket refuses to trade');

  // 10. no live-trading control exists, and the live route refuses
  const body = await pg.locator('body').innerText();
  ensure(!/place live|submit live|go live|live order/i.test(body), 'a live trading control appears in the UI');
  const live = await api('/api/orders/live', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{"instrument_id":"BTC-USD"}' });
  ensure(live.error.code === 'LIVE_TRADING_DISABLED', 'live route did not refuse');
  console.log('live trading: no UI control; route refuses with', live.error.code);

  // 11. persistence across reload
  await pg.reload(); await pg.waitForSelector('.topbar');
  const after = (await api('/api/portfolios')).data;
  ensure(after.length === 2 && (await api('/api/orders')).data.length === 2, 'state lost');
  console.log('persisted portfolios:', after.map(p => p.name + '/' + p.kind).join(', '));
  httpErrors.splice(0, httpErrors.length, ...httpErrors.filter(e => !/POST \/api\/orders\/live|PUT \/api\/risk\/limits/.test(e)));
  console.log('HTTP errors (excluding the two deliberate refusals):', JSON.stringify(httpErrors));
  ensure(httpErrors.length === 0, 'unexpected HTTP errors');
  console.log('JS errors:', errors.length ? errors.join('\n') : 'none');
  ensure(!errors.length, 'JS errors');
  await b.close();
})().catch(e => { console.error('E2E FAIL', e.message); process.exit(1); });
