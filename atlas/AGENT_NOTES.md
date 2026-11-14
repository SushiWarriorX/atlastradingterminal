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
- Before finishing: backend `pytest`, `npm run typecheck && npm test` in `mobile`, then `npm run export:web` and `node e2e/signal.e2e.cjs` after UI changes.

## When code fetches something from the internet
- Timeout on every request, a short cache, and a labelled "unavailable" result on failure; one failing half must not hide the other.
- Parse untrusted XML defensively (refuse a DOCTYPE or entities); never build a link from a field without checking its characters; show only https links.
- Keep a trimmed real response as the test fixture, and test the failure, stale and demo paths, not only the happy one.

## Treasury FiscalData (the source behind many Macro cards)
- Missing values arrive as the text "null", not as nulls; amounts are strings, usually in millions of dollars (a few are in dollars). Convert once, state the unit on screen.
- Read the field the source really fills: in the cash-balance table the closing balance sits in `open_today_bal`. Prove it with two live rows that must agree (one day's closing equals the next day's opening) before trusting it.
- Mixed-type tables hide look-alikes (inflation-protected and floating-rate notes inside "Note"): filter with the source's own flag fields, never by guessing from a name or a yield.
- A page-size limit can cut the oldest month in half; count what is really there before promising "N months", and show "no comparison" when a month is missing.
- Check your own arithmetic against a total the source publishes (a deficit, a year-to-date row) in a test.
- A source can be behind: the bill-auction table stopped 26 days before "today". Show OVERDUE with the real gap and list what is pending; never fill the gap or call it current. Keep a test that uses the real fetch date.
- Daily Treasury Statement amounts are in millions and the month and fiscal-year totals are columns on each row: fetch the newest day, the month's days and the same day a year earlier as three small queries (`filter=record_date:gte:` / `lte:`, `sort=-record_date`), and test that the days add up to the source's own month-to-date figure.
- Rows that look like part of a total may not be: trust-fund (Government Account Series) rows are trillions of government-to-government debt, and the inflation adjustment on TIPS is an "issue" with no cash. Leave them out or label them on their own line, and say so in the note.
- Read the phone screenshot for sentence grammar, not only numbers: a phrase reused mid-line and as a sentence start produced "this month. a year earlier". Write phrases that work in both places.

## Research engine and browser-test lessons (from the fundamentals build)
- Quarterly figures: companies file 3-, 6-, 9- and 12-month cumulative cash-flow totals and never a fourth quarter; derive a quarter as the difference of two cumulative totals and label it "derived". Never sum quarters that are not consecutive.
- Tests: the first valid bar of any rolling indicator is bar n-1 (a 50-bar average first exists on bar 49); I wrote this off-by-one three times. Build fixtures from hand-checkable numbers and never write `or True` into an assertion.
- JSON: infinity and NaN are not JSON. "No upper limit" must become null before it reaches an answer, and a test needs a saved result to see it (an empty state hides the bug).
- Screens: view screenshots, not just assertions. They showed small amounts printed as $0, warnings buried in collapsed sections, invisible inputs and 35px buttons. A formatter must never turn a small non-zero amount into zero.
- Clipboard and pop-ups: start the copy and open the tab inside the click; report "copied" only after a real success; `window.open` with `noopener` always returns null, so detach with `opener = null` instead; test with permissions granted, refused and the tab blocked.
- Test text that denies something (a disclaimer saying "not a price target") will trip a naive advice detector: strip the app's own disclaimers before scanning.

## Mistakes from the shift loops (2026-11-09 and 10)
- Editing a file from a script: never open it for writing before reading it (`open(p, "w").write(open(p).read() + ...)` empties it first). Read into a variable, then write; check the diff shows only additions.
- Editing a markdown table by searching for a heading word: the word also appears in the intro, so rows landed in the wrong table. Search for the full heading line, and re-read the result.
- A test that depends on the clock or weekday fails at odd hours (three-day-old prices were "the latest session" on a Monday morning). Make fixtures stale by a margin that holds on any day, or fix the clock in the test.
- Derive a hand-checked number before trusting it (a Hull average on a straight line lags 4/3 bars, not 0). If the code and the expectation disagree, work out which is right first.
- A rule with a stop fixed at entry can end up as buy-and-hold (the NR7 rule entered in 2015 and never exited). Look at the entry and exit dates of a new backtest, not only the totals, and a rule needs at least one parameter for the robustness check.

## Phone lists
- Signal's screens render lists with a scroll view and `map`. That is fine while the server caps the rows (calendar 40 a day over at most 21 days, filings 40, watchlist 100). Any new list that could pass about 100 rows should use `FlatList`, or the server should cap it.

## Working style the user prefers
- Short, plain-English reports for a beginner: what changed, what was checked, what was not, what is needed from them.
- Do not merge, keep the PR draft, ask before anything paid or outward-facing.

## Tooling traps found 2026-11-11
- Inside a Python script written through a shell heredoc, "\\n" puts a literal backslash-n into the target file (and `rstrip("\\n")` strips backslashes and the letter n). Use real "\n", or the Edit tool, and grep the diff for `\\n` before committing.
- A `sed` line holding `$` and `${` (template strings) made the sandbox refuse the WHOLE command, including later steps, as an unverifiable removal. Make such edits with the Edit tool and run build and test commands as separate calls.
- When a fix is for a whole class of bug (raw dates, missing caveat), put the check for the class into the browser script; the raw-date check found five spots a manual pass missed.
- A source whose unit is not stated anywhere reachable (per day or per week) is HELD, not shipped, even when its numbers are internally consistent; a self-check proves consistency, not meaning.
- Browser scripts go stale silently when the UI is restyled (the old terminal scripts expected old nav labels, an AI panel and a toolbar button, and had not been run for days). Run the Signal browser script (`node e2e/signal.e2e.cjs` in `mobile`, all scenarios) after any UI change; it starts its own backend and database for each scenario.
- Test layouts with the worst real content, not the sample content: a five-digit price and the longest status word ("UNAVAILABLE") broke a Watchlist that passed with "169.78" and "DELAYED". When a layout depends on text length, add worst-case text to the Signal browser script.
