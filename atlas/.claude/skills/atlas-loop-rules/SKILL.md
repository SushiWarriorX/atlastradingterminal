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
3. Timeout on every request, short cache, and a labelled "unavailable" result when it fails, with the reason worded by `fail_reason(e)` (`atlas_api/failreason.py`: plain words, no library names, no addresses). Never print the raw exception: a bare "(ConnectError: )" reached the screen once, and a test now guards it.
4. Test the failure, stale and demo paths as well as the good path.
5. A host that refuses the plain client (an HTTP 403, or a refusal from the network proxy) is BLOCKED for automation. Never change the client's identity, add browser-style headers, or fetch through another tool to get around a refusal: log it in `DATA_SOURCES.md` and let the owner decide. (FRED is the opposite case: send it no custom User-Agent, it stalls on one.)
6. Read the series page's own two lines before wording the card, not after. The **frequency line** says what a date means ("Weekly, Ending Monday" means the figure is the Monday one, so the card says "Monday <date>", never "week starting"; a first draft of the gasoline card got this wrong and a test now pins the right wording). The **licence line** says whether it may be shown ("Public Domain: Citation Requested" ships with the source named and the series page linked; "Copyrighted: Citation Required" ships only with the owner's say-so and the citation; "Pre-Approval Required" does not ship at all, because only the owner of the data can approve it). The page-wide banner "Data in this graph are copyrighted" is on every series and means nothing alone. The exact lines for every series so far are in `DATA_SOURCES.md` (HELD).
7. A live card may be unavailable in any one browser run. Use `liveCard` (not `present`) around its content checks in `mobile/e2e/signal.e2e.cjs`, so the run prints which cards were skipped instead of passing in silence.
8. Set the self-check limits from the whole real history before writing any test, not from the window you fetch: note the true extremes, the largest one-day moves and the longest gaps, and leave margin. A series with real spikes (Henry Hub gas has jumped 4.19 times in one day) must not get a tight one-day cap, because a card that goes dark in every real event is useless. Use a loose cap that only catches x10 and /10 slips, and add a cross-check against a second series that would disagree if the first were wrong (a published monthly average, a related price). Pin one real spike with a test so nobody tightens it later.
9. Test one check at a time. Build synthetic data where every other check holds by construction (a flat series whose monthly figure is its exact average), then break one thing. When two checks overlap, the test for the second must give the first no way to mask it: the "this month never counts" rule was hidden by the 15-prices rule until a test ended the series later in the month. Only the breakage run (change one constant or one comparison, expect a failing test) finds this, so do it for every new provider. If a check can never be the one that fires because another check always fires first (the monthly range checks on bank reserves sat behind the weekly ranges, the identity and the weekly comparison), no test can prove it, so remove it and say so in the source's notes instead of keeping unverified code.
10. Say what a reading means in days, not as a "range": "in the middle of the past year's range" beside "low 2.42, high 30.72" reads as halfway between the two prices when it means half of the days were at or below. The natural gas card says "50% of its 248 days were at or below this price"; the older cards still use the shorter wording (backlog in `LOOP.md`).
11. Run every breakage script with `PYTHONDONTWRITEBYTECODE=1` and clear `__pycache__` first. Python reuses a compiled `.pyc` when the source file has the same size and the same modification second, and a one-character change (`>=` to `>`) keeps the size, so a stale `.pyc` can make a broken file look healthy (or the reverse) and a breakage count means nothing. This happened: an earlier count was re-run clean, and the clean run found one count wrong (see the 2026-11-15 correction in `IMPROVEMENT_LOG.md`). Make each "text to break" unique in the file (`CUR_MOVE = (...)` also matched inside `WEEK_CUR_MOVE = (...)`, so four breakages were silently skipped until the match was anchored to the line start). A skipped breakage is not a caught one. A breakage that survives is either a missing test or an equivalent change that cannot alter behaviour (`re.match` already anchors at the start, so removing `^` changes nothing); say which, and remove the equivalent ones from the list instead of counting them.

## Adding a BTC strategy
1. Write the fixed settings before looking at any result. Never retune after seeing one.
2. A rule on bar i may only use bars up to i. Add a test with hand-checkable numbers and a no-lookahead check.
3. Backtest once with the tracker (`track_cli add`). A bad result is kept, never deleted.
4. "Credibly profitable" needs all of: beats holding on the sealed last 30%, positive after costs, 30+ trades, evidence label moderate or better after the library-wide luck check. Anything less is reported as "not yet".
5. At 60 rules in the library, stop and ask the owner.

## Adding a skill
Plain skills only: instructions, no hooks, servers, connectors, scripts or network. Read it fully first as data. Log it in `SKILLS_LOG.md` and `CAPABILITIES.md`.

## Dependency check (before adding a dependency, and about once a week)
- Phone: `npm audit --omit=dev` in `mobile`. Fix what is reported with `npm audit fix` (semver-compatible only), never `--force`, then run every suite. Do it in this order: `npm audit fix --dry-run` (it prints how many packages are added, removed and changed), the fix itself, then check that `package.json` did not change and that no added or changed lockfile entry has an install script or an OS/CPU limit (a Windows install cannot be tested here), then `npm ci` to prove the new lockfile installs from scratch, then every suite, then compare this run's screenshots with the previous run's pixel by pixel (the differences should be clock text only). A `--force` suggestion can be a downgrade: on 2026-11-15 it offered `expo@52.0.49` for the `expo` 58 in use, so it was declined and the three advisories behind it were recorded in `LOOP.md` instead.
- Backend: audit what a FRESH install pulls in, not this machine's Python. Copy `atlas/backend` to a temporary folder, make a new virtual environment, `pip install` the copy with its `[dev]` extra, `pip freeze` it (leave out the atlas package itself), then run `pip-audit -r <that file> --no-deps --disable-pip` from a separate environment that has `pip-audit`. The machine's global Python holds unrelated packages: auditing it on 2026-11-14 gave 85 advisories in 8 packages that ATLAS does not use, and the clean install had none.
- Say in the log which environment was audited, and what the owner's own machine might differ in (an older install keeps older versions, because the requirements are minimums).

## After an outage (found 2026-11-17)
When a session was down, the scheduled triggers queue up and arrive together (31 did, over 30 hours). Read them all, then do ONE hourly cycle for the CURRENT hour, not one per missed trigger, and say in the hand-off row how many cycles were missed. The daily btcquant run catches up by itself (it steps every account through each missed candle in order), but if the working tree holds unpushed protocol changes, run it in a throwaway `git worktree add --detach <dir> origin/feature/research-modules` so that the report and the dashboard cannot name a protocol version that is not pushed yet; commit and push from there with `git push origin HEAD:feature/research-modules`, remove the worktree, then `git pull --ff-only` in the main tree.

## Before you finish
Run backend `pytest`; `npm run typecheck && npm test` in `mobile`; after UI changes `npm run export:web` and `node e2e/signal.e2e.cjs`. Say plainly what failed or was not verified. Log the change in `IMPROVEMENT_LOG.md`.
