# Known limitations

- **Free equity data is delayed and unofficial** (Yahoo). Do not trade off it. Replace with a licensed feed (Tier 2).
- **BTC is one venue** (Coinbase). Prices differ across exchanges; never read it as "the" BTC price.
- **Equity session**: after-hours ends 20:00 ET even on early-close days (real after-hours ends earlier). Pre-market starts 04:00 ET. Extended-hours quotes are not requested from Yahoo; outside regular hours the UI shows `HISTORICAL`.
- **Index/yield "bp" change** in the top bar is the change versus the previous observation, not a trading-day change for FRED.
- **UI polls over REST** at the configured frequency; the WebSocket endpoint exists and is tested but the UI does not use it yet, so there is no sequence-gap or order-book handling.
- **Instrument catalog is a small seed** (~25 symbols). Uncatalogued US tickers resolve as `EQUITY:US:<SYM>` with exchange `UNVERIFIED`. Broad-universe ingestion is Phase 3.
- **Demo provider is internally inconsistent**: its quote and its candles come from separate seeded walks, so a demo quote will not match the last demo candle. This is irrelevant for live data.
- **AI**: output validation guarantees sources and levels exist in the snapshot, not that the interpretation is sound. Treat as research assistance, not advice.
- **Single user, no auth**: bind to localhost only. CORS is limited to the Vite dev origin.
- **SQLite** with a process-wide lock; fine for one user, not for deployment.
- **Scanner uses daily bars only** (Yahoo, unofficial, delayed). While the market is open today's bar is partial, so RVOL and % change are in-progress; the results bar warns about this.
- **Scanner universe**: `core` is a static ~100-name seed with sectors. `us_listed` comes from the official Nasdaq Trader directory (needs network, no sector data, ETFs excluded) and scanning ~8k symbols through Yahoo is slow and may be rate-limited. Failed symbols are counted and excluded, never guessed. There is no point-in-time universe, so historical use would have survivorship bias.
- **Scanner thresholds are defaults, not validated edges.** Scores are percentile ranks among matches, not probabilities. Results are candidates to investigate.
- **Scan jobs live in memory** (lost on restart). Saved scans and run history persist.
- **Natural language is pattern-based**, not an LLM. It handles a fixed set of phrasings and tells you what it ignored.
- **Alerts are polled, not streamed.** The server checks every `ATLAS_ALERT_SECONDS` (default 30 s) against cached data (quotes 3 s, bars 20 s). A price that crosses a level and reverts between two checks is missed. Latency is therefore up to one interval plus provider delay; Yahoo equity data is itself ~15 min delayed, so equity alerts are not suitable for fast moves.
- **Alerts fire on transitions between checks.** A new, edited or re-enabled alert records its baseline on the first check and only fires on a later false-to-true change. A condition already true at creation does not fire.
- **Alert delivery: in-app, optional browser notifications (while a tab is open) and Telegram.** No email/Discord yet.
- **RVOL alerts use daily bars and today's partial volume** while the market is open, so they under-report until late in the session.
- **Demo quotes oscillate +/-1% (period ~25 s)** so alerts are exercisable offline. They are still labelled DEMO and are not market data.
- **Alert loop runs in-process** (one server). Restarting the server restarts the loop; checks missed while it is down are not replayed.
- **Telegram**: one chat only (`TELEGRAM_CHAT_ID`), one bot. Messages are plain text with no inline buttons, so you cannot acknowledge or snooze from the phone. Delivery is best effort: a failure is recorded on the event (visible in the Alerts panel) and not retried later once the 3 attempts are used. The per-minute cap (20) drops excess external messages (`telegram:rate_limited`) but they remain in-app. Timestamps in messages are UTC. Delivery latency is the alert check interval (default 30 s) plus Telegram's.
- **Telegram privacy**: Telegram messages are not end-to-end encrypted for bot chats, and message text includes symbols and levels you set. Anyone with the bot token can send as your bot: keep it only in the backend environment and rotate it via @BotFather if it is ever exposed.
- **Compare** works on daily and weekly bars across calendars. Intraday bars from different calendars (e.g. BTC on the hour vs Yahoo equity bars at :30) share no timestamps and are refused rather than approximated. Series are rebased to 100 at the first shared bar, so the starting point matters. Correlation and beta are descriptive; they shift over time (see the ρ60 range) and say nothing about causation.
- **Multi-timeframe rules are one possible definition**, not objective truth. Structure uses fractal swings (k bars each side, default 3; swings are only confirmed k bars late), so the newest swing is always missing. BOS/CHoCH are simple "close beyond the last swing" rules. Weekly trend uses SMA50 only when fewer than 200 weekly bars exist (the label says so in its factors).
- **Technical score** is a weighted tilt of current conditions with hand-chosen default weights, **not calibrated or backtested** and not a probability. Equities default to SPY as the relative-strength benchmark; BTC has none by default (choose one, e.g. QQQ, explicitly). Volatility is shown as context only (weight 0).
- **MTF data cost**: each analysis fetches five timeframes (weekly is derived from up to ~840 daily bars for crypto). Results are cached 20 s; with live Coinbase this is several paginated requests per refresh, so the widget refreshes slowly (about once a minute).

## Paper trading and portfolio risk

- **It is a simulator, not a broker.** Fills use polled quotes with an assumed spread (when the quote has none), slippage, fees and a volume-participation cap, all editable and all assumptions. Queue position, hidden liquidity, intra-poll price paths and market impact are not modelled. Treat results as indicative; paper P&L routinely looks better than live P&L.
- **Delayed data means delayed fills.** Equity prices come from Yahoo (~15 min delay), so equity paper fills happen at delayed prices and are tagged `DELAYED` on every fill. The risk check warns and the UI shows the badge. BTC is near real time.
- **Polling granularity.** The fill loop runs every `ATLAS_PAPER_SECONDS` (default 5 s). A stop is evaluated on the last price at poll time, so a spike that reverses between polls is missed, and a gap fills at the then-current market (shown in the fill note), not at the stop.
- **Long-only, cash-only.** No short selling and no leverage/margin (sells beyond the held quantity are rejected). Equities trade in whole shares unless you enable fractional shares. US regular session only: extended hours are not simulated, so equity orders wait for the open; market orders placed while closed are rejected on purpose.
- **A planned stop is not an order.** It only feeds risk sizing and the aggregate-risk check. Nothing protects the position if price falls through it. Place a separate stop order if you want one. Planned risk is not worst-case loss: gaps and slippage can exceed it.
- **Risk checks run at preview and submit, not at fill.** A working order can later fill while limits have changed or been breached by other fills. Cash is reserved for working buys, so buying power is protected.
- **Event risk is not checked** (no economic or earnings calendar yet). Daily-loss limits depend on the first equity sample of the New York day, so they only work while the server has been running that day.
- **Accounting uses average cost** with buy fees capitalised; no FIFO/LIFO tax lots, no dividends, splits or other corporate actions on positions, single base currency (USD).
- **Previews live in memory.** A server restart invalidates open previews (you just preview again). The idempotency key, orders, fills, positions, limits and the kill switch are persisted.
- **Equity history is sampled** about once a minute while the server runs, so drawdown/return from it have gaps and understate intra-minute moves.
- **Risk analytics are descriptive.** Historical simulation with today's weights over at most ~300 aligned daily observations (needs 60; VaR 99% needs 200; ES needs 10 tail points), cash earns 0, fees ignored, mixed calendars aligned to shared dates, annualised with sqrt(252). BTC volume is single-venue, so liquidity figures for BTC are optimistic or pessimistic depending on the venue. Betas and correlations are unstable.
- **Scenarios are instantaneous shocks on current marks.** No gap, liquidity, margin or correlation-regime effects; beta-implied shocks are labelled estimates.
- **Manual holdings are exactly what you type.** Marks come from the market data providers; if a price is unavailable the position is valued at cost and flagged.
- **Single process, single user, no authentication.** Order placement is protected by the kill switch, risk limits, preview/confirm and idempotency, not by user accounts.

## Journal, performance analysis and brokers

- **Trades are derived, with conventions you may not share.** FIFO lot matching (the paper engine reports average cost, so multi-lot trades can differ slightly between the two). A trade is one flat-to-flat lifecycle in one symbol of one source; scaling in/out stays one trade; a fill through zero splits into two trades. Spot and perpetual positions in the same symbol name inside one source would be merged: keep them in separate sources.
- **Imports depend on your file being read correctly.** Naive timestamps are assumed UTC unless you choose a timezone, and time-of-day statistics are only as right as that choice: the preview shows the first and last parsed times so you can check. Currency symbols/commas/parentheses are parsed; ambiguous formats (e.g. 03/04/2026) are read month-first. Rows without a trade id get a stable synthetic id, so editing a file and re-importing it can duplicate rows.
- **Exchange-reported realized P&L is intentionally ignored** (the journal computes its own) to avoid double counting, so it will not match an exchange's P&L column exactly (fees, funding and rounding conventions differ). Funding signs are a convention: tick "invert amount sign" if your export shows payments you made as positive.
- **Fees:** IBKR sends commissions asynchronously, so an execution first seen before its commission report is stored with a fee of 0. A later sync fills in a non-zero fee, but only ever replaces a stored 0 (an existing non-zero fee is never overwritten), and trades computed before that sync used the 0. Perp funding and liquidation fees are only included if your file has them.
- **Statistics describe the past.** Intervals are approximations (Wilson for win rate, bootstrap for expectancy, both assuming independent trades, which real trades are not). With fewer than 30 trades no interval is shown at all. Groups are many comparisons on the same data, so a "best setup" among many will often be luck. Time buckets use entry time in New York time. P&L in different currencies is never added (the most frequent currency is analysed).
- **R-multiples need a planned stop** (entered on the trade or inherited from a paper order). Without it a trade has no R, and averages only cover trades that have one.
- **IBKR scope.** Orders: US stocks and ETFs only (market, limit, stop, stop-limit; DAY/GTC), whole or fractional quantities as IBKR allows. Positions: stocks only are shown in a linked portfolio; other instruments are listed as unsupported, not valued. Cash is TotalCashValue in USD. One account per connection. Order and fill state is polled every few seconds (not streamed). TWS only returns recent executions; use a Flex Query for history.
- **IBKR paper-only enforcement is by account-id convention** (paper accounts start with `DU`) and by refusing the standard live ports. If IBKR ever changed that convention the guard would refuse paper accounts (fail closed), not accept live ones. Read-only mode with a live account is possible by design and cannot place orders because the API connection itself is opened read-only.
- **Connection management is manual.** ATLAS does not auto-connect or auto-reconnect: press Connect after starting TWS/Gateway or after a disconnect. While disconnected, IBKR orders stay in their last known state and the order row says so.
- **Variational has no API here.** Its API keys are not currently offered (private beta), so there is nothing to sync from: import CSV exports. Because the export is capped at 10,000 rows and 365 days per file (per their documentation summary), large histories need several files; duplicates are skipped by trade id.

## Backtester

- **Survivorship bias.** The universe is today's list. Symbols that were delisted, acquired or dropped are absent, which flatters long strategies. Not corrected.
- **Daily bars only.** A stop and a target touched in the same bar resolve to the stop; a gap through a stop fills at the open. Real intrabar order is unknowable from a daily bar.
- **Costs are assumptions** (default 1 bp commission and 5 bps slippage per side), not measured from any broker. Targets are treated as limit orders and pay no slippage.
- **Not dividend-adjusted** (Yahoo `auto_adjust=False`); split-adjusted only.
- **The hold-out is a stability check, not validation.** Nothing is fitted on either part. Testing many variants on the same history and keeping the best is overfitting, and the tool does not guard against it; each run is saved so the number of variants tried stays visible.
- **Features use a trailing 400-bar window** (recursive indicators such as RSI and ATR are seeded on it), so values can differ very slightly from a full-history scan.
- **Same-day entries beyond the position limit are skipped in alphabetical symbol order.** No ranking is used, which is a tie-break, not a view.
- **Verified only on synthetic demo bars and constructed fixtures.** No real Yahoo 5-year history was available in the build session; the first real run may surface data quirks (missing days, splits).

## Hyperliquid sync

- **Unverified against the live API.** The build sandbox could not reach `api.hyperliquid.xyz`. Field names (`coin`, `px`, `sz`, `side` B/A, `time` in ms, `fee`, `feeToken`, `tid`, `dir`, `startPosition`, `closedPnl`, `liquidation`; funding `delta.usdc`) come from the public documentation as remembered. Unparseable rows are counted with a reason, never dropped silently.
- **Funding sign is assumed:** `usdc` is stored as given (negative = paid by you). If the first real sync shows the opposite, flip it in `parse_funding` and re-import (delete the source first).
- **History window:** the API serves roughly the most recent 10,000 fills. If the oldest fill starts from a non-flat position, the sync warns that earlier opening fills are missing and that trade's P&L is unreliable.
- **Reported vs derived P&L:** Hyperliquid's `closedPnl` uses its own entry-price accounting and excludes fees; the journal uses FIFO lots. Totals can differ slightly; a large gap means missing history.
- **Read-only and keyless by design.** Only a public address is accepted. A 64-hex value (a private key) is refused before any request is made.

## News (RSS)

- **None of the default feed URLs was fetched while building.** The sandbox had no internet; the URLs (Federal Reserve, SEC, CoinDesk, Cointelegraph, MarketWatch, CNBC, BBC and Yahoo Finance's per-symbol feed) are from memory and may have moved, require a specific User-Agent (the SEC asks for a contact address: set `ATLAS_NEWS_USER_AGENT`) or block automated clients. Each feed shows its own health; a dead one is reported, never hidden.
- **Polled, not real time.** Feeds refresh every 15 minutes (`ATLAS_NEWS_SECONDS`) and every item is labelled DELAYED. In DEMO mode polling is off and there are no placeholder headlines.
- **Tags are conservative and are not relevance or sentiment.** A headline that names a company without a cashtag or exchange-qualified ticker stays untagged, so the per-symbol view misses stories. There is no sentiment, impact score or "catalyst" flag.
- **Near-duplicate grouping is word overlap** (Jaccard >= 0.7 within 48 h). It can miss a reworded story and can rarely merge two similar ones.
- **Headline, link and a 320-character plain-text summary only**, kept 14 days. Publishers' terms apply; this is for personal research.
- **Feed URLs are checked as text** (http/https, no credentials, no loopback/private literal addresses, redirects re-checked). A DNS name that resolves to a private address is not caught; feed URLs are chosen by the single local user.
- **The AI agents cannot read news** by design for now: headlines are untrusted text and a prompt-injection path until a tool wrapper is designed for it.

## Fundamentals (backend only; the screen section was removed)

- **Unverified against live Yahoo.** The sandbox had no internet. The `info` keys used (trailingEps, forwardEps, marketCap, enterpriseValue, totalRevenue, ebitda, bookValue, sharesOutstanding, totalCash, totalDebt, dividendRate, revenueGrowth, margins, returnOnEquity, mostRecentQuarter, ...) and the `calendar` earnings-date shape come from memory and change between yfinance versions. Missing keys show as "—" with a count; they never raise or get guessed.
- **Unofficial and lagging.** Company data lags filings by weeks. `financials_as_of` and a flag after 135 days say how old it is. Nothing here is a licensed data feed.
- **Ratios mix periods.** P/E uses the current price over trailing EPS; margins and growth are the provider's latest-quarter or TTM figures. Debt/equity uses book value per share times shares, which is only as good as those two inputs. Forward EPS is an analyst estimate.
- **Sector and industry are Yahoo's labels**, not GICS.
- **No scanner filters on fundamentals** (each would need a company-data fetch per symbol), no peer comparison, no history of ratios, no filings text, no analyst ratings or price targets.
- **Funds and ETFs** return only price-range data; company ratios are marked not applicable.
- **The 6-hour cache** means a figure can be up to 6 hours old even on a "live" fetch; the refresh button bypasses it.

## AI specialists and chief

- **Untested with a real model.** Everything was tested against a scripted fake that follows the schema. A live model may produce malformed JSON, cite the wrong facts, or hit the pattern guard on legitimate wording. The server retries once with the rejection reason, then reports `failed_validation` instead of showing an unchecked answer.
- **Validation proves the evidence exists, not that the reasoning is right.** A report can cite real facts and still draw a poor conclusion. The cross-checks (macro reference tilt, limit breaches, negative earnings, constructive-vs-adverse) are a few hand-written rules, not a general reasoning check.
- **The order-language guard is a pattern list**, a safety net behind the schema (which has no order, size, stop or target field). It can miss a creative phrasing and can reject an innocent sentence; the retry message says what matched.
- **Macro thresholds are hand-chosen and uncalibrated** (inverted curve, VIX above 25 or below 16, S&P versus its 200-day average, 10-year yield up 25 bp in 20 observations). The tilt is a reference, not a forecast. In DEMO mode the macro series are synthetic (the demo VIX is not realistic).
- **Conflicts only compare directional words** (bullish/supportive/risk-on against bearish/adverse/risk-off). "Mixed" never conflicts, and the risk agent is excluded from conflict detection because it describes risk, not direction.
- **The chief reads validated specialist output, not raw data**, and gets no tools: it cannot fetch anything itself.
- **Cost:** the full desk makes up to five model calls (four specialists plus the chief), each retried at most once.
- **No news, scanner or strategy agent**, by design (see implementation status).

## IBKR market data

- **Never run against a real TWS or IB Gateway.** It was written from the ib_async API as remembered and tested with a fake. First things to check on a real run: where delayed ticks land (`last`/`bid` versus `delayedLast`/`delayedBid`; both are read), the market-data type switch, historical-request pacing (error 162 becomes a fallback to Yahoo), and ambiguous symbols (SMART routing without a primary exchange).
- **Quote volume is deliberately not reported.** IBKR reports US stock snapshot volume in round lots; until verified against another source the field is left empty rather than shown ten or a hundred times off. Bars do carry IBKR's volume as reported, marked unverified.
- **Snapshots, not streaming.** Each quote is a one-shot request (cached a few seconds by the service); there is no tick stream, so the UI polls as before.
- **Live only with a subscription.** Without one the quote is DELAYED (the declared delay is 15 minutes) and says so. A paper account has its own data entitlements and may show delayed data even when the live account is subscribed.
- **Stocks and ETFs in USD only.** Indices (SPX, VIX, NDX), crypto, FX and futures stay on their current providers. Regular trading hours only; no extended-hours bars.
- **Not adjusted for dividends.** Historical bars are as IBKR reports them (split-adjusted).
- **Mixed sources inside one chart.** If IBKR answers some requests and Yahoo others (for example during a reconnect), the two can differ slightly in volume and in the last bar; the provider and the fallback note are on each response.
- **One request at a time** (a lock) keeps IBKR's rate limits safe but makes a cold scan of many symbols slow. The scanner and backtester still use their own Yahoo daily-bar source.

## BTC derivatives

- **Unverified against the live exchanges.** The sandbox had no internet. Endpoints (Hyperliquid `metaAndAssetCtxs`, Binance `premiumIndex` and `openInterest`, Bybit v5 `tickers`, OKX `funding-rate`, `open-interest`, `mark-price`, `index-tickers`) and field names are from memory. A mismatch shows up as that venue FAILED with a "shape" error, never as a guess.
- **Regional blocks.** Some exchanges refuse some countries or networks (HTTP 403 or 451). That venue shows as unavailable with the reason; the others still work and coverage is displayed.
- **Perpetuals only.** The basis shown is the perpetual's mark premium to the index, not a dated-futures basis. No options, implied volatility, liquidations, ETF flows or on-chain data: those have no reliable free source and are shown as unavailable, never as zero.
- **Funding intervals.** Hyperliquid is hourly, OKX is measured from its own timestamps, Binance and Bybit are assumed 8 h (BTCUSDT's default). A symbol with a different interval would be mis-scaled until the assumption is replaced by the venues' funding-info endpoints.
- **Annualised funding is simple (rate x periods per year), not compounded,** and it is a description of the current rate, not a forecast or a yield.
- **Open interest covers the venues that answered**, not the whole market, and is in BTC at each venue's mark price. Coin-margined products are not included.
- **Percentiles and 24 h change need ATLAS's own history.** They appear after about 100 recorded points (roughly 8 hours at the 5-minute default) and only while ATLAS is running; there is no backfill from the exchanges.
- **Venue timestamps.** Hyperliquid's response has no timestamp, so local receive time is used; a venue's age is measured against your computer's clock, so a wrong PC clock can show LIVE data as stale or the reverse.

## Desks (BTC only, stocks/ETFs only, per-chart assets)

- **"Equities only" means stocks and ETFs.** Indices (SPX, VIX) and macro series open on the Overview. An unlisted ticker is accepted as an unverified US stock, which is how a symbol such as `BTC` (a real Bitcoin ETF ticker) can be offered as an equity.
- **Per-chart assets and the last stock are remembered in this browser only** (local storage), not in ATLAS's database, so another browser or a cleared cache starts fresh.
- **The BTC desk's compare box still overlays other symbols** for correlation; it does not change the desk's asset.
- Typing into a chart's symbol box keeps keyboard focus there, so the `/` shortcut types into the box: click elsewhere (or press Escape) before using the command bar.

## Removed sections (Portfolio, Risk, Alerts, Trade Ideas)

- **The backend engines still run.** The alert loop keeps evaluating any alert that already exists in the database and Telegram can still deliver it, but there is no screen to create, edit or see alerts any more. Set `ATLAS_ALERT_LOOP=0` to stop the loop. The paper-trading loop (`ATLAS_PAPER_LOOP`) is likewise still on by default and has nothing to do while no orders exist.
- **The Settings page still shows the Telegram section.** It only matters for alerts, so it is now unused unless alerts are created through the API.
- **No way to place a paper order or see a paper portfolio from the screen.** The journal can still import IBKR executions ("Sync executions to journal" in Settings), and the backtester has its own simulated account.
- **Tests for the removed screens (alerts, Telegram, trading) were deleted;** their logic remains covered by the unit and API tests.

## Removed pages (Charts, AI Desk)

- **There is no multi-chart page any more.** One chart on the Overview can change asset; the BTC and Equities pages each have their own fixed charts. Side-by-side charts of different assets are not possible.
- **The AI panel lives on the Overview, BTC Intelligence and Macro pages.** On the BTC page it is locked to Bitcoin; elsewhere it follows the selected instrument. Typing `AI BTC` or a free-text question switches to the Overview, where the panel is small.
- **Ctrl+1 to Ctrl+7 follow the sidebar order** (Overview, BTC, Equities, Scanner, News, Macro, Backtest), so the shortcuts changed again.

## Market-data reliability (fix/market-data-reliability)
- Yahoo serves regular-session prices only. In pre-market and after-hours, Yahoo quotes and all bar data are labelled HISTORICAL ("regular-session price") instead of STALE. Real extended-hours prices are not available from Yahoo; an IBKR quote keeps its own LIVE/DELAYED label.
- Scanner relative strength compares the stock and benchmark over the same two trading dates. If the benchmark lacks either date, the RS field is empty and RS filters cannot pass.
- Identical simultaneous quote/bar requests share one provider call. Yahoo quotes still use a 5-day 1-minute history plus `fast_info` per symbol (needed for previous close, market cap, VWAP); failures are not cached.
