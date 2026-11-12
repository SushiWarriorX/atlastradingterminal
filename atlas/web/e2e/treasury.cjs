// Treasury panels on the Macro desk, against a NON-demo backend (mobile/e2e/fake_backend.py --port 8000) so the panels show the real layout, and `npm run dev` on :5173.
// Interest on the debt, Treasury buybacks and Treasury bill auctions each show their source, say plainly when they are unavailable or overdue, write dates in words, and make no forecasts.
// Usage: node e2e/treasury.cjs [screenshot-folder]   (the live Treasury source answers from this machine; when it does not, the panels must say so instead of showing numbers)
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const S = process.argv[2] || '';
if (S) fs.mkdirSync(S, { recursive: true });
const fail = (m) => { throw new Error(m); };
const FORECASTS = /\b(will (rise|fall|double)|forecast to|predict(s|ed)|price target|guaranteed|buy now|sell now)\b/i;
const OWN_CAVEAT = /not (a|market) (market )?signals? or (a )?forecasts?/gi;
(async () => {
  const b = await chromium.launch();
  const pg = await b.newPage({ viewport: { width: 1680, height: 1500 } });
  const errors = [];
  pg.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
  pg.on('console', (m) => { if (m.type() === 'error' && !/Failed to load resource/.test(m.text())) errors.push('console: ' + m.text()); });
  await pg.goto('http://127.0.0.1:5173'); await pg.waitForSelector('.topbar .cell');
  await pg.keyboard.press('Control+4');                                                              // Macro desk
  await pg.waitForTimeout(800);
  for (const [id, title, shot] of [['interest', /INTEREST ON THE DEBT/, 'interest'], ['buybacks', /TREASURY BUYBACKS/, 'buybacks'], ['bills', /TREASURY BILL AUCTIONS/, 'bills'], ['borrowing', /TREASURY BORROWING/, 'borrowing'], ['dealers', /DEALER TREASURY POSITIONS/, 'dealers'], ['futurespos', /FUTURES POSITIONING/, 'futurespos'], ['commoditypos', /COMMODITY POSITIONING/, 'commoditypos'], ['currencypos', /CURRENCY & VOLATILITY POSITIONING/, 'currencypos'], ['realyields', /REAL YIELDS & BREAKEVEN INFLATION/, 'realyields'], ['customs', /CUSTOMS DUTIES/, 'customs'], ['receipts', /WHERE FEDERAL REVENUE COMES FROM/, 'receipts'], ['outlays', /WHERE FEDERAL MONEY GOES/, 'outlays']]) {
    const loc = pg.locator(`[data-testid="${id}"]`);
    await loc.waitFor({ timeout: 60000 });
    await loc.scrollIntoViewIfNeeded();
    await pg.waitForTimeout(400);
    const panel = pg.locator('.panel', { has: loc });
    const all = (await panel.innerText()).replace(/\s+/g, ' ');
    if (!title.test(all)) fail(`${id}: panel title missing: ${all.slice(0, 80)}`);
    if (!/US Treasury|Treasury FiscalData|New York Fed|CFTC/.test(all)) fail(`${id}: the source is not named`);
    const stripped = all.replace(OWN_CAVEAT, '');
    if (FORECASTS.test(stripped)) fail(`${id}: forecast-like wording: ${stripped.match(FORECASTS)[0]}`);
    if (/\b20\d\d-\d\d-\d\d\b/.test(all.replace(/https?:\S+/g, ''))) fail(`${id}: a raw ISO date is on screen`);
    const live = !/could not be read|Demo mode|unavailable/i.test(all);
    if (live) {
      if (!/what already happened|already happened|not (a )?market signals? or (a )?forecasts?/i.test(all)) fail(`${id}: the plain-words caveat is missing`);
      if (id === 'interest' && !(/(January|February|March|April|May|June|July|August|September|October|November|December) 20\d\d/.test(all) && /Treasury bills/.test(all) && /from a year earlier/.test(all))) fail('interest: month in words, bills line and year-ago comparison expected');
      if (id === 'interest' && !/Bars: interest for each of the last \d+ months, oldest on the left, drawn from zero\. Lowest \$[\d.,]+B, highest \$[\d.,]+B, latest \$[\d.,]+B\./.test(all)) fail('interest: the bar strip needs its caption (what the bars are, their order, the baseline and the range)');
      if (id === 'buybacks' && !(/Latest operation/.test(all) && /LAST 90 DAYS/.test(all) && /LAST 12 MONTHS/.test(all) && /RECENT OPERATIONS/.test(all))) fail('buybacks: latest operation, both windows and recent list expected');
      if (id === 'bills' && !(/4-week/.test(all) && /13-week/.test(all) && /26-week/.test(all) && /Bid-to-cover/.test(all))) fail('bills: terms and bid-to-cover expected');
      if (id === 'borrowing' && !(/SO FAR \(through [A-Z][a-z]{2} \d{1,2}, 20\d\d\)/.test(all) && /FISCAL 20\d\d SO FAR/.test(all) && /Net new borrowing/.test(all) && /Treasury bills/.test(all) && /Same point a year earlier/.test(all))) fail('borrowing: month, fiscal year, net borrowing, types and the year-ago comparison expected');
      if (id === 'borrowing' && /DOES NOT MATCH/.test(all)) fail('borrowing: the self-check against the source failed');
      if (id === 'dealers' && !(/NET POSITION IN US TREASURIES \(as of [A-Z][a-z]{2} \d{1,2}, 20\d\d\)/.test(all) && /Same week a year earlier/.test(all) && /Higher than \d+ of those \d+ weeks/.test(all) && /Bars: one per week for the last \d+ weeks, oldest on the left\. The scale starts at the lowest week/.test(all))) fail('dealers: date, year-ago, range and the bar caption (with its scale warning) expected');
      if (id === 'dealers' && /DOES NOT MATCH/.test(all)) fail('dealers: the self-check against the source failed');
      if (id === 'futurespos' && !(/S&P 500 FUTURES \(E-MINI\) · as of [A-Z][a-z]{2} \d{1,2}, 20\d\d/.test(all) && /10-YEAR TREASURY NOTE FUTURES/.test(all) && /Leveraged funds/.test(all) && /Asset managers/.test(all) && /Dealers/.test(all) && /Checked: the groups add up to the report's own totals/.test(all) && /not a market signal or a forecast/.test(all))) fail('futurespos: contracts, groups, the dated header, the check line and the caveat are expected');
      if (id === 'futurespos' && /did not add up/.test(all)) fail('futurespos: a contract failed its own totals check');
      if (id === 'commoditypos' && !(/GOLD FUTURES · as of [A-Z][a-z]{2} \d{1,2}, 20\d\d/.test(all) && /CRUDE OIL FUTURES \(WTI\)/.test(all) && /COPPER FUTURES/.test(all) && /NATURAL GAS FUTURES/.test(all) && /Managed money/.test(all) && /Producers and merchants/.test(all) && /Swap dealers/.test(all) && /Checked: the groups add up to the report's own totals/.test(all) && /not a market signal or a forecast/.test(all))) fail('commoditypos: contracts, groups, the dated header, the check line and the caveat are expected');
      if (id === 'commoditypos' && /did not add up/.test(all)) fail('commoditypos: a contract failed its own totals check');
      if (id === 'currencypos' && !(/EURO FUTURES · as of [A-Z][a-z]{2} \d{1,2}, 20\d\d/.test(all) && /JAPANESE YEN FUTURES/.test(all) && /BRITISH POUND FUTURES/.test(all) && /VIX FUTURES/.test(all) && /Leveraged funds/.test(all) && /Asset managers/.test(all) && /Checked: the groups add up to the report's own totals/.test(all) && /not a market signal or a forecast/.test(all))) fail('currencypos: contracts, groups, the dated header, the check line and the caveat are expected');
      if (id === 'currencypos' && /did not add up/.test(all)) fail('currencypos: a contract failed its own totals check');
      if (id === 'realyields' && !(/as of [A-Z][a-z]{2} \d{1,2}, 20\d\d/.test(all) && /10-year/.test(all) && /30-year/.test(all) && /Breakeven inflation/.test(all) && /Real yield \(TIPS\)/.test(all) && /Compared with [A-Z][a-z]{2} \d{1,2}, 20\d\d and [A-Z][a-z]{2} \d{1,2}, 20\d\d/.test(all) && /Bars: 10-year breakeven inflation for each of the last \d+ days, oldest on the left\. The scale starts at the lowest day/.test(all) && /Checked: both curves are for the same day/.test(all) && /not a market signal or a forecast/.test(all) && /not a forecast of inflation/.test(all))) fail('realyields: date, maturities, comparison dates, bar caption with its scale warning, the check line and the caveats are expected');
      if (id === 'customs' && !(/(January|February|March|April|May|June|July|August|September|October|November|December) 20\d\d/.test(all) && /Collected/.test(all) && /paid back in refunds/.test(all) && /FISCAL 20\d\d SO FAR/.test(all) && /Same point last year/.test(all) && /LAST \d+ MONTHS/.test(all) && /Checked: each month's collected minus refunded equals what was kept/.test(all) && /does not say why refunds/.test(all) && /not a market signal or a forecast/.test(all))) fail('customs: month in words, collected / refunded / kept, year so far vs last year, the month table, the check line and the caveats are expected');
      if (id === 'receipts' && !(/Fiscal 20\d\d so far/.test(all) && /Individual income taxes/.test(all) && /Corporate income taxes/.test(all) && /Customs duties \(tariffs\)/.test(all) && /All receipts/.test(all) && /Same point last year/.test(all) && /Checked: the seven sources add up to the source's own total/.test(all) && /does not say why any category rose or fell/.test(all) && /not a market signal or a forecast/.test(all))) fail('receipts: fiscal year so far, the categories, the total row, last year, the check line and the caveats are expected');
      if (id === 'outlays' && !(/Fiscal 20\d\d so far/.test(all) && /Social Security/.test(all) && /Medicare/.test(all) && /Net Interest/.test(all) && /National Defense/.test(all) && /All spending \(net outlays\)/.test(all) && /All receipts \(income\)/.test(all) && /Gap \(spending minus receipts\)/.test(all) && /Same point last year/.test(all) && /Checked: the purposes add up to the source's own total spending/.test(all) && /does not say why any purpose rose or fell/.test(all) && /not a market signal or a forecast/.test(all))) fail('outlays: fiscal year so far, the purposes, the three total rows, last year, the check line and the caveats are expected');
    }
    console.log(`${id}: ${live ? 'live data' : 'unavailable, said so'}: ok`);
    if (S) await panel.screenshot({ path: path.join(S, `terminal-${shot}.png`) }).catch(() => undefined);
  }
  // The older Macro panels (written before dates were put in words) must not show raw ISO dates either.
  for (const [title, shot] of [[/FED INTEREST RATE/, 'fedrates'], [/TREASURY CASH BALANCE/, 'tga'], [/FED LIQUIDITY OPERATIONS/, 'fedops'], [/WHAT THE FED HOLDS/, 'fedholds'], [/INTEREST THE TREASURY PAYS/, 'debtrates'], [/WHAT THE US DEBT IS MADE OF/, 'debtmix'], [/TREASURY AUCTIONS/, 'auctions'], [/US TREASURY . yield curve/, 'curve']]) {
    const panel = pg.locator('.panel', { hasText: title }).last();
    if (!(await panel.count())) { console.log(`${shot}: panel not on screen, skipped`); continue; }
    await panel.scrollIntoViewIfNeeded();
    await pg.waitForTimeout(300);
    const text = (await panel.innerText()).replace(/\s+/g, ' ').replace(/https?:\S+/g, '');
    if (/\b20\d\d-\d\d-\d\d\b/.test(text)) fail(`${shot}: a raw ISO date is on screen: ${text.match(/\b20\d\d-\d\d-\d\d\b/)[0]}`);
    console.log(`${shot}: no raw dates: ok`);
    if (S) await panel.screenshot({ path: path.join(S, `terminal-${shot}.png`) }).catch(() => undefined);
  }
  if (errors.length) fail('browser errors: ' + errors.slice(0, 3).join(' | '));
  await b.close();
  console.log('TREASURY PANELS OK');
})().catch((e) => { console.error('FAIL: ' + e.message); process.exit(1); });
