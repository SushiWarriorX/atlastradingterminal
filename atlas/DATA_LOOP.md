# ATLAS data-source loop (every 10 minutes)

Goal: keep adding **new, free, public data** to Signal, one verified source per cycle. Research only: no order controls, ever.

## Each cycle (do these in order; stop early and log if a step fails)
1. Read `atlas/DATA_SOURCES.md` (what is live, what is queued, what was rejected and why). Pick the first QUEUED candidate; if none, search the web for one new candidate (free, no key, official or clearly public, useful for BTC, US stocks or macro) and add it to the queue.
   Finding an ECB series (checked live 2026-11-17; the ECB website and the Data Portal pages are refused by the proxy): `GET https://data-api.ecb.europa.eu/service/dataflow/ECB?detail=allstubs` lists the ECB's own dataflows in one small request, `.../service/dataflow/all/<ID>?detail=allstubs` finds a flow of any agency (Eurostat's `LFSI` and `MNA` are served through it), and `.../service/data/<ID>/<key>?lastNObservations=3&format=csvdata` returns a few values with their title, unit, multiplier and status columns. Eurostat's own host (`ec.europa.eu`) is refused too: BLOCKED, do not go round it (loop-rules item 5).
2. **Check it live from this machine** with a plain request (use `ATLAS_SEC_CONTACT` style polite User-Agent; never put the user's account email in a request). Record the HTTP status and a real sample. If it cannot be reached here, mark it BLOCKED (note the host) and move to the next candidate. Never ship a source that was not fetched live in this cycle.
3. Check terms: public/open data or an API that allows this use, no login, no key, no scraping of pages that forbid it, no paid plan. Otherwise REJECTED with the reason.
   Read the notes of EVERY series you will use on its source page, not only the licence line (found 2026-11-17: a series that is calculated by a third party from the others, with its own copyright notice, sat among the three "parts" of a candidate and made its exact built-in check true by construction). A part that is derived from the others cannot check them, and a series with a third-party copyright notice is HELD, not shipped.
4. Build it as a provider with its own cache, timeout and a clear "unavailable" state (word the reason with `fail_reason(e)` from `atlas_api/failreason.py`, never with the raw exception: a test fails if a provider prints `{type(e).__name__}: {str(e)}`). Every figure carries source name, observation date and freshness. Never fill a gap with a guess. Save a small real sample as a test fixture.
5. Show it: a card on the relevant Signal tab (or an extra row in an existing card), unless it is a research-only input for the experiments (then record it under RESEARCH SOURCES in `atlas/DATA_SOURCES.md` instead). Label what it is and what it is not.
6. Tests: backend pytest (add tests for parsing, failure and staleness), mobile typecheck/tests; if UI changed, `npm run export:web` then `node e2e/signal.e2e.cjs`. All must pass.
7. Update `atlas/DATA_SOURCES.md` and `atlas/IMPROVEMENT_LOG.md`, commit, push to `feature/research-modules`. Do not merge, keep the PR draft.
8. Reply with a 3-line update: **source added**, what it shows, where to see it (or why nothing shipped this cycle).

## Hard rules
- Free and keyless only. A key, a paid plan or a terms problem is a question for the user, not something to work around.
- No secrets in the repo; the SEC contact stays in the environment variable.
- No fabricated data, no demo data presented as real. Demo mode stays labelled.
- One source per cycle. If a cycle ships nothing, say so plainly.
- If tests fail and the cause is not obvious in one try, revert the change and log it.
- If the same blocker (for example a host this sandbox cannot reach) stops two cycles in a row, stop the loop's work and tell the user what is needed instead of repeating.
