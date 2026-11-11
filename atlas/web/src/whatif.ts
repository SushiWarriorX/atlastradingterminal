// Mirrors GET /api/signal/whatif/{asset}. Every figure is calculated by the server from the asset's own daily closes.
export interface WhatIf {
  asset: { id: string; symbol: string; name: string };
  amount: number; from: string; to: string; years: number; bars: number; bars_per_year: number; last_price: number;
  prov: { provider: string; status: string }; adjustment: string;
  lump_sum: { label: string; buy_date: string; buy_price: number; invested: number; value_now: number; gain: number; return_pct: number; per_year_pct: number | null; lowest_vs_cost_pct: number; max_drawdown_pct: number; days_below_cost: number; days: number }[];
  monthly: { label: string; from: string; buys: number; invested: number; value_now: number; gain: number; return_pct: number; average_price: number; same_money_lump_sum_return_pct: number }[];
  every_start: { label: string; worst_pct: number; median_pct: number; best_pct: number; share_positive: number; share_lost_20: number; worst_buy_date: string; best_buy_date: string; note: string }[];
  exit_rules: { label: string; rules: { rule: string; label: string; result_pct: number; sold: boolean; sold_on: string | null; why: string }[] }[];
  bootstrap: { paths: number; p5_pct: number; median_pct: number; p95_pct: number; share_positive: number; share_lost_20: number; typical_worst_dip_pct: number; note: string } | null;
  notes: string[]; caveats: string[];
}

export interface Sentiment {
  available: boolean; reason?: string; demo: boolean; source: string; url: string; note: string; as_of: string;
  value?: number; label?: string; date?: string; age_days?: number; freshness?: "CURRENT" | "OVERDUE";
  yesterday?: number | null; a_week_ago?: number | null; a_month_ago?: number | null; history?: { date: string; value: number }[];
}

export interface NarrativeBasketRow { symbol: string; available: boolean; price?: number; change_1d_pct?: number | null; return_5d_pct?: number | null; return_1m_pct?: number | null; above_50d?: boolean | null; volume_vs_normal?: number | null; last_bar?: string }
export interface NarrativeData {
  asof: string; created_at: string; demo: boolean; theme: string | null; notes: string[]; disclaimer: string; gaps: string[];
  method: { weights: Record<string, number>; scales: Record<string, string>; steps: string[]; note: string };
  data: { prices: string; prices_status: string; prices_as_of: string | null };
  name: string; score: number; parts: Record<string, number | null>; context: string; context_note: string; why_now: string[]; basket: NarrativeBasketRow[];
  headlines: { title: string; link: string | null; feed: string | null; published: string | null }[]; risks: string[]; volatility_note: string; recent_excluded: string[];
  facts: { median_return_1m_pct: number; spy_return_1m_pct: number | null; relative_1m_pct: number; share_above_50d: number | null; median_volume_vs_normal: number | null; headlines_48h: number | null; median_daily_range_pct: number };
  runners_up: { theme: string; name: string; score: number; relative_1m_pct: number }[]; all_themes: { theme: string; name: string; score: number; recently_featured: boolean }[];
}

export interface TreasuryCurve { available: boolean; reason?: string; date?: string; age_days?: number; freshness?: "CURRENT" | "OVERDUE"; source?: string; note?: string;
  points?: { tenor: string; rate: number | null; change_1d_bp: number | null; change_1m_bp: number | null }[];
  spreads?: { "2s10s_bp": number | null; "3m10y_bp": number | null; "2s10s_inverted": boolean | null; "3m10y_inverted": boolean | null }; compared_with?: { previous_day: string | null; one_month: string | null } }
export interface TreasuryDebt { available: boolean; reason?: string; date?: string; age_days?: number; freshness?: "CURRENT" | "OVERDUE"; source?: string; note?: string;
  total_trillions?: number; held_by_public_trillions?: number; intragovernmental_trillions?: number; change_vs_previous_day_billions?: number | null; change_vs_a_year_ago_pct?: number | null }
export interface TreasuryData { as_of: string; demo: boolean; curve: TreasuryCurve; debt: TreasuryDebt }

export interface PositioningGroup { key: string; name: string; who: string; long: number; short: number; net: number; net_change: number | null; long_pct_oi: number; short_pct_oi: number; net_rank_1y: number | null; net_history: number[] }
export interface Positioning { available: boolean; reason?: string; demo: boolean; as_of: string; date?: string; age_days?: number; freshness?: "CURRENT" | "OVERDUE"; source?: string; market?: string;
  open_interest?: number; open_interest_change?: number | null; traders?: number | null; weeks_of_history?: number; groups?: PositioningGroup[]; note?: string }

export interface StablecoinTop { name: string; symbol: string; billions: number; share_pct: number | null; change_7d_pct: number | null; change_30d_pct: number | null }
export interface Stablecoins { available: boolean; reason?: string; demo: boolean; as_of: string; source?: string; url?: string; note?: string; date?: string; age_days?: number; freshness?: "CURRENT" | "OVERDUE";
  total_billions?: number; changes?: { label: string; ref_date: string; change_billions: number; change_pct: number }[]; peak?: { date: string; total_billions: number; below_peak_pct: number };
  history?: { date: string; total_billions: number }[]; top?: StablecoinTop[] }

export interface OnChainFees { available: boolean; reason?: string; sat_per_vbyte?: { fastest: number; half_hour: number; hour: number; economy: number; minimum: number }; typical_tx_vbytes?: number; typical_tx_sats_fastest?: number; typical_tx_sats_economy?: number;
  mempool?: { transactions: number; megavbytes: number; blocks_worth: number; total_fees_btc: number } }
export interface OnChainDifficulty { available: boolean; reason?: string; progress_pct?: number; estimated_change_pct?: number; previous_change_pct?: number; remaining_blocks?: number; estimated_date?: string | null; next_adjustment_height?: number; block_height?: number | null; note?: string }
export interface OnChainHashrate { available: boolean; reason?: string; date?: string; seven_day_average_eh?: number; latest_day_eh?: number; current_eh?: number | null; changes?: { label: string; change_pct: number }[]; history?: { date: string; eh: number }[]; highest_day?: { date: string; eh: number }; note?: string }
export interface OnChain { as_of: string; demo: boolean; source: string; url: string; fees: OnChainFees; difficulty: OnChainDifficulty; hashrate: OnChainHashrate }

export interface FxPair { pair: string; currency: string; rate: number; date: string; dollar_vs_1d_pct: number; dollar_vs_30d_pct: number | null; compared_with_30d: string | null }
export interface FxData { available: boolean; reason?: string; demo: boolean; as_of: string; date?: string; age_days?: number; freshness?: "CURRENT" | "OVERDUE"; pairs?: FxPair[]; breadth?: { stronger_30d: number; of: number }; source?: string; url?: string; note?: string }

export interface TrackMetrics { net_return_pct: number | null; max_drawdown_pct: number | null; sharpe: number | null; trades: number; win_rate_pct?: number | null }
export interface TrackerForward { error?: string; added?: string; days?: number; from?: string | null; to?: string; enough?: boolean; position_now?: "long" | "flat"; conditions?: { rule: string; met: boolean | null; value: string }[]; note?: string;
  strategy?: { return_pct: number | null; max_drawdown_pct: number | null; closed_trades: number; win_rate_pct: number | null } | null; buy_and_hold?: { return_pct: number | null; max_drawdown_pct: number | null } | null }
export interface TrackerEntry {
  id: string; name: string; family: string; added_at: string; idea: string; why: string; rule: { summary: string; entry: string; exit: string; stop: string } | null;
  snapshot: { library_size: number; data_from: string; data_to: string; bars: number; full: TrackMetrics; in_sample: TrackMetrics; out_of_sample: TrackMetrics; walk_forward: Partial<TrackMetrics>;
    buy_and_hold: { full: TrackMetrics; out_of_sample: TrackMetrics }; robustness: { share_positive: number; doubled_costs_oos_return_pct: number };
    luck_check: { lower_bound: { lower: number; confidence_pct: number; n_compared: number } | null; note: string | null }; evidence: { level: "none" | "weak" | "moderate"; reasons: string[] } };
  forward: TrackerForward | null;
}
export interface TrackerData { as_of: string; demo: boolean; entries: TrackerEntry[]; library_size: number; min_forward_days: number; notes: string[]; data: { demo: boolean; source: string; last_bar: string | null } }

export interface WorldRow { country: string; iso: string; available: boolean; year?: number; value?: number; previous_year?: number | null; previous_value?: number | null; change?: number | null; years_old?: number; history?: { year: number; value: number }[] }
export interface WorldIndicator { key: string; title: string; unit: string; what: string; available: boolean; reason?: string; rows: WorldRow[] }
export interface WorldData { available: boolean; reason?: string; demo: boolean; as_of: string; source: string; url: string; note: string; indicators: WorldIndicator[] }

export interface CryptoMarket { available: boolean; reason?: string; demo: boolean; as_of: string; source: string; url: string; credit: string; note: string; updated_at?: string; age_minutes?: number; freshness?: "CURRENT" | "OVERDUE";
  total_market_cap_trillions?: number; change_24h_pct?: number; volume_24h_billions?: number; volume_to_cap_pct?: number; btc_dominance_pct?: number; eth_dominance_pct?: number; other_pct?: number;
  stablecoin_share_pct?: number | null; stablecoin_note?: string | null; coins?: number; markets?: number; top?: { symbol: string; share_pct: number }[] }

export interface OpsJob { id: string; title: string; kind: string | null; description: string; registered: boolean; enabled: boolean; paused: boolean; priority: number; uses_ai: boolean;
  preferred_market_s: number; preferred_off_s: number; preferred_now_s: number; effective_interval_s: number; why_effective: string[]; differs: boolean; next_run_at: string | null; last_success_at: string | null;
  age_s: number | null; stale: boolean; last_status: string | null; last_error: string | null; deferred_reason: string | null; failures: number; avg_tokens: number | null; avg_runtime_s: number | null;
  runs_total: number; max_tokens: number; max_runtime_s: number; max_experiments: number; running: boolean }
export interface OpsBudget { bucket: string; window: string; unit: string; limit: number | null; used: number; resets_at: string; note: string | null; remaining: number | null; remaining_fraction: number | null; optional_work_allowed: boolean }
export interface OpsRun { id: number; job_id: string; trigger: string; started_at: string; finished_at: string | null; status: string; attempt: number; reason: string | null; tokens_in: number; tokens_out: number; provider_calls: number; duration_s: number | null; error: string | null }
export interface OpsOverview {
  as_of: string; scheduler_alive: boolean; scheduler_heartbeat_age_s: number | null; market_open: boolean; paused: boolean; emergency_stop: boolean; reserve_pct: number; max_concurrent: number; market_note: string;
  claude: { access: string; model: string; telemetry: string; usage_known: boolean; usage_note: string; dollar_cost_known: boolean };
  budgets: OpsBudget[]; jobs: OpsJob[]; runs: OpsRun[]; dead_letters: { id: number; job_id: string; failed_at: string; attempts: number; error: string | null }[]; events: { ts: string; kind: string; severity: string; message: string }[];
}

export interface FedOpsData { available: boolean; reason?: string; demo: boolean; as_of: string; url: string; source?: string; note?: string; date?: string; age_days?: number; freshness?: "CURRENT" | "OVERDUE";
  reverse_repo?: { billions: number; previous_day_billions: number; change_billions: number; average_billions: number; highest_billions: number; highest_date: string; dates_in_window: number };
  repo?: { billions: number; window_total_billions: number; days_used: number; highest_billions: number; dates_in_window: number };
  history?: { date: string; reverse_repo_billions: number; repo_billions: number }[] }

export interface TgaData { available: boolean; reason?: string; demo: boolean; as_of: string; url: string; source?: string; note?: string; date?: string; age_days?: number; freshness?: "CURRENT" | "OVERDUE";
  balance_billions?: number; change_1d_billions?: number; change_month_billions?: number | null; month_average_billions?: number; dates_in_window?: number;
  year_low_billions?: number; year_low_date?: string; year_high_billions?: number; year_high_date?: string; days_in_year_range?: number;
  history?: { date: string; balance_billions: number }[] }

export interface AuctionRow { tenor: string; term: string; auction_date: string; reopening: boolean; age_days: number; high_yield: number; previous_yield: number | null; yield_change: number | null;
  bid_to_cover: number; average_bid_to_cover: number | null; compared_with: number; offering_billions: number | null }
export interface AuctionsData { available: boolean; reason?: string; demo: boolean; as_of: string; url: string; source?: string; note?: string; date?: string; age_days?: number; freshness?: "CURRENT" | "OVERDUE";
  tenors?: AuctionRow[]; pending_results?: { tenor: string; auction_date: string }[] }

export interface InterestData { available: boolean; reason?: string; demo: boolean; as_of: string; url: string; source?: string; note?: string; date?: string; age_days?: number; freshness?: "CURRENT" | "OVERDUE";
  fiscal_year?: number; month_total_billions?: number; year_ago_month_total_billions?: number | null; month_change_pct?: number | null; ytd_months?: number; ytd_total_billions?: number;
  year_ago_ytd_billions?: number | null; ytd_change_pct?: number | null; breakdown?: { key: string; label: string; billions: number; share_pct: number | null }[];
  ytd_check?: { ours_billions: number; source_billions: number; match: boolean } | null; history?: { date: string; total_billions: number }[] }
export interface BuybackOp { date: string; type: string; security: string; maturity: string | null; offered_billions: number | null; accepted_billions: number | null; maximum_billions: number | null; bought_share_pct: number | null; issues_accepted: number | null }
export interface BuybackWindow { operations: number; with_result: number; no_result: number; accepted_billions: number; offered_billions: number; bought_share_pct: number | null }
export interface BuybackGroup { key: string; label: string; operations: number; accepted_billions: number; offered_billions: number }
export interface BuybacksData { available: boolean; reason?: string; demo: boolean; as_of: string; url: string; source?: string; note?: string; date?: string; age_days?: number; freshness?: "CURRENT" | "OVERDUE";
  latest?: BuybackOp; last_90_days?: BuybackWindow; last_365_days?: BuybackWindow; by_security?: BuybackGroup[]; by_type?: BuybackGroup[]; by_maturity?: BuybackGroup[]; recent?: BuybackOp[]; anomalies?: number; program_start?: string }
export interface BillTerm { term: string; auction_date: string; reopening: boolean; age_days: number; investment_rate: number; discount_rate: number; previous_rate: number | null; rate_change_bps: number | null;
  bid_to_cover: number; average_bid_to_cover: number | null; compared_with: number; offering_billions: number | null; accepted_billions: number | null;
  mix: { dealers_pct: number; direct_pct: number; indirect_pct: number; sum_ok: boolean } | null }
export interface BillAuctionsData { available: boolean; reason?: string; demo: boolean; as_of: string; url: string; source?: string; note?: string; date?: string; age_days?: number; freshness?: "CURRENT" | "OVERDUE";
  terms?: BillTerm[]; pending_results?: { term: string; auction_date: string; offering_billions: number | null }[] }
export interface BorrowingPeriod { issues_billions: number; redemptions_billions: number; net_billions: number; year_ago_net_billions?: number | null }
export interface BorrowingData { available: boolean; reason?: string; demo: boolean; as_of: string; url: string; source?: string; note?: string; date?: string; age_days?: number; freshness?: "CURRENT" | "OVERDUE"; fiscal_year?: number;
  latest_day?: { issues_billions: number; redemptions_billions: number; net_billions: number }; month_to_date?: BorrowingPeriod; fiscal_year_to_date?: BorrowingPeriod; year_ago_date?: string | null;
  by_security?: { key: string; label: string; mtd_issues_billions: number; mtd_redemptions_billions: number; mtd_net_billions: number; fytd_net_billions: number }[];
  mtd_check?: { days: number; issues_billions: number; redemptions_billions: number; source_issues_billions: number; source_redemptions_billions: number; match: boolean } | null }
export interface DealersData { available: boolean; reason?: string; demo: boolean; as_of: string; url: string; source?: string; note?: string; date?: string; age_days?: number; freshness?: "CURRENT" | "OVERDUE";
  net_position_billions?: number; previous_date?: string; week_change_billions?: number | null; year_ago_date?: string | null; year_ago_billions?: number | null;
  range_52w?: { weeks: number; low_billions: number; low_date: string; high_billions: number; high_date: string; weeks_lower_than_now: number };
  check?: { weeks: number; mismatches: number; match: boolean; latest_ours_billions: number; latest_source_billions: number } | null; history?: { date: string; net_billions: number }[] }
export interface BudgetData { available: boolean; reason?: string; demo: boolean; as_of: string; url: string; source?: string; note?: string; date?: string; age_days?: number; freshness?: "CURRENT" | "OVERDUE";
  fiscal_year?: number; month?: string; month_receipts_billions?: number; month_outlays_billions?: number; month_deficit_billions?: number;
  ytd_months?: number; ytd_receipts_billions?: number; ytd_outlays_billions?: number; ytd_deficit_billions?: number;
  prior_ytd_receipts_billions?: number | null; prior_ytd_outlays_billions?: number | null; prior_ytd_deficit_billions?: number | null;
  history?: { fiscal_year: number; month: string; receipts_billions: number; outlays_billions: number; deficit_billions: number }[] }

export interface DebtRateRow { name: string; rate: number; change_month: number | null; change_year: number | null }
export interface DebtRatesData { available: boolean; reason?: string; demo: boolean; as_of: string; url: string; source?: string; note?: string; date?: string; age_days?: number; freshness?: "CURRENT" | "OVERDUE";
  rows?: DebtRateRow[]; history?: { date: string; rate: number }[] }

export interface DebtMixRow { name: string; billions: number; share_of_total_pct: number; change_month_billions: number | null }
export interface DebtMixData { available: boolean; reason?: string; demo: boolean; as_of: string; url: string; source?: string; note?: string; date?: string; age_days?: number; freshness?: "CURRENT" | "OVERDUE";
  rows?: DebtMixRow[]; total_billions?: number; held_by_public_billions?: number; held_by_government_accounts_billions?: number; bills_share_of_marketable_pct?: number | null;
  change_since_billions?: number; since?: string; months_covered?: number; history?: { date: string; total_billions: number }[] }

export interface FedHoldingsData { available: boolean; reason?: string; demo: boolean; as_of: string; url: string; source?: string; note?: string; date?: string; age_days?: number; freshness?: "CURRENT" | "OVERDUE";
  total_billions?: number; treasuries_billions?: number; mbs_billions?: number; mix?: { name: string; billions: number; share_pct: number }[];
  changes?: { period: string; since: string | null; change_billions: number | null; change_pct: number | null }[];
  peak_billions?: number; peak_date?: string; from_peak_billions?: number; from_peak_pct?: number; history?: { date: string; total_billions: number }[] }

export interface FedRatesData { available: boolean; reason?: string; demo: boolean; as_of: string; url: string; source?: string; note?: string; date?: string; age_days?: number; freshness?: "CURRENT" | "OVERDUE";
  effr?: number; effr_change_pp?: number | null; target_low?: number; target_high?: number; effr_position?: "inside" | "below" | "above"; effr_above_bottom_pp?: number; sofr_minus_effr_pp?: number | null;
  rates?: { code: string; name: string; rate: number; date: string; p1: number | null; p99: number | null; volume_billions: number | null }[];
  history_available?: boolean; history_reason?: string;
  last_change?: { date: string; days_ago: number; from_range: number[]; to_range: number[]; change_pp: number; window_days: number } | null;
  history?: { date: string; rate: number }[] }
export interface FuturesGroup { key: string; name: string; who: string; long: number; short: number; spread: number; net: number; net_change: number | null; long_pct_oi: number; short_pct_oi: number; net_rank_1y: number | null; net_history: number[] }
export interface FuturesContract { code: string; name: string; what: string; available: boolean; reason?: string; date?: string; age_days?: number; freshness?: "CURRENT" | "OVERDUE"; open_interest?: number; open_interest_change?: number | null; traders?: number | null; weeks_of_history?: number;
  groups?: FuturesGroup[]; checks?: { weeks_checked: number; groups_add_up: boolean; oi_change_pairs: number; oi_change_mismatches: number; ok: boolean } }
export interface FuturesPositioningData { available: boolean; reason?: string; demo: boolean; as_of: string; url?: string; source?: string; note?: string; date?: string; age_days?: number; freshness?: "CURRENT" | "OVERDUE"; contracts?: FuturesContract[] }
export interface RealYieldRow { tenor: string; nominal_pct: number | null; real_pct: number | null; breakeven_pct: number; breakeven_change_1m_bp: number | null; breakeven_change_1y_bp: number | null; real_change_1y_bp: number | null }
export interface RealYieldsData { available: boolean; reason?: string; demo: boolean; as_of: string; url?: string; source?: string; note?: string; date?: string; age_days?: number; freshness?: "CURRENT" | "OVERDUE";
  month_ago_date?: string | null; year_ago_date?: string | null; rows?: RealYieldRow[]; history?: { date: string; breakeven_10y_pct: number }[];
  checks?: { same_day: boolean; range_ok: boolean; latest_dates_differ: boolean; maturities_left_out: string[] } }
