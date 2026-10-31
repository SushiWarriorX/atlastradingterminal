# Data providers

**Pricing and licensing below are NOT verified.** This build session had no access to provider sites. Cost columns are assumptions to confirm before subscribing. For every provider, confirm personal vs professional use, display vs non-display, storage, and AI-processing rights.

## Integrated now (written without network access; unit-tested against mocked HTTP only)

| Provider | Data | Timeliness | Coverage / limits | Tier |
|---|---|---|---|---|
| Coinbase Exchange public REST | BTC-USD spot ticker, 24h stats, candles (1m 5m 15m 1h 6h 1d; 2h/4h/30m/3m/1w derived by resampling) | Near real-time (REST polling) | Single venue, not the global BTC market. 300 candles/request (paginated). No VWAP or bid/ask sizes. `prev_close` is the 24h rolling open (labelled) | Free |
| Yahoo Finance via `yfinance` | Equities, ETFs, indices (SPX/NDX/DJI/RUT/VIX); quote built from 1m bars; history 1m to 1M | Delayed (declared 900s; typical, not verified per symbol) | Unofficial; can break or rate-limit. No bid/ask, float or halts. Daily bars split-adjusted only | Free (personal use) |
| FRED `fredgraph.csv` | DGS10, DGS2 daily | Daily; observation date lags publication | No vintages (ALFRED needs a key) | Free |

## Planned

| Provider | Category | Real-time? | Priority | Est. cost (assumption) |
|---|---|---|---|---|
| Massive (ex-Polygon) | Consolidated US equities, WebSocket, reference data, corporate actions | RT on paid tiers | Tier 2, first | tens to low hundreds USD/mo |
| Alpaca Market Data | US equities. Free tier is a limited-venue feed (not consolidated). Paper trading | RT (limited venue) free; consolidated paid | Tier 2 alternative; Phase 8 paper broker | free to ~100 USD/mo |
| Databento | Institutional tick/L2, historical | RT/historical | Tier 3 | usage-based |
| CoinGlass / exchange derivatives APIs | Funding, OI, liquidations, basis | varies | Phase 7 | paid tiers; modelled liquidation maps must be labelled estimates |
| Benzinga / licensed news | News | RT | Phase 4 | paid. No scraping of paywalled sites |
| SEC EDGAR, Fed, BLS, BEA, Treasury | Filings, macro releases | official | Phases 4-5 | free |
| FRED/ALFRED JSON API | Series + vintages | official | Phase 5 | free key |
| IBKR (TWS / IB Gateway API) | **Integrated (portfolio, paper orders, executions)**; market data via IBKR not yet used | account-dependent | done for portfolio/orders/journal | account-dependent |
| Variational Omni | Perp DEX. No public API keys currently offered (private beta). CSV exports documented (trades, funding, realized P&L, transfers) | n/a | CSV import done (format unverified) | free |

Adding a provider means one class with `name`, `entitlement`, `delay_seconds`, `native_intervals`, `async quote()`, `async ohlcv()`, registered in `create_app`. The service adds provenance, status, caching and derived intervals.
