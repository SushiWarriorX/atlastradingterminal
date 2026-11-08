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
| CoinGecko whole-crypto-market snapshot (cycle 9) | Total crypto market value, 24h change and volume, Bitcoin / Ether / stablecoin share ('dominance') | Terminal BTC desk panel, Signal BTC page card |
| US Treasury average interest rates on debt (cycle 14) | Average rate the government pays on all debt outstanding, by type (bills, notes, bonds, TIPS, floating-rate, all marketable, all interest-bearing), with change from last month and a year ago; 15-month history | Terminal Macro desk panel, Signal Macro card |
| US federal budget, Monthly Treasury Statement (cycle 13) | Latest month's receipts, outlays and deficit; fiscal-year-to-date totals against the same months a year earlier; 24-month history | Terminal Macro desk panel, Signal Macro card |
| US Treasury note and bond auction results (cycle 12) | For 2, 3, 5, 7, 10, 20 and 30-year fixed-rate auctions: high yield, change from the previous auction of the same term, bid-to-cover against the average of the four before, amount offered; auctions held but not yet published are listed as pending | Terminal Macro desk panel, Signal Macro card |
| US Treasury General Account, Daily Treasury Statement (cycle 11) | The government's cash balance at the Fed: latest closing balance, 1-day and about-a-month change, month average, 1-year low and high, 60-day history | Terminal Macro desk panel, Signal Macro card |
| NY Fed repo and reverse repo operations (cycle 10) | Cash parked at the Fed overnight (reverse repo) with day change, month average and peak; cash the Fed lent (standing repo) with days used and peak; 40-day history | Terminal Macro desk panel, Signal Macro card |
| World Bank annual indicators (cycle 8) | Yearly economic growth, inflation and unemployment for the US, euro area, China, Japan, UK and India, each with its own latest year and change from the year before | Terminal Macro desk panel, Signal Macro card |
| ECB euro reference exchange rates (cycle 7) | The US dollar against EUR, JPY, GBP, CHF, CNY, CAD and AUD: rate, 1-day and 30-day change in dollar strength, and how many of the seven the dollar is stronger against | Terminal Macro desk panel, Signal Macro card |
| mempool.space Bitcoin network (cycle 6) | Fees (sat/vB and a typical transaction), mempool queue, mining difficulty cycle with estimated next change, hashrate (7-day average, 30/90-day change, 90-day history) | Terminal BTC desk panel, Signal BTC page card |
| DefiLlama stablecoin supply (cycle 5) | Total US-dollar stablecoin supply, changes over 7d/30d/90d/1y, distance from peak, 90-day history, top 6 issuers with share and changes | Terminal BTC desk panel, Signal BTC page card |
| CFTC Commitments of Traders, CME Bitcoin futures (cycle 4) | Weekly long/short/net by trader group (leveraged funds, asset managers, dealers, others), open interest, 1-year rank | Terminal BTC desk panel, Signal BTC page card |
| US Treasury yield curve and debt (cycle 3) | Full par yield curve 1M-30Y with 2s10s / 3m10y inversion checks; total public debt outstanding | Macro desk panel (terminal), Macro card (Signal) |
| NY Fed SOFR (cycle 2) | Overnight funding rate with daily change, next to the Fed target range | Macro key indicators (terminal and Signal) |
| alternative.me Fear & Greed (cycle 1) | Daily 0-100 crypto mood gauge, 31-day history | Terminal BTC desk, Signal BTC page |

## QUEUED (candidates, in order; each must be fetched live before it ships)
(queue is empty: the next cycle searches for new candidates, e.g. Treasury bill auction results, Treasury debt held by the public by holder (check live first), DefiLlama DeFi value once api.llama.fi answers)

## BLOCKED
- api.bls.gov (cycles 13 and 14, still no reply): no reply from this machine (the host is not on the allowed list). It would give official CPI and unemployment without FRED, which is also blocked, so the Macro screen's key indicators stay empty. **Needs the user:** add `api.bls.gov` to the environment's allowed hosts if they want this; the free keyless v1 API allows 25 requests a day.
- api.llama.fi, api.blockchain.info (checked cycle 11): no reply from this machine. DefiLlama stablecoins data shipped earlier; the TVL host is silent now.
- mempool.space Lightning statistics (cycle 11): reachable but the newest record is dated 2026-08-30 (about 70 days old), so it is not shipped as current data. Recheck if it resumes.
- fred.stlouisfed.org: added to the allowed hosts but still no reply after the change (checked cycle 1). Retry next cycle; if still silent, the PPI series ids stay unverified.
- Earlier (before hosts were allowed) every candidate timed out; after the change NY Fed, CFTC, DefiLlama, mempool.space and alternative.me all answered HTTP 200.

## REJECTED
- Hyperliquid open interest and basis (queue item, cycle 9): already shown by the existing BTC derivatives panel (multi-venue funding, open interest and basis, Hyperliquid included). Duplicate; not rebuilt.
