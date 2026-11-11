// Narrow-window sweep (NON-demo backend on :8000: `python3 mobile/e2e/fake_backend.py --port 8000`, and `npm run dev` on :5173).
// Opens every desk at laptop and small-window widths and fails if any panel's content is wider than the panel (horizontal overflow, which cuts text off or forces sideways scrolling).
// Usage: node e2e/narrow.cjs [screenshot-folder]
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const S = process.argv[2] || '';
if (S) fs.mkdirSync(S, { recursive: true });
const WIDTHS = [1280, 1024, 820];
const DESKS = [['Control+1', 'overview'], ['Control+2', 'btc'], ['Control+3', 'equities'], ['Control+4', 'macro']];
(async () => {
  const b = await chromium.launch();
  const bad = [];
  for (const w of WIDTHS) {
    const pg = await b.newPage({ viewport: { width: w, height: 1400 } });
    await pg.goto('http://127.0.0.1:5173'); await pg.waitForSelector('.topbar .cell');
    for (const [key, name] of DESKS) {
      await pg.keyboard.press(key);
      await pg.waitForTimeout(2500);
      const found = await pg.evaluate(() => {
        const out = [];
        document.querySelectorAll('.panel').forEach((p) => {
          const body = p.querySelector('.panel-b') || p;
          const title = (p.querySelector('.panel-t') || {}).innerText || '';
          // any element inside the panel that sticks out past the panel's right edge
          const edge = p.getBoundingClientRect().right;
          let worst = 0, which = '';
          p.querySelectorAll('*').forEach((e) => {
            const r = e.getBoundingClientRect();
            if (r.width > 0 && r.right - edge > worst) { worst = r.right - edge; which = e.tagName.toLowerCase() + '.' + (e.className || '').toString().slice(0, 20); }
          });
          if (worst > 2 || body.scrollWidth > body.clientWidth + 2) out.push({ title: title.replace(/\s+/g, ' ').slice(0, 60), over: Math.round(Math.max(worst, body.scrollWidth - body.clientWidth)), which });
        });
        return out;
      });
      for (const f of found) bad.push(`${w}px ${name} / ${f.title}: ${f.over}px too wide (${f.which})`);
      if (S && name === 'macro') await pg.screenshot({ path: path.join(S, `macro-${w}.png`), fullPage: false }).catch(() => undefined);
      console.log(`${w}px ${name}: checked`);
    }
    await pg.close();
  }
  await b.close();
  if (bad.length) { console.error('HORIZONTAL OVERFLOW:\n  ' + bad.join('\n  ')); process.exit(1); }
  console.log('NO HORIZONTAL OVERFLOW AT ANY WIDTH');
})().catch((e) => { console.error('FAIL: ' + e.message); process.exit(1); });
