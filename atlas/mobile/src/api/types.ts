// Mirrors the Signal backend contract (atlas_api/signal/models.py and the /api/signal/* routes). Nothing here is computed on the device:
// every figure, label and timestamp arrives from the server already calculated, attributed and formatted.

export type DataStatus = "LIVE" | "DELAYED" | "HISTORICAL" | "STALE" | "DEMO" | "UNAVAILABLE";
export type AssetType = "crypto" | "stock" | "etf";
export type AgentName = "news" | "technical" | "macro" | "fundamentals";
export type Stance = "supportive" | "mixed" | "cautious" | "neutral" | "insufficient";
export type ChartRange = "1D" | "1W" | "1M" | "3M" | "1Y" | "5Y";

export interface Asset {
  id: string;            // stable id: CRYPTO:COINBASE:ETH-USD:SPOT, EQUITY:NASDAQ:AAPL, ETF:ARCA:SPY. Never the ticker.
  symbol: string;
  name: string;
  type: AssetType;
  venue: string;
  support: "supported" | "unverified";
  note: string | null;
}

export interface Prov {
  provider: string;
  status: DataStatus;
  event_time: string | null;
  delay_seconds: number | null;
  session: string | null;
  quality: string[];
}

export interface QuoteView {
  price: number;
  display: string;
  change: number | null;
  change_pct: number | null;
  basis: string;         // what the change is measured against ("previous session close", "24h rolling open")
  prov: Prov;
}

export interface Takeaway { text: string; timeframe: string; source: string; as_of: string }
export interface RowError { code: string; message: string }

export interface WatchRow {
  asset: Asset;
  quote: QuoteView | null;
  spark: number[] | null;
  takeaway: Takeaway | null;
  error: RowError | null;
  spark_error?: string;
  /** Client-only: a row added optimistically that the server has not answered for yet. It is neither a price nor a failure, so it is shown as loading. */
  loading?: boolean;
}
export interface WatchlistResponse { items: WatchRow[]; count: number; demo: boolean; as_of: string }
export interface AssetHeader extends WatchRow { saved: boolean }
export interface SearchResponse { query: string; results: Asset[]; unsupported: { query: string; message: string } | null; notes: string[] }
export interface ChartResponse {
  asset: Asset; range: ChartRange; interval: string; points: [number, number][]; first: number; last: number; change: number; change_pct: number | null;
  derived_from: string | null; prov: Prov; note: string;
}

export interface Source { name: string; url: string | null; kind: "data" | "article" | "official" | "protocol"; as_of: string | null; status: string | null; note: string | null }
export interface Fact {
  key: string; label: string; value: number | string | boolean | null; display: string; unit: string | null; as_of: string | null; source: string;
  timeframe: string | null; kind: "reported" | "calculated";
}
export interface Interpretation { text: string; based_on: string[]; caveat: string | null; timeframe: string | null }
export interface Missing { what: string; why: string }
export interface Story {
  id: string; title: string; link: string | null; source: string; published: string | null; event_time: string | null; fetched_at: string | null;
  scope: "asset" | "industry"; kind: "reporting" | "opinion" | "unconfirmed"; category: string; why_it_matters: string | null; why_origin: "rules" | "ai";
  also: { source: string; title: string; link: string | null }[]; demo: boolean;
}
export interface Level { id: string; kind: "support" | "resistance"; price: number; display: string; timeframe: string; distance_pct: number | null; derivation: string }
export interface EventItem { id: string; title: string; at_utc: string | null; date: string | null; kind: "scheduled" | "release"; link: string | null; note: string | null }
export interface Explanation { text: string; origin: "ai"; model: string; note: string }

export interface Finding {
  agent: AgentName;
  status: "ok" | "partial" | "unavailable" | "not_applicable" | "pending";
  stance: Stance | null;
  stance_rule: string | null;
  takeaway: string;
  facts: Fact[];
  interpretations: Interpretation[];
  stories: Story[];
  levels: Level[];
  events: EventItem[];
  missing: Missing[];
  sources: Source[];
  limitations: string[];
  explanation: Explanation | null;
  data_as_of: string | null;
  analyzed_at: string | null;
  ttl_seconds: number;
  next_refresh_at: string | null;
  demo: boolean;
  error: string | null;
}

export interface BriefingLine { agent: AgentName; text: string; fact_keys: string[]; at_utc: string | null }
export interface Disagreement { agents: AgentName[]; text: string }
export interface Briefing {
  headline: string;
  changed: BriefingLine[];
  supports: BriefingLine[];
  risks: BriefingLine[];
  watch: BriefingLine[];
  disagreements: Disagreement[];
  coverage: { agents_ok: number; agents_total: number; partial: string[]; pending: string[]; unavailable: { agent: string; reason: string }[]; not_applicable: string[] };
  generated_at: string;
  demo: boolean;
}
export interface ResearchResponse { asset: Asset; generated_at: string; demo: boolean; pending: AgentName[]; findings: Record<AgentName, Finding>; briefing: Briefing }

export interface Meta {
  service: string; version: number; demo: boolean; agents: AgentName[]; ai: { enabled: boolean; model: string | null; note: string };
  coverage: { crypto: string; stocks_etfs: string }; directory: { loaded: boolean; error: string | null }; live_trading: false; notes: string[];
}
export interface AuthStatus { required: boolean; authenticated: boolean }
export interface LoginResult extends AuthStatus { token?: string; expires_in?: number }

// --- journal (the simple entries; shared with the terminal) ---------------------------------------------------------------------------
export interface JournalEntry {
  id: string; origin: "manual" | "imported"; editable: boolean; symbol: string; asset_class: string; direction: "long" | "short";
  size: string | null; entry_price: string | null; exit_price: string | null; entry_at: string; exit_at: string | null; fees: string | null; planned_stop: string | null;
  note: string | null; thesis: string | null; risk_plan: string | null; outcome: string | null; has_screenshot: boolean; screenshot?: string | null;
  status: "note" | "open" | "closed"; gross_pnl: string | null; net_pnl: string | null; net_pnl_num: number | null; return_pct: number | null; r_multiple: number | null;
  holding_seconds: number | null; pnl_missing: string[];
}
export interface JournalStats { n: number; reliable: boolean; note?: string | null; wins?: number; losses?: number; win_rate?: number; net_pnl?: number; profit_factor?: number | null }
export interface JournalLog { items: JournalEntry[]; total: number; stats: JournalStats }
export type JournalFilters = { q?: string; status?: "" | "open" | "closed" | "note" };

export interface MacroBriefItem { kind: "fact" | "interpretation"; title: string; detail: string; source: string; link?: string | null }
export interface MacroIndicator { id: string; label: string; available: boolean; reason?: string; value?: number | string | null; unit?: string | null; obs_date?: string | null; change?: { label: string; value: number; unit: string } | null; freshness?: string | null }
export interface MacroEvent { date: string; at_utc: string | null; title: string; source: string; link?: string | null }
export interface MacroHeadline { feed: string; title: string; link: string | null; published: string | null; topic: string; topic_label: string; implication: string; implication_kind: string }
export interface MacroBriefData { as_of: string; demo: boolean; today: MacroBriefItem[]; indicators: MacroIndicator[]; indicators_note: string | null; upcoming: MacroEvent[]; headlines: MacroHeadline[]; topics: Record<string, string>; calendar_warning: string | null; errors: string[]; gaps: string[]; notice: string | null }

export interface StockYear { end: string; revenue: number | null; revenue_growth_pct: number | null; operating_margin_pct: number | null; net_margin_pct: number | null; net_income: number | null; free_cash_flow: number | null; net_cash: number | null; debt_to_equity: number | null }
export interface StockCase { id: string; text: string; based_on: string[]; kind: string }
export interface StockResearchData {
  symbol: string; as_of: string; demo: boolean;
  company: { name: string | null; sector: string | null; industry: string | null; sic_description: string | null; source: string };
  financials: { available: boolean; years: StockYear[]; revenue_cagr: { value_pct: number; from: string; to: string } | null; source: string; note: string };
  valuation: { rows: { key: string; label: string; value: number | null; unit: string; note: string | null }[]; source: string | null; status: string | null } | null;
  earnings: { next_date: string | null; source: string; guidance: { reason: string }; consensus: { reason: string } };
  bull: StockCase[]; bear: StockCase[]; case_note: string;
  catalysts: { date: string; title: string; source: string; link: string | null }[];
  filings: { form: string; filed: string; link: string | null; items: { item: string; meaning: string }[] }[];
  news: { title: string; link: string | null; feed: string; published: string | null }[]; errors: string[]; gaps: string[];
}
export interface EarningsData { as_of: string; window_days: number; items: { symbol: string; name: string | null; instrument_id: string; date: string; days_away: number; sector: string | null }[]; checked: number; errors: string[]; note: string }

export interface LabMetrics { net_return_pct: number | null; sharpe: number | null; max_drawdown_pct: number | null; win_rate_pct: number | null; profit_factor: number | null; trades: number; no_losing_trades?: boolean }
export interface LabResult {
  id: string; name: string; family: string;
  out_of_sample: LabMetrics; walk_forward: LabMetrics; buy_and_hold: { out_of_sample: LabMetrics };
  robustness: { share_positive: number; doubled_costs_oos_return_pct: number };
  judgement: { luck_check_note: string | null; sharpe_lower_bound: { lower: number; confidence_pct: number; n_compared: number } | null; plain: string | null };
  evidence: { level: "none" | "weak" | "moderate"; reasons: string[] };
  now: { rule_position: string; conditions: { rule: string; met: boolean | null; value: string }[]; as_of: string; note: string };
  curve: { strategy: number[]; buy_and_hold: number[] };
}
export interface LabRunData { findings: { as_of: string; points: string[] }; settings: { timeframe: string; market: string; leverage: number }; period: { from: string; to: string; bars: number }; results: LabResult[]; skipped: { id: string; reason: string }[]; notes: string[]; caveats: string[]; data: { demo: boolean; source: string; status: string; notes: string[] } }
export interface LabRunBody { strategies?: string[]; timeframe: string; market: string; leverage: number; long_short: boolean }

export interface DiscoverPick {
  symbol: string; name: string | null; sector: string | null; asset_id: string; score: number; coverage: number; of: number; rank?: number;
  factors: Record<string, { score: number } | null>;
  reasons: string[]; risks: string[]; evidence: { label: string; value: number | null; unit: string; source: string; as_of: string }[];
  pe: number | null; revenue_growth_pct: number | null;
}
export interface DiscoverData {
  asof: string; created_at: string; demo: boolean; shortlist: DiscoverPick[]; ranked: DiscoverPick[]; stale_notice?: string; notes: string[];
  universe: { name: string; size: number; priced: number; liquid: number; scored: number };
  data: { prices: string; prices_status: string; prices_as_of: string | null; fundamentals: string };
  method: { weights: Record<string, number>; scales: Record<string, string>; steps: string[]; note: string };
  gaps: string[]; disclaimer: string;
}

export interface WhatIfData {
  asset: Asset; amount: number; from: string; to: string; years: number; bars: number; bars_per_year: number; last_price: number; prov: Prov; adjustment: string;
  lump_sum: { label: string; buy_date: string; buy_price: number; invested: number; value_now: number; gain: number; return_pct: number; per_year_pct: number | null; lowest_vs_cost_pct: number; max_drawdown_pct: number; days_below_cost: number; days: number }[];
  monthly: { label: string; from: string; buys: number; invested: number; value_now: number; gain: number; return_pct: number; average_price: number; same_money_lump_sum_return_pct: number }[];
  every_start: { label: string; worst_pct: number; p10_pct: number; median_pct: number; p90_pct: number; best_pct: number; share_positive: number; share_lost_20: number; worst_buy_date: string; best_buy_date: string; note: string; n: number }[];
  exit_rules: { label: string; rules: { rule: string; label: string; result_pct: number; sold: boolean; sold_on: string | null; why: string }[] }[];
  bootstrap: { paths: number; p5_pct: number; p25_pct: number; median_pct: number; p75_pct: number; p95_pct: number; share_positive: number; share_lost_20: number; typical_worst_dip_pct: number; bad_year_dip_pct: number; note: string } | null;
  notes: string[]; caveats: string[];
}

export interface CalendarEvent {
  kind: "earnings" | "economy" | "rates" | "dividend" | "auction"; date: string; at_utc: string | null; time_label: string | null; title: string; symbol: string | null; name: string | null;
  importance: "high" | "medium" | "low"; market_cap: number | null; details: Record<string, string | number | boolean | null>; source: string; official: boolean; link: string | null; watch: boolean; instrument_id: string | null;
}
export interface CalendarData { as_of: string; from: string; to: string; demo: boolean; scope: string; items: CalendarEvent[]; counts: Record<string, number>; sources: { id: string; name: string; official: boolean; ok: boolean; error: string | null }[]; notes: string[]; importance_note: string }

export interface Sentiment {
  available: boolean; reason?: string; demo: boolean; source: string; url: string; note: string; as_of: string;
  value?: number; label?: string; date?: string; age_days?: number; freshness?: "CURRENT" | "OVERDUE";
  yesterday?: number | null; a_week_ago?: number | null; a_month_ago?: number | null; history?: { date: string; value: number }[];
}

export interface SecFiling {
  symbol: string; name: string | null; instrument_id: string; form: string; meaning: string; importance: "high" | "medium" | "low"; filed: string; report_date: string | null;
  accepted_at: string | null; items: { item: string; meaning: string }[]; link: string | null; origin: string; fetched_at: string;
}
export interface SecFilingsData { as_of: string; forms: string[]; checked: number; demo: boolean; source: string; note: string; items: SecFiling[]; errors: string[]; needs_contact?: boolean }

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
export interface ExperimentEntry { id: string; name: string; date: string; registered: string; idea: string; period: string; verdict: "failed" | "passed"; results: { k: string; v: string }[]; conditions: { rule: string; met: boolean }[]; reading: string; not_verified: string }
export interface ExperimentsData { entries: ExperimentEntry[]; tested: number; passed: number; note: string; as_of?: string }
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

// ---- fundamental research, newly listed companies and new-to-me candidates (shapes of /api/research/{symbol}, /api/discover/listings, /api/discover/candidates)
export interface Src { form: string; filed: string; link: string | null }
export interface RevRow { period_start: string; period_end: string; value: number; basis: string; yoy_pct?: number | null; yoy_note?: string | null; growth_pct?: number | null; growth_note?: string | null; source: Src }
export interface RevenueAnalysis {
  available: boolean; reason?: string; currency?: string; units?: string; annual?: RevRow[]; quarterly?: RevRow[];
  ttm?: { value: number; period_start: string; period_end: string; basis: string; quarters: string[] } | null; ttm_previous?: { value: number; period_end: string } | null;
  ttm_growth_pct?: number | null; ttm_growth_note?: string | null; cagr?: { from: string; to: string; years: number; value_pct: number; formula: string } | null;
  trend?: { label: string; latest_yoy_pct?: number; earlier_average_pct?: number; change_pp?: number; rule: string; reason?: string };
  per_share?: { period_end: string; revenue_per_diluted_share: number | null; diluted_shares: number | null }[]; share_count_change?: { from: string; to: string; change_pct: number; basis: string } | null;
  latest_period_end?: string | null; age_days?: number | null; stale?: boolean; missing?: string[]; not_in_structured_data?: string[];
}
export interface QualityRow { key: string; label: string; value: number | null; unit: string; note?: string | null }
export interface QualityData {
  available: boolean; reason?: string; basis?: string | null; rows?: QualityRow[]; ttm_period_end?: string; capitalised_software_ttm?: number | null;
  balance?: { cash: { value: number; end: string } | null; debt: { value: number; end: string } | null; equity: { value: number; end: string } | null; net_cash: number | null; note: string; as_of: string | null };
}
export interface R40Score {
  end: string; available: boolean; reason?: string; basis?: string; growth_pct?: number; margin_pct?: number; score?: number; reaches_40?: boolean; label?: string;
  ttm_revenue?: number; ttm_revenue_previous?: number; ttm_operating_cash_flow?: number; ttm_capital_expenditures?: number; ttm_free_cash_flow?: number; ttm_operating_income?: number; ttm_depreciation_amortisation?: number; ttm_ebitda?: number;
}
export interface Rule40 {
  definition: string; threshold: number; caveat: string; applicable: boolean; available?: boolean; label: string; reason?: string; sector?: string; current?: R40Score;
  history?: { end: string; score: number; growth_pct: number; margin_pct: number; reaches_40: boolean }[]; ebitda_variant?: R40Score; peers?: { available: boolean; reason: string };
  capitalised_software_ttm?: number; capitalised_software_note?: string;
}
export interface Scenario {
  name: "bear" | "base" | "bull"; fair_value_per_share: number; equity_value: number; enterprise_value: number; terminal_share_of_ev_pct: number | null; upside_pct: number;
  assumptions: { start_growth_pct: number; terminal_growth_pct: number; fcf_margin_start_pct: number; fcf_margin_end_pct: number; discount_rate_pct: number; years: number; annual_dilution_pct: number };
}
export interface Multiple { key: string; label: string; value: number | null; basis: string; note?: string | null }
export interface Valuation {
  label: string; label_key: "under" | "within" | "over" | "none"; reason?: string; caveat?: string; warnings?: string[]; price?: number | null; price_time?: string | null; price_source?: string | null;
  policy?: { discount_rate_pct: number; terminal_growth_pct: number; band_pct: number; years: number; min_evidence: string }; classification_rule?: string; sector?: string;
  evidence: { level: string; checks: { key: string; ok: boolean; essential: boolean; text: string }[]; limits: string[] };
  multiples?: Multiple[]; scenarios?: Scenario[]; fair_value_range?: { low: number; base: number; high: number };
  reverse_dcf?: { available: boolean; implied_growth_pct?: number; reported_ttm_growth_pct?: number; difference_pp?: number; reading?: string; reason?: string } | null;
  sensitivity?: { rows: string; cols: string; discount_rates: number[]; growths: number[]; values: (number | null)[][]; unit: string } | null;
  influence?: { input: string; low_value: number; high_value: number; swing: number }[]; invalidators?: string[];
  methods?: { dcf?: { available: boolean; reason?: string } | null; peers?: { available: boolean; reason: string }; own_history?: { available: boolean; reason: string } };
  inputs?: { shares_basis?: string | null; shares?: number | null; cash?: number | null; debt?: number | null; ttm_revenue?: number | null; ttm_fcf?: number | null; annual_dilution_pct?: number | null; financials_end?: string | null };
}
export interface Thesis { what_must_be_true: string[]; what_would_disprove_it: string[]; research_next: string[] }
export interface MyState {
  state: { symbol: string; first_seen_at: string | null; opened_at: string | null; saved_at: string | null; dismissed_at: string | null; researched_at: string | null; shown_count: number };
  notes: { id: number; body: string; created_at: string }[]; last_review: { reviewed_at: string; snapshot: Record<string, unknown> } | null;
}
export interface FundamentalResearch {
  available: boolean; reason?: string; demo?: boolean; symbol: string; as_of: string; errors: string[];
  company?: { name?: string | null; cik?: number | string | null; sic?: number | string | null; sector_kind?: string; special_sector_note?: string | null };
  revenue?: RevenueAnalysis; quality?: QualityData; rule_of_40?: Rule40; valuation?: Valuation; thesis?: Thesis; coverage?: { covered: string[]; not_covered: string[] };
  definitions?: Record<string, string>; sources?: { filings?: { origin: string; fetched_at: string; source: string }; submissions?: { sic_description?: string | null; exchanges?: string[] | null } | null }; my_state?: MyState;
}
export interface Brief { markdown: string; chars: number; detail: "concise" | "detailed"; symbol: string; filename: string; included: { notes: boolean; position: boolean }; redactions: number; explanation: string; default_question_used: boolean; sections: string[] }
export interface ChangeRow { key: string; label: string; unit: string; before: unknown; after: unknown }
export interface Changes { available: boolean; has_review: boolean; reason?: string; note?: string; reviewed_at?: string; changed?: ChangeRow[]; unchanged_count?: number }

export interface ListingItem {
  deal_id: string; symbol: string | null; name: string; exchange: string | null; exchange_text: string | null; stage: string; status: string; status_text: string; listing_type: string; listing_type_note: string;
  price: string | null; shares_offered: number | null; offer_amount: number | null; priced_date: string | null; expected_date: string | null; expected_first_trade?: string; first_trade_date?: string;
  verification?: { verified: boolean; note: string; evidence: { form: string; filed: string; link: string | null } | null }; newness?: { new: boolean | null; reason: string };
}
export interface ListingsFeed {
  available: boolean; reason?: string; as_of?: string; fetched_at?: string; age_hours?: number; stale?: boolean; window_days?: number; today?: { priced: number; expected_first_trade: number; text: string };
  upcoming: ListingItem[]; recent: ListingItem[]; counts?: { upcoming: number; recent: number; confirmed_trading: number; verified_by_sec: number }; source?: string; url?: string; coverage: string; errors?: string[];
}
export interface Candidate {
  symbol: string; name: string; exchange: string; sector: string | null; industry: string | null; country: string | null; market_cap: number | null; size_bucket: string | null; ipo_year: number | null;
  dollar_volume: number | null; price: number | null; price_time: string; price_source: string; score: number; factors: Record<string, number | null>; why_selected: string[]; risks: string[];
  main_opportunity: string; main_risk: string; why_shown_again: string | null; description: { classification?: number | string | null; industry: string | null; sector: string | null; note: string };
  revenue: { ttm: number | null; ttm_period_end: string | null; growth_pct: number | null; trend: string | null; fcf_margin_pct: number | null; age_days: number | null; latest_period_end: string | null };
  rule_of_40: { applicable: boolean; label: string; score: number | null }; valuation: { label: string; label_key: string; evidence: string | null; base_fair_value: number | null };
  state: { seen: boolean; opened: boolean; saved: boolean; shown_count: number };
}
export interface CandidatesFeed {
  available: boolean; reason?: string; asof?: string; age_days?: number; stale?: boolean; target?: number; shown?: number; items: Candidate[]; pool_size?: number; evidence_note?: string; gaps: string[];
  excluded_by_my_filters?: Record<string, number>; hidden_because_seen?: { symbol: string; reason: string }[]; kept_varied?: { symbol: string; reason: string }[];
  study?: { universe: number; after_filters: number; studied: number; passed: number; left_out_reasons: Record<string, number>; could_not_study: Record<string, number> };
  method?: { weights: Record<string, number>; min_total: number; min_factors: number; max_per_sector: number; cooldown_days: number }; source?: { universe: string; filings: string };
}

export interface FuturesGroup { key: string; name: string; who: string; long: number; short: number; spread: number; net: number; net_change: number | null; long_pct_oi: number; short_pct_oi: number; net_rank_1y: number | null; net_history: number[] }
export interface FuturesContract { code: string; name: string; what: string; available: boolean; reason?: string; date?: string; age_days?: number; freshness?: "CURRENT" | "OVERDUE"; open_interest?: number; open_interest_change?: number | null; traders?: number | null; weeks_of_history?: number;
  groups?: FuturesGroup[]; checks?: { weeks_checked: number; groups_add_up: boolean; oi_change_pairs: number; oi_change_mismatches: number; ok: boolean } }
export interface FuturesPositioningData { available: boolean; reason?: string; demo: boolean; as_of: string; url?: string; source?: string; note?: string; date?: string; age_days?: number; freshness?: "CURRENT" | "OVERDUE"; contracts?: FuturesContract[] }

export interface FinConditionsData { available: boolean; reason?: string; demo: boolean; as_of: string; url?: string; source?: string; note?: string; date?: string; age_days?: number; freshness?: "CURRENT" | "OVERDUE";
  nfci?: number; adjusted?: number; reading?: string; pieces?: { risk: number; credit: number; leverage: number }; change_1w?: number | null; change_4w?: number | null; change_1y?: number | null;
  year_low?: number; year_high?: number; weeks_in_year?: number; history?: { date: string; nfci: number }[] }
export interface JoblessClaimsData { available: boolean; reason?: string; demo: boolean; as_of: string; url?: string; source?: string; note?: string; date?: string; age_days?: number; freshness?: "CURRENT" | "OVERDUE"; reading?: string;
  initial?: { value: number; avg4: number; avg4_official: number; change_1w: number | null; change_1y_pct: number | null; year_low: number; year_high: number; weeks_in_year: number; rank_in_year: number };
  continuing?: { value: number; date: string; change_1w: number | null; change_1y_pct: number | null }; history?: { date: string; initial: number }[] }
export interface OilSeries { value: number; date: string; age_days: number; freshness: "CURRENT" | "OVERDUE"; change_1d: number | null; change_1m_pct: number | null; change_1y_pct: number | null; year_low: number; year_high: number; days_in_year: number; rank_in_year: number; reading: string }
export interface OilPricesData { available: boolean; reason?: string; demo: boolean; as_of: string; url?: string; source?: string; note?: string; wti?: OilSeries; brent?: OilSeries; spread?: { value: number; date: string }; history?: { date: string; wti: number }[] }
export interface RealYieldRow { tenor: string; nominal_pct: number | null; real_pct: number | null; breakeven_pct: number; breakeven_change_1m_bp: number | null; breakeven_change_1y_bp: number | null; real_change_1y_bp: number | null }
export interface RealYieldsData { available: boolean; reason?: string; demo: boolean; as_of: string; url?: string; source?: string; note?: string; date?: string; age_days?: number; freshness?: "CURRENT" | "OVERDUE";
  month_ago_date?: string | null; year_ago_date?: string | null; rows?: RealYieldRow[]; history?: { date: string; breakeven_10y_pct: number }[];
  checks?: { same_day: boolean; range_ok: boolean; latest_dates_differ: boolean; maturities_left_out: string[] } }

export interface CustomsData { available: boolean; reason?: string; demo: boolean; as_of: string; url?: string; source?: string; note?: string; date?: string; age_days?: number; freshness?: "CURRENT" | "OVERDUE"; fiscal_year?: number;
  latest?: { gross_billions: number; refunds_billions: number; net_billions: number; refunds_share_of_gross_pct: number | null };
  year_so_far?: { gross_billions: number; refunds_billions: number; net_billions: number; same_point_last_year_net_billions: number; change_vs_last_year_pct: number | null; months: number };
  months?: { date: string; gross_billions: number; refunds_billions: number; net_billions: number }[];
  checks?: { months_checked: number; identity_failures: number; fytd_sum_checks: number; fytd_sum_mismatches: number; ok: boolean } }

export interface ReceiptCategory { name: string; what: string; month_billions: number; year_so_far_billions: number; share_of_year_pct: number | null; same_point_last_year_billions: number; change_vs_last_year_pct: number | null }
export interface ReceiptsData { available: boolean; reason?: string; demo: boolean; as_of: string; url?: string; source?: string; note?: string; date?: string; age_days?: number; freshness?: "CURRENT" | "OVERDUE"; fiscal_year?: number; months_in_year?: number;
  total?: { month_billions: number; year_so_far_billions: number; same_point_last_year_billions: number; change_vs_last_year_pct: number | null }; categories?: ReceiptCategory[];
  checks?: { categories_add_up_to_total: boolean; on_plus_off_budget_equals_total: boolean; problems: string[]; ok: boolean } }

export interface OutlayFunction { name: string; what: string; month_billions: number; year_so_far_billions: number; share_of_outlays_pct: number | null; same_point_last_year_billions: number; change_vs_last_year_pct: number | null }
export interface OutlayTotals { month_billions: number; year_so_far_billions: number; same_point_last_year_billions: number; change_vs_last_year_pct: number | null }
export interface OutlaysData { available: boolean; reason?: string; demo: boolean; as_of: string; url?: string; source?: string; note?: string; date?: string; age_days?: number; freshness?: "CURRENT" | "OVERDUE"; fiscal_year?: number; months_in_year?: number;
  outlays?: OutlayTotals; receipts?: OutlayTotals; deficit?: OutlayTotals; functions?: OutlayFunction[];
  checks?: { purposes_add_up_to_total_outlays: boolean; receipts_lines_add_up_to_total: boolean; problems: string[]; ok: boolean } }
