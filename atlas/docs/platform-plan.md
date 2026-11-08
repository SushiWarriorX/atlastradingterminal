# Platform upgrade: plan, status and operating notes

Goal: turn the app into a private, cloud-accessible research platform with recurring data collection, strategy backtesting, position scenarios and maintenance checks. Research only: live trading stays disabled and nothing here presents history or forecasts as guaranteed.

Status at 2026-11-08 (branch `feature/research-modules`, draft PR #7, nothing merged):

| Phase | Status |
|---|---|
| 1. Inspect and baseline | Done (below) |
| 2. Shared scheduler, persistence, quota controls, operations dashboard | Done and verified (below) |
| 3. Research connectors, source registry, Research Intelligence | Not started |
| 4. Stock Strategy Lab (bounded experiments, holdout, multiple-testing control) | Not started (the BTC Strategy Lab and tracker already exist and follow these rules) |
| 5. Position Scenarios | Not started |
| 6. Cloud deployment, PWA, backups, CI, rollback, bug audit | Partly present (Docker + Caddy + password login + CI existed; worker container added); not deployed |

## Phase 1: what the app was

- **Stack:** FastAPI (Python 3.13 tested; Docker uses 3.12) + one SQLite file with numbered SQL migrations (017 now); React/Vite terminal; Expo/React Native phone app that also runs in the browser.
- **Background work before this phase:** in-process timer loops inside the web server (alerts, paper trading, news, derivatives). They hold no state, survive nothing, and stop when the server stops.
- **Deployment before this phase:** `Dockerfile`, `docker-compose.yml` (app + Caddy HTTPS), single-user password login (`ATLAS_AUTH_PASSWORD`), `docs/cloud-deploy.md` for a small VPS. No worker, no backups job, no staging.
- **CI before this phase:** GitHub Actions: backend `pytest`, web build and tests, mobile typecheck and tests.
- **Baseline checks (run before changing anything in this phase, same machine):** backend 964 tests passed, phone 43 unit tests + 47 browser checks, web 10 tests + build + browser checks.
- **Data providers:** Coinbase, Hyperliquid, Yahoo (unofficial, not reachable from the build machine), FRED (not reachable from the build machine), SEC EDGAR (needs `ATLAS_SEC_CONTACT`), RSS, plus the free sources in `atlas/DATA_SOURCES.md`.

## Phase 2: the scheduler (verified)

**Process model.** Jobs run in a scheduler that keeps all state in the database. Locally it runs inside the app. In the cloud it runs in a separate **worker container** (`python -m atlas_api.worker`), so jobs continue when the laptop, browser and phone are closed. The web container is started with `ATLAS_SCHEDULER=off`. Both share one database volume (WAL mode, 30 s busy timeout).

**Not an AI loop.** Handlers are ordinary deterministic code. None of the five jobs registered so far calls Claude; the machinery for AI jobs (token limits, reservations, cost recording) is in place and tested for the experiment and explanation jobs added in later phases.

**Safety properties, each covered by a test:**
- Leases stop overlapping and duplicate runs, including from two processes on one database file.
- Budget reservation is atomic (`BEGIN IMMEDIATE`): six threads on two connections racing for a budget that fits two reservations produced exactly two.
- Reservation is all-or-nothing across buckets; a refused request charges nothing.
- A crash leaves its reservation counted as spent (we cannot know it was not).
- Retries: bounded exponential backoff with jitter (30 s doubling to 1 h), `Retry-After` respected (capped at 6 h), then a dead-letter record after 5 failures in a row.
- Restart recovery: interrupted runs are detected from expired leases and resumed from their checkpoint.
- Timeouts per run; emergency stop cancels at the next check and blocks manual runs; pause stops scheduled runs but allows manual ones.
- Notices are deduplicated (same message for the same cause is suppressed for 24 h; a changed message goes through) and sent to Telegram when it is configured.

**How the effective interval is decided** (`sched/intervals.py`, pure and tested). Start from the interval you set for the current state (market hours or not, US Eastern 09:30-16:00 on weekdays; US market holidays are not modelled). Then:
1. Under 50% of a limited allowance left: slow down by 0.5 / fraction left (at most 8x).
2. Only the usage reserve (default 20%) left: optional work (priority 1-4) is deferred until the allowance resets; essential work (priority 5) may use it.
3. A job whose average cost times runs per day would exceed its share of the day's budget is slowed until it fits.
4. Low-priority jobs (1-2) slow a further 1.5x while any budget is under 80%.
5. Very stale data on an important job (priority 4-5) can tighten the interval, never below half your setting.
The dashboard shows the effective interval, whether it differs from yours, and every reason.

**Allowances (settings, editable from the app).** Claude daily token budget, optional daily and monthly dollar limits, and per-provider hourly quotas for SEC, RSS, Yahoo and other public APIs, plus worker runtime per day. The provider defaults are conservative guesses I chose, not published limits. A limit of 0 means "none set".

**Claude access and usage telemetry (what is and is not known).** I cannot tell which Claude access you have; the setting starts as `unknown` and the app never assumes it. From the official documentation (read 2026-11-08 by a helper, with links; I did not independently re-read every page):
- A server-side product should use an **API key** (Console, pay-as-you-go). Anthropic's terms say developers building products, including on the Agent SDK, should use API-key authentication, and a subscription login must not be offered to others or routed through. Scripted use of a personal subscription exists (`claude -p`, a long-lived token) but the documentation I was given does not endorse it for an always-on server product.
- Whether a subscription includes API credits is not stated explicitly in the pages read; the documented billing is separate.
- The API returns token counts for every call and rate-limit headers (`anthropic-ratelimit-*`, `retry-after` on some 429s). The organisation-level cost API needs an admin key and is not available to individual accounts. A Console monthly spend limit can be set; hitting your own limit returns HTTP 400, hitting the tier cap returns 429 with no `retry-after`.
- The only documented way to read remaining subscription allowance is inside Claude Code's status line (five-hour and seven-day percentage used and reset time). Nothing a server can poll.
- So this app shows **"usage unknown"** for the provider's remaining allowance and enforces **your own configured budgets**, counting what the app itself spends from per-call token counts.
- Prices are not assumed. Enter the current price per million tokens in settings to turn token counts into dollars; until then dollar cost shows as unknown. For reference only, the helper read these prices on 2026-11-08 (USD per million input / output tokens): Haiku 5.5 $0.10 / $0.50, Sonnet 5.5 $2 / $10, Opus 5.5 $4 / $20. Please confirm on the pricing page before relying on them.

**Cost estimate (assumptions stated).**
- Hosting: a small VPS, about $6-12 a month (the existing `cloud-deploy.md` estimate; provider prices change, please check). The worker adds no extra server: it is a second container on the same machine.
- Database and storage: SQLite on the VPS volume, no extra cost; add backup storage if you copy backups off-site.
- Data providers: all current sources are free and keyless; X/Twitter access (Phase 3) would be a paid API, and I will not enable it without your decision.
- Claude: **$0 today** (no job calls Claude yet). Ceiling if later jobs use the full default daily token budget of 200,000 tokens at a 70/30 input/output split on Sonnet 5.5 at the prices above: 0.14M x $2 + 0.06M x $10 = $0.88 a day, about $26 a month. Caching and batch discounts could lower it; the budget limits cap it.

**Operating it.**
- Local: nothing to do; the scheduler starts with the app. Settings desk (terminal) or Settings screen (phone) shows Operations.
- Cloud: `docker compose up -d --build` starts the web app, the worker and Caddy. The worker's health check passes while its heartbeat is under 3 minutes old. `docker compose logs -f worker` shows runs.
- Controls: pause all, resume, emergency stop (confirmation required), run a job now, change each job's intervals and on/off, retry or dismiss dead letters, set reserve and Claude budgets.
- The cloud deployment itself has NOT been done or tested (see "Remaining").

## Remaining (honest list)

- Phases 3-6 above. Phase 6 includes backup and restore testing, staging, the rollback procedure, PWA install and the audit of the existing app for financial-arithmetic, leakage, timezone and security bugs.
- A real Windows or phone run of the new screens; the browser checks use the phone app in a desktop browser.
- Everything in the cloud is untested until a server exists.

## Questions only you can answer

1. **Which Claude access do you have** (subscription, Claude Code, or an API key from console.anthropic.com)? For the cloud worker I recommend an API key with a workspace spend limit you set. Add it only as a server environment variable, never in the browser or the repository.
2. **Hosting and spending:** the existing setup is one small VPS running Docker Compose with HTTPS. Do you approve about $6-12 a month for that, and do you have a provider account or a domain? I will prepare everything and will not spend anything without your yes.
3. **X/Twitter:** do you have authorised API access (which is paid) for the accounts and lists you want? If not I will mark it unavailable and skip it.
