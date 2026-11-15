# btcquant build plan (the owner's mission of 2026-11-15)

The owner asked for an autonomous Bitcoin quantitative research and paper trading system: strategy library, rigorous backtests, champion versus challenger, persistent paper accounts that record every trade on signal, daily reports, retained experiment history, and a daily run at 00:15 UTC. The rules are in `PROTOCOL.md` (pre-registered, version 1). **Anyone continuing the work (including an hourly cycle) takes the first unchecked step below, writes its tests first, and marks it done here with the commit.**

Code lives in `atlas/backend/atlas_api/btcquant/`, tests in `atlas/backend/tests/test_btcquant_*.py`, artifacts (data, state, reports, registry, strategy notes) in `atlas/btcquant/`.

## Steps

- [x] 0. Protocol written and pushed before any code (`PROTOCOL.md`).
- [x] 1. Data layer (`btcquant/data.py`, 24 tests): Coinbase BTC-USD daily and hourly download with paging, validation, complete-versus-incomplete candle flag, manifest (`btcquant/data/manifest.json`), CSV storage; 4-hour candles built from complete hours; first download committed 2026-11-15: 2,875 daily candles 2019-01-01 to 2026-11-14 with no gaps, 68,990 hourly candles with 9 reported gaps (1 to 5 missing hours each, never filled).
- [x] 2. Indicators (`btcquant/indicators.py`, 10 tests with hand-worked numbers).
- [x] 3. Account and execution engine (`btcquant/account.py`, 30 tests; 41 deliberate breakages each caught by a failing test, run clean): next-open fills, fee and slippage, 1% risk sizing, stops, armed re-entry, circuit breaker, weight mode, as one step function with a signal-time order ledger.
- [x] 4. Strategy families 1 to 12 plus benchmarks as code (`btcquant/strategies.py`, 54 tests; 47 deliberate breakages each caught), with `strategies/<family>.md` notes and `SOURCES.md` pushed first (commit 420babb, protocol v1.1) and a future-perturbation test over all 100 configurations. Nothing has been run on real data.
- [x] 5. Metrics (`btcquant/metrics.py`, 20 tests with hand-worked numbers; 48 deliberate breakages each caught): every number of protocol section 6, regimes with their equality boundaries, the exposure-matched hold with costs.
- [x] 6. Backtest runner (`btcquant/backtest.py`, 19 tests; 32 deliberate breakages each caught): periods on the calendar, benchmarks, exposure-matched hold, full-exposure and cost sensitivities, regimes, circuit-breaker cool-off; no look-ahead from the runner's point of view.
- [x] 7. Validation (`btcquant/validation.py`, 38 tests; 79 deliberate breakages each caught; `btcquant/calibration.py` and `CALIBRATION.md`): neighbour-smoothed selection, stability, walk-forward, cost and full-exposure sensitivity, deflated Sharpe (reported), random-timing null, gates A1 to A5 and P1 to P5. The v1.1 gates failed a calibration on synthetic data and became v1.2 before the real data was touched.
- [x] 8. Registry (`btcquant/registry.py`, 17 tests; 29 breakages caught): candidate log with specification hash and renamed-copy check at 0.90, challengers and champions with frozen specifications, a once-only look at TEST.
- [x] 9. Paper engine (`btcquant/paper.py`, 19 tests; 20 breakages caught): persistent accounts, ledger written on signal, idempotent catch-up, refuses to step across a missing candle, exact parity with the backtest candle by candle.
- [x] 10. Daily runner (`btcquant/daily.py`, 16 tests; with the research run in `btcquant/research.py`, 11 tests; 42 breakages caught): data update, accounts, catch-up, report, `dashboard.json`.
- [x] 11. First full research run, once, on the real data (2026-11-15 10:34 UTC, protocol 1.2, 2,875 daily candles to 2026-11-14, hash c9cb205d...): **0 of 12 families admitted** (11 rejected, 1 too thin). Record: `reports/research_1.2.md` and `.json`, `registry/`. The twelve chosen configurations are paper-traded as monitors; the benchmarks and the empty $100,000 portfolio are open. Nothing was run on the TEST period.
- [x] 12. Schedule (00:15 UTC, a scheduled task bound to the hourly session), `DAILY_LOOP.md`, and the Signal **Journey** tab for the paper accounts (owner request 2026-11-15: TradingView-style redesign of the app plus a Journey page that runs the backtested strategies; `GET /api/btcquant/paper`, `view.py` with 18 tests and 52 breakages caught, phone `JourneyView`, 18 unit tests for its helpers and a browser check).
- [x] 13. Research queue (`RESEARCH_QUEUE.md`, `btcquant/novelty.py`, 32 tests, 47 deliberate breakages caught): six hypotheses found in published and practitioner sources, their rules and planned grids fixed and pushed BEFORE the screen (a07df08), then screened against all 100 existing configurations on the TRAIN and VALIDATION days: none is a renamed copy (highest correlations +0.02 to +0.69). The order is fixed by the written priority rule: `monday`, `three_down`, `volume_surge`, `squeeze_break`, `money_flow`, `near_high`. Nothing was run.
- [x] 14a. Engineering for adding a family (protocol amendment v1.2b, tests in `tests/test_btcquant_versions.py`, 14 tests, 31 deliberate breakages caught): a family carries the protocol version it was pre-registered under, so a version bump changes no specification hash or account id; a research run covers the families of its own version; the runs of all versions read as one record (dashboard, daily report, phone view).
- [ ] 14b. Take the queue one entry at a time, `monday` first: restate the calibration for thirteen families, then the note, the protocol amendment (v1.3) and the family with its tests, pushed, then one run, logged whatever it shows.

## Rules for continuing

- Never run a family or a candidate before its protocol entry and note exist and are pushed.
- Never change a family after its VALIDATION or TEST result is seen; make a new version.
- Mutation-check the accounting and the gates (break one comparison, expect a failing test).
- Say plainly what is not verified. Do not claim anything makes money.
