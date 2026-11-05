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
