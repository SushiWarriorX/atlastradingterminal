export type WidgetType = "derivatives" | "fundamentals" | "news" | "newsfeeds" | "backtest" | "journaltrades" | "journaleditor" | "journalimport" | "journalsources" | "performance2" | "portfolio" | "ticket" | "orders" | "risklimits" | "riskanalytics" | "scenario" | "performance" | "mtf" | "alerts" | "alertevents" | "scanner" | "chart" | "watchlist" | "quote" | "tech" | "ai" | "health" | "yields" | "unavailable" | "settings";
export interface WidgetCfg { i: string; type: WidgetType; x: number; y: number; w: number; h: number; props?: Record<string, string> }
export interface WorkspaceDef { id: string; name: string; widgets: WidgetCfg[] }

const BTC = "CRYPTO:COINBASE:BTC-USD:SPOT";
const un = (i: string, view: string, x: number, y: number, w: number, h: number): WidgetCfg => ({ i, type: "unavailable", x, y, w, h, props: { view } });

export const WORKSPACES: Record<string, WorkspaceDef> = {
  overview: { id: "overview", name: "Global Market Overview", widgets: [
    { i: "chart", type: "chart", x: 0, y: 0, w: 7, h: 13 },
    { i: "watch", type: "watchlist", x: 7, y: 0, w: 5, h: 13 },
    { i: "quote", type: "quote", x: 0, y: 13, w: 3, h: 11 },
    { i: "yields", type: "yields", x: 3, y: 13, w: 4, h: 6 },
    { i: "health", type: "health", x: 3, y: 19, w: 4, h: 7 },
    { i: "news", type: "news", x: 7, y: 13, w: 5, h: 6 },
    { i: "ai", type: "ai", x: 7, y: 19, w: 5, h: 10 },
  ] },
  markets: { id: "markets", name: "Markets", widgets: [
    { i: "c1", type: "chart", x: 0, y: 0, w: 6, h: 10, props: { id: "INDEX:SPGI:SPX" } },
    { i: "c2", type: "chart", x: 6, y: 0, w: 6, h: 10, props: { id: "INDEX:NASDAQ:NDX" } },
    { i: "c3", type: "chart", x: 0, y: 10, w: 6, h: 10, props: { id: "INDEX:CBOE:VIX" } },
    { i: "c4", type: "chart", x: 6, y: 10, w: 6, h: 10, props: { id: BTC } },
    { i: "watch", type: "watchlist", x: 0, y: 20, w: 6, h: 10 },
    { i: "yields", type: "yields", x: 6, y: 20, w: 6, h: 6 },
  ] },
  btc: { id: "btc", name: "BTC Trading Desk", widgets: [
    { i: "c1h", type: "chart", x: 0, y: 0, w: 8, h: 13, props: { id: BTC, interval: "1h" } },
    { i: "quote", type: "quote", x: 8, y: 0, w: 4, h: 13, props: { id: BTC } },
    { i: "c15", type: "chart", x: 0, y: 13, w: 4, h: 10, props: { id: BTC, interval: "15m" } },
    { i: "cd", type: "chart", x: 4, y: 13, w: 4, h: 10, props: { id: BTC, interval: "1d" } },
    { i: "ai", type: "ai", x: 8, y: 13, w: 4, h: 10 },
    { i: "tech", type: "tech", x: 0, y: 23, w: 8, h: 8 },
    { i: "mtf", type: "mtf", x: 0, y: 31, w: 12, h: 16 },
    { i: "deriv", type: "derivatives", x: 0, y: 47, w: 12, h: 15 },
  ] },
  equities: { id: "equities", name: "US Equity Trading Desk", widgets: [
    { i: "chart", type: "chart", x: 0, y: 0, w: 8, h: 13 },
    { i: "watch", type: "watchlist", x: 8, y: 0, w: 4, h: 13 },
    { i: "quote", type: "quote", x: 0, y: 13, w: 4, h: 11 },
    { i: "tech", type: "tech", x: 4, y: 13, w: 8, h: 11 },
    { i: "mtf", type: "mtf", x: 0, y: 24, w: 12, h: 16 },
    { i: "news", type: "news", x: 0, y: 40, w: 12, h: 10 },
  ] },
  scanner: { id: "scanner", name: "Equity Scanner", widgets: [
    { i: "scan", type: "scanner", x: 0, y: 0, w: 12, h: 20 },
    { i: "chart", type: "chart", x: 0, y: 20, w: 7, h: 13 },
    { i: "tech", type: "tech", x: 7, y: 20, w: 5, h: 13 },
  ] },
  alerts: { id: "alerts", name: "Alerts", widgets: [
    { i: "rules", type: "alerts", x: 0, y: 0, w: 7, h: 22 },
    { i: "events", type: "alertevents", x: 7, y: 0, w: 5, h: 22 },
    { i: "chart", type: "chart", x: 0, y: 22, w: 7, h: 12 },
    { i: "quote", type: "quote", x: 7, y: 22, w: 5, h: 12 },
  ] },
  portfolio: { id: "portfolio", name: "Portfolio & Paper Trading", widgets: [
    { i: "pf", type: "portfolio", x: 0, y: 0, w: 7, h: 16 },
    { i: "ticket", type: "ticket", x: 7, y: 0, w: 5, h: 22 },
    { i: "orders", type: "orders", x: 0, y: 16, w: 7, h: 12 },
    { i: "chart", type: "chart", x: 0, y: 28, w: 7, h: 12 },
    { i: "quote", type: "quote", x: 7, y: 22, w: 5, h: 18 },
  ] },
  risk: { id: "risk", name: "Portfolio & Risk", widgets: [
    { i: "limits", type: "risklimits", x: 0, y: 0, w: 5, h: 22 },
    { i: "analytics", type: "riskanalytics", x: 5, y: 0, w: 7, h: 22 },
    { i: "perf", type: "performance", x: 0, y: 22, w: 5, h: 13 },
    { i: "scenario", type: "scenario", x: 5, y: 22, w: 7, h: 13 },
  ] },
  journal: { id: "journal", name: "Journal & Performance", widgets: [
    { i: "trades", type: "journaltrades", x: 0, y: 0, w: 7, h: 15 },
    { i: "editor", type: "journaleditor", x: 7, y: 0, w: 5, h: 22 },
    { i: "perf", type: "performance2", x: 0, y: 15, w: 7, h: 22 },
    { i: "import", type: "journalimport", x: 0, y: 37, w: 7, h: 20 },
    { i: "sources", type: "journalsources", x: 7, y: 22, w: 5, h: 22 },
  ] },
  fundamentals: { id: "fundamentals", name: "Fundamentals", widgets: [
    { i: "fa", type: "fundamentals", x: 0, y: 0, w: 8, h: 26 },
    { i: "quote", type: "quote", x: 8, y: 0, w: 4, h: 13 },
    { i: "news", type: "news", x: 8, y: 13, w: 4, h: 13 },
    { i: "chart", type: "chart", x: 0, y: 26, w: 8, h: 12 },
  ] },
  news: { id: "news", name: "News", widgets: [
    { i: "news", type: "news", x: 0, y: 0, w: 8, h: 24 },
    { i: "feeds", type: "newsfeeds", x: 8, y: 0, w: 4, h: 24 },
    { i: "chart", type: "chart", x: 0, y: 24, w: 7, h: 12 },
    { i: "quote", type: "quote", x: 7, y: 24, w: 5, h: 12 },
  ] },
  backtest: { id: "backtest", name: "Backtester", widgets: [
    { i: "bt", type: "backtest", x: 0, y: 0, w: 12, h: 34 },
    { i: "chart", type: "chart", x: 0, y: 34, w: 7, h: 13 },
    { i: "tech", type: "tech", x: 7, y: 34, w: 5, h: 13 },
  ] },
  charts: { id: "charts", name: "Multi-chart", widgets: [
    { i: "c1", type: "chart", x: 0, y: 0, w: 6, h: 12, props: { interval: "1d" } },
    { i: "c2", type: "chart", x: 6, y: 0, w: 6, h: 12, props: { interval: "1h" } },
    { i: "c3", type: "chart", x: 0, y: 12, w: 6, h: 12, props: { interval: "15m" } },
    { i: "c4", type: "chart", x: 6, y: 12, w: 6, h: 12, props: { interval: "5m" } },
  ] },
  macro: { id: "macro", name: "Macro Research Desk", widgets: [
    { i: "c10", type: "chart", x: 0, y: 0, w: 6, h: 12, props: { id: "MACRO:FRED:DGS10", title: "US 10Y YIELD (FRED, daily)" } },
    { i: "c2", type: "chart", x: 6, y: 0, w: 6, h: 12, props: { id: "MACRO:FRED:DGS2", title: "US 2Y YIELD (FRED, daily)" } },
    { i: "yields", type: "yields", x: 0, y: 12, w: 5, h: 7 },
    un("fed", "macro_fed", 5, 12, 7, 7),
    { i: "ai", type: "ai", x: 0, y: 19, w: 12, h: 10 },
  ] },
  ai: { id: "ai", name: "AI Research Desk", widgets: [
    { i: "ai", type: "ai", x: 0, y: 0, w: 6, h: 24 },
    { i: "chart", type: "chart", x: 6, y: 0, w: 6, h: 12 },
    { i: "tech", type: "tech", x: 6, y: 12, w: 6, h: 12 },
  ] },
  settings: { id: "settings", name: "Settings", widgets: [
    { i: "settings", type: "settings", x: 0, y: 0, w: 6, h: 12 },
    { i: "health", type: "health", x: 6, y: 0, w: 6, h: 12 },
  ] },
};
// Views without a workspace render a single "not built yet" panel driven by /api/meta/views.
export const NAV: { view: string; label: string }[] = [
  ["overview", "OVERVIEW"], ["markets", "MARKETS"], ["btc", "BTC INTELLIGENCE"], ["equities", "EQUITIES"], ["fundamentals", "FUNDAMENTALS"], ["charts", "CHARTS"],
  ["scanner", "SCANNER"], ["news", "NEWS"], ["macro", "MACRO"], ["ai", "AI DESK"], ["ideas", "TRADE IDEAS"], ["portfolio", "PORTFOLIO"],
  ["risk", "RISK"], ["backtest", "BACKTEST"], ["journal", "JOURNAL"], ["alerts", "ALERTS"], ["settings", "SETTINGS"],
].map(([view, label]) => ({ view, label }));
