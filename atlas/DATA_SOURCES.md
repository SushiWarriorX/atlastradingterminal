# Data sources

Status key: LIVE (shipped), QUEUED (next), BLOCKED (not reachable from the build machine, host noted), REJECTED (reason noted).

## LIVE
| Source | What it gives | Where |
| --- | --- | --- |
| Coinbase Exchange public candles | BTC-USD daily/hourly prices | Strategy Lab, charts |
| Hyperliquid funding history | BTC perpetual funding (from 2023) | Strategy Lab |
| SEC EDGAR (needs `ATLAS_SEC_CONTACT`) | Filings, annual financials | Stock deep-dive, Discover |
| FRED public CSV | Yields, CPI, PCE, PPI, jobs, GDP, Fed rate, dollar index, Fed balance sheet | Macro |
| BLS release calendar (ICS) | CPI, jobs, PPI release dates | Macro, Calendar |
| BEA schedule page | GDP and PCE release dates | Calendar |
| Treasury FiscalData | Upcoming auctions | Calendar |
| Nasdaq public calendars (unofficial) | Earnings, dividends | Calendar |
| Fed FOMC table (hand-entered) | Meeting dates | Macro, Calendar |
| Yahoo Finance (unofficial) | Stock prices, valuation | Signal, Stocks |
| RSS feeds | Headlines | News, Macro |
| CoinGecko, mempool.space | Crypto fundamentals | Signal |
| alternative.me Fear & Greed (cycle 1) | Daily 0-100 crypto mood gauge, 31-day history | Terminal BTC desk, Signal BTC page |

## QUEUED (candidates, in order; each must be fetched live before it ships)
1. NY Fed SOFR and reference rates (markets.newyorkfed.org JSON)
2. Treasury FiscalData: debt to the penny, daily Treasury yield curve
3. CFTC Commitments of Traders for Bitcoin futures (publicreporting.cftc.gov)
4. DefiLlama stablecoin supply (liquidity proxy for crypto)
5. mempool.space on-chain fees and hashrate (BTC network activity)
6. ECB reference exchange rates (EUR/USD and others)
7. World Bank / IMF annual macro series (slow-moving context)
8. Hyperliquid open interest and basis (extend the existing client)

## BLOCKED
- fred.stlouisfed.org: added to the allowed hosts but still no reply after the change (checked cycle 1). Retry next cycle; if still silent, the PPI series ids stay unverified.
- Earlier (before hosts were allowed) every candidate timed out; after the change NY Fed, CFTC, DefiLlama, mempool.space and alternative.me all answered HTTP 200.

## REJECTED
- (none yet)
