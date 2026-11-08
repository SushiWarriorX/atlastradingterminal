# Improvement log

Newest entry first. Written by the scheduled improvement loop (see `LOOP.md`) and by hand.




















## 2026-11-08 · Improvement loop (6-hour): no change
- **Checked:** clean tree after the data and strategy cycles; backend 1012 passed, phone 43 unit + 48 of 48 browser checks, terminal 10 tests + build + desk browser check, all run minutes earlier. Viewed the phone Macro screenshot: top of screen reads correctly (calendar, plain "indicators could not be loaded" message, SOFR with date).
- **Not verified:** the new Fed liquidity card sits below the fold of that screenshot and was not looked at as an image (its text and states are covered by the browser checks).
- **Why no change:** nothing defective found, and the last hour already added a data source and a strategy; no work invented. Next candidates: scroll-through screenshots of the lower Macro cards, Journal CSV export.

## 2026-11-08 · Data cycle 10 and strategy cycle 3 (parallel loops)
- **Data:** NY Fed repo and reverse repo operations (free, official, no key). Backend `fedops.py` (7 tests, fixture from a real 120-operation response), route `/api/macro/fedops`, terminal Macro desk panel, Signal Macro card, added to the macro refresh job. Shown with its date, OVERDUE after 6 days, described as plumbing not a signal. Demo mode shows nothing.
- **Strategy:** Parabolic SAR (Wilder), fixed settings (step 0.02, max 0.2), no tuning. Frozen backtest: evidence **weak**. Whole history +2,255.5% vs holding +26,962.8%; last 30% (out of sample) +68.8% vs +187.8%, 51 trades; worst drop out of sample -35.4% vs -53.1%; 100% of nearby settings positive out of sample; doubled costs +52.4%. It did not beat holding after adjusting for risk, and the luck check (23 rules in the library) could not rule out luck. Reported as it is.
- **Checks:** backend 1012 passed, phone 43 unit + 48 browser checks, terminal 10 tests + build + browser check (new Macro desk check).
- **Skills cycle:** looked at Superpowers, megapowers, no-cape, Tackle (all hook into every session with broad access): none installed, see SKILLS_LOG.md.

## 2026-11-08 · Development-skills review routine (user request, additive)
- **Environment inspected:** skills are folders with a `SKILL.md` (name and description header, optional version/scripts/references) in the project (`.claude/skills`, none yet), the user folder, and the account-synced folder (10 skills, managed by the account, never modified). Catalog search works only inside a Claude Code session; GitHub is not reachable from the build machine.
- **Built:** `atlas/devtools/skills_review.py` + config + README + `tests/` (44 tests): inventory, needs from the project record, static inspection (critical patterns reject, risky patterns flag, nothing executed), overlap/redundancy/version/customization checks, ledger of reviews and decisions, read-only shared-budget deferral and interval stretching (same rules as the scheduler, lowest priority), approve/apply/evaluate/record-eval/adopt/rollback with backups, `add-candidate` for catalog finds, `note` for outside decisions.
- **First real run (manual):** 10 installed skills seen; needs counted from the log; 4 catalog candidates recorded as metadata-only (react-native-best-practices, a11y-enforcer, data-validation, expo); all four are marked NOT INSPECTED and cannot be installed until their files are downloaded and inspected. Nothing installed. Exit code 10 (something worth reading).
- **Bugs the tests caught in my own code:** "test" matched inside "backtest" (now whole-word starts); a candidate was compared with its own installed copy and called redundant (same-name now means update); CLI default file paths were bound at import so a test wrote the real ledger (now resolved at call time, real files cleaned up); metadata-only candidates read "0 flagged items", implying they were inspected (now "NOT INSPECTED").
- **Not active:** recurring execution. A weekly workflow is prepared (`.github/workflows/skills-review.yml`, read-only, opens/updates one issue only on exit code 10) but scheduled workflows run from the default branch only. The GitHub fetch path is mock-tested only.

## 2026-11-08 · Platform upgrade, phases 1-2: baseline and shared scheduler (user request)
- **Plan and status:** `atlas/docs/platform-plan.md` (what existed, what was built, what is verified, remaining work, cost assumptions, the three questions only the user can answer).
- **Built:** durable scheduler (`atlas_api/sched/`: settings, atomic budget reservation, interval adaptation, engine with leases, retries, dead letters, recovery, emergency stop), five default jobs (news, SEC filings, macro, crypto data, health check), `/api/ops/*`, worker process (`python -m atlas_api.worker`) plus a worker container and heartbeat health check in `docker-compose.yml`, Operations screens in the terminal Settings desk and Signal Settings.
- **Evidence:** 38 new scheduler/ops tests (including two-connection race on one budget, lease across two schedulers, crash recovery, backoff bounds, Retry-After, dead letters); a real worker process was started against a database file, ran four jobs and exited cleanly on SIGTERM; backend 1002 pass; phone browser 48/48; terminal browser check; web build.
- **Honest limits:** Claude remaining allowance is shown as unknown (no supported server-side signal for subscriptions; the API gives per-call token counts only), prices are user-entered, provider quota defaults are cautious guesses, US market holidays are not modelled, the compose worker has not been run in Docker here, and nothing is deployed.
- **Fix found on the way:** none of the existing behaviour changed; the SQLite connection now uses WAL and a 30 s busy timeout so the web process and the worker can share the file.

## 2026-11-08 · Data-source loop, cycle 9: CoinGecko whole-crypto-market snapshot
- **Queue item skipped:** Hyperliquid open interest/basis is already in the BTC derivatives panel (checked the code and the live API); logged as a duplicate. The loop searched for a new candidate instead.
- **Verified live first:** api.coingecko.com/api/v3/global (no key): total value $2.52T, Bitcoin share 60.0%, Ether 10.7%, Tether 7.0%, USD Coin 2.8%, 24h change -3.8%. Trimmed real response is the fixture.
- **Shipped:** `cgglobal.py`, `GET /api/btc/market`. Terminal: panel on the BTC desk. Signal: card on the BTC page. Shows the credit "Data provided by CoinGecko"; a rate limit (HTTP 429) is said plainly; descriptive, not a signal.
- **Tests:** 6 new backend (964 pass), phone browser 47/47 (extended), terminal browser check extended, web build.

## 2026-11-08 · Data-source loop, cycle 8: World Bank annual indicators
- **Verified live first:** api.worldbank.org (data updated 2026-10-08): GDP growth, CPI inflation and unemployment for the US, euro area, China, Japan, UK and India; newest year 2025 for most, 2024 for US inflation. Real responses are the test fixtures.
- **Shipped:** `worldbank.py`, `GET /api/macro/world`. Each country keeps its own newest year (shown), plus the change from the year before by subtraction; one failing indicator leaves the others; demo mode shows nothing. Terminal: panel on the Macro desk. Signal: card on the Macro screen.
- **Honesty built in:** labelled annual context, not a forecast or what the market expects; figures arrive months late and are revised; unemployment is a modelled estimate.
- **Tests:** 9 new backend, phone browser 47/47 (extended), web build.

## 2026-11-08 · Strategy loop, cycle 2: ADX trend (Wilder)
- **Rule (fixed from the source, queue item 1):** enter when ADX(14) > 25 and +DI > -DI; exit when +DI < -DI. Spot, long-only, fees 5 bps and slippage 5 bps per side. Not tuned.
- **Frozen backtest (all Coinbase daily history to 2026-11-08), evidence: weak.** Whole history +9,353% vs +26,911% holding; worst drop -44% vs -84%. Last 30%: +70.1% vs +187.3% holding, worst drop -31.6% vs -53.1%, 17 trades. Walk-forward +398%. All nearby settings made money out of sample; doubled costs +64% out of sample.
- **Why only weak:** it did not beat holding on risk-adjusted terms out of sample, and the luck check could not rule out luck (safe Sharpe lower bound -0.76 with 22 rules in the library).
- **Tests:** 3 new (directional movement hand-checked: in a steady rise +DI is exactly 50; no look-ahead). One test expectation was my own arithmetic slip (I first wrote +DI above 70); corrected to the hand-derived 50, the strategy code was not changed. 958 backend pass.

## 2026-11-08 · Strategy tracker, strategy loop, and a self-updating launcher (user requests)
- **Strategy tracker:** every strategy the loop adds is backtested ONCE on all BTC daily history (same evaluation as the Strategy Lab: fees, slippage, 70/30 split, walk-forward, neighbouring settings, doubled costs, luck check counting the whole library) and the result is frozen in `btclab/tracker_ledger.json`; `track_cli` refuses to rerun an id. The app then follows each rule FORWARD on bars after its add date (the only evidence nobody had seen), and says "too little to say anything" under 60 days. `GET /api/btclab/tracker`; terminal BTC desk panel under the Strategy Lab; Signal BTC page card. No forward record in demo mode.
- **Strategy loop:** `atlas/STRATEGY_LOOP.md` (rules + a queue of 20 published ideas with FIXED settings, so settings are never chosen by looking at BTC results; bad results are kept and reported). Every 10 minutes (session job).
- **Cycle 1: Aroon trend** (Chande, 1995; n=25). Evidence: weak. Whole history +14,616% vs +26,883% holding (worst drop -69% vs -84%); last 30%: +67.8% vs +187% holding; 22 out-of-sample trades; 100% of nearby settings positive out of sample; the luck check (21 rules in the library) could not rule out luck (safe Sharpe lower bound -0.69), and it did not beat holding on risk-adjusted terms.
- **Launcher:** `start-windows.ps1` now fetches GitHub on every start and fast-forwards to the latest version, reinstalls packages when `pyproject.toml` or the web `package.json` changed, restarts itself once if the start script changed, resets npm's own lock-file changes, and never overwrites the user's own changes (it says so and starts the version they have). `-NoUpdate` or `ATLAS_NO_UPDATE=1` skips it. The Signal launcher window also checks on open and says when a newer version is waiting. Not run on Windows from here (no PowerShell on the build machine): syntax reviewed only.
- **Tests:** 10 new tracker tests; 946 backend pass; phone browser 47/47 (extended); terminal browser check extended; web build.

## 2026-11-08 · Data-source loop, cycle 7: ECB euro reference exchange rates
- **Verified live first:** data-api.ecb.europa.eu CSV, 7 currencies, latest 2026-11-06 (EUR/USD 1.1165, USD per euro; JPY 176.77, GBP 0.83415 per euro). The real file (trimmed columns) is the test fixture.
- **Shipped:** `ecb.py`, `GET /api/macro/fx`. The ECB publishes euro-based rates, so dollar pairs are calculated (dollars-per-yen = dollars-per-euro divided by yen-per-euro) and quoted the usual way (EUR/USD, USD/JPY, GBP/USD, USD/CHF, USD/CNY, USD/CAD, AUD/USD). "Dollar vs it" is the change in units of the other currency per dollar, so positive always means the dollar got stronger; a test pins both directions. Terminal: panel on the Macro desk. Signal: card on the Macro screen.
- **Honesty built in:** labelled reference rates for information, not tradable quotes; once a day; overdue after 5 days; a missing currency is left out, never guessed; failure or demo shows nothing.
- **Tests:** 8 new backend (937 pass), phone browser 47/47 (extended), web build.

## 2026-11-08 · Data-source loop, cycle 6: mempool.space Bitcoin network health
- **Verified live first:** fees (fastest 2 sat/vB), mempool (61,466 transactions waiting), difficulty cycle (67% through, estimated next change -5.2%), block height 975,081, 3 months of hashrate (about 905-985 EH/s). Real responses are the test fixtures.
- **Shipped:** `onchain.py`, `GET /api/btc/network`. Three independent sections (fees and mempool, difficulty cycle, hashrate); one failing leaves the others, and a missing mempool or block height only drops that extra. Headline hashrate is a 7-day average because single days are noisy. Terminal: panel on the BTC desk. Signal: card on the BTC page.
- **Honesty built in:** "estimated next difficulty change" is labelled an estimate; "not a price signal" on both screens; a typical-transaction cost is plain arithmetic (fee rate x 140 vB) and labelled; demo mode invents nothing.
- **Tests:** 9 new backend (929 pass), phone browser 47/47 (extended), terminal browser check extended, web build.

## 2026-11-08 · Data-source loop, cycle 5: DefiLlama stablecoin supply
- **Verified live first:** stablecoins.llama.fi total USD-pegged supply $293.7B on 2026-11-08 (about $307B a month earlier, so shrinking), Tether $176.8B and USD Coin $70.6B the largest. Trimmed real responses are the test fixtures.
- **Shipped:** `stablecoins.py`, `GET /api/btc/stablecoins`. Total supply, changes over 7 days / 30 days / 90 days / 1 year (a comparison is left out when the history does not reach back, never invented), distance below the peak, 90-day bars, top 6 USD issuers with share and 7d/30d change. Non-USD stablecoins are excluded. Terminal: panel on the BTC desk. Signal: card on the BTC page.
- **Honesty built in:** labelled a liquidity gauge, not a price signal; a tracker's sum, not an official statistic; failure or either request failing shows nothing; demo mode invents nothing.
- **Tests:** 8 new backend (920 pass), phone browser 47/47 (extended), terminal browser check extended, web build.

## 2026-11-08 · Data-source loop, cycle 4: CFTC Commitments of Traders, CME Bitcoin futures
- **Verified live first:** publicreporting.cftc.gov Traders in Financial Futures, contract 133741 (CME Bitcoin), latest report 2026-11-03: open interest 17,527; leveraged funds long 5,114 / short 7,705. 60 real weeks are the test fixture.
- **Shipped:** `cftc.py`, `GET /api/btc/positioning`. Per trader group: long, short, net, change on the week, share of open interest, 1-year rank (0-100, only with 20+ weeks of data). Terminal: panel on the BTC desk. Signal: card on the BTC page.
- **Honesty built in:** covers CME Bitcoin futures only, not spot, ETFs or perps; Tuesday data published Friday (at least 3 days old, marked overdue after 12 days); the screen says net short is not the same as bearish (basis trade). Failure shows nothing; demo mode invents nothing.
- **Tests:** 8 new backend (912 pass), phone browser 47/47 (extended), terminal browser check extended, web build.

## 2026-11-08 · Data-source loop, cycle 3: US Treasury yield curve and debt
- **Verified live first:** home.treasury.gov daily par yield curve XML (10Y 4.86%, 2Y 4.51% on 2026-11-06) and FiscalData Debt to the Penny ($40.56T on 2026-11-05). Real responses are the test fixtures.
- **Shipped:** `treasury.py` and `GET /api/macro/treasury`. Full curve 1M-30Y with change vs previous day and about a month ago, 2s10s and 3m10y spreads with inversion flags, and total debt (held by public / intragovernmental, daily and yearly change). Terminal: new panel on the Macro desk. Signal: new card on the Macro screen. Each half fails on its own and says so; demo mode shows nothing invented. XML with a DOCTYPE or entities is refused.
- **Tests:** 8 new backend (904 pass), phone browser 47/47, web build.

## 2026-11-08 · Data-source loop, cycle 2: NY Fed SOFR
- **Verified live first:** markets.newyorkfed.org answered with SOFR 3.92% for 2026-11-05 (percentiles, volume). A real response is the test fixture.
- **Shipped:** `nyfed.py`; SOFR is a key indicator right after the Fed target range in Macro (terminal and Signal), with its date, daily change and freshness. Failure shows "unavailable" with a reason; demo mode shows nothing.
- **Bug caught by the browser test:** SOFR loading alone hid the "FRED could not be loaded" message. The one-message rule now ignores SOFR and keeps loaded rows.
- **Tests:** 6 new backend; 47/47 phone browser; 896+ backend pass.

## 2026-11-08 · Narrative of the day in Discover (user request)
- **What:** every UTC day the app features one market theme (Quantum, Nuclear and uranium, Robotics, AI infrastructure, Power, Space, Cybersecurity, Defense and drones, Obesity drugs, Chip equipment, Gold, Crypto-linked stocks, Solar, Fintech, Oil and gas). `GET /api/discover/narrative` (saved per day in `narrative_runs`, migration 016), `/api/discover/narrative/history`.
- **How it picks:** fixed baskets of liquid US stocks. Four measures: median one-month return versus SPY (40%), share above the 50-day average (25%), volume versus normal (15%), headlines in the last 48 hours from the user's RSS feeds (20%). Highest score among themes not featured in the previous 5 calendar days wins. Missing news is left out and the rest rescaled, never counted as zero.
- **Shows:** why it is in focus (facts), the basket with moves, hand-written context (labelled as such), risks, volatility note, headlines, other themes, method. Terminal: top of the Discover/Scanner desk. Signal: top of the Discover tab.
- **Bugs caught by tests while building:** "last 5 days" originally meant the last 5 saved rows; themes with more keywords collected more headlines (now max 3 keywords each).
- **Not verified live:** the sandbox cannot reach Yahoo, so price fetching for the baskets runs on test data here; it uses the same bar source as Discover. Some tickers may have changed symbol; a theme needs 4 names with data or it is skipped.
- **Tests:** 10 backend, phone browser 47/47.

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
