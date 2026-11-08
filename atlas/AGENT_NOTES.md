# Notes for Claude working on ATLAS and Signal

Short, project-specific lessons. Keep under 80 lines; delete anything that stops being true.

## Always
- Research and paper only. No order tickets, buy/sell controls or brokerage links, anywhere. Tests check this.
- Every number shows source, date and freshness. A gap is stated as a gap, never filled. Demo data is labelled on every screen and never mixed with live data.
- The server calculates; the apps display. Written explanations may not introduce figures.
- Report outcomes as they are: a failing test, an unverified source or a skipped step is said plainly.

## Before shipping a data source
- Fetch it live in the same session; keep one real sample as the test fixture. If it cannot be reached, log it as blocked, do not ship it.
- Free and keyless only. Check terms. The SEC contact and any keys live in environment variables or the untracked `local-settings.ps1`, never in the repo or a request header from the user's account.
- Show what it is and what it is not (a mood gauge is not a signal). Say "unavailable" with a reason when the source fails.

## Numbers that went wrong once
- Bars per year: about 252 for stocks, 365 for crypto. Derive it from the dates, never hard-code.
- Backtests: decide on a design period only; keep the last 30% sealed until the end; raise the bar for every extra variant tried; a win on a handful of trades is "inconclusive".
- Year-over-year price indexes (CPI, PCE, PPI) need the same month a year earlier; a missing month means "unavailable", not a guess.

## Tooling traps in this repo
- Phone app tokens are `color.up` and `color.down` (not good/bad); `Txt` variants are hero, title, h2, body, small, tiny, label.
- React Native accessibility props must not reach an SVG on web (the browser warns); the browser test fails on console warnings.
- Browser tests: Playwright selectors from the helper `V()` contain `:visible`, which is not valid inside `page.waitForFunction`; use a plain attribute selector there.
- A long heredoc mixed with shell edits can be blocked by the safety check; write files with the file tools and run small scripts from files.
- The cloud machine only reaches hosts on the environment's allowed list; a timeout (no HTTP code) usually means "host not allowed", not "site down".
- Before finishing: backend `pytest`, `npm run typecheck && npm test` in `mobile` and `web`, then `npm run export:web` and `node e2e/signal.e2e.cjs` after UI changes.

## When code fetches something from the internet
- Timeout on every request, a short cache, and a labelled "unavailable" result on failure; one failing half must not hide the other.
- Parse untrusted XML defensively (refuse a DOCTYPE or entities); never build a link from a field without checking its characters; show only https links.
- Keep a trimmed real response as the test fixture, and test the failure, stale and demo paths, not only the happy one.

## Phone lists
- Signal's screens render lists with a scroll view and `map`. That is fine while the server caps the rows (calendar 40 a day over at most 21 days, filings 40, watchlist 100). Any new list that could pass about 100 rows should use `FlatList`, or the server should cap it.

## Working style the user prefers
- Short, plain-English reports for a beginner: what changed, what was checked, what was not, what is needed from them.
- Do not merge, keep the PR draft, ask before anything paid or outward-facing.
