# Data sources

Status key: LIVE (shipped), QUEUED (next), BLOCKED (not reachable from the build machine, host noted), REJECTED (reason noted).

## LIVE
| Source | What it gives | Where |
| --- | --- | --- |
| Coinbase Exchange public candles | BTC-USD daily/hourly prices | Strategy Lab, charts |
| Hyperliquid funding history | BTC perpetual funding (from 2023) | Strategy Lab |
| SEC EDGAR (needs `ATLAS_SEC_CONTACT`) | Annual financials; filings feed: 10-K, 10-Q, 8-K, insider Form 4/144, 5% holders, proxies, offerings, late notices | Stock deep-dive, Discover, SEC Filings panel (terminal Equities desk) and card (Signal stock page) |
| FRED public CSV | Yields, CPI, PCE, PPI, jobs, GDP, Fed rate, dollar index, Fed balance sheet | Macro |
| BLS release calendar (ICS) | CPI, jobs, PPI release dates | Macro, Calendar |
| BEA schedule page | GDP and PCE release dates | Calendar |
| Treasury FiscalData | Upcoming auctions | Calendar |
| Nasdaq public calendars (unofficial) | Earnings, dividends | Calendar |
| Fed FOMC table (hand-entered) | Meeting dates | Macro, Calendar |
| Yahoo Finance (unofficial) | Stock prices, valuation | Signal, Stocks |
| RSS feeds | Headlines | News, Macro |
| CoinGecko, mempool.space | Crypto fundamentals | Signal |
| CFTC Commitments of Traders, CME Bitcoin futures (cycle 4) | Weekly long/short/net by trader group (leveraged funds, asset managers, dealers, others), open interest, 1-year rank | Terminal BTC desk panel, Signal BTC page card |
| US Treasury yield curve and debt (cycle 3) | Full par yield curve 1M-30Y with 2s10s / 3m10y inversion checks; total public debt outstanding | Macro desk panel (terminal), Macro card (Signal) |
| NY Fed SOFR (cycle 2) | Overnight funding rate with daily change, next to the Fed target range | Macro key indicators (terminal and Signal) |
| alternative.me Fear & Greed (cycle 1) | Daily 0-100 crypto mood gauge, 31-day history | Terminal BTC desk, Signal BTC page |

## QUEUED (candidates, in order; each must be fetched live before it ships)
1. DefiLlama stablecoin supply (liquidity proxy for crypto)
2. mempool.space on-chain fees and hashrate (BTC network activity)
3. ECB reference exchange rates (EUR/USD and others)
4. World Bank / IMF annual macro series (slow-moving context)
5. Hyperliquid open interest and basis (extend the existing client)

## BLOCKED
- fred.stlouisfed.org: added to the allowed hosts but still no reply after the change (checked cycle 1). Retry next cycle; if still silent, the PPI series ids stay unverified.
- Earlier (before hosts were allowed) every candidate timed out; after the change NY Fed, CFTC, DefiLlama, mempool.space and alternative.me all answered HTTP 200.

## REJECTED
- (none yet)
