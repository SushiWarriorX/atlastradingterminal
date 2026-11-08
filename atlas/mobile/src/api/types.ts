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
export interface TrackerData { as_of: string; demo: boolean; entries: TrackerEntry[]; library_size: number; min_forward_days: number; notes: string[]; data: { demo: boolean; source: string; last_bar: string | null } }

export interface WorldRow { country: string; iso: string; available: boolean; year?: number; value?: number; previous_year?: number | null; previous_value?: number | null; change?: number | null; years_old?: number; history?: { year: number; value: number }[] }
export interface WorldIndicator { key: string; title: string; unit: string; what: string; available: boolean; reason?: string; rows: WorldRow[] }
export interface WorldData { available: boolean; reason?: string; demo: boolean; as_of: string; source: string; url: string; note: string; indicators: WorldIndicator[] }
