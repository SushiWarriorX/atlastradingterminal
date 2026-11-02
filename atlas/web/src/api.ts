import type { CheckState_ } from "./health";
import type { FedWatch, MacroOverview } from "./macro";
export type Status = "LIVE" | "DELAYED" | "HISTORICAL" | "STALE" | "DEMO" | "UNAVAILABLE";

export interface Prov {
  provider: string; instrument_id: string; venue: string | null; event_time: string | null; ingested_time: string;
  currency: string; session: string | null; entitlement: string; delay_seconds: number | null; status: Status; quality: string[];
}
export interface Quote {
  instrument_id: string; price: number; bid: number | null; ask: number | null; open: number | null; high: number | null;
  low: number | null; prev_close: number | null; prev_close_basis: string; volume: number | null; vwap: number | null;
  market_cap: number | null; change: number | null; change_pct: number | null; spread: number | null;
  unsupported_fields: string[]; prov: Prov;
}
export interface QuoteErr { instrument_id: string; error: string; status: "UNAVAILABLE" }
export type QuoteOrErr = Quote | QuoteErr;
export const isErr = (q: QuoteOrErr): q is QuoteErr => "error" in q;

export interface Candle { time: number; open: number; high: number; low: number; close: number; volume: number }
export interface OHLCV {
  instrument_id: string; interval: string; candles: Candle[]; adjustment: string; line_only: boolean;
  derived_from: string | null; prov: Prov;
}
export interface Instrument {
  id: string; symbol: string; name: string; asset_class: string; exchange: string; provider: string; note: string | null;
  supported_intervals?: string[];
}
export interface Watchlist { id: number; name: string; items: string[] }
export interface Prefs { theme: "dark" | "light"; update_seconds: number; selected_instrument: string; workspace: string; telegram_enabled: boolean; telegram_min_severity: "info" | "warning" | "critical" }
export interface StripItem { instrument_id: string; symbol: string; name: string; quote?: Quote; error?: string; status?: Status }
export interface MarketStatus {
  server_time_utc: string; broker_env: string; live_trading_enabled: boolean; demo_mode: boolean;
  ny: { state: string; early_close: boolean; ny_time: string; next_open: string; holiday_reason: string | null };
  providers: Record<string, { entitlement: string; delay_seconds: number | null; ok: number; fail: number; last_ok: string | null; last_error: string | null; consecutive_failures: number }>;
  ai: { configured: boolean; model: string | null }; update_seconds: number; trading_halted?: boolean;
}
export interface CommandResult {
  ok: boolean; view: string | null; instrument_ids: string[]; params: Record<string, unknown>; implemented: boolean;
  phase: number | null; message: string | null; error: string | null; suggestions: string[];
}
export interface ViewMeta { implemented: boolean; phase: number | null; description: string }

export class ApiFailure extends Error {
  constructor(public code: string, message: string, public httpStatus: number, public extra: Record<string, unknown> = {}) { super(message); }
}

/** One line for a failed call: "CODE: message" for API errors, the plain text otherwise. */
export const errText = (e: unknown): string => (e instanceof ApiFailure ? `${e.code}: ${e.message}` : String(e));

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  let r: Response;
  try {
    r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...init });
  } catch {
    throw new ApiFailure("BACKEND_UNREACHABLE", "Backend not reachable. Is the API running on :8000?", 0);
  }
  const j = await r.json().catch(() => null);
  if (j?.error?.code === "AUTH_REQUIRED") window.dispatchEvent(new Event("atlas-auth-required"));      // the session ended: show the login screen
  if (!j || j.ok !== true) throw new ApiFailure(j?.error?.code ?? "ERROR", j?.error?.message ?? `HTTP ${r.status}`, r.status, j?.error ?? {});
  return j.data as T;
}
const body = (m: string, b: unknown): RequestInit => ({ method: m, body: JSON.stringify(b) });

export const api = {
  status: () => call<MarketStatus>("/api/market/status"),
  authStatus: () => call<{ required: boolean; authenticated: boolean }>("/api/auth/status"),
  login: (password: string) => call<{ required: boolean; authenticated: boolean }>("/api/auth/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ password }) }),
  logout: () => call<{ required: boolean; authenticated: boolean }>("/api/auth/logout", { method: "POST" }),
  macroFed: () => call<FedWatch>("/api/macro/fed"),
  macroOverview: () => call<MacroOverview>("/api/macro/overview"),
  healthCheckLast: () => call<CheckState_>("/api/health/check"),
  healthCheckRun: () => call<CheckState_>("/api/health/check", { method: "POST", headers: { "Content-Type": "application/json", "X-Atlas-Request": "health-check" } }),
  views: () => call<Record<string, ViewMeta>>("/api/meta/views"),
  strip: () => call<StripItem[]>("/api/market/strip"),
  quotes: (ids: string[]) => call<QuoteOrErr[]>(`/api/quotes?ids=${encodeURIComponent(ids.join(","))}`),
  instrument: (id: string) => call<Instrument>(`/api/instruments/${id}`),
  search: (q: string) => call<Instrument[]>(`/api/instruments/search?q=${encodeURIComponent(q)}`),
  ohlcv: (id: string, interval: string, limit = 300) => call<OHLCV>(`/api/ohlcv/${id}?interval=${interval}&limit=${limit}`),
  indicators: (id: string, interval: string, specs: string[]) =>
    call<{ times: number[]; series: Record<string, (number | null)[]> }>(
      `/api/technical/indicators?instrument_id=${encodeURIComponent(id)}&interval=${interval}&ind_specs=${encodeURIComponent(specs.join(","))}`),
  levels: (id: string, interval: string) =>
    call<{ levels: { id: string; kind: string; price: number; derivation: string }[]; trend: { label: string; factors: Record<string, unknown> }; prov: Prov }>(
      `/api/technical/levels?instrument_id=${encodeURIComponent(id)}&interval=${interval}`),
  command: (text: string) => call<CommandResult>("/api/command", body("POST", { text })),
  suggest: (q: string) => call<{ suggestions: { text: string; kind: string; name?: string; id?: string }[]; recent: string[] }>(`/api/command/suggest?q=${encodeURIComponent(q)}`),
  watchlists: () => call<Watchlist[]>("/api/watchlists"),
  wlCreate: (name: string) => call<Watchlist>("/api/watchlists", body("POST", { name })),
  wlDelete: (id: number) => call<unknown>(`/api/watchlists/${id}`, { method: "DELETE" }),
  wlAdd: (id: number, instrument_id: string) => call<Watchlist>(`/api/watchlists/${id}/items`, body("POST", { instrument_id })),
  wlRemove: (id: number, instrument_id: string) => call<Watchlist>(`/api/watchlists/${id}/items/${instrument_id}`, { method: "DELETE" }),
  prefs: () => call<Prefs>("/api/prefs"),
  setPrefs: (p: Partial<Prefs>) => call<Prefs>("/api/prefs", body("PUT", p)),
  layout: (ws: string) => call<unknown>(`/api/layouts/${ws}`),
  saveLayout: (ws: string, layout: unknown) => call<unknown>(`/api/layouts/${ws}`, body("PUT", layout)),
  resetLayout: (ws: string) => call<unknown>(`/api/layouts/${ws}`, { method: "DELETE" }),
  aiStatus: () => call<{ configured: boolean; model: string | null; tools: string[] }>("/api/ai/status"),
  aiChat: (message: string, instrument_id?: string) =>
    call<{ analysis_id: string; answer: string; status: string; tool_calls: { name: string; ok: boolean; source_id?: string }[]; usage: { input_tokens: number; output_tokens: number }; model: string }>(
      "/api/ai/chat", body("POST", { message, instrument_id })),
  aiAnalyze: <T,>(agent: string, instrument_id: string) => call<T>("/api/ai/analyze", body("POST", { instrument_id, agent })),
  aiTechnical: (instrument_id: string) =>
    call<{ analysis_id: string; status: string; report: TechReport | null; error: string | null; snapshot_id: string; model: string }>(
      "/api/ai/analyze", body("POST", { instrument_id, agent: "technical" })),
  scanPresets: () => call<{ presets: ScanPreset[]; unavailable: Record<string, string>; universes: Record<string, string>; demo: boolean; data_source: string }>("/api/scanner/presets"),
  scanFields: () => call<Record<string, { type: "number" | "bool" | "string"; label: string; unit: string }>>("/api/scanner/fields"),
  scanNL: (text: string) => call<NLResult>("/api/scanner/nl", body("POST", { text })),
  scanRun: (x: { preset?: string; spec?: ScanSpec }) => call<{ job_id: string }>("/api/scanner/run", body("POST", x)),
  scanJob: (id: string) => call<ScanJob>(`/api/scanner/jobs/${id}`),
  derivatives: (fresh = false) => call<DerivSnapshot>(`/api/derivatives/btc${fresh ? "?fresh=true" : ""}`),
  derivativesHistory: (hours = 72) => call<DerivHistory>(`/api/derivatives/btc/history?hours=${hours}`),
  news: (x: { symbol?: string; q?: string }) => call<NewsResult>(`/api/news?${new URLSearchParams(Object.entries(x).filter(([, v]) => v) as [string, string][])}`),
  newsRefresh: () => call<{ results: { id: number; name: string; ok: boolean; new: number; seen: number; error: string | null }[] }>("/api/news/refresh", body("POST", {})),
  newsFeeds: () => call<{ feeds: NewsFeed[]; note: string }>("/api/news/feeds"),
  newsFeedAdd: (name: string, url: string) => call<NewsFeed>("/api/news/feeds", body("POST", { name, url })),
  newsFeedToggle: (id: number, enabled: boolean) => call<unknown>(`/api/news/feeds/${id}`, body("PATCH", { enabled })),
  newsFeedDelete: (id: number) => call<unknown>(`/api/news/feeds/${id}`, { method: "DELETE" }),
  btPresets: () => call<{ presets: BtPreset[]; universes: Record<string, string>; demo: boolean; caveats: string[] }>("/api/backtest/presets"),
  btRun: (x: { preset?: string; overrides?: Partial<BtSpec>; spec?: BtSpec }) => call<{ job_id: string }>("/api/backtest/run", body("POST", x)),
  btJob: (id: string) => call<BtJob>(`/api/backtest/jobs/${id}`),
  btRuns: () => call<{ id: number; name: string; trades: number; ran_at: string }[]>("/api/backtest/runs"),
  btGet: (id: number) => call<{ id: number; result: BtResult }>(`/api/backtest/runs/${id}`),
  btDelete: (id: number) => call<unknown>(`/api/backtest/runs/${id}`, { method: "DELETE" }),
  scanSave: (name: string, spec: ScanSpec) => call<unknown>("/api/scanner/save", body("POST", { name, spec })),
  scanSaved: () => call<{ id: number; name: string; spec: ScanSpec }[]>("/api/scanner/saved"),
  journalSources: () => call<{ sources: JournalSource[]; batches: ImportBatch[] }>("/api/journal/sources"),
  journalPresets: () => call<{ presets: Record<string, { label: string; verified: boolean; note: string }>; roles: { trades: string[]; flows: string[] } }>("/api/journal/presets"),
  journalPreview: (b: ImportBody) => call<ImportPreview>("/api/journal/import/preview", body("POST", b)),
  journalImport: (b: ImportBody) => call<{ batch_id: number; inserted: number; duplicates: number; skipped: Record<string, number>; errors: number; warnings: string[] }>("/api/journal/import", body("POST", { ...b, confirm: true })),
  journalManual: (b: Record<string, string>) => call<{ inserted: number }>("/api/journal/executions", body("POST", b)),
  journalDelete: (source: string) => call<{ executions_deleted: number }>(`/api/journal/source?source=${encodeURIComponent(source)}&confirm=true`, { method: "DELETE" }),
  journalHyperliquid: (address: string) => call<HyperliquidSync>("/api/journal/hyperliquid/sync", body("POST", { address })),
  journalSync: () => call<Record<string, unknown>>("/api/journal/sync", { method: "POST" }),
  journalTrades: (q: { source?: string; status?: string; symbol?: string }) => call<{ trades: JTrade[]; total: number }>(`/api/journal/trades?${new URLSearchParams(Object.entries(q).filter(([, v]) => v) as [string, string][])}`),
  journalTrade: (key: string) => call<{ trade: JTrade; note: JNote | null; executions: JExec[] }>(`/api/journal/trade?key=${encodeURIComponent(key)}`),
  journalNote: (key: string, n: Partial<JNote>) => call<JNote>(`/api/journal/notes?key=${encodeURIComponent(key)}`, body("PUT", n)),
  journalStats: (q: { source?: string; symbol?: string; since?: string; until?: string }) => call<JStats>(`/api/journal/stats?${new URLSearchParams(Object.entries(q).filter(([, v]) => v) as [string, string][])}`),
  ibkrStatus: () => call<IbkrStatus>("/api/ibkr/status"),
  ibkrConnect: () => call<IbkrStatus>("/api/ibkr/connect", { method: "POST" }),
  ibkrDisconnect: () => call<IbkrStatus>("/api/ibkr/disconnect", { method: "POST" }),
  ibkrSync: () => call<{ journal: { executions_seen: number; inserted: number; duplicates: number; note: string } }>("/api/ibkr/sync", { method: "POST" }),
  compare: (ids: string[], interval: string, limit = 300) => call<CompareResult>(`/api/compare?ids=${encodeURIComponent(ids.join(","))}&interval=${interval}&limit=${limit}`),
  mtf: (id: string, benchmark?: string) => call<MtfResult>(`/api/technical/mtf?instrument_id=${encodeURIComponent(id)}${benchmark ? `&benchmark=${benchmark}` : ""}`),
  telegramStatus: () => call<TelegramStatus>("/api/telegram/status"),
  telegramTest: () => call<{ sent: boolean }>("/api/telegram/test", { method: "POST" }),
  scanDelete: (id: number) => call<unknown>(`/api/scanner/saved/${id}`, { method: "DELETE" }),
};

export interface FactCite { fact: string; value: number; comment: string }
export interface SpecialistRep {
  agent: string; assessment: string; summary: string; pillars: { name: string; rating: string; evidence: FactCite[] }[]; supporting: FactCite[]; contradictory: FactCite[];
  data_limitations: string[]; consistency_notes: string[]; computed?: { limit_breaches?: string[]; computed_tilt?: { label: string; score: number; note: string; signals: { name: string; text: string }[] } };
}
export interface SpecialistResult { analysis_id?: string; status: string; report?: (SpecialistRep & Partial<TechReport>) | null; error?: string | null; data_limitations?: string[] }
export interface ChiefRep {
  stance: "constructive" | "cautious" | "neutral" | "insufficient_data"; agreements: string[]; conflicts_addressed: string[]; what_would_change_my_mind: string[];
  data_limitations: string[]; cites: string[]; summary: string; consistency_notes: string[];
}
export interface DeskResult {
  analysis_id: string; status: "completed" | "partial" | "no_data" | "failed_validation"; chief: ChiefRep | null; error: string | null; instrument_id: string;
  specialists: Record<string, SpecialistResult>; views: Record<string, string>; conflicts: { between: string[]; text: string }[]; usage: { input_tokens: number; output_tokens: number }; model: string;
}
export interface TechReport {
  directional_assessment: string; time_horizon: string; summary: string; observations: string[];
  key_levels: { role: string; level_id: string; price: number; kind: string; derivation: string }[];
  scenarios: { name: string; conditions: string; invalidation: string }[]; data_limitations: string[]; analysis_timestamp: string;
  mtf?: { source_id: string; verdict: string; text: string; score: number | null; label: string | null; benchmark: string | null };
  consistency_notes?: string[];
}

// --- scanner -----------------------------------------------------------------
export interface ScanFilter { field: string; op: string; value: number | boolean | string | number[] | string[] }
export interface ScanSpec {
  name: string; universe: string; benchmark: string; filters: ScanFilter[]; score_weights: Record<string, number>;
  sort_by: string; sort_desc: boolean; limit: number;
}
export interface ScanRow {
  symbol: string; instrument_id: string; price: number | null; change_pct: number | null; rvol: number | null; atr_pct: number | null;
  rsi14: number | null; trend: string | null; rs_21d: number | null; setup: string | null; score: number | null; sector: string | null;
  last_bar_date: string | null; score_breakdown: { field: string; weight: number; value: number | null; percentile: number | null; contribution: number }[];
  [k: string]: unknown;
}
export interface ScanMeta {
  universe: string; universe_size: number; with_data: number; failed: number; failed_sample: Record<string, string>; insufficient_history: number;
  matched: number; coverage_pct: number; provider: string; status: Status; data_as_of: string | null; latest_bar_date: string | null;
  ran_at: string; duration_ms: number; notes: string[]; spec: ScanSpec;
}
export interface ScanJob { id: string; status: "running" | "done" | "failed"; done: number; total: number; error: string | null; result: { results: ScanRow[]; meta: ScanMeta } | null }
export interface ScanPreset { id: string; name: string; description: string; spec: ScanSpec }
export interface NLResult { ok: boolean; error?: string; spec: ScanSpec | null; matched: string[]; unsupported: string[]; rules?: string[]; note?: string }


// --- BTC derivatives ---------------------------------------------------------------
export interface DerivVenue {
  venue: string; label: string; ok: boolean; status: Status | "UNAVAILABLE"; mark?: number; index?: number | null; basis_pct?: number | null; funding_rate?: number; funding_interval_h?: number;
  funding_8h_pct?: number; funding_annual_pct?: number; oi_btc?: number; oi_usd?: number; age_seconds?: number | null; notes?: string[]; error?: { code: string; message: string };
}
export interface Pctile { available: boolean; pctile?: number; points?: number; have?: number; need?: number }
export interface DerivSnapshot {
  venues: DerivVenue[]; as_of: string; demo: boolean; history_points: number; notes: string[];
  aggregate: {
    available: boolean; venues_ok: number; venues_expected: number; venues_failed: string[]; flags: string[]; oi_btc?: number; oi_usd?: number; funding_annual_pct?: number;
    funding_spread_annual_pct?: number; mark_dispersion_pct?: number; funding_percentile_30d?: Pctile; oi_percentile_30d?: Pctile;
    oi_change_24h_pct?: { available: boolean; value?: number; reason?: string };
  };
}
export interface DerivHistory { funding_annual_pct: { ts: string; v: number }[]; oi_usd: { ts: string; v: number }[]; hours: number }

// --- news ---------------------------------------------------------------------
export interface NewsItem {
  id: number; title: string; link: string | null; summary: string; feed: string; published: string | null; fetched_at: string; symbols: string[]; status: Status;
  also: { feed: string; title: string; link: string | null; published: string | null }[];
}
export interface NewsResult {
  items: NewsItem[]; total_stories: number; raw_items: number;
  meta: { feeds_enabled: number; feeds_ok: number; feeds_failing: { name: string; error: string }[]; never_fetched: number; as_of: string | null; note: string;
    symbol_fetch: { ok: boolean; new: number; error: string | null } | null };
}
export interface NewsFeed { id: number; name: string; url: string; enabled: boolean; builtin: boolean; items: number; last_fetch: string | null; last_ok: string | null; last_error: string | null; last_count: number | null }

// --- backtester --------------------------------------------------------------
export interface BtSpec {
  name: string; universe: string; benchmark: string; side: "long" | "short"; entry: ScanFilter[]; exit_filters: ScanFilter[];
  stop_atr: number | null; target_r: number | null; max_hold_bars: number; commission_bps: number; slippage_bps: number; initial_capital: number;
  risk_pct: number; max_position_pct: number; max_positions: number; oos_fraction: number; start: string | null; end: string | null; max_symbols: number;
}
export interface BtStats {
  n: number; reliable: boolean; min_sample: number; note?: string | null; win_rate?: number; win_rate_ci95?: [number, number] | null;
  expectancy?: number; expectancy_ci95?: [number, number] | null; expectancy_note?: string | null; profit_factor?: number | null; avg_win?: number | null;
  avg_loss?: number | null; best?: number; worst?: number; net_pnl?: number; avg_hold_bars?: number | null; r?: { n: number; avg_r: number | null; total_r: number | null };
  max_loss_streak?: number; unit?: string;
}
export interface BtMetrics { total_return_pct: number; cagr_pct: number | null; max_drawdown_pct: number; vol_ann_pct: number | null; sharpe: number | null; calmar: number | null; days: number }
export interface BtGroupRow { key: string; n: number; reliable: boolean; win_rate: number | null; net_pnl: number | null; expectancy: number | null; profit_factor: number | null; avg_r: number | null }
export interface BtTrade {
  symbol: string; instrument_id: string; side: string; signal_date: string; entry_date: string; entry_px: number; stop: number | null; target: number | null; exit_date: string;
  exit_px: number; exit_reason: string; bars_held: number; net_pct: number; r_multiple: number | null; setup: string | null;
}
export interface BtResult {
  summary: BtStats; in_sample: BtStats; out_of_sample: BtStats; split: { oos_fraction: number; cutoff_date: string | null; note: string };
  groups: Record<string, BtGroupRow[]>;
  portfolio: { curve: { t: number; equity: number }[]; metrics: BtMetrics; skipped: Record<string, number>; exposure_avg_pct: number | null; final_equity?: number; open_at_end?: number; note?: string };
  benchmark: (BtMetrics & { symbol: string; curve: { t: number; equity: number }[] }) | null;
  trades: BtTrade[]; open_at_end: { symbol: string; entry_date: string; entry_px: number; last_close: number; unrealized_pct: number; bars_held: number }[];
  pending_signals: { symbol: string; date: string; close: number; setup: string | null }[]; symbols_traded: number; symbols_tested: number; compute_mode: string;
  meta: {
    spec: BtSpec; universe: string; universe_size: number; with_data: number; failed: number; failed_sample: Record<string, string>; provider: string; status: Status;
    data_as_of: string | null; bars_from: string | null; bars_to: string | null; ran_at: string; duration_ms: number; notes: string[]; caveats: string[];
  };
}
export interface BtJob { id: string; status: "running" | "done" | "failed"; done: number; total: number; error: string | null; result: BtResult | null; run_id?: number }
export interface BtPreset { id: string; name: string; description: string; spec: BtSpec }

// --- alerts ------------------------------------------------------------------

export interface TelegramStatus {
  configured: boolean; setup?: string; enabled?: boolean; min_severity?: "info" | "warning" | "critical";
  verified?: boolean; bot_username?: string | null; chat_hint?: string;
}

// --- compare + multi-timeframe ---------------------------------------------------
export interface PairStats {
  observations: number; full_sample_corr: number | null; total_return_pct: { base: number; other: number };
  windows: Record<string, { available: boolean; observations?: number; corr?: number | null; beta_of_other_on_base?: number | null }>;
  rolling_60?: { latest: number; min: number; max: number; samples: number; note: string };
}
export interface CompareResult {
  interval: string; base: string; aligned_bars: number; times: number[]; range: [number, number]; notes: string[];
  series: Record<string, { symbol: string; name: string; closes: number[]; rebased: number[]; bars_before_alignment: number; prov: Prov }>;
  stats: Record<string, PairStats>;
}
export interface MtfTf {
  interval: string; available: boolean; reason?: string; bars?: number; last_close?: number; trend?: string; rsi14?: number | null; macd_hist?: number | null;
  atr_pct?: number | null; rvol?: number | null; change_pct?: number; nearest_support?: number | null; nearest_resistance?: number | null;
  structure?: { label: string; event: string | null; derivation?: string }; data?: { status: Status; provider: string; derived_from: string | null };
}
export interface MtfFactor { value: number | null; weight: number; effective_weight: number; contribution: number; available: boolean; inputs: Record<string, number | string | null>; note?: string; context_only?: boolean }
export interface MtfResult {
  instrument_id: string; symbol: string; benchmark: string | null; swing_k: number; as_of: string; timeframes: MtfTf[];
  alignment: { verdict: string; text: string; bullish: string[]; bearish: string[]; available: number; of?: number; note?: string };
  score: { score: number | null; tilt: number | null; label: string | null; factors: Record<string, MtfFactor>; unavailable: string[]; disclaimer: string; rules: Record<string, string> };
  rules: Record<string, string>;
}


// --- journal / performance / IBKR ---------------------------------------------------------------
export interface HyperliquidSync {
  source: string; fills_seen: number; executions: { inserted: number; duplicates: number }; funding: { seen: number; inserted: number; duplicates: number };
  skipped: Record<string, number>; warnings: string[]; reported: { closed_pnl: string; note: string }; history_limit_note: string | null;
}
export interface JournalSource { source: string; executions: number; cashflows: number; first: string | null; last: string | null; symbols: number }
export interface ImportBatch { id: number; source: string; kind: string; filename: string | null; rows_total: number; inserted: number; duplicates: number; skipped: number; created_at: string }
export interface ImportBody { source: string; kind: "trades" | "flows"; text: string; preset?: string; mapping?: Record<string, string | null>; options?: Record<string, unknown>; filename?: string }
export interface ImportPreview {
  headers: string[]; mapping: Record<string, string | null>; options: Record<string, unknown>; rows_total: number; parsed: number; already_imported: number; will_insert: number;
  errors: { line: number; error: string }[]; errors_total: number; skipped: Record<string, number>; kinds: Record<string, number>; warnings: string[];
  sample: Record<string, string>[]; time_range: [string, string] | null; preset: { label: string; verified: boolean; note: string } | null;
}
export interface JTrade {
  key: string; source: string; symbol: string; asset_class: string; side: "long" | "short"; status: "open" | "closed"; currency: string; opened_at: string; closed_at: string | null;
  qty_max: string; qty_open: string; entry_avg: string | null; exit_avg: string | null; gross_pnl: string; fees: string; funding: string; net_pnl: string; net_pnl_num: number;
  return_pct: number | null; holding_seconds: number | null; liquidated: boolean; n_execs: number; planned_stop: string | null; r_multiple: number | null; setup: string | null;
  tags: string[]; has_notes: boolean; has_screenshot: boolean;
}
export interface JExec { ext_id: string; ts: string; side: string; qty: string; price: string; fee: string; kind: string }
export interface JNote { setup: string | null; thesis: string | null; catalyst: string | null; timeframe: string | null; planned_stop: string | null; targets: string[]; notes: string | null; mistakes: string[]; lessons: string | null; tags: string[]; screenshot: string | null }
export interface JSummary {
  n: number; reliable: boolean; min_sample: number; note?: string | null; wins?: number; losses?: number; breakeven?: number; win_rate?: number; win_rate_ci95?: [number, number] | null;
  avg_win?: number | null; avg_loss?: number | null; payoff_ratio?: number | null; gross_profit?: number; gross_loss?: number; net_pnl?: number; profit_factor?: number | null; profit_factor_note?: string | null;
  expectancy?: number; expectancy_ci95?: [number, number] | null; expectancy_note?: string | null; best?: number; worst?: number; max_drawdown?: number; fees?: number; funding?: number;
  max_win_streak?: number; max_loss_streak?: number; avg_hold_seconds?: number | null; median_hold_seconds?: number | null; r?: { n: number; avg_r: number | null; total_r: number | null; note: string | null };
}
export interface JGroupRow { key: string; n: number; reliable: boolean; win_rate: number | null; win_rate_ci95: [number, number] | null; net_pnl: number | null; expectancy: number | null; profit_factor: number | null; avg_r: number | null }
export interface JStats { currency: string | null; excluded: Record<string, number>; summary: JSummary; equity_curve: { ts: string; pnl: number; cum: number }[]; groups: Record<string, JGroupRow[]>; caveats: string[] }
export interface IbkrStatus {
  configured: boolean; help?: string; mode?: "readonly" | "paper_trading"; connected?: boolean; host?: string; port?: number; accounts?: string[]; account?: string | null;
  account_is_paper?: boolean; can_trade?: boolean; last_error?: string | null; note?: string;
  market_data?: { enabled: boolean; active: boolean; note: string };
}
