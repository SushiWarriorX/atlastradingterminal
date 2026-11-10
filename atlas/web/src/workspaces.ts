export type WidgetType = "calendar" | "discover" | "btclab" | "stockresearch" | "whatif" | "sentiment" | "secfilings" | "narrative" | "treasury" | "positioning" | "stablecoins" | "network" | "fx" | "tracker" | "world" | "cryptomarket" | "ops" | "fedops" | "tga" | "auctions" | "budget" | "interest" | "buybacks" | "bills" | "borrowing" | "debtrates" | "debtmix" | "fedholdings" | "fedrates" | "fundresearch" | "listings" | "newtome" | "earnings" | "journalquick" | "derivatives" | "news" | "newsfeeds" | "backtest" | "journaltrades" | "journaleditor" | "journalimport" | "journalsources" | "performance2" | "mtf" | "scanner" | "chart" | "watchlist" | "quote" | "tech" | "ai" | "health" | "yields" | "unavailable" | "settings";
export interface WidgetCfg { i: string; type: WidgetType; x: number; y: number; w: number; h: number; props?: Record<string, string> }
export interface WorkspaceDef { id: string; name: string; widgets: WidgetCfg[]; scope?: "btc" | "equity" }

import { BTC_ID as BTC } from "./ids";
const un = (i: string, view: string, x: number, y: number, w: number, h: number): WidgetCfg => ({ i, type: "unavailable", x, y, w, h, props: { view } });

export const WORKSPACES: Record<string, WorkspaceDef> = {
  overview: { id: "overview", name: "Global Market Overview", widgets: [
    { i: "chart", type: "chart", x: 0, y: 0, w: 9, h: 22, props: { pick: "any" } },
    { i: "watch", type: "watchlist", x: 9, y: 0, w: 3, h: 11 },
    { i: "quote", type: "quote", x: 9, y: 11, w: 3, h: 11 },
  ] },
  btc: { id: "btc", name: "BTC Intelligence (Bitcoin only)", scope: "btc", widgets: [
    { i: "c1h", type: "chart", x: 0, y: 0, w: 8, h: 13, props: { id: BTC, interval: "1h" } },
    { i: "quote", type: "quote", x: 8, y: 0, w: 4, h: 13, props: { id: BTC } },
    { i: "c15", type: "chart", x: 0, y: 13, w: 4, h: 10, props: { id: BTC, interval: "15m" } },
    { i: "cd", type: "chart", x: 4, y: 13, w: 4, h: 10, props: { id: BTC, interval: "1d" } },
    { i: "ai", type: "ai", x: 8, y: 13, w: 4, h: 10 },
    { i: "tech", type: "tech", x: 0, y: 23, w: 8, h: 8 },
    { i: "fng", type: "sentiment", x: 8, y: 23, w: 4, h: 8 },
    { i: "mtf", type: "mtf", x: 0, y: 31, w: 12, h: 16 },
    { i: "lab", type: "btclab", x: 0, y: 47, w: 12, h: 30 },
    { i: "track", type: "tracker", x: 0, y: 77, w: 12, h: 20 },
    { i: "deriv", type: "derivatives", x: 0, y: 97, w: 12, h: 15 },
    { i: "cot", type: "positioning", x: 0, y: 112, w: 12, h: 14 },
    { i: "mkt", type: "cryptomarket", x: 0, y: 126, w: 12, h: 11 },
    { i: "stable", type: "stablecoins", x: 0, y: 137, w: 12, h: 13 },
    { i: "net", type: "network", x: 0, y: 150, w: 12, h: 13 },
    { i: "whatif", type: "whatif", x: 0, y: 163, w: 12, h: 22 },
  ] },
  equities: { id: "equities", name: "US Equity Trading Desk (stocks and ETFs only)", scope: "equity", widgets: [
    { i: "chart", type: "chart", x: 0, y: 0, w: 8, h: 13, props: { pick: "equity" } },
    { i: "watch", type: "watchlist", x: 8, y: 0, w: 4, h: 13 },
    { i: "quote", type: "quote", x: 0, y: 13, w: 4, h: 11 },
    { i: "tech", type: "tech", x: 4, y: 13, w: 8, h: 11 },
    { i: "fundres", type: "fundresearch", x: 0, y: 24, w: 12, h: 60 },
    { i: "research", type: "stockresearch", x: 0, y: 84, w: 12, h: 26 },
    { i: "filings", type: "secfilings", x: 0, y: 110, w: 12, h: 18 },
    { i: "whatif", type: "whatif", x: 0, y: 128, w: 12, h: 22 },
    { i: "earn", type: "earnings", x: 0, y: 150, w: 12, h: 12 },
    { i: "mtf", type: "mtf", x: 0, y: 162, w: 12, h: 16 },
    { i: "news", type: "news", x: 0, y: 178, w: 12, h: 10 },
  ] },
  scanner: { id: "scanner", name: "Discover, Scanner and Backtester", widgets: [
    { i: "listings", type: "listings", x: 0, y: 0, w: 12, h: 22 },
    { i: "newtome", type: "newtome", x: 0, y: 22, w: 12, h: 34 },
    { i: "narr", type: "narrative", x: 0, y: 56, w: 12, h: 24 },
    { i: "disc", type: "discover", x: 0, y: 80, w: 12, h: 34 },
    { i: "scan", type: "scanner", x: 0, y: 114, w: 12, h: 20 },
    { i: "bt", type: "backtest", x: 0, y: 134, w: 12, h: 34 },
    { i: "chart", type: "chart", x: 0, y: 168, w: 7, h: 13 },
    { i: "tech", type: "tech", x: 7, y: 168, w: 5, h: 13 },
  ] },
  journal: { id: "journal", name: "Journal", widgets: [
    { i: "quick", type: "journalquick", x: 0, y: 0, w: 12, h: 30 },
  ] },
  "journal-advanced": { id: "journal-advanced", name: "Journal: imports and detailed analytics", widgets: [
    { i: "trades", type: "journaltrades", x: 0, y: 0, w: 7, h: 15 },
    { i: "editor", type: "journaleditor", x: 7, y: 0, w: 5, h: 22 },
    { i: "perf", type: "performance2", x: 0, y: 15, w: 7, h: 22 },
    { i: "import", type: "journalimport", x: 0, y: 37, w: 7, h: 20 },
    { i: "sources", type: "journalsources", x: 7, y: 22, w: 5, h: 22 },
  ] },
  news: { id: "news", name: "News", widgets: [
    { i: "news", type: "news", x: 0, y: 0, w: 8, h: 24 },
    { i: "feeds", type: "newsfeeds", x: 8, y: 0, w: 4, h: 24 },
    { i: "chart", type: "chart", x: 0, y: 24, w: 7, h: 12 },
    { i: "quote", type: "quote", x: 7, y: 24, w: 5, h: 12 },
  ] },
  macro: { id: "macro", name: "Macro Research Desk", widgets: [
    { i: "cal", type: "calendar", x: 0, y: 0, w: 12, h: 26 },
    { i: "c10", type: "chart", x: 0, y: 26, w: 6, h: 12, props: { id: "MACRO:FRED:DGS10", title: "US 10Y YIELD (FRED, daily)" } },
    { i: "c2", type: "chart", x: 6, y: 26, w: 6, h: 12, props: { id: "MACRO:FRED:DGS2", title: "US 2Y YIELD (FRED, daily)" } },
    un("fed", "macro_fed", 0, 38, 12, 24),                     // the Macro Dashboard panel (the placeholder id is kept so saved layouts pick it up)
    { i: "fedrates", type: "fedrates", x: 0, y: 62, w: 12, h: 12 },
    { i: "treasury", type: "treasury", x: 0, y: 74, w: 12, h: 14 },
    { i: "fx", type: "fx", x: 0, y: 88, w: 12, h: 11 },
    { i: "fedops", type: "fedops", x: 0, y: 99, w: 12, h: 12 },
    { i: "tga", type: "tga", x: 0, y: 111, w: 12, h: 11 },
    { i: "auctions", type: "auctions", x: 0, y: 122, w: 12, h: 15 },
    { i: "budget", type: "budget", x: 0, y: 137, w: 12, h: 12 },
    { i: "interest", type: "interest", x: 0, y: 149, w: 12, h: 15 },
    { i: "buybacks", type: "buybacks", x: 0, y: 164, w: 12, h: 16 },
    { i: "bills", type: "bills", x: 0, y: 180, w: 12, h: 15 },
    { i: "borrowing", type: "borrowing", x: 0, y: 195, w: 12, h: 14 },
    { i: "debtrates", type: "debtrates", x: 0, y: 209, w: 12, h: 13 },
    { i: "debtmix", type: "debtmix", x: 0, y: 222, w: 12, h: 15 },
    { i: "fedholdings", type: "fedholdings", x: 0, y: 237, w: 12, h: 14 },
    { i: "world", type: "world", x: 0, y: 251, w: 12, h: 16 },
    { i: "yields", type: "yields", x: 0, y: 267, w: 5, h: 7 },
    { i: "ai", type: "ai", x: 5, y: 267, w: 7, h: 10 },
  ] },
  settings: { id: "settings", name: "Settings", widgets: [
    { i: "settings", type: "settings", x: 0, y: 0, w: 6, h: 12 },
    { i: "health", type: "health", x: 6, y: 0, w: 6, h: 12 },
    { i: "ops", type: "ops", x: 0, y: 12, w: 12, h: 38 },
  ] },
};
// Views without a workspace render a single "not built yet" panel driven by /api/meta/views.
export const NAV: { view: string; label: string }[] = [
  ["overview", "OVERVIEW"], ["btc", "BTC"], ["equities", "STOCKS"], ["macro", "MACRO"], ["scanner", "DISCOVER"], ["journal", "JOURNAL"],
  ["news", "NEWS"], ["settings", "SETTINGS"],
].map(([view, label]) => ({ view, label }));
