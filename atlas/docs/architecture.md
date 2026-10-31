# Architecture

Modular monolith: one FastAPI process, one SPA. Boundaries are enforced by module, not by network hops.

```
browser (React SPA)
   │  REST + WebSocket (/ws/market-data); envelope {ok, data | error{code,message}}
FastAPI (app.py)
   ├─ commands.py      command grammar -> validated structured operation (no free-form execution)
   ├─ service.py       provider routing, TTL cache, interval derivation (resample), health, provenance + status
   │    └─ providers/  coinbase | yahoo | fred | demo   (one interface: quote, ohlcv)
   ├─ indicators.py    deterministic maths (numpy); warm-up values are NaN
   ├─ technical.py     swings, prior-day range, MA levels, trend, each with a derivation string
   ├─ sessions.py      NYSE calendar (exchange_calendars): premarket/regular/after-hours/holiday/early close
   ├─ status.py        LIVE/DELAYED/HISTORICAL/STALE/DEMO classification (pure function)
   ├─ ai/              llm.py (provider abstraction) · tools.py (read-only registry, per-agent permissions)
   │                   desk.py (tool-using chat + validated technical agent)
   ├─ trading/         money (Decimal) · models · sim (pure fills) · accounting (pure) · risk (pure pre-trade gate)
   │                   engine (preview/confirm/idempotency, order lifecycle, ledger, reconcile) · analytics (VaR/ES/beta/scenarios)
   ├─ journal/         matching (FIFO round trips, pure) · stats (performance analytics, pure) · importers (CSV) · store (executions, notes, sources)
   ├─ brokers/ibkr.py  IBKR via ib_async: readonly | paper_trading (paper accounts only); no live mode exists
   └─ db.py            SQLite + SQL migrations: watchlists, prefs, layouts, snapshots, analyses, audit_log, alerts,
                       portfolios, positions, orders, fills, order_events, equity_history
```

## Principles as implemented

- **Provenance on every datum**: provider, venue, event/ingested time, entitlement, declared delay, status, quality notes.
- **No silent synthetic data**: the demo provider exists only when `ATLAS_DEMO=1`, and every response is then `DEMO`. Without it, a failing provider yields `UNAVAILABLE` (503 or a per-item error), never an invented number. Tested.
- **Math in code, interpretation in the model**: the LLM receives computed features. Technical-agent output cites `level_id`s; the server resolves prices from the snapshot and rejects unknown source IDs or level IDs (one corrective retry, then `failed_validation`).
- **Execution safety**: PAPER ONLY. There is no live broker adapter and `POST /api/orders/live` always refuses. No AI tool can place or preview an order (a test asserts no registered tool name contains order/trade/execute). A paper order needs a risk-approved preview (single use, 60 s), an idempotency key and, if the kill switch is on, nothing gets through. The risk gate is pure Python run by the server at preview and again at submit.
- **Untrusted content**: tool results are wrapped in `<tool_data untrusted="true">` and the system prompt says to ignore instructions inside. This is defence in depth only; the real control is that no dangerous tool exists.
- **Reliability**: HTTP wrapper with rate limit and retries with exponential backoff on 429/5xx/network errors, per-provider health counters, WebSocket per-client loop with cancellation.

## Deviations from the master spec

| Spec | Built | Reason |
|---|---|---|
| Next.js | Vite + React SPA | Single-user desktop app; no SSR/SEO need. |
| PostgreSQL/Timescale, SQLAlchemy, Alembic, Redis | SQLite + SQL migration runner, in-process cache | Zero-setup Tier 1. Schema is portable; migration is on the roadmap. |
| Tailwind/shadcn, TanStack Table/Virtual, ECharts | Hand CSS, plain tables | Dense terminal look; virtualization matters once the scanner exists (Phase 3). |
| Canonical IDs incl. `…:PERP` | Format supported; only spot catalogued | Perp data needs a derivatives provider (Phase 7). |
