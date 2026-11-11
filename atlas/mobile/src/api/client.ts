import type { Brief, CandidatesFeed, Changes, FundamentalResearch, ListingsFeed, MyState, CalendarData, DiscoverData, LabRunBody, LabRunData, EarningsData, StockResearchData, WhatIfData, Positioning, Stablecoins, OnChain, FxData, TrackerData, WorldData, CryptoMarket, OpsOverview, FedOpsData, TgaData, AuctionsData, BudgetData, InterestData, BuybacksData, BillAuctionsData, BorrowingData, DealersData, FuturesPositioningData, RealYieldsData, CustomsData, ReceiptsData, DebtRatesData, DebtMixData, FedHoldingsData, FedRatesData, TreasuryData, NarrativeData, SecFilingsData, Sentiment, JournalEntry, JournalFilters, JournalLog, MacroBriefData, AgentName, AssetHeader, AuthStatus, ChartRange, ChartResponse, LoginResult, Meta, ResearchResponse, SearchResponse, WatchlistResponse } from "./types";

/** A failure with a code the UI can act on. `network` means we never got an answer. */
export class ApiError extends Error {
  constructor(public code: string, message: string, public status = 0) {
    super(message);
    this.name = "ApiError";
  }
  get isNetwork() { return this.code === "NETWORK"; }
  get isAuth() { return this.code === "AUTH_REQUIRED"; }
}

export interface ClientOptions {
  baseUrl: string;
  token?: string | null;
  fetchImpl?: typeof fetch;
  timeoutMs?: number;
  onAuthRequired?: () => void;
}

/** Trim and validate a server address. Returns null if it is not an http(s) URL. */
export function normalizeBaseUrl(raw: string): string | null {
  let s = raw.trim();
  if (!s || /^https?:\/*$/i.test(s)) return null;
  s = s.replace(/\/+$/, "");
  if (/^[a-z][a-z0-9+.-]*:\/\//i.test(s) && !/^https?:\/\//i.test(s)) return null;          // ftp://, file://, ... are not Signal servers
  if (!/^https?:\/\//i.test(s)) s = `http://${s}`;
  try {
    const u = new URL(s);
    return u.protocol === "http:" || u.protocol === "https:" ? `${u.origin}${u.pathname === "/" ? "" : u.pathname.replace(/\/+$/, "")}` : null;
  } catch {
    return null;
  }
}

export function createApi(opts: ClientOptions) {
  const f = opts.fetchImpl ?? fetch;
  const base = opts.baseUrl.replace(/\/+$/, "");

  async function call<T>(path: string, init: { method?: string; body?: unknown; timeoutMs?: number } = {}): Promise<T> {
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), init.timeoutMs ?? opts.timeoutMs ?? 20_000);
    let res: Response;
    try {
      res = await f(`${base}${path}`, {
        method: init.method ?? "GET",
        headers: { Accept: "application/json", ...(init.body !== undefined ? { "Content-Type": "application/json" } : {}), ...(opts.token ? { Authorization: `Bearer ${opts.token}` } : {}) },
        body: init.body !== undefined ? JSON.stringify(init.body) : undefined,
        signal: ctl.signal,
      });
    } catch (e) {
      throw new ApiError("NETWORK", ctl.signal.aborted ? "The server took too long to answer." : "Can't reach the Signal server. Check the address and your connection.");
    } finally {
      clearTimeout(timer);
    }
    let json: { ok?: boolean; data?: T; error?: { code?: string; message?: string } } | null = null;
    try { json = await res.json(); } catch { json = null; }
    if (json?.ok === true) return json.data as T;
    const code = json?.error?.code ?? (res.status === 401 ? "AUTH_REQUIRED" : "HTTP_ERROR");
    if (code === "AUTH_REQUIRED") opts.onAuthRequired?.();
    throw new ApiError(code, json?.error?.message ?? `The server answered ${res.status}.`, res.status);
  }
  const enc = encodeURIComponent;
  return {
    meta: () => call<Meta>("/api/signal/meta"),
    authStatus: () => call<AuthStatus>("/api/auth/status"),
    login: (password: string) => call<LoginResult>("/api/auth/login", { method: "POST", body: { password, client: "mobile" } }),
    search: (q: string) => call<SearchResponse>(`/api/signal/search?q=${enc(q)}`),
    watchlist: () => call<WatchlistResponse>("/api/signal/watchlist"),
    addToWatchlist: (id: string) => call<{ added: boolean; id: string; ids: string[] }>("/api/signal/watchlist", { method: "POST", body: { id } }),
    removeFromWatchlist: (id: string) => call<{ removed: boolean; id: string; ids: string[] }>(`/api/signal/watchlist/${enc(id)}`, { method: "DELETE" }),
    reorderWatchlist: (ids: string[]) => call<{ ids: string[] }>("/api/signal/watchlist/positions", { method: "PUT", body: { ids } }),
    asset: (id: string) => call<AssetHeader>(`/api/signal/asset/${enc(id)}`),
    chart: (id: string, range: ChartRange) => call<ChartResponse>(`/api/signal/chart/${enc(id)}?range=${range}`),
    research: (id: string, wait = 4) => call<ResearchResponse>(`/api/signal/research/${enc(id)}?wait=${wait}`, { timeoutMs: 40_000 }),
    calendar: (q: string) => call<CalendarData>(`/api/calendar?${q}`, { timeoutMs: 60_000 }),
    discover: (refresh = false) => call<DiscoverData>(`/api/discover/shortlist?refresh=${refresh}`, { timeoutMs: 120_000 }),
    labRun: (body: LabRunBody) => call<LabRunData>("/api/btclab/run", { method: "POST", body, timeoutMs: 180_000 }),
    secFilings: (symbol: string, forms: string[], days: number) => call<SecFilingsData>(`/api/stocks/filings?symbols=${encodeURIComponent(symbol)}&forms=${encodeURIComponent(forms.join(","))}&limit=40&days=${days}`, { timeoutMs: 60_000 }),
    narrative: (refresh = false) => call<NarrativeData>(`/api/discover/narrative?refresh=${refresh}`, { timeoutMs: 120_000 }),
    treasury: () => call<TreasuryData>("/api/macro/treasury", { timeoutMs: 45_000 }),
    btcPositioning: () => call<Positioning>("/api/btc/positioning", { timeoutMs: 45_000 }),
    btcStablecoins: () => call<Stablecoins>("/api/btc/stablecoins", { timeoutMs: 60_000 }),
    btcNetwork: () => call<OnChain>("/api/btc/network", { timeoutMs: 45_000 }),
    fx: () => call<FxData>("/api/macro/fx", { timeoutMs: 45_000 }),
    strategyTracker: () => call<TrackerData>("/api/btclab/tracker", { timeoutMs: 60_000 }),
    worldBank: () => call<WorldData>("/api/macro/world", { timeoutMs: 60_000 }),
    btcMarket: () => call<CryptoMarket>("/api/btc/market", { timeoutMs: 45_000 }),
    opsOverview: () => call<OpsOverview>("/api/ops/overview", { timeoutMs: 30_000 }),
    opsPost: (path: string, body: unknown = {}) => call<OpsOverview>(`/api/ops/${path}`, { method: "POST", body, timeoutMs: 60_000 }),
    fedOps: () => call<FedOpsData>("/api/macro/fedops", { timeoutMs: 45_000 }),
    auctions: () => call<AuctionsData>("/api/macro/auctions", { timeoutMs: 45_000 }),
    budget: () => call<BudgetData>("/api/macro/budget", { timeoutMs: 45_000 }),
    interest: () => call<InterestData>("/api/macro/interest", { timeoutMs: 45_000 }),
    buybacks: () => call<BuybacksData>("/api/macro/buybacks", { timeoutMs: 45_000 }),
    bills: () => call<BillAuctionsData>("/api/macro/bills", { timeoutMs: 45_000 }),
    borrowing: () => call<BorrowingData>("/api/macro/borrowing", { timeoutMs: 45_000 }),
    dealers: () => call<DealersData>("/api/macro/dealers", { timeoutMs: 45_000 }),
    receipts: () => call<ReceiptsData>("/api/macro/receipts", { timeoutMs: 45_000 }),
    customs: () => call<CustomsData>("/api/macro/customs", { timeoutMs: 45_000 }),
    realYields: () => call<RealYieldsData>("/api/macro/real-yields", { timeoutMs: 45_000 }),
    futuresPositioning: () => call<FuturesPositioningData>("/api/macro/futures-positioning", { timeoutMs: 45_000 }),
    commodityPositioning: () => call<FuturesPositioningData>("/api/macro/commodity-positioning", { timeoutMs: 45_000 }),
    currencyPositioning: () => call<FuturesPositioningData>("/api/macro/currency-positioning", { timeoutMs: 45_000 }),
    debtRates: () => call<DebtRatesData>("/api/macro/debtrates", { timeoutMs: 45_000 }),
    debtMix: () => call<DebtMixData>("/api/macro/debtmix", { timeoutMs: 45_000 }),
    fedHoldings: () => call<FedHoldingsData>("/api/macro/fedholdings", { timeoutMs: 60_000 }),
    fedRates: () => call<FedRatesData>("/api/macro/fedrates", { timeoutMs: 45_000 }),
    tga: () => call<TgaData>("/api/macro/tga", { timeoutMs: 45_000 }),
    btcSentiment: () => call<Sentiment>("/api/btc/sentiment", { timeoutMs: 30_000 }),
    whatIf: (id: string, amount: number) => call<WhatIfData>(`/api/signal/whatif/${enc(id)}?amount=${amount}`, { timeoutMs: 60_000 }),
    fundamentalResearch: (symbol: string) => call<FundamentalResearch>(`/api/research/${encodeURIComponent(symbol)}`, { timeoutMs: 90_000 }),
    researchBrief: (symbol: string, b: { detail: string; question?: string; include_notes: boolean; include_position: boolean; shares?: number; buy_price?: number }) =>
      call<Brief>(`/api/research/${encodeURIComponent(symbol)}/brief`, { method: "POST", body: b, timeoutMs: 90_000 }),
    researchChanges: (symbol: string) => call<Changes>(`/api/research/${encodeURIComponent(symbol)}/changes`, { timeoutMs: 90_000 }),
    researchReview: (symbol: string) => call<{ snapshot: Record<string, unknown> }>(`/api/research/${encodeURIComponent(symbol)}/review`, { method: "POST", body: {}, timeoutMs: 90_000 }),
    researchNoteAdd: (symbol: string, text: string) => call<{ id: number }>(`/api/research/${encodeURIComponent(symbol)}/notes`, { method: "POST", body: { body: text } }),
    researchNoteDelete: (id: number) => call<{ deleted: number }>(`/api/research/notes/${id}`, { method: "DELETE" }),
    discoverListings: (days = 30) => call<ListingsFeed>(`/api/discover/listings?days=${days}`),
    discoverCandidates: (qs: string) => call<CandidatesFeed>(`/api/discover/candidates${qs ? `?${qs}` : ""}`),
    discoverState: (symbol: string, state: string, on = true) => call<MyState["state"]>("/api/discover/state", { method: "POST", body: { symbol, state, on } }),
    stockResearch: (symbol: string) => call<StockResearchData>(`/api/stocks/${encodeURIComponent(symbol)}/research`, { timeoutMs: 60_000 }),
    earnings: (days: number) => call<EarningsData>(`/api/stocks/earnings?days=${days}`, { timeoutMs: 60_000 }),
    macroBrief: () => call<MacroBriefData>("/api/macro/brief", { timeoutMs: 40_000 }),
    journalLog: (f: JournalFilters = {}) => call<JournalLog>(`/api/journal/log?${new URLSearchParams(Object.entries(f).filter(([, v]) => v) as [string, string][])}`),
    journalGet: (id: string) => call<JournalEntry>(`/api/journal/entries/${id.split(":")[1]}`),
    journalCreate: (body: Record<string, string | null>) => call<JournalEntry>("/api/journal/entries", { method: "POST", body }),
    journalUpdate: (id: string, body: Record<string, string | null>) => call<JournalEntry>(`/api/journal/entries/${id.split(":")[1]}`, { method: "PUT", body }),
    journalDelete: (id: string) => call<{ deleted: boolean }>(`/api/journal/entries/${id.split(":")[1]}`, { method: "DELETE" }),
    refreshAgent: (id: string, agent: AgentName) => call<ResearchResponse>(`/api/signal/research/${enc(id)}/refresh`, { method: "POST", body: { agent }, timeoutMs: 60_000 }),
  };
}
export type Api = ReturnType<typeof createApi>;
