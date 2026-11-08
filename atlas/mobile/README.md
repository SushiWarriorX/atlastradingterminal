# Signal Mobile

**Windows, easiest way:** double-click `start-signal-windows.bat` in the project folder (or run `.\start-signal-windows.bat` in PowerShell). It starts the backend and Signal for you; when Signal asks for a server, type `http://localhost:8000`.

A simple, fast phone app for researching **Bitcoin, crypto tokens, US stocks and ETFs**, built on your ATLAS server. Four research agents (News, Technical, Macro, Fundamentals) are folded into one screen per asset.

**Research and paper trading only.** The app cannot place trades, connect to a brokerage or hold money, and the backend has no route that could. Nothing in it is financial advice.

- On a wide screen (a desktop browser, 1000px or more) it shows three panes side by side: watchlist or search on the left, the research in the middle, the News agent's stories on the right, with a ticker strip on top. On a phone it stays one screen at a time.
- Five tabs: **BTC**, **Stocks** (your watchlist, with a search button), **Macro**, **Discover** and **Journal**. Macro shows what matters today, key indicators, upcoming events and labelled headlines. The BTC tab has a Strategy Lab card that compares tested BTC rules after costs. Discover shows a daily shortlist of five US stocks to research, with reasons, risks, evidence and dates. Settings sit behind the small profile icon. The Journal is a simple list of your own trades and notes: a symbol is enough, and P&L is calculated when size, entry and exit are filled in.
- Tap an asset for one continuous research screen: price and freshness, a chart, a **What matters now** briefing, and four expandable agent rows.
- Every market number shows where it came from, when, and an honest label: *Live, Delayed, Market closed, Stale, Demo* or *Unavailable*.
- Numbers are calculated by the server. The app only displays them.

> **Status: prototype.** It runs end to end against a scripted backend (browser tests below) and against ATLAS demo mode. It has **not** been run against live market providers or on a physical phone from this build environment. See [What is not done yet](#what-is-not-done-yet).

## Run it

You need Node 20+ and the ATLAS backend running (see the main [README](../README.md)).

### 1. Start the ATLAS backend

**On Windows (the usual way).** Copy `local-settings.example.ps1` to `local-settings.ps1` (it is never uploaded) and add:

```powershell
$env:ATLAS_CORS_ORIGINS = "http://localhost:8081"      # only needed for the browser version of the app
```

Then double-click `start-windows.bat` (practice data, everything labelled **Demo**) or run `start-windows.bat -Real` (real data from Coinbase, Yahoo Finance and, if you set a key, FRED).

**Mac or Linux:**

```bash
cd atlas/backend
ATLAS_DEMO=1 ATLAS_CORS_ORIGINS=http://localhost:8081 python -m atlas_api     # drop ATLAS_DEMO=1 for real data
```

`ATLAS_CORS_ORIGINS` is only for opening the app in a **browser**; the phone app does not need it.

### 2. Start the app

```bash
cd atlas/mobile
npm install
npm start
```

Press `w` to open it in your browser, or scan the QR code with **Expo Go** on your phone.

On the first screen enter your server address:

| Where you run the app | Server address |
| --- | --- |
| Browser on the same PC | `http://localhost:8000` |
| Phone on the same Wi-Fi | `http://<your PC's IP address>:8000` |
| Anywhere (recommended) | `https://<your cloud address>` from the [cloud guide](../docs/cloud-deploy.md) |

For a phone on your Wi-Fi the backend must listen on the network and ask for a password (it refuses to do otherwise). On Windows add these two lines to `local-settings.ps1` and restart; on Mac or Linux set the same variables before `python -m atlas_api`:

```powershell
$env:ATLAS_HOST = "0.0.0.0"
$env:ATLAS_AUTH_PASSWORD = "a password of 12 or more characters"
```

Your PC's address is the "IPv4 Address" shown by `ipconfig` (Windows) or `ifconfig` (Mac/Linux). Allow Python through the Windows firewall when it asks. Plain `http://` sends your password and login token unencrypted over the Wi-Fi, so use it only at home; use the HTTPS cloud setup for anything else. To pre-fill the address in the app, set `EXPO_PUBLIC_ATLAS_URL` before `npm start`.

### Tests

```bash
npm run typecheck      # TypeScript
npm test               # 29 unit tests (formatting, freshness wording, watchlist edits, per-server query keys, the API client)
```

Browser tests drive the real app (web export, phone-sized) against the real backend with scripted prices, news and directory data. No network or accounts are needed:

```bash
npm run export:web                                   # builds dist/
npm i --no-save playwright && npx playwright install chromium
export SIGNAL_E2E_PYTHON=/path/to/atlas/backend/.venv/bin/python     # a Python with the backend and its dev extras installed: pip install -e '.[dev]'
node e2e/signal.e2e.cjs                              # all scenarios; or name some: healthy stale partial missing login demo
SIGNAL_E2E_SHOTS=/tmp/shots node e2e/signal.e2e.cjs  # also save screenshots
```

| Scenario | What it proves |
| --- | --- |
| `healthy` | Connect flow; five tabs; search tells **Bitcoin the coin from the Bitcoin ETF** (and SOL the token from SOL the stock); the watchlist survives a reload, a brand-new browser profile, reordering and removal because it lives on the server; asset identity; chart ranges; briefing; each agent's evidence, sources and "not available" list; hostile headlines stay inert; disagreeing agents are both shown; no trading controls and no provider requests from the app; offline mode keeps the saved list and says so. |
| `stale` | Three-day-old prices are labelled stale on the list, the asset screen and in the Technical agent, which declines to give a current reading. |
| `partial` | With News, Fundamentals and Macro down, price, chart and Technical still work and the screen says "Based on 1 of 4 agents". |
| `missing` | With no prices and no charts, rows say *Unavailable*, the chart offers a retry, and research that does not need prices still loads. |
| `login` | Without a login every API call is refused; a wrong password is rejected; the login survives a reload; logging out and a changed server password both return to the login screen. |
| `demo` | Demo data is labelled on every screen; switching to a live server drops the demo list and recent searches; a saved copy from another server is never shown. |

## How it is built

**Reused from ATLAS (not rewritten):** the market-data service and its freshness classification (Coinbase, Yahoo Finance), the multi-timeframe technical engine and indicator library, the RSS news store, the fundamentals service, the FRED macro and Fed Watch services (draft work, see the main status doc), the provenance model, the password login and the SQLite database.

**New:**

| Part | Where |
| --- | --- |
| Backend research layer: asset identity, four agents, orchestrator, cache, demo fixtures, API under `/api/signal/*` | `atlas/backend/atlas_api/signal/` |
| Phone login token (`Authorization: Bearer`), opt-in CORS | `atlas_api/auth.py`, `app.py` |
| The app (Expo, React Native, TypeScript, expo-router, TanStack Query) | `atlas/mobile/src/` |
| Browser test harness | `atlas/mobile/e2e/` |

The backend design, API, agent rules and data-source notes are in [`docs/signal-mobile.md`](../docs/signal-mobile.md).

## What is not done yet

- **Live verification.** Nothing here has been run against live Coinbase, Yahoo Finance, FRED, CoinGecko or mempool.space from this build environment, and not on a physical iPhone or Android phone (only the web export was exercised). Run it against your own server before relying on it.
- **Macro and Fed Watch are draft work in ATLAS.** The Macro agent reuses them and says "not available" when FRED is not configured.
- **Written explanations are off by default** and, if you turn them on (`ATLAS_SIGNAL_AI=1` plus an Anthropic key), have only been tested with a scripted model, never a real one.
- **Data-use terms were not checked.** Before sharing the app with anyone else, or promising more tokens, read the checklist in [`docs/signal-mobile.md`](../docs/signal-mobile.md#data-sources-and-terms-checklist).
- Reordering uses up and down arrows (no drag and drop yet). No push notifications or alerts. The web build keeps its login token in browser storage; phones use the secure store.
- App icon, splash screen and the bundle identifiers (`com.example.signalmobile`) are placeholders; change them before building for a device.

Expo notes for developers are further down in [`AGENTS.md`](AGENTS.md).
