# ATLAS TERMINAL

Single-user, desktop-first trading research terminal for **BTC** and **US equities/ETFs**: command-driven workspace, deterministic technical analytics, and an AI research desk that is only allowed to use computed data.

> **Status: Phase 0 + Phase 1 milestone.** See [docs/implementation-status.md](docs/implementation-status.md) for exactly what works and what does not. Trading is **paper only**: there is no live broker connection and the live-order route always refuses.

## Run it

Requires Python 3.11+ and Node 20+.

```bash
# 1. backend (terminal 1). ATLAS_DEMO=1 uses synthetic data, labeled DEMO, so you can explore offline
cd atlas/backend
python3 -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
ATLAS_DEMO=1 python -m atlas_api        # http://127.0.0.1:8000/docs for the OpenAPI UI
```

```bash
# 2. frontend (terminal 2)
cd atlas/web
npm install
npm run dev                             # http://127.0.0.1:5173
```

Telegram alerts (optional): create a bot with @BotFather, message it once, find your chat id (for example via @userinfobot), then start the backend with `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` set. Open Settings and press **Send test message**; choose a minimum severity there. The token never leaves the backend. Alerts based on DEMO data are not sent unless you set `ATLAS_TELEGRAM_ALLOW_DEMO=1`.

**Journal and performance.** Open `JOURNAL` (or `PERF`). Import CSV exports (Variational, IBKR Flex Query, or any trades CSV): choose a preset, paste or pick the file, **preview** (nothing is saved), check the column mapping and the parsed times (set the timezone if your file uses local time), then import. Paper-trading fills appear automatically. Add your thesis, planned stop (gives the trade an R-multiple), mistakes and a screenshot to any trade. The performance panel shows statistics with sample-size warnings. The Variational export format is a best guess (its docs weren't reachable when this was built): check the mapping preview.

**Interactive Brokers (optional).** Run TWS or IB Gateway locally with the API enabled, then start the backend with `IBKR_ENABLED=1`.

```bash
# read positions and executions from ANY account (the API connection itself is read-only); default
IBKR_ENABLED=1 IBKR_MODE=readonly IBKR_PORT=7496 python -m atlas_api
# route orders to your PAPER account only (refuses live ports and any non-paper account)
IBKR_ENABLED=1 IBKR_MODE=paper_trading IBKR_PORT=7497 python -m atlas_api
```

Then **Settings > Interactive Brokers > Connect**, and **Link this account as a portfolio**. There is no mode that places orders on a live account. This was tested against a fake IBKR only: try it with a paper account and a single share first.

Live mode: drop `ATLAS_DEMO=1`. BTC comes from Coinbase's public API, equities/indices from Yahoo (delayed), yields from FRED. For the AI desk, `export ANTHROPIC_API_KEY=...` before starting the backend. `.env.example` lists every variable.

## Test it

```bash
cd atlas/backend && pytest                        # indicators, sessions/DST, providers, API, AI guardrails
cd atlas/web && npm run typecheck && npm test     # types + formatting helpers
# browser smoke test: demo backend + `npm run dev` running, and `npm i -g playwright` or similar available
node atlas/web/e2e/smoke.cjs ./e2e-out
node atlas/web/e2e/scanner.cjs ./e2e-out
# alerts e2e needs a fast loop: ATLAS_DEMO=1 ATLAS_ALERT_SECONDS=2 python -m atlas_api
node atlas/web/e2e/alerts.cjs ./e2e-out
node atlas/web/e2e/analysis.cjs ./e2e-out   # compare overlay + multi-timeframe
node atlas/web/e2e/hyperliquid.cjs ./e2e-out  # needs e2e/fake_hyperliquid.py; see the header of the script
node atlas/web/e2e/news.cjs ./e2e-out       # needs e2e/fake_rss.py; see the header of the script
node atlas/web/e2e/backtest.cjs ./e2e-out   # backtester (demo data; saves a run, use a throwaway ATLAS_DB)
# trading e2e (fresh DB): ATLAS_DEMO=1 ATLAS_ALERT_SECONDS=2 ATLAS_PAPER_SECONDS=2 python -m atlas_api
node atlas/web/e2e/trading.cjs ./e2e-out    # portfolio, paper orders, risk limits, kill switch, scenarios
# telegram e2e: see the header of atlas/web/e2e/telegram.cjs (uses a local fake Bot API, no real Telegram needed)
```

## Using it

Press `/` or `Ctrl+K` and type: `BTC`, `BTC CHART`, `NVDA TECH`, `AAPL`, `MACRO`, `AI BTC`, `SCAN BREAKOUT`, `ALERT BTC ABOVE 70000`, `COMPARE BTC QQQ`, `NVDA MTF`, `PORT`, `RISK`, `BUY BTC 0.1 SL 67000`, `HELP`. `BUY`/`SELL` only draft an order in the paper ticket: you preview it (risk checks), then confirm. Unknown input gets suggestions. Modules that are not built (NEWS, PORT...) say so and name their roadmap phase instead of showing fake data. `Ctrl+1..7` jump between workspaces. Panels drag and resize; layouts, watchlists and preferences persist on the backend.

## Layout

```
atlas/
  backend/atlas_api/   providers/ (coinbase, yahoo, fred, demo), indicators, technical, sessions, status,
                       service, commands, db, ai/ (llm, tools, desk), app (FastAPI)
  backend/migrations/  versioned SQL migrations
  web/src/             Vite + React + TypeScript; widgets/, workspaces, command bar
  docs/                architecture, data-providers, roadmap, implementation-status, known-limitations
```
