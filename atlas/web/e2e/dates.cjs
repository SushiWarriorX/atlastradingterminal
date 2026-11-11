// Raw-date sweep (NON-demo backend on :8000: `python3 mobile/e2e/fake_backend.py --port 8000`, and `npm run dev` on :5173).
// Opens every desk and fails if any panel shows a raw ISO date (2026-11-06) instead of words (Nov 6, 2026). Links are ignored.
// Usage: node e2e/dates.cjs
const { chromium } = require('playwright');
const ISO = /\b20\d\d-\d\d-\d\d\b/;
const DESKS = [['Control+1', 'overview'], ['Control+2', 'btc'], ['Control+3', 'equities'], ['Control+4', 'macro'], ['Control+5', 'desk5'], ['Control+6', 'desk6']];
(async () => {
  const b = await chromium.launch();
  const pg = await b.newPage({ viewport: { width: 1680, height: 1500 } });
  const errors = [];
  pg.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
  await pg.goto('http://127.0.0.1:5173'); await pg.waitForSelector('.topbar .cell');
  const bad = [];
  for (const [key, name] of DESKS) {
    await pg.keyboard.press(key);
    await pg.waitForTimeout(2500);                                                    // let live panels answer
    const panels = await pg.locator('.panel').all();
    let seen = 0;
    for (const p of panels) {
      const title = ((await p.locator('.panel-t').first().innerText().catch(() => '')) || '').replace(/\s+/g, ' ').trim();
      const text = (await p.innerText().catch(() => '')).replace(/\s+/g, ' ').replace(/https?:\S+/g, '');
      seen++;
      const m = text.match(ISO);
      if (m) bad.push(`${name} / ${title.slice(0, 60)}: …${text.slice(Math.max(0, m.index - 40), m.index + 14)}`);
    }
    console.log(`${name}: ${seen} panels checked`);
  }
  if (errors.length) { console.error('browser errors: ' + errors.slice(0, 3).join(' | ')); process.exit(1); }
  if (bad.length) { console.error('RAW DATES ON SCREEN:\n  ' + bad.join('\n  ')); process.exit(1); }
  await b.close();
  console.log('NO RAW DATES ON ANY DESK');
})().catch((e) => { console.error('FAIL: ' + e.message); process.exit(1); });
