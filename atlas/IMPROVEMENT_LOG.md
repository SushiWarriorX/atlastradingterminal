# Improvement log

Newest entry first. Written by the scheduled improvement loop (see `LOOP.md`) and by hand.








## 2026-11-08 · SEC filings feed (user request)
- **What:** `GET /api/stocks/filings?symbols=&forms=&limit=&days=` (default: the watchlist's stocks). Covers 10-K/10-Q, 8-K (with item meanings), insider Form 4/144, 5% holders (13D/13G), proxies, offerings, late-filing notices. Newest first, importance dot, link to the document on sec.gov, plain-English meaning that is explicitly generic.
- **Where:** terminal Equities desk panel "SEC FILINGS" (this stock or whole watchlist, filter chips); Signal card on every stock page (open by default, filters).
- **Verified live:** Apple, Nvidia and Tesla filings fetched from EDGAR in this session; a trimmed real Apple response is the test fixture.
- **Honest limits:** needs `ATLAS_SEC_CONTACT` (said plainly with the fix when missing); ETFs have no SEC company; Form 4 rows say an insider trade was filed, not whether it was a buy or sell (that needs the filing's own text).
- **Tests:** 9 backend, phone browser 47/47, terminal browser check; 880 backend tests pass.

## 2026-11-08 · Data-source loop, cycle 1: Crypto Fear & Greed (user request)
- **Loop:** `atlas/DATA_LOOP.md` (playbook) and `atlas/DATA_SOURCES.md` (live / queued / blocked / rejected). Runs every 10 minutes inside this session (scheduled tasks cannot go below 1 hour); the session job expires after 7 days.
- **Network:** the build machine only reached Coinbase and SEC, so ten exact public hosts were added to the allowed list (with approval).
- **Shipped:** alternative.me Fear & Greed. `GET /api/btc/sentiment`, terminal panel on the BTC desk, Signal card on the BTC page. Source, date and "not a forecast" shown; unreachable source says so; demo mode shows nothing invented.
- **Tests:** 8 backend, phone browser 46/46, terminal browser check. FRED still unreachable.

## 2026-11-08 · Macro trimmed to the core numbers (user request)
- Removed the "What matters today" rule-based notes from the terminal and phone Macro views. Key indicators now show only: Fed rate, CPI, core CPI, PCE, core PCE, PPI, core PPI. Upcoming dates and headlines stay. The server still returns every indicator (yields, jobs, GDP, dollar, balance sheet), so they can be shown again by editing one list (`CORE`) in `MacroToday.tsx` and `MacroView.tsx`.
- Phone browser test now checks the notes section is gone. 45/45.

## 2026-11-08 · Terminal what-if panel + PPI on the macro side (user requests)
- **Terminal:** the "What if I had bought X?" panel (same server route as Signal) is on the Equities and BTC desks. New browser check `web/e2e/whatif.cjs`. Caught a title bug (BTC showed "SPOT" because its id ends in :SPOT).
- **Macro:** CPI and PCE (headline and core) were already shown; added PPI and core PPI (FRED `WPSFD49207`, `WPSFD4131`) next to them, with plain "why it matters" notes. A failing PPI series cannot hide CPI or PCE (tested).
- **Not verified:** FRED is not reachable from this sandbox, so the two PPI series ids are untested against live data. If they are wrong, PPI shows "unavailable" with a reason and nothing else breaks.
- **Known:** `web/e2e/desks.cjs` still expects the old sidebar names from before the five-destination redesign; it fails on that, unrelated to this change.

## 2026-11-08 · "What if I had bought it?" simulator + deep-dive fix (user requests)
- **Deep-dive was empty:** the Windows start script never set `ATLAS_SEC_CONTACT`, so SEC filings were off and the card showed nothing useful. Now: a clear banner with the fix in the phone card, a warning in `start-windows.ps1`, and the setting documented in `local-settings.example.ps1`. The email stays in the user's untracked `local-settings.ps1`.
- **New Signal section (every asset page):** `GET /api/signal/whatif/{asset}?amount=` and `WhatIfCard`. Five replays from daily closes: one purchase held to today (1/3/5 years ago), the same amount monthly, every possible start date (worst/typical/best), exit rules (20% stop, 30% target, 20% trailing stop), and 2,000 shuffled years. Price-only, no dividends/tax/fees, stops on closes; labelled DEMO in demo mode.
- **Caught on the way:** years were counted as 252 bars, wrong for crypto (365); now derived from the dates.
- **Tests:** 8 backend, 1 new browser check (45/45), no trade controls.

## 2026-11-08 · Self-improving loop for the Strategy Lab (user request)
- **What:** `btclab/agent.py` runs: 5-year stress test -> find where the rule loses money -> pick a fix from a fixed menu -> rerun -> keep or discard. API: `POST /api/btclab/agent`, `GET /api/btclab/agent/history` (runs saved, migration 015).
- **Guards:** last 30% of the 5 years is a sealed holdout (opened once, at the end; a test proves changing it changes no decision). Fixes are fixed in advance, never tuned. The bar to keep a fix rises with every fix tried. A win on fewer than 3 holdout trades is "inconclusive", not success.
- **First real run (Coinbase daily, ~5.2y):** 5 library rules. Only "trailing-return momentum" kept a fix (200-day trend filter) and it made 1 holdout trade -> inconclusive. The other four: no menu fix passed. Breakout rules lost 26% on the holdout; the loop correctly did not pretend to fix that.
- **Next:** Monte Carlo resampling of the 5 years (idea from the public day-trader-skill README) as an extra stress; web/phone view of the loop; scheduled cycles can call the endpoint.

## 2026-11-08 · Browser console warning fixed (user report)
- **Problem:** the browser console warned "React does not recognize the `accessibilityElementsHidden` prop on a DOM element" (from the small price lines, `Sparkline`).
- **Fix:** web now gets `aria-hidden`; phones keep the native prop. Harmless, but noisy.
- **Guard:** the browser test now fails on React console warnings, and a unit test blocks accessibility props on `<Svg>`. 44/44 browser checks, 43 unit tests pass.

## 2026-11-08, cycle 8: the phone calendar's two filter rows no longer both say "All"
- **Found (reviewing the new phone calendar):** the company filter and the type filter each had a chip called "All", so it was unclear which one a tap would change.
- **Changed:** company filter chips are now "Big companies", "My watchlist" and "Everything"; the type filter starts with "All types". Labels only; no logic changed.
- **Verified:** backend 849 tests, web and phone type checks and unit tests (phone 42), browser suite 44 of 44; viewed the new Macro screenshot.
- **Still open:** the calendar shows times in the device's own time zone (fine on a phone, but the sandbox screenshots read UTC, so "1:30 PM" for an 8:30 AM ET release); the owner's request for a Voices section (follow a trader and see their narrative) is waiting on the choice between a free paste-in box and a paid X API key.
- **Next candidates:** Voices (once the owner answers); calendar reminders for watchlist events; keyboard shortcuts for the terminal desks.

## 2026-11-08, on request: one calendar for earnings, economic data, rates, dividends and Treasury auctions
- **Asked for:** an earnings calendar like eToro's: company earnings, CPI data, interest-rate decisions, dividend payments, and so on.
- **Built:** `/api/calendar` (backend `eventcal` package), a CALENDAR panel at the top of the terminal's Macro desk, and a Calendar card at the top of the phone's Macro tab. Five kinds: company earnings and dividends (Nasdaq's public calendars, unofficial, with the analyst EPS estimate it shows and the last-year figure), economic releases (BLS: CPI, jobs, PPI, JOLTS, employment cost; BEA: GDP and PCE), Fed decisions, minutes and press conferences (the hand-entered FOMC table), and Treasury auctions (US Treasury API). Filters: 7, 14 or 21 days; type; Major companies, My watchlist or Everything; add-to-watchlist in the terminal; tap a company on the phone to open it.
- **Honest labels:** every event says official or unofficial and names its source; a source that fails is listed by name and the others still show; importance (high, medium, low) is explained as a guide, not a prediction; days with more than 40 small company events show the 40 biggest and say how many are hidden.
- **Needed:** the sandbox's network allowance was extended to `api.nasdaq.com`, `www.bls.gov`, `api.fiscaldata.treasury.gov` and `www.bea.gov` to check against real data (all four answered; BLS needs a descriptive User-Agent, which the calendar sends).
- **Verified:** ran against the real sources (85 major earnings, CPI, PPI, FOMC minutes and dividends in a two-week window, about 5 seconds); backend 849 tests (13 new for parsing, filters, failure reporting and caps); phone unit tests 42; browser suite 44 of 44 using canned sources, so the tests never use the real internet.
- **Known limits:** Nasdaq's feeds are unofficial and can be late or wrong; the Treasury lists only auctions already announced (about a week ahead); central-bank meetings other than the Fed are not included; dividend lists are per ex-date.
- **Next candidates:** a "Voices" section to follow chosen traders and see their narratives (owner asked; needs a decision about X access because X's API is paid); calendar reminders for watchlist events.

## 2026-11-08, cycle 7: no luck check for a rule with too few trades
- **Found (by looking at the real results screen for the first time):** a rule that made a single out-of-sample trade showed "safe lower Sharpe estimate 6.59". The luck check resamples daily returns, so a few long holdings look like many independent days and the number was meaningless. The label said "No reliable evidence" but the figure beside it looked reassuring.
- **Tried first and rejected:** making the resampling blocks as long as the holding period. A test showed that does not reliably make a Sharpe estimate more cautious (Sharpe of a series with long flat stretches is not monotone in block length), so that change was reverted rather than shipped.
- **Changed:** the luck check only runs with at least 15 out-of-sample trades; otherwise the result says "Too few out-of-sample trades (n; at least 15 are needed) to run a luck check." (`luck_check_note`). Such a rule can never be better than "No reliable evidence". The evidence tag on the phone is a pill, not full-width.
- **Verified:** backend 836 tests (the old assertions updated, one new), web and phone type checks and unit tests, browser suite 44 of 44 (its Strategy Lab check now expects the "too few trades" message); viewed the new results screenshot.
- **Honest limit:** with 15 or more trades the luck check is still an approximation (a block bootstrap of daily returns); treat it as guidance.
- **Next candidates:** let the user choose the out-of-sample split; Stocks empty-state suggestions; keyboard shortcuts for the terminal desks; check the new Windows launcher on a real Windows machine (reported by the owner as not starting before it existed; untested here).

## 2026-11-08, cycle 6 (on request): strategy research on real BTC data, and a harder-to-fool lab
- **Asked for:** look for different trading strategies, backtest them, and improve judgement.
- **Method:** downloaded real data (Coinbase BTC-USD daily from 2015, hourly and 4-hour from late 2023; Hyperliquid funding from 2023). Ran every strategy through the existing evaluator (fees 5 bps, slippage 5 bps per side), spot and perpetuals, daily, 4h and 1h.
- **Added five candidates:** Supertrend, breakout with a trailing stop, long average with a buffer, RSI strength trend, trend filtered by calm volatility. The library now has 21 rules, each fixed in advance and not tuned.
- **What the data said (past results, not forecasts):**
  - Daily spot 2015 to 2026: buy and hold about +27,000%, worst drop 84%. Last 30% of history (out of sample): holding +187%; the best rule, momentum with a trend filter, +210% with a worst drop of about 27 to 44% instead of 53 to 84%. Most others earned less than holding. Their real benefit was smaller drops.
  - Perpetuals 2023 to 2026 and 4h or 1h spot: most rules lost money after fees, slippage and funding; none reached moderate evidence. Faster timeframes lose to costs.
  - Nothing among the new candidates was a standout.
- **Judgement upgrades (the main change):** (1) a luck check: a block-bootstrap lower bound on the out-of-sample Sharpe ratio that counts the whole library (the best of 20 rules looks good by chance), so "moderate" now needs the lower bound above 0; with the whole library in play nothing on the real data reaches it. (2) capture ratios: how much of buy and hold's up bars and down bars each rule took part in, and a plain-English line saying so. (3) regime split: yearly return while BTC was above or below its own 200-bar average, versus holding. (4) a dated "what the research found so far" note in the API, the terminal panel and the phone card.
- **Verified:** backend 835 tests (5 new for the luck check, capture, regimes and library-wide counting), web and phone type checks and unit tests, browser suite 44 of 44 including a check that the luck check names how many strategies were in play; ran the whole thing against real downloaded data.
- **Not verified:** how a user's own settings (other fees, other periods) change the verdicts; the bootstrap is an approximation (it does not model every dependence in the data).
- **Next candidates:** let the user choose the out-of-sample split; show the equity curve with the regime shading; research position sizing (volatility targeting) as a separate engine feature.

## 2026-11-08, cycle 5 (run on request): the Strategy Lab says what it is doing while it works
- **Found:** on real data the first Strategy Lab run downloads BTC history (up to about a minute for perpetuals, because funding history is fetched too). The only feedback was a spinner, which looks frozen, and the spinner was white on the silver button so it was hard to see.
- **Changed:** while a comparison runs, phone and terminal show a plain-words message ("Running the comparison. The first run on real data downloads BTC price history; later runs are quick." plus a funding-history line for perpetuals and an hourly-prices line for 4h and 1h). The button spinner is now dark on silver. The wording lives in one small tested function (`busyText`); the browser test slows the request on purpose to check the message appears and disappears.
- **Also reviewed (no change needed):** the terminal's colours. Its small text uses `--dim` (about 5.5:1 on its lightest panel tint), so the contrast candidate from cycle 4 is closed.
- **Verified:** phone unit tests (39, two new groups), web and phone type checks, backend 830 tests, browser suite 44 of 44; viewed the busy-state screenshot before and after the spinner fix.
- **Not verified:** the real download time on a real connection (the sandbox runs this against fast fixtures); the copy says "up to about a minute", which matches the 50 seconds measured for funding history earlier.
- **Next candidates:** Stocks empty-state suggestions; keyboard shortcuts for the five terminal desks; Discover first-scan loading message ("about 20 seconds" is shown, check it reads well on a phone).

## 2026-11-07, cycle 4: small source and date captions are readable on every card
- **Found:** the grey captions that carry each figure's source and date (for example "SEC EDGAR 10-K · as of 2026-12-31") were close to invisible on the brighter top Discover card (contrast about 1.1 to 1), and below the accessibility minimum on ordinary cards too (about 2.9 to 1 at the top of a card). Those captions are how the app keeps its "every number has a source and a date" promise.
- **Changed:** the "faint" text colour is lighter (`#9AA0AB`) and the highlight card is a cooler, darker steel-blue instead of a bright grey. The silver and graphite look is unchanged elsewhere. New `lib/contrast.ts` and a unit test that fails if small captions or secondary text drop below 4.5:1 on any card gradient stop or on the screen background.
- **Verified:** phone unit tests (37, two new), phone type check, backend 830 tests, web checks, browser suite 44 of 44; viewed the new Discover screenshot, captions now clear.
- **Not verified:** the terminal's small captions use a different CSS palette and were not measured this cycle.
- **Next candidates:** run the same contrast check on the terminal's CSS colours; Stocks empty-state suggestions; loading states for Discover and Strategy Lab on the phone.

## 2026-11-07, cycle 3: the silver glow no longer ends in a hard edge
- **Found:** on every phone tab the glow behind the header stopped in a visible straight edge about 300 points down (the right-hand corner of the second gradient was still slightly lit where the box ended).
- **Changed:** `TopGlow` now ends with a final fade into the screen colour, so no corner can end abruptly. One small change in `Gradient.tsx`; no colours or layout changed.
- **Verified:** phone type check and unit tests, backend 830 tests, web checks, browser suite 44 of 44; compared before and after screenshots of the Stocks, Journal and Macro tabs: the edge is gone.
- **Not verified:** a real phone's GPU rendering (checked in the browser only).
- **Next candidates:** Stocks empty-state suggestions; loading states for Discover and Strategy Lab on the phone; keyboard shortcuts for the five terminal desks.

## 2026-11-07, cycle 2: a plain Journal note is no longer tagged "Long"
- **Found:** a note with only a symbol and some text (no size or prices) showed a "Long" tag in the phone list and "long" in the terminal table, because the form's side defaults to long. That reads as if a position had been taken.
- **Changed:** notes now show "Note" instead of a side (phone tag, accessibility label, terminal table); trades still show Long or Short. New helper `sideLabel` with a unit test; the browser test now fails if a bare note ever looks like a long or short.
- **Why this one:** it is a misleading label in a place where a beginner records their own decisions; honesty beats polish.
- **Verified:** backend 830 tests, web and phone type checks and unit tests (phone 35), browser suite 44 of 44; viewed the new Journal screenshot.
- **Still open:** the top-of-screen silver glow ends in a faint hard edge near 600px on every phone tab (add a final fade to the background colour): next cycle's candidate. Also: Stocks empty-state suggestions; loading states for Discover and Strategy Lab.

## 2026-11-07, cycle 1: Macro says "indicators unavailable" once, in plain words
- **Found:** with the official data unreachable, the Macro screen listed eight red rows reading "Unavailable: unavailable (CPIAUCSL)": repetitive, and raw series codes mean nothing to a beginner.
- **Changed:** `macro_brief.py` now returns an empty indicator list plus one `indicators_note` when none load (a different note in demo mode). A single failed indicator among working ones stays listed, with a plain reason ("no data came back from the source"). The technical detail stays in the "Some sources failed" box. Phone and terminal show the note.
- **Why this one:** it affects every first-time user who has no connection to FRED, and it keeps the honesty rule (missing data is said to be missing) while being readable.
- **Verified:** backend 830 tests pass (2 new, 1 updated because it asserted the old raw-code wording), web and phone type checks and unit tests pass, browser suite 44 of 44 including a stricter Macro check; viewed the phone screenshot.
- **Not verified:** live FRED data from the sandbox (indicators show as unavailable here).
- **Next candidates:** the top-of-screen glow ends in a faint hard edge near 600px on phone screens (add a final fade to the background colour); Stocks empty state could offer one-tap suggestions; Discover and Strategy Lab phone loading states.

## 2026-11-06: loop set up
- Added `LOOP.md` (the rules and the cycle) and this log.
- State at start: Signal phone app and ATLAS terminal both have the five destinations (BTC, Stocks, Macro, Discover, Journal), the BTC Strategy Lab, Stock Research, Macro Intelligence, Discover and the Journal, in the silver gradient look.
- Not yet verified against live data: Yahoo prices (blocked in the sandbox), so Discover prices, earnings dates and stock valuation have only been tested with fakes.
- Known gaps (see the backlog in `LOOP.md`): Discover covers about 100 large caps; Macro shows only the 2-year and 10-year yields; PCE and GDP release dates are not loaded.
