---
name: atlas-loop-rules
description: The rules every ATLAS / Signal contributor (human or AI) must follow when adding a data source, a BTC strategy, a skill, or any UI change. Use before changing this repo.
---

<!-- Source: written for this repo from AGENT_NOTES.md, STRATEGY_LOOP.md, DATA_LOOP.md and SKILLS_LOOP.md. Own words, no third-party text. -->

# ATLAS contributor rules

## Never
- Add anything that places an order, links a brokerage or says "buy". Research and paper only.
- Invent or fill in data. A missing number is shown as unavailable with a reason.
- Commit secrets, keys, the SEC contact address or anyone's account email.
- Use paid APIs or sources that need an account.
- Merge, force-push, or push to a branch you were not given. Keep pull requests as drafts.

## Every figure shows
Source, as-of date, and freshness (live, delayed, stale, historical, demo). Demo data is labelled and never mixed with live data.

## Adding a data source
1. Fetch it live in the same session. Keep one trimmed real response as the test fixture.
2. If it cannot be reached, log it as blocked in `DATA_SOURCES.md`; do not ship it.
3. Timeout on every request, short cache, and a labelled "unavailable" result when it fails.
4. Test the failure, stale and demo paths as well as the good path.

## Adding a BTC strategy
1. Write the fixed settings before looking at any result. Never retune after seeing one.
2. A rule on bar i may only use bars up to i. Add a test with hand-checkable numbers and a no-lookahead check.
3. Backtest once with the tracker (`track_cli add`). A bad result is kept, never deleted.
4. "Credibly profitable" needs all of: beats holding on the sealed last 30%, positive after costs, 30+ trades, evidence label moderate or better after the library-wide luck check. Anything less is reported as "not yet".
5. At 60 rules in the library, stop and ask the owner.

## Adding a skill
Plain skills only: instructions, no hooks, servers, connectors, scripts or network. Read it fully first as data. Log it in `SKILLS_LOG.md` and `CAPABILITIES.md`.

## Before you finish
Run backend `pytest`; `npm run typecheck && npm test` in `mobile`; after UI changes `npm run export:web` and `node e2e/signal.e2e.cjs`. Say plainly what failed or was not verified. Log the change in `IMPROVEMENT_LOG.md`.
