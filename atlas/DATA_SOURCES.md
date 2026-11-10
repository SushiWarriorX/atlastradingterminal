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
| NY Fed reference rates: Fed policy rate (EFFR), target range, overnight rates (cycle 17) | Effective federal funds rate with day change, the Fed's target range and where the rate sits in it, when the range last changed (found from the data), and OBFR, TGCR, BGCR and SOFR; 60-day EFFR history | Terminal Macro desk panel (high on the desk), Signal Macro card (right after the key indicators) |
| NY Fed System Open Market Account holdings (cycle 16) | What the Fed holds, weekly: total, Treasuries vs mortgage-backed securities, mix and shares, changes over 1, 4, 13 and 52 weeks, distance from the 2022 peak, two years of weekly history | Terminal Macro desk panel, Signal Macro card |
| US debt by type of security, Monthly Statement of the Public Debt (cycle 15) | Total public debt outstanding split into bills, notes, bonds, TIPS, floating-rate and non-marketable, each with size, share of the total and monthly change; held by the public vs owed to government accounts; bills' share of marketable debt; 10 month-ends of history | Terminal Macro desk panel, Signal Macro card |
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
| US Treasury interest expense on debt held by the public (FiscalData `v2/accounting/od/interest_expense`, verified live 2026-11-09: HTTP 200, no key, newest 2026-10-31) | Monthly interest owed on bills, notes, bonds, TIPS, floating rate notes and savings bonds, with the same month and year-to-date a year earlier, checked against the source's own year-to-date figure (FY2026 $1,068.5B, FY2025 $973.7B, exact). Government-account (intragovernmental) rows left out on purpose | Macro: terminal INTEREST ON THE DEBT panel, Signal Macro card |
| US Treasury buyback operations (FiscalData `v1/accounting/od/buybacks_operations`, verified live 2026-11-10: HTTP 200, no key, newest 2026-11-05, 233 rows since 2000, 171 in the current program) | What dealers offered, what the Treasury bought, by operation type, security type and maturity bucket; last 90 days and 12 months, independent sum checked; missing results counted apart, not as zero; rows before May 2024 left out (closed earlier program) | Macro: terminal TREASURY BUYBACKS panel, Signal Macro card |
| US Treasury bill auction results (FiscalData `v1/accounting/od/auctions_query` with `security_type = Bill`, verified live 2026-11-10: HTTP 200, no key; newest completed auction 2026-10-15, results for Oct 19 and 20 not yet published) | Per term (4, 6, 8, 13, 17, 26, 52 weeks): rate, change from the previous auction, bid-to-cover versus the last four, size, who bought (dealers, direct, indirect). Marked OVERDUE with the real gap when the source is behind; pending auctions listed, not guessed; cash management bills left out | Macro: terminal TREASURY BILL AUCTIONS panel, Signal Macro card |
| US Treasury marketable borrowing, Daily Treasury Statement Public Debt Transactions (FiscalData `v1/accounting/dts/public_debt_transactions`, verified live 2026-11-10: HTTP 200, no key, newest day 2026-11-06, 128,952 rows) | New bills, notes, bonds and TIPS sold, old ones paid back, and net, for the latest day, the month so far and the fiscal year so far, by type, with the same point a year earlier; the month's daily amounts are added up and checked against the source's own month-to-date totals; trust-fund (Government Account Series) and savings rows left out | Macro: terminal TREASURY BORROWING panel, Signal Macro card |
| NY Fed primary dealers' net position in US Treasuries excluding TIPS (Primary Dealer Statistics API `markets.newyorkfed.org/api/pd/get/PDPOSGST-TOT.json`, verified live 2026-11-10: HTTP 200, no key; newest as-of 2026-10-28, weekly since 2013) | The net position (long minus short), the week-on-week change checked against the source's own change series (`PDPOSGST-TOTC`) over 26 weeks, the same week a year earlier, the 52-week low and high and how many of those weeks were lower, and 104 weeks of history. Weeks the source marks `*` or `N/A` are left out, never zero. The breakdown by maturity is held back: bills, FRNs and the seven coupon buckets do not add up to the total (about $36B short in the latest week), so it cannot be checked | Macro: terminal DEALER TREASURY POSITIONS panel, Signal Macro card |
| alternative.me Fear & Greed (cycle 1) | Daily 0-100 crypto mood gauge, 31-day history | Terminal BTC desk, Signal BTC page |

## QUEUED (candidates, in order; each must be fetched live before it ships)
(otherwise the queue is empty: the next cycle searches for new candidates, e.g. DefiLlama DeFi value once api.llama.fi answers)

## BLOCKED
- Nasdaq public website feeds (cycle: fundamentals upgrade): `api.nasdaq.com/api/ipo/calendar` and `/api/screener/stocks` answer from this machine and feed the new Discover panels (listings and the "new to me" universe). They are unofficial, undocumented and their terms were not reviewed; if you do not want them, say so and those two panels will be switched off.
- SEC EDGAR from this session: the request needs `ATLAS_SEC_CONTACT`; this session's safety check refused a command containing the contact email, so live SEC data for the new research engine is unverified here.
- Exchange and market-data hosts (checked cycle 15, no reply, not on the allowed list): www.deribit.com (BTC options and the DVOL volatility index), api.kraken.com, api.bitfinex.com, www.okx.com, api.bybit.com, fapi.binance.com, ticdata.treasury.gov (foreign holders of Treasuries). **Needs the user:** adding hosts to the environment's allowed list would unlock BTC implied volatility (Deribit) and foreign Treasury holdings (TIC); each is free and keyless.
- api.bls.gov (cycles 13 and 14, still no reply): no reply from this machine (the host is not on the allowed list). It would give official CPI and unemployment without FRED, which is also blocked, so the Macro screen's key indicators stay empty. **Needs the user:** add `api.bls.gov` to the environment's allowed hosts if they want this; the free keyless v1 API allows 25 requests a day.
- api.llama.fi, api.blockchain.info (checked cycle 11): no reply from this machine. DefiLlama stablecoins data shipped earlier; the TVL host is silent now.
- mempool.space Lightning statistics (cycle 11): reachable but the newest record is dated 2026-08-30 (about 70 days old), so it is not shipped as current data. Recheck if it resumes.
- fred.stlouisfed.org: added to the allowed hosts but still no reply after the change (checked cycle 1). Retry next cycle; if still silent, the PPI series ids stay unverified.
- Earlier (before hosts were allowed) every candidate timed out; after the change NY Fed, CFTC, DefiLlama, mempool.space and alternative.me all answered HTTP 200.

## REJECTED
- Hyperliquid open interest and basis (queue item, cycle 9): already shown by the existing BTC derivatives panel (multi-venue funding, open interest and basis, Hyperliquid included). Duplicate; not rebuilt.
