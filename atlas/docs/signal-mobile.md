# Signal Mobile: design, API and open gaps

Signal Mobile is a phone app for research on Bitcoin, crypto tokens, US stocks and ETFs. It sits on top of the ATLAS backend and adds one backend package (`atlas_api/signal/`) and one app (`atlas/mobile/`). Setup and tests: [`atlas/mobile/README.md`](../mobile/README.md).

**Status: prototype.** It is verified against scripted data and ATLAS demo mode, not against live providers and not on a physical phone. The Macro dashboard, Fed Watch and cloud hosting it builds on are themselves draft work in ATLAS.

## Rules it follows

1. **Research and paper only.** No order route exists in the Signal API (a test posts to likely names and expects 404/405); `GET /api/signal/meta` reports `live_trading: false`; the app has no buy/sell control (a browser test scans every screen).
2. **Every market number carries provenance:** `source`, `as_of`, and for prices a `status` of `LIVE`, `DELAYED`, `HISTORICAL` (shown as *Market closed* / *Last known*), `STALE`, `DEMO` or `UNAVAILABLE`. The server decides the label (`status.classify`); the app only words it.
3. **Math happens in code.** Indicators, scores, ratios, ETF concentration and Bitcoin supply figures are computed in Python from raw inputs. An optional AI layer (off by default) may only *word* a finding; it cannot add, change or calculate figures (see below).
4. **Three kinds of statement are kept apart** in every finding: *reported facts* (with source and time), *agent interpretations* (rule-based, each tied to the facts it rests on and, for technicals, a timeframe), and *missing information* (named, with the reason).
5. **Untrusted text stays inert.** Headlines and feed text are classified by fixed patterns and displayed as plain text; only `http(s)` links are ever opened; nothing from an article is passed to a model as an instruction.
6. **No provider keys in the app.** The app talks only to your ATLAS server (a browser test records every request origin and scans the bundle).
7. **Demo and live never mix.** Demo data is generated server-side, labelled `DEMO` on every field, prefixed `[DEMO]` in stories, and the live code path never imports the fixtures (tested). On the device, the saved watchlist copy and recent searches are stored per server.

## Asset identity

Search returns stable ids so two things with one ticker cannot be confused:

| Kind | Id | Notes |
| --- | --- | --- |
| Crypto | `CRYPTO:COINBASE:BTC-USD:SPOT` | priced from Coinbase's USD pair only; the id names venue, pair and market type |
| Stock | `EQUITY:NASDAQ:AAPL` | listed exchange from the Nasdaq Trader directory |
| ETF | `ETF:ARCA:BTC` | e.g. *Grayscale Bitcoin Mini Trust ETF*, a different asset from the coin |
| Unverified | `EQUITY:US:XYZ` | ticker accepted only if a price can be found; marked "unverified" everywhere |

Coverage: about 38 hand-entered large tokens (checked against Coinbase's product list when it can be reached), the ATLAS catalog, and the Nasdaq Trader US-listed directory (downloaded lazily, cached on disk, failures remembered for 10 minutes). A query that matches nothing says so and says what is supported (`unsupported` in the search response); it never returns a look-alike. Same-ticker neighbours are listed by `AssetRegistry.same_symbol` and called out in the News agent's limits.

## API (all under `/api/signal`, all read-only except the watchlist)

| Route | Purpose |
| --- | --- |
| `GET /meta` | demo flag, agents, data coverage, directory status, `live_trading: false`, AI on/off |
| `GET /search?q=` | `results[]` (id, symbol, name, type, venue, support, note), `unsupported`, `notes` |
| `GET /watchlist` · `POST /watchlist {id}` · `DELETE /watchlist/{id}` · `PUT /watchlist/positions {ids}` | the one saved list (SQLite `signal_watchlist`); rows carry quote + provenance, 30-point sparkline, one-line takeaway |
| `GET /asset/{id}` | identity + quote + saved flag |
| `GET /chart/{id}?range=1D\|1W\|1M\|3M\|1Y\|5Y` | points + provenance + bar interval |
| `GET /research/{id}?wait=` | the four findings and the combined briefing; agents still running come back as `pending` and are polled |
| `POST /research/{id}/refresh {agent}` | re-run one agent (30 s cooldown) |

Phone login: `POST /api/auth/login {password, client:"mobile"}` returns a bearer token (30 days, signed with a key derived from the password, so changing the password signs every phone out). Without a password configured ATLAS refuses to listen beyond localhost.

## The four agents

Each returns a `Finding`: `takeaway`, `stance` + `stance_rule`, `facts[]` (value, display, source, `as_of`, `kind` reported/calculated, timeframe), `interpretations[]`, `stories[]`, `levels[]`, `events[]`, `missing[]`, `sources[]`, `limitations[]`, `data_as_of`, `analyzed_at`, `status` (`ok | partial | unavailable | not_applicable | pending`).

| Agent | Reuses | Notes |
| --- | --- | --- |
| **News** | ATLAS RSS store, per-symbol feeds | Groups duplicates; shows publication time (event time is not in RSS and is said to be missing); labels each story *reporting / opinion / unconfirmed* **by wording only**; assigns a category and a fixed "why it may matter" sentence; no sentiment score; industry stories are marked as such and ranked lower. |
| **Technical** | MTF engine, indicator library | Weekly/daily/1h(/15m) trends, RSI/MACD/ATR/volume, swing-based levels, conflicts between timeframes named, an invalidation level ("a daily close below X would weaken this setup", not a stop or target). Relative strength vs SPY (stocks) or BTC (tokens). **If the prices are stale it gives no stance and says so first.** |
| **Macro** | `MacroService`, `FedWatchService` (draft) | Reads the asset's *exposure profile* (rates-sensitive equity, broad equity, bitcoin, token, bond/gold ETF, …) and counts tailwinds/headwinds from yields, dollar, liquidity, inflation and the curve against fixed thresholds. Official releases and the agent's reading are shown separately; upcoming events come with local-time countdowns. "Not available" when FRED is not configured. |
| **Fundamentals** | `FundamentalsService`, CoinGecko adapter, mempool.space | Stocks: valuation, growth, margins, cash flow, balance sheet, rule-based checks. ETFs: expense ratio, holdings concentration, computed here. Crypto: supply, issuance and (for Bitcoin) halving math computed from protocol rules, plus CoinGecko market data. Token unlock schedules, governance and on-chain data for tokens other than Bitcoin are **listed as not available**, not guessed. |

### Orchestrator

`Orchestrator.research(asset, wait)` runs the agents concurrently with per-agent timeouts (25-35 s) and shares in-flight work between callers. A slow agent comes back as `pending` placeholder and the app polls; a failed agent becomes `unavailable` with its reason; the rest still render. Cache lifetimes follow the source's cadence: Technical 90 s, News 10 min, Macro 30 min, Fundamentals 6 h (partial results 5 min, failures 45 s). Each agent can be refreshed independently.

The **briefing** ("What matters now") answers *What changed? What supports it? Main risks? Watch next?* with at most 3 lines per section, chosen round-robin across agents by priority, de-duplicated, each line naming its agent. **Disagreements are preserved:** if one agent reads supportive and another cautious, the briefing says so and both stay visible; it never averages them. A coverage note states how many agents contributed.

### Optional AI wording (`ATLAS_SIGNAL_AI=1` + an Anthropic key)

The model gets the finding with placeholders (`{fact:KEY}`, `{story:ID}`) and may write one short plain-language paragraph. The reply is rejected (and retried once, then dropped for the rule-based text) if it contains any digit, URL, advice, forecast or instruction-like phrase of its own. Tested with a scripted model only: **it has never been run against a real model.**

## Data sources and terms checklist

The sandbox this was built in could not reach the providers' websites, so **none of their current terms were read or verified.** Confirm each before sharing the app beyond your own use or promising wider coverage.

| Source | Used for | Check before sharing / redistributing |
| --- | --- | --- |
| Coinbase public market data | crypto prices, candles, product list | API and market-data terms; whether in-app display to other people is allowed |
| Yahoo Finance (via `yfinance`) | stock/ETF prices, bars, company data | **Unofficial** endpoints, and no licence for an app other people use that we know of. Treat as personal use only until confirmed; for anyone else use a licensed vendor or IBKR |
| FRED (St. Louis Fed) | rates, inflation, liquidity | API terms and attribution wording; some series carry third-party copyright |
| CoinGecko | token market data in Fundamentals | Plan limits, attribution and commercial-use rules for the key you use |
| mempool.space | Bitcoin network figures | Public API rate limits and terms; self-host for heavier use |
| RSS feeds (Yahoo per-symbol and the ATLAS feed list) | headlines | The app shows title, source, time and a link only, never article text; check each publisher's terms |
| Nasdaq Trader symbol directory | US stock/ETF search | Terms of use of the directory files |

Wider token coverage needs a provider with a licence that covers it; the current list is a deliberate, small, Coinbase-backed set.

## How this was verified

- Backend: `tests/test_signal_*.py` (assets, agents, orchestrator, API, AI wording) plus the existing suites; run `cd atlas/backend && python -m pytest -q`.
- App: 26 unit tests and a strict TypeScript check.
- Browser: `atlas/mobile/e2e/signal.e2e.cjs`, six scenarios, see the mobile README for what each proves.

While building the browser tests three problems in existing ATLAS code or in the new layer were found and fixed, each with a test that fails without the fix:

- **News:** a story carried by two symbols' feeds was stored once and tagged only for the first symbol (`news/service.py`).
- **Freshness:** while the market was closed or in extended hours, *any* old price was labelled "market closed" instead of stale. A price from before the latest session opened is now `STALE` (`status.py`, `sessions.py`).
- **Technical agent:** stale prices produced a normal-looking reading; it now declines to give a stance and leads with the warning.

## Remaining integration gaps

1. **Live runs:** Coinbase, Yahoo, FRED, CoinGecko, mempool.space and the Nasdaq directory have not been exercised from this environment; their adapters are tested against hand-written sample payloads only.
2. **Physical devices:** only the web export was driven in a browser. iOS/Android builds (Expo Go and a development build), the secure token store, safe-area layout and pull-to-refresh need a hands-on pass.
3. **HTTPS and Docker:** the cloud setup the phone should use is unverified (no Docker daemon was available).
4. **Macro / Fed Watch:** draft ATLAS work; the Macro agent inherits that status and the lack of a live FRED run.
5. **AI wording:** never run with a real model.
6. **Data terms:** unchecked (table above). Yahoo data in particular should be treated as personal use only.
7. **Token coverage:** about 38 large tokens; no DEX/long-tail tokens, no contract-address search, no unlock calendars or governance data.
8. **Not built:** push notifications and alerts, drag-and-drop reordering (arrows are used), multi-user accounts, tablet layout, accessibility audit with a screen reader, localisation.
