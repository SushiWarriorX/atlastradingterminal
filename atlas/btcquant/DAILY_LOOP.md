# btcquant daily run (00:15 UTC)

The scheduled task "btcquant daily run" fires at 00:15 UTC every day (the owner's mission of 2026-11-15; `PROTOCOL.md` sections 9 and 10). It is **not** one of the hourly jobs and does not replace one: the hourly cycle at :17 runs its own job as usual, two minutes later.

## What to do (repo `/home/user/atlastradingterminal`, branch `feature/research-modules`)

1. `git pull --ff-only`. Never merge, never force-push.
2. `cd atlas/backend && python3 -m atlas_api.btcquant.daily`. It prints one status line and exits 0; exit 1 means a step failed and the line says which. If Python lacks the packages: `python3 -m venv /tmp/atlasvenv && /tmp/atlasvenv/bin/pip install -e atlas/backend[dev]`.
3. Read `atlas/btcquant/reports/latest.md` (the day's report) and check `atlas/btcquant/dashboard.json`: `frozen_check` must be empty, `data.stale` false, and every account's `days` must have gone up by one (by more if earlier days were missed: the run steps every account through each newly completed candle in order, so a missed day is caught up, never skipped).
4. Commit only what the run writes: `atlas/btcquant/data`, `atlas/btcquant/state`, `atlas/btcquant/reports`, `atlas/btcquant/dashboard.json`. Message `btcquant daily run YYYY-MM-DD`, ending with the usual attribution lines. Push to `feature/research-modules`.
5. Report in plain English, three to five sentences: the new candle and its close; any order signalled, filled, stopped or halted by the circuit breaker today (they are in the report, worded as the phone shows them); each paper account's return since it opened, against buying and holding; anything that went wrong. Say whether anything passed the "credibly profitable" bar: it stays **not yet** until an admitted challenger completes the forward gates (P5: at least 90 days, at least 5 trades, no circuit-breaker trip, not more than 5 points behind its exposure-matched hold). Nothing is admitted today, so nothing can pass.

## What the daily run never does

- It never re-runs the research (`python -m atlas_api.btcquant.research` refuses a repeat on the same protocol and data), never changes a family, a protocol constant, an account's rules or a registry entry, and never touches an account by hand.
- It never places an order. Nothing in this system can; every account is a simulation, and the ledger records each order at the moment its rule signals it, and each fill at the next open.
- A failed download is reported and the stored candles are used. A missing candle stops the affected account and says so; the next run catches up.

## Where the owner sees it

The Signal phone app, **Journey** tab (`GET /api/btcquant/paper`, built from `dashboard.json`, the research report, the stored candles and the ledgers): the verdict of the research run, the paper accounts as cards, each strategy with its backtest beside holding Bitcoin, and every order recorded on signal. The same facts are in `reports/latest.md`.
