# BTC quantitative research and paper trading system: PROTOCOL v1.2

Pre-registered 2026-11-15 (UTC), BEFORE any strategy was run on the real data under this system. Versions 1.1 and 1.2 (same day, still before any real result; see the amendments log) fix gates that no strategy could have satisfied as first written (1.1) and admission gates that were measuring the market's drift instead of skill (1.2, found by running the whole procedure on synthetic data where the truth is known; see `CALIBRATION.md`). Research and paper only: nothing here places a real order, holds a key, uses leverage or sells short. Everything below is fixed in advance; changing any of it is an amendment (section 11), never a quiet edit.

The point of this document is to decide, before looking at results, what counts as evidence. A backtest with a high return is not evidence of an edge.

## 1. Data

- **Asked for:** Binance BTC/USDT spot. **Status: BLOCKED from this environment.** On 2026-11-15 all four Binance hosts (`api.binance.com`, `data-api.binance.vision`, `api.binance.us`, `data.binance.vision`) answered HTTP 403 from the network proxy, and so did Kraken, Bitfinex and OKX. A refusal is not worked around.
- **Used instead (the "alternative provider" you allowed):** Coinbase Exchange public candles, **BTC-USD** (US dollars, not USDT). Differences to keep in mind: USDT trades at a small premium or discount to the dollar (usually a few tenths of a percent, wider in stress such as May 2022), Coinbase volume is smaller than Binance's, and OHLC values differ slightly. If you allow Binance hosts in the environment network settings, switching is a one-line provider setting; results would then be rerun as a new data version.
- **Timeframes.** The 1-day candle is the only timeframe any strategy trades in v1. 1-hour candles are downloaded and stored (4-hour candles are built from complete 1-hour candles) for later research, but no 1-hour or 4-hour strategy is evaluated yet, so that the daily results cannot be contaminated by extra tries on other timeframes. Adding them is an amendment.
- **Window.** Candles from 2019-01-01 (indicator warm-up, never traded). Evaluation from 2020-01-01 00:00 UTC to the latest complete candle.
- **Clock.** Everything is UTC. A daily candle opens at 00:00 UTC. A candle is COMPLETE only when its open time plus 24 hours is not after the current time. The candle that contains "now" is incomplete and is never used for a signal, a fill or an equity mark.
- **Validation of every download:** timestamps sorted and unique; no gaps (reported, never filled); high at least the larger of open and close, low at most the smaller of them; prices above zero; volume not negative; any close-to-close move beyond 40% flagged for review. A failed check stops the run and says so.
- **Manifest** stored with every run: SHA-256 of the daily file, number of candles, first and last candle, number of gaps, provider, fetch time.

## 2. Periods (calendar, UTC, fixed)

| Period | From | To | Use |
| --- | --- | --- | --- |
| TRAIN | 2020-01-01 | 2022-12-31 | choose parameters |
| VALIDATION | 2023-01-01 | 2024-12-31 | check the choice, admit challengers |
| TEST | 2025-01-01 | latest complete candle at the time of the one evaluation | one look per frozen candidate version |

Each period is simulated from a flat start with the full starting equity. Indicator history may reach back before the period start (past data only).

**Honesty note on the TEST period.** Earlier work in this repository (experiments 1 to 7 and the 40-rule strategy library) already scored a sealed final 30% of Coinbase history, which runs from 2023-06 to 2026-11 and overlaps TEST. The author has therefore seen how Bitcoin and several rule families behaved in 2025 and 2026. TEST is **contaminated** in the strict sense. Its results count only as a necessary condition, never as proof. The only fully clean evidence is the **forward paper record** that starts on the first daily run after this protocol is committed.

## 3. Execution and costs

- Fee 0.10% of notional per side. Slippage 0.05% per side, applied against the trade. Cash earns nothing. (Earlier experiments here used 0.05% plus 0.05%; the higher costs are deliberate.)
- A signal uses only completed daily candles up to the close of candle i. The order executes at the **open of candle i+1** (the next executable price). No intrabar information is used for decisions.
- A protective stop is checked against the candle's low. If the stop is hit the fill is at the stop price, or at the open if the open is already below it (a gap); slippage and fee apply to stop fills too. A position entered at the open can be stopped out in the same candle. An entry whose fill price is at or below its stop is rejected.
- Sensitivity runs: (fee, slippage) of (0.05%, 0.02%), (0.10%, 0.05%) the default, (0.20%, 0.10%) and (0.30%, 0.15%).
- Not modelled: exchange minimum order sizes, partial fills, outages, taxes, the USDT basis, market impact (balances stay at or under $100,000). The paper clock (the 00:15 UTC run) is modelled as if orders were placed at the 00:00 open; a 15-minute delay would add noise of roughly 0.3% of price, not a bias.

## 4. Accounts and risk

- Strategy comparison accounts start at $10,000 each. The main portfolio starts at $100,000 and holds **only champions**; with no champion it stays in cash and the report says so.
- **Stop-based strategies** (families 1 to 10): size = the smaller of (equity x 1% divided by the distance between the entry fill and the protective stop) and (equity x 100% divided by the entry fill, with the fee reserved). The 1% is the planned loss at the stop, before gaps, slippage and fees. Default protective stop: the entry-decision close minus 3 x ATR(14) (families that have their own stop rule say so below).
- **Weight-mode strategies** (families 11 and 12, simple risk-managed exposure) are exempt from the 1% rule because their risk control is the exposure itself; capped at 100%, no leverage.
- **Circuit breaker:** when an account's equity, marked at a close, is 15% below its running peak, all positions are closed at the next open and the account halts (no new entries). It applies to every strategy and portfolio account except the buy-and-hold and cash benchmarks. The **main portfolio** stays halted until a human resets it (it is the owner's portfolio control). A **research account** (a backtest, or the shadow account of a challenger) resumes by itself at the close 30 days after the trip: flat, armed again, with the peak re-based to the then-current equity. Without that, a full-exposure Bitcoin account trips within months and sits in cash for the rest of the period, which measures nothing. Every trip is recorded and shown in the report. (v1.1)
- **Re-entry rule** (stop-based families): a strategy is "armed" at the start and whenever its state is OFF. It may enter only when armed and flat and its state is ON; entering disarms it. So after a stop-out it waits for the state to go OFF and ON again; it does not re-enter the next day.
- **Disclosure about sizing.** With 1% risk and a 3 x ATR stop, typical Bitcoin exposure is roughly 10 to 15% of equity, so raw returns are small compared with buy-and-hold by construction. Every report therefore also shows (a) the same signals at full exposure (100% when long, no per-trade risk cap), labelled as a sensitivity, and (b) an **exposure-matched hold** (the same average exposure held constantly), because a strategy that is merely invested less is not better.

## 5. Strategy families (fixed grids; 100 configurations in total, so N = 100)

Notation: close, high, low are of the completed candle i. SMA_n is the mean of the last n closes. ATR(14) is Wilder's average true range (RMA with alpha 1/14, seeded with the first 14 true ranges). RSI(n) is Wilder's. Standard deviation for Bollinger bands has ddof 0. Realised volatility is the ddof-1 standard deviation of the last 20 daily returns times the square root of 365. A family's STATE is evaluated at each close; ON from the next open.

| # | Family | State is ON when | Grid | Own stop rule |
| --- | --- | --- | --- | --- |
| 1 | `sma_cross` (trend) | SMA_fast > SMA_slow | fast 10, 20, 30, 50; slow 50, 100, 150, 200; fast < slow (15) | fixed at entry: 3 ATR |
| 2 | `donchian` (trend) | close > highest high of the previous N candles; stays ON until stopped | N 20, 40, 55, 80 (4) | trailing: lowest low of the last N/2 candles including i, ratcheted up only |
| 3 | `ma_atr_trend` (trend, ATR exit) | close > SMA_L and armed (re-armed when close <= SMA_L); stays ON until stopped | L 100, 150, 200; m 2, 3, 4 (9) | trailing: ratchet of (close - m x ATR) |
| 4 | `tsmom` (momentum) | close / close[i-L] - 1 > 0 | L 30, 60, 90, 180, 365 (5) | fixed: 3 ATR |
| 5 | `rsi_momentum` | RSI > enter threshold; OFF when RSI < exit threshold (hysteresis) | n 14, 21; enter 55, 60, 65; exit 40, 45, 50 (18) | fixed: 3 ATR |
| 6 | `mom_vol` (momentum + volatility filter) | return over L > 0 and realised volatility <= cap | L 30, 60, 90; cap 0.6, 0.8, 1.0 (9) | fixed: 3 ATR |
| 7 | `bollinger_mr` (mean reversion) | enter when close < SMA_n - k x sigma_n; OFF when close >= SMA_n | n 20, 30; k 1.5, 2.0, 2.5 (6) | fixed: 3 ATR |
| 8 | `rsi_oversold` (mean reversion) | enter when RSI(n) < enter threshold; OFF when RSI > exit threshold | n 7, 14; enter 20, 25, 30; exit 50, 55 (12) | fixed: 3 ATR |
| 9 | `vol_breakout` | close[i] - close[i-1] > k x ATR(14)[i-1]; OFF after `hold` candles | k 1.0, 1.5, 2.0; hold 5, 10, 20 (9) | fixed: 3 ATR |
| 10 | `regime_switch` (trend vs ranging) | if ADX(14) > threshold (trend): SMA_50 > SMA_200; else (ranging): close < SMA_20 - 1.5 x sigma_20 | ADX threshold 20, 25, 30 (3) | fixed: 3 ATR |
| 11 | `vol_target` (weight mode) | target weight = min(1, target / realised volatility over `window`), rebalanced only if it moves more than 0.10 | target 0.30, 0.40, 0.50; window 20, 40 (6) | none |
| 12 | `sma_filter` (weight mode) | weight 1 if close > SMA_L else 0 | L 100, 150, 200, 250 (4) | none |
| B1 | `buy_hold` benchmark | 100% from the first open of the period, one entry | none | none |
| B2 | `cash` benchmark | 0% always | none | none |

Each family's documentation (hypothesis, rationale, where it should work and fail, rules, sizing, parameters, costs, risk limits, failure modes, sources) lives in `strategies/<family>.md` and must exist before the family is run.

## 6. Metrics (all after costs)

Total return; CAGR; maximum drawdown; Sharpe (daily returns, 365 days a year, risk-free zero); Sortino; Calmar; profit factor; win rate; average win and average loss; expectancy per trade; number of trades; average holding period; turnover (traded notional divided by average equity); market exposure (average share of equity in Bitcoin); fees and slippage paid; return relative to buy-and-hold and to the exposure-matched hold; performance by regime. **Excess return** (v1.2): the strategy's daily return less the exposure-matched hold's over the same days; its Sharpe ratio is the **information ratio** used in gate A2. It removes the drift of simply being invested, which is most of what a raw Sharpe ratio measures for a long-only Bitcoin strategy. Regimes are defined from information known at the time: BULL when close > SMA_200 and SMA_200 is higher than 20 days earlier, BEAR when close < SMA_200 and SMA_200 is lower than 20 days earlier, otherwise RANGE.

## 7. Procedure (per family, in this order, once)

1. **Select on TRAIN.** Run every configuration of the grid on TRAIN. The score of a configuration is the mean of its own TRAIN Sharpe and the TRAIN Sharpe of its grid neighbours (index distance 1 in one parameter, valid combinations only), which prefers a stable region to an isolated peak. The highest score wins; a tie goes to lower turnover.
2. **Check on VALIDATION.** Run the chosen configuration and its neighbours on VALIDATION.
3. **Walk-forward.** Expanding window: the first fit uses 2020-01-01 to 2021-12-31, then the window grows by six months at a time, each fit choosing parameters with the rule in step 1 and being scored on the next six months, up to the latest complete candle. The stitched out-of-sample record (each segment starting flat) is compared with buy-and-hold over the same windows.
4. **Sensitivity.** The four cost settings of section 3; the full-exposure variant of section 4; neighbours.
5. **Multiple testing.** (a) The deflated Sharpe ratio (Bailey and Lopez de Prado, 2014) with N = 100 trials on the pooled TRAIN plus VALIDATION daily returns, using the variance of the per-day Sharpe ratios of all 100 configurations; computed on the strategy's returns and on its returns in excess of the exposure-matched hold. It is **reported, not an admission gate** (v1.2): on raw returns a threshold of 0.50 is a coin flip for the best of many trials and the number rewards the market's drift, and on excess returns it could not be passed even on synthetic data with a planted edge (`CALIBRATION.md`). Gate P3 uses the excess-returns version at 0.95. (b) A random-timing null: the strategy's own exposure schedule (the share of equity in Bitcoin held through each day, measured at the open after that day's order) is shifted around a circle by whole days, at least 60 days from the real alignment, against the same close-to-close price path and the same costs; 1,000 distinct shifts, or all of them when fewer exist (612 on VALIDATION alone); the p-value is the share of shifted copies with a Sharpe at least as high as the real schedule's (which starts flat). On VALIDATION alone it is gate A3: the configuration was chosen on TRAIN, so VALIDATION is untouched by the choice and the p-value is valid for it. On the pooled days including TEST it is part of gate P3.
6. **Gates** (section 8) are applied mechanically. The TEST period is evaluated only by the promotion pipeline, once per frozen candidate version, and each look is recorded in `registry/holdout_log.jsonl`.

No family's rules or grid may change after its VALIDATION or TEST result is seen. A change is a new candidate version: it counts toward N, and its VALIDATION and TEST results are flagged "reused" and cannot support promotion.

## 8. Gates (v1.1; the gate numbers of v1 are mapped in the amendments log)

**Challenger admission** (the strategy gets its own paper account, a shadow forward test; it is NOT a champion, and an admission is not evidence of an edge: `CALIBRATION.md` gives the share of pure-noise datasets in which something is admitted). All must hold:
- **A1.** At least 10 completed trades (weight mode: at least 10 position changes) on TRAIN plus VALIDATION, so that there is something to watch. (The sample-size requirement proper is P1.)
- **A2.** The information ratio against the exposure-matched hold is above zero on TRAIN and on VALIDATION (v1.2: replaces gates on raw Sharpe and return, which measured the market's drift).
- **A3.** The random-timing p-value on VALIDATION alone is at most 0.05 (v1.2: replaces "VALIDATION Sharpe at least half of TRAIN's", which punished the winner's curse and rewarded drift, and the deflated-Sharpe gate).
- **A4.** Parameter stability on TRAIN: at least 60% of the neighbours reach at least 70% of the chosen configuration's Sharpe. (Computed only when the chosen configuration's TRAIN Sharpe is above zero; otherwise A4 fails.) Neighbours are compared on raw Sharpe because stability asks whether the chosen region is robust, not whether it beats holding.
- **A5.** Net Sharpe above zero on TRAIN plus VALIDATION with doubled costs (0.20% plus 0.10%).

**Champion promotion** (eligible for the main portfolio). All of A1 to A5, and:
- **P1. Sample size.** At least 30 completed trades (weight mode: 30 position changes) over TRAIN plus VALIDATION plus TEST, and total net profit still positive after removing the single best trade. Slow rules make only a few trades a year and will often stay challengers for years; the report then says "too few trades to judge", never "no edge".
- **P2.** TEST (one look, contaminated, a necessary condition only): net Sharpe at least the buy-and-hold Sharpe plus 0.10, and maximum drawdown at most 75% of the exposure-matched hold's maximum drawdown.
- **P3.** Deflated Sharpe ratio of the excess returns at least 0.95 on TRAIN plus VALIDATION plus TEST, and random-timing null p at most 0.05 over the same days.
- **P4.** Walk-forward: stitched out-of-sample Sharpe at least the buy-and-hold Sharpe over the same windows, and positive in at least 60% of the windows.
- **P5. Forward paper record:** at least 90 days and at least 5 closed trades since admission, no circuit-breaker trip, forward net return not worse than the exposure-matched hold by more than 5 percentage points. Under 60 days of forward record nothing is said about a strategy beyond "too early".
- **P6.** A written promotion record (date, evidence, spec hash). A champion's rules and parameters are then frozen (hash-checked at every run). Replacement needs a new promotion.

Three outcomes are reported, not two: **rejected** (the evidence says no), **admitted** (worth watching in paper), and **too thin to judge** (not enough trades or too short a record to say anything). Only the first is a statement about edge.

Stated expectation, before any run: most families will not beat buy-and-hold on risk-adjusted terms over 2020 to 2024 (a window with a very high buy-and-hold Sharpe); trend and filter families will probably cut drawdown at the price of return; mean-reversion families will probably lose after 0.30% round-trip costs; **zero champions is the most likely outcome**, and the system is built to say so plainly rather than to find something.

## 9. Forward paper trading

- Starts with the first daily run after this protocol is committed. The daily run is scheduled for 00:15 UTC.
- One persistent account per challenger and per benchmark ($10,000 each), plus the main portfolio ($100,000, champions only). Challenger accounts are research accounts (30-day breaker cool-off, section 4); the main portfolio waits for a human.
- **A trade is recorded on signal.** When a strategy's state changes on a completed candle, an order is written to the ledger immediately (signal time, rule state and the numbers behind it, intended side and size, the stop), then updated with the fill (execution time, price, quantity, fee, slippage cost, equity before and after) at the next open, or marked rejected with the reason. Every fill, stop-out and circuit-breaker action is a ledger row. Per account the state keeps starting balance, cash, BTC quantity, equity, realised and unrealised profit and loss, fees and slippage paid, exposure, running peak, drawdown, circuit-breaker state and the pending order.
- The paper engine and the backtester are the same code stepping through candles; a test checks that stepping one candle at a time gives exactly the backtest ledger.
- Challengers are never promoted because they recently did well; champions are never tuned on their own paper results.

## 10. Records and reports

Every candidate, rejected or not, is appended to `registry/candidates.jsonl` with a canonical hash of its specification, protocol version, data manifest, results and decision, so failed ideas are not repeated. A new candidate whose position series correlates 0.90 or more with an existing one is flagged as a renamed version of it and counted with it. The daily report (`reports/YYYY-MM-DD.md`, `reports/latest.md`, `dashboard.json`) shows data status, signals, trades, account equity against benchmarks, drawdowns, exposure, circuit-breaker state, what was tested, what was rejected and why, and what is not verified.

## 11. Amendments

Versioned and dated at the bottom of this file. Earlier results are never reinterpreted under a later protocol; they are rerun and reported next to the old ones.

## Sources (the research behind the families; claims are the authors', not ours, and several are about other markets)

Trend and moving averages: Brock, Lakonishok and LeBaron (1992), *Simple technical trading rules and the stochastic properties of stock returns*, Journal of Finance 47(5); Faber (2007), *A quantitative approach to tactical asset allocation*, Journal of Wealth Management 9(4); Faith (2007), *Way of the Turtle* (Donchian channels); Wilder (1978), *New Concepts in Technical Trading Systems* (ATR, RSI, ADX). Momentum: Moskowitz, Ooi and Pedersen (2012), *Time series momentum*, Journal of Financial Economics 104(2); Liu and Tsyvinski (2021), *Risks and returns of cryptocurrency*, Review of Financial Studies 34(6). Volatility management: Barroso and Santa-Clara (2015), *Momentum has its moments*, Journal of Financial Economics 116(1); Moreira and Muir (2017), *Volatility-managed portfolios*, Journal of Finance 72(4). Mean reversion: Bollinger (2001), *Bollinger on Bollinger Bands*; Connors and Alvarez (2009), *Short Term Trading Strategies That Work* (practitioner claims, not peer reviewed). Technical analysis overall: Park and Irwin (2007), *What do we know about the profitability of technical analysis?*, Journal of Economic Surveys 21(4). Multiple testing and overfitting: Bailey and Lopez de Prado (2014), *The deflated Sharpe ratio*, Journal of Portfolio Management 40(5); White (2000), *A reality check for data snooping*, Econometrica 68(5); Harvey, Liu and Zhu (2016), *... and the cross-section of expected returns*, Review of Financial Studies 29(1). Citation details were written from memory and are checked against the sources in `strategies/SOURCES.md` as the research proceeds; a citation not yet checked there is marked so.

## Amendments log

- v1, 2026-11-15: first version.
- v1.1, 2026-11-15, **before any family was run and before any result was seen** (found while writing the strategy notes, by asking of each gate whether the strategies it is meant to judge could ever pass it):
  - (a) Section 4, circuit breaker: as written, an account halted for good after its first trip. A full-exposure Bitcoin account trips within months, so the weight-mode families and every full-exposure sensitivity would have measured the first trip and then a flat line. Research accounts now resume after a 30-day cool-off with the peak re-based; the main portfolio still waits for a human. Trips are counted and reported.
  - (b) Gate 1 (at least 30 trades) was an admission gate. Slow rules (a 50/200 crossover, a 365-day momentum rule) make a handful of trades in five years, so no slow rule could ever have been admitted, and "cannot be judged" would have been reported as "no edge". Admission now needs 10 trades (A1); 30 trades is a promotion condition (P1) with a best-trade check. The outcome "too thin to judge" is reported separately.
  - (c) Gate 2 (no circuit-breaker trip on TRAIN or VALIDATION) is dropped because of (a); A2 now asks for a positive TRAIN Sharpe and a positive VALIDATION return. A4 is computed only when the chosen configuration's TRAIN Sharpe is positive.
  - (d) Gate 7 (maximum drawdown "10 percentage points shallower than the exposure-matched hold") cannot be met by a risk-sized strategy, whose exposure-matched hold has a drawdown of under 10 points itself. P2 now asks for at most 75% of the matched hold's maximum drawdown.
  - Gate map v1 to v1.1: 1 to A1 and P1; 2 to A2; 3 to A3; 4 to A4; 5 to A5; 6 to A6; 7 to P2; 8 to P3; 9 to P4; 10 to P5; 11 to P6.
- v1.2, 2026-11-15, **before any family was run on the real data**. Found by running the whole procedure on synthetic candles with the same calendar, where the truth is known (`CALIBRATION.md`, code `atlas_api/btcquant/calibration.py`):
  - (a) The v1.1 admission gates did not discriminate. On 24 datasets per world they admitted at least one family in 75% of pure-noise datasets with an upward drift, 25% of pure-noise datasets with a mild drift, and only 17% and 13% of datasets with a strong and a weak planted trend edge. A2, A3, A5 and A6 read raw Sharpe ratios and returns, which for a long-only Bitcoin strategy mostly measure the market's drift (Bitcoin's drift over 2020 to 2024 is very large), and A6 at 0.50 is a coin flip for the best of many trials.
  - (b) Changes. A2: the information ratio against the exposure-matched hold must be above zero on TRAIN and on VALIDATION (was: TRAIN Sharpe above zero and VALIDATION return above zero). A3: the random-timing p-value on VALIDATION alone must be at most 0.05; the configuration was chosen on TRAIN, so VALIDATION is untouched by the choice and the p-value is valid for it (was: VALIDATION Sharpe at least half of TRAIN's, which punished the winner's curse). A6 (deflated Sharpe at least 0.50) is removed as a gate and reported instead: on raw returns it rewards drift, and on excess returns it was never reached even in the strong planted world (the cross-trial variance sets a hurdle above what five years can show). P3 now uses the deflated Sharpe of the excess returns. A1, A4 and A5 are unchanged.
  - (c) The limit of 0.05 for A3 is the loosest on the grid 0.01 to 0.15 for which the share of no-skill datasets with something admitted stays at about 15% or less (12% and 16% on the 100 datasets per world used to choose it, a little optimistic for that reason; 20% and 28% on 25 fresh datasets per world; pooled 14% and 18%); the same gates admit something in 60% of strong-edge datasets (44% on the fresh 25, 57% pooled) and about one weak-edge dataset in five. The target was set after a first look at 24 datasets per world and before the 100-dataset table.
  - (d) What an admission means is now stated in the protocol and in every report: if the data were noise, roughly one dataset in six admits something (the pooled estimate, with a wide margin).
  - Gate map v1.1 to v1.2: A1 unchanged; A2 changed; A3 changed; A4 and A5 unchanged; A6 removed from the gates (reported); P3 changed; P1, P2, P4, P5 and P6 unchanged.
