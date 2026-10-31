# Roadmap

Legend: done / partial / not started. Per-feature detail is in implementation-status.md.

| Phase | Scope | State |
|---|---|---|
| 0 Validation | API matrix, stack decisions, docs | partial: matrix done; pricing and licensing unverified (no web access) |
| 1 Foundation | Shell, nav, theme, workspaces, command bar, backend, DB, provider interface, BTC + equity charts, watchlists, status, AI desk | done, except that the UI polls over REST instead of using the WebSocket |
| 2 Technical intelligence | Full indicator set, multi-timeframe, structure, scoring, alerts, compare overlay, drawings | partial: core indicators, levels, trend, alert engine (price, % change, RSI, SMA, MACD, RVOL, scan matches) with in-app and Telegram delivery, compare overlay with aligned correlation, multi-timeframe structure and transparent score |
| 3 Scanner | Universe ingestion, rules engine, presets, results table, NL to filters, scanner agent | partial: daily-bar scanner on Yahoo (core + US-listed universes), 7 presets, NL, saved scans. Missing: fundamentals, catalysts, alerts, AI agent, virtualization |
| 4 News | Licensed feeds, clustering, impact scoring, news agent | partial: RSS headlines with feed health, grouping and conservative tags (unverified against the live feeds). Missing: licensed feeds, impact scoring, news agent, catalyst scans, news alerts |
| 5 Macro | FRED/ALFRED, calendar, Fed/inflation/labour dashboards, cross-asset correlations, macro agent | partial: 10Y/2Y only |
| 6 Multi-agent | Orchestrator, shared snapshots, strategy/risk/chief agents, trade ideas | partial: technical, fundamental, macro and risk agents plus a chief with computed conflicts, tool-using desk, snapshots, audit (tested against a scripted model only). Missing: news, scanner and strategy agents (deliberate), trade ideas |
| 7 BTC derivatives | Funding, OI, liquidations, ETF flows, on-chain | not started (needs a provider) |
| 8 Portfolio and paper | Decimal accounting, paper OMS, risk analytics, journal | mostly done: journal + performance analysis (CSV import for Variational/IBKR Flex/generic, IBKR executions), IBKR paper/read-only broker integration (tested against a fake only). Earlier work: Decimal accounting, paper OMS with preview/confirm/idempotency, 16-check risk gate, kill switch, portfolio risk analytics, scenarios, manual holdings. Missing: AI Strategy/Risk agents, Alpaca adapter, IBKR market data |
| 9 Backtest and live | Backtester, optional gated live adapters, deployment | partial: daily-bar backtester built (see implementation-status); live adapters deliberately absent |

Cross-cutting backlog: Postgres + Alembic; Redis; background workers; streaming AI responses; WebSocket in the UI with reconnect/backoff and sequence-gap handling; auth for any non-local deployment.
