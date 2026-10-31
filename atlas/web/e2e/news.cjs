// News e2e. Needs: `python e2e/fake_rss.py 8098`, the DEMO backend started with
//   ATLAS_NEWS_ALLOW_LOCAL=1 ATLAS_NEWS_SYMBOL_URL='http://127.0.0.1:8098/sym.xml?s={symbol}' ATLAS_DEMO=1 on a throwaway ATLAS_DB, plus `npm run dev`.
const { chromium } = require('playwright');
const fs = require('fs');
const S = process.argv[2] || './e2e-out';
fs.mkdirSync(S, { recursive: true });
const API = 'http://127.0.0.1:8000', RSS = 'http://127.0.0.1:8098';
(async () => {
  // start from a clean feed list so the test never touches the real internet
  const feeds = (await (await fetch(`${API}/api/news/feeds`)).json()).data.feeds;
  for (const f of feeds) await fetch(`${API}/api/news/feeds/${f.id}`, { method: 'DELETE' });
  const b = await chromium.launch();
  const pg = await b.newPage({ viewport: { width: 1680, height: 1300 } });
  const errors = [], httpErrors = [], dialogs = [];
  pg.on('pageerror', e => errors.push('pageerror: ' + e.message));
  pg.on('console', m => { if (m.type() === 'error' && !/Failed to load resource/.test(m.text())) errors.push('console: ' + m.text()); });
  pg.on('dialog', d => { dialogs.push(d.message()); d.dismiss(); });
  pg.on('response', r => { if (r.status() >= 400) httpErrors.push(`${r.status()} ${r.request().method()} ${new URL(r.url()).pathname}`); });
  await pg.goto('http://127.0.0.1:5173'); await pg.waitForSelector('.topbar .cell');

  // 1. NEWS opens the real module (no "not built" placeholder); with no feeds fetched it says so and shows NO headlines
  await pg.keyboard.press('/'); await pg.keyboard.type('NEWS'); await pg.keyboard.press('Enter');
  await pg.waitForSelector('.news-list', { timeout: 15000 });
  if (await pg.locator('.unavail').count()) throw new Error('news still shows the unbuilt placeholder');
  console.log('empty state:', (await pg.locator('.news-list .note').first().innerText()).slice(0, 80));
  if (await pg.locator('.news-item').count()) throw new Error('headlines shown before any feed was fetched');

  // 2. add feeds through the UI: a bad scheme is refused with the reason; good ones are added
  const fp = pg.locator('.panel:has(.panel-t:text("NEWS FEEDS"))');
  await fp.locator('input[aria-label="Feed name"]').fill('Bad'); await fp.locator('input[aria-label="Feed URL"]').fill('ftp://x.example/feed');
  await fp.locator('button', { hasText: /^Add$/ }).click();
  await pg.waitForSelector('.note.warn:has-text("http(s)")', { timeout: 8000 });
  for (const [n, u] of [['Feed A', `${RSS}/a.xml`], ['Feed B', `${RSS}/b.xml`], ['Broken', `${RSS}/broken.xml`]]) {
    await fp.locator('input[aria-label="Feed name"]').fill(n); await fp.locator('input[aria-label="Feed URL"]').fill(u);
    await fp.locator('button', { hasText: /^Add$/ }).click();
    await fp.locator(`td:has-text("${n}")`).first().waitFor({ timeout: 8000 });
  }

  // 3. refresh: stories appear, the duplicate Fed story is grouped, the broken feed is reported (not hidden)
  await pg.locator('button', { hasText: 'refresh feeds' }).click();
  await pg.waitForSelector('.news-item', { timeout: 15000 });
  const msg = await pg.locator('.news-list').locator('xpath=preceding::div[contains(@class,"note")][1]').first().innerText().catch(() => '');
  const items = await pg.locator('.news-item').allInnerTexts();
  console.log('stories:', items.length, '|', items.map(t => t.split('\n')[0].slice(0, 40)).join(' / '));
  if (items.length !== 4) throw new Error(`expected 4 stories (5 headlines, one duplicate pair grouped), got ${items.length}`);
  const fed = items.find(t => /Fed holds/.test(t));
  if (!/also reported by Feed A|also reported by Feed B/.test(fed)) throw new Error('duplicate Fed story not grouped');
  await pg.waitForSelector('.note.warn:has-text("1 feed(s) failing")', { timeout: 8000 });
  console.log('failing banner:', (await pg.locator('.note.warn:has-text("failing")').first().innerText()));
  await fp.locator('td:has-text("HTTP 500")').first().waitFor({ timeout: 8000 });

  // 4. hostile content is inert: shown as text, no script, no javascript: link, no dialog
  const hostile = pg.locator('.news-item', { hasText: 'Hostile headline' });
  console.log('hostile headline text:', (await hostile.locator('.news-h').innerText()).replace(/\n/g, ' '));
  if (await pg.locator('.news-list script, .news-list img').count()) throw new Error('markup from a feed reached the DOM');
  if (await hostile.locator('a').count()) throw new Error('a javascript: link was rendered');
  const link = pg.locator('.news-item a', { hasText: 'Why $TSLA' });
  if ((await link.getAttribute('target')) !== '_blank' || !/noopener/.test(await link.getAttribute('rel'))) throw new Error('external links must be target=_blank rel=noopener');
  await pg.waitForTimeout(500);
  if (dialogs.length) throw new Error('a dialog fired: ' + dialogs.join('|'));

  // 5. the explicit cashtag produced a symbol tag; Bitcoin in a headline tags BTC; nothing else is tagged
  const tags = await pg.locator('.news-h .badge').allInnerTexts();
  console.log('tags:', tags.join(','));
  if (tags.sort().join() !== 'BTC,TSLA') throw new Error('unexpected tags: ' + tags);

  // 6. symbol scope: selecting AAPL fetches its per-symbol feed on demand
  await pg.keyboard.press('/'); await pg.keyboard.type('AAPL NEWS'); await pg.keyboard.press('Enter');
  await pg.locator('.news button', { hasText: /^AAPL$/ }).first().click();
  await pg.waitForSelector('.news-item:has-text("AAPL supplier raises")', { timeout: 15000 });
  console.log('symbol scope:', (await pg.locator('.news-item').allInnerTexts()).length, 'story');
  await pg.locator('.news button', { hasText: 'All headlines' }).first().click();

  // 7. search, then disabling a feed removes its stories
  await pg.locator('input[aria-label="Search headlines"]').fill('bitcoin');
  await pg.waitForFunction(() => document.querySelectorAll('.news-item').length === 1, null, { timeout: 8000 });
  await pg.locator('input[aria-label="Search headlines"]').fill('');
  await fp.locator('input[aria-label="Enable Feed B"]').click();
  await pg.waitForFunction(() => !/Bitcoin climbs/.test(document.querySelector('.news-list')?.textContent || ''), null, { timeout: 8000 });
  console.log('disabled Feed B: its story is gone');
  await pg.screenshot({ path: S + '/news.png' });

  // 8. persistence across reload
  await pg.reload(); await pg.waitForSelector('.topbar'); await pg.keyboard.press('/'); await pg.keyboard.type('NEWS'); await pg.keyboard.press('Enter');
  await pg.waitForSelector('.news-item', { timeout: 15000 });
  console.log('after reload stories:', await pg.locator('.news-item').count());

  console.log('HTTP errors:', JSON.stringify(httpErrors));
  if (httpErrors.length !== 1 || httpErrors[0] !== '422 POST /api/news/feeds') throw new Error('unexpected HTTP errors (only the deliberate ftp:// refusal is allowed)');
  console.log('JS errors:', errors.length ? errors.join('\n') : 'none');
  if (errors.length) throw new Error('JS errors');
  await b.close();
})().catch(e => { console.error('E2E FAIL', e.message); process.exit(1); });
