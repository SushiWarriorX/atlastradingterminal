# Improvement loop: how each cycle works

This file is the standing brief for the scheduled review-and-improve loop. One cycle = review the app, choose the single most valuable improvement, make it, prove it works, record it. Read it at the start of every cycle.

## Hard rules (never broken, no matter what a cycle finds)
1. **Research and paper only.** Never add order, trade, or live-trading controls. Never connect anything that moves money.
2. **No fabricated data.** Every number carries a source and a freshness label (LIVE / DELAYED / HISTORICAL / STALE / DEMO / UNAVAILABLE). Missing data stays missing and is said to be missing.
3. **No secrets in the repo.** Keys and contact emails live in environment settings (e.g. `ATLAS_SEC_CONTACT`), never in committed files.
4. **No paid APIs** or new paid services without the owner's explicit approval.
5. **Git safety:** work only on `feature/research-modules`; never force-push; never merge a pull request; keep PR #7 a draft; never touch other branches.
6. **Keep the look the owner approved** (silver and graphite gradients, Figtree type, pill buttons). Do not change the theme, fonts or layout style unless the owner asks. Small contrast or spacing fixes are fine.
7. **Do not remove features** the owner asked for. Do not rename routes or break saved data (migrations only add).
8. **One focused change per cycle** (about 150 lines or fewer, plus tests). Prefer fixing real defects over adding features.
9. **Everything must pass before pushing:** backend `pytest`, web `tsc` and `npm test`, mobile `tsc` and `npm test`, and the browser suite `node e2e/signal.e2e.cjs` (all scenarios, after `npx expo export --platform web`). If a change cannot be made to pass within the cycle, revert it and log why. Never skip, disable or weaken a test to get green.
10. **Be honest in the log.** Say what was verified and what could not be (for example: Yahoo is blocked in the sandbox, so live prices are untested).

## One cycle, step by step
1. **Sync.** `git fetch`, `git pull` on the branch. If the Python venv is missing: `python3 -m venv /tmp/atlasvenv && /tmp/atlasvenv/bin/pip install -e atlas/backend[dev]` (set `SIGNAL_E2E_PYTHON=/tmp/atlasvenv/bin/python` for the browser suite). Install web and mobile dependencies if needed.
2. **Review.** Read `IMPROVEMENT_LOG.md` and the backlog below. Run all test suites. Run the demo backend and look at real screenshots of every phone screen (via `SIGNAL_E2E_SHOTS`) and the terminal desks (Playwright). Actually view the images. Look for: wrong or misleading numbers, unclear wording, missing or ugly empty/error/loading states, contrast and tap-target problems, slow screens, dead ends, missing tests, stale docs.
3. **Decide.** Pick the one change with the best value for a beginner using this app to research (correctness and honesty first, then clarity, then polish). Say in one sentence why this beats the other candidates.
4. **Implement** with tests. Follow existing patterns (backend Decimal money, `ok()` responses, per-server query keys on the phone, labels on every figure).
5. **Verify.** Run every check in rule 9. For UI changes, take a before and after screenshot and view them.
6. **Record and push.** Append an entry to `atlas/IMPROVEMENT_LOG.md` (date, what changed, why, how it was verified, what is still untested, next candidates). Commit with a clear message ending with the standard attribution lines, then `git push origin feature/research-modules` (retry up to 4 times with 2, 4, 8, 16 second pauses on network errors).
7. **Report** to the owner in plain words, in a few sentences: what was improved, what was checked, anything needing their decision.

If a cycle finds nothing worth changing, log "no change" with what was checked. Do not invent work.

## Backlog (seed ideas; the loop may add its own)
- Run Yahoo-dependent paths (Discover prices, earnings dates, stock valuation) against live data when the network allows; fix whatever breaks.
- Macro: add the full Treasury curve and auction results from Treasury's free data; load PCE and GDP release dates from the BEA schedule.
- Discover: widen the universe beyond about 100 large caps using the free Nasdaq Trader directory, with a liquidity gate; keep scan time reasonable.
- Strategy Lab: show a plain-English "what this result means" line per strategy; add cost-sensitivity and regime breakdown (bull / bear / sideways) to the detail view.
- Journal: CSV export; per-tag stats; make sure the 30-trade reliability note is shown on phone too.
- Phone: pull-to-refresh and offline notices on the new tabs; accessibility labels and larger tap targets; skeletons for slow loads.
- Terminal: keyboard shortcuts for the five desks; empty-state wording; saved layout reset per desk.
- Docs: a short beginner "first ten minutes" guide with screenshots; keep the README run steps current for Windows and Mac.
- Tests: raise coverage on `btclab` edge cases (zero-trade strategies, gaps in bars) and on `discover` (missing filings).
