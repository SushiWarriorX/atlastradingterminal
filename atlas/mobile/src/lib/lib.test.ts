import { describe, expect, it } from "vitest";
import type { Asset, Briefing, Finding, Prov, WatchlistResponse, WatchRow } from "../api/types";
import { AGENT_ORDER, briefingSections, coverageNote, lineText, rowKind } from "./briefing";
import { countdown, dateOnly, directionOf, formatPct, formatPrice, hueFor, initials, localClock, localDateTime, relativeTime } from "./format";
import { describeFreshness, isOutdated, summarizeTones, worstTone } from "./freshness";
import { keys } from "./keys";
import { safeUrl } from "./links";
import { MAX_RECENTS, parseRecents, pushRecent } from "./recents";
import { applyAdd, applyRemove, applyReorder, idsOf, moveId, settledRows } from "./watchlist";
import { blankForm, fromEntry, missingText, resultText, signed, toBody } from "./journal";

const NOW = Date.parse("2026-12-01T12:00:00Z");
const asset = (id: string, symbol: string, type: Asset["type"] = "stock", venue = "Nasdaq"): Asset => ({ id, symbol, name: symbol + " Inc", type, venue, support: "supported", note: null });
const prov = (status: Prov["status"], extra: Partial<Prov> = {}): Prov => ({ provider: "yahoo", status, event_time: "2026-12-01T11:55:00Z", delay_seconds: null, session: null, quality: [], ...extra });
const row = (a: Asset): WatchRow => ({ asset: a, quote: null, spark: null, takeaway: null, error: null });
const wl = (...a: Asset[]): WatchlistResponse => ({ items: a.map(row), count: a.length, demo: false, as_of: "2026-12-01T12:00:00Z" });

describe("formatting", () => {
  it("formats prices like the server does", () => {
    expect(formatPrice(67120.5)).toBe("$67,120.50");
    expect(formatPrice(0.0345)).toBe("$0.0345");
    expect(formatPrice(0.000022)).toBe("$0.000022");
    expect(formatPrice(0)).toBe("$0.00");
    expect(formatPrice(null)).toBe("n/a");
    expect(formatPrice(Number.NaN)).toBe("n/a");
  });
  it("formats percentages with a real minus sign", () => {
    expect(formatPct(2.345)).toBe("+2.35%");
    expect(formatPct(-0.5)).toBe("−0.50%");
    expect(formatPct(-0.5, 1, false)).toBe("−0.5%");
    expect(formatPct(undefined)).toBe("n/a");
    expect(directionOf(-1)).toBe("down");
    expect(directionOf(0)).toBe("flat");
    expect(directionOf(null)).toBe("flat");
  });
  it("words relative times and countdowns", () => {
    expect(relativeTime("2026-12-01T11:59:50Z", NOW)).toBe("just now");
    expect(relativeTime("2026-12-01T11:48:00Z", NOW)).toBe("12m ago");
    expect(relativeTime("2026-12-01T09:00:00Z", NOW)).toBe("3h ago");
    expect(relativeTime("2026-11-28T12:00:00Z", NOW)).toBe("3d ago");
    expect(relativeTime(null, NOW)).toBe("unknown time");
    expect(relativeTime("garbage", NOW)).toBe("unknown time");
    expect(countdown("2026-12-09T19:00:00Z", NOW)).toBe("in 8d 7h");
    expect(countdown("2026-12-01T14:15:00Z", NOW)).toBe("in 2h 15m");
    expect(countdown("2026-12-01T12:12:00Z", NOW)).toBe("in 12m");
    expect(countdown("2026-12-01T11:00:00Z", NOW)).toBe("now or past");
    expect(countdown(null, NOW)).toBe("");
  });
  it("shows the same instant in the viewer's timezone", () => {
    expect(localDateTime("2026-12-09T19:00:00Z", "America/New_York")).toMatch(/Dec 9.*2:00\s?PM/);
    expect(localDateTime("2026-12-09T19:00:00Z", "Asia/Singapore")).toMatch(/Dec 10.*3:00\s?AM/);
    expect(localClock("2026-12-09T19:00:30Z", "America/New_York")).toMatch(/2:00\s?PM/);
    expect(localDateTime(null)).toBe("n/a");
    expect(localDateTime("nope")).toBe("n/a");
    expect(dateOnly("2026-12-09")).toBe("Dec 9");
    expect(dateOnly(null)).toBe("n/a");
  });
  it("gives each asset id its own avatar colour and short initials", () => {
    expect(hueFor("EQUITY:NASDAQ:AAPL")).toBe(hueFor("EQUITY:NASDAQ:AAPL"));
    expect(hueFor("CRYPTO:COINBASE:BTC-USD:SPOT")).not.toBe(hueFor("ETF:ARCA:BTC"));      // same ticker, different asset: different colour
    expect(initials("AAPL")).toBe("AA");
    expect(initials("BTC")).toBe("BTC");
    expect(initials("")).toBe("?");
  });
});

describe("freshness labels", () => {
  it("never upgrades a stale or unavailable price", () => {
    expect(describeFreshness(prov("LIVE"), NOW, "UTC")).toMatchObject({ tone: "live", label: "Live", warn: false });
    expect(describeFreshness(prov("DELAYED", { delay_seconds: 900 }), NOW, "UTC")).toMatchObject({ tone: "delayed", label: "Delayed ~15 min", warn: false });
    const stale = describeFreshness(prov("STALE", { event_time: "2026-12-01T09:00:00Z" }), NOW, "UTC");
    expect(stale).toMatchObject({ tone: "stale", label: "Stale", warn: true });
    expect(stale.detail).toBe("last update 3h ago");
    expect(describeFreshness(prov("HISTORICAL", { session: "CLOSED" }), NOW, "UTC").label).toBe("Market closed");
    expect(describeFreshness(prov("HISTORICAL"), NOW, "UTC").label).toBe("Last known");
    expect(describeFreshness(prov("DEMO"), NOW)).toMatchObject({ tone: "demo", label: "Demo data", detail: "synthetic, not real" });
    expect(describeFreshness(prov("UNAVAILABLE"), NOW)).toMatchObject({ tone: "unavailable", warn: true });
    expect(describeFreshness(null, NOW)).toMatchObject({ tone: "unavailable", label: "No data", warn: true });
    expect(describeFreshness(prov("LIVE", { event_time: null }), NOW).detail).toBe("update time unknown");
  });
  it("flags data the device itself has held too long", () => {
    expect(isOutdated(NOW - 60_000, NOW)).toBe(false);
    expect(isOutdated(NOW - 300_000, NOW)).toBe(true);
    expect(isOutdated(null, NOW)).toBe(true);
  });
  it("summarises a list's freshness without hiding the bad news", () => {
    expect(worstTone(["live", "delayed", "stale"])).toBe("stale");
    expect(worstTone(["live", "unavailable"])).toBe("unavailable");
    expect(worstTone([])).toBeNull();
    expect(summarizeTones(["live", "stale", "stale", "delayed", "unavailable"])).toBe("2 stale · 1 unavailable");
    expect(summarizeTones(["live", "delayed", "historical", "demo"])).toBe("");      // normal states never raise a banner
    expect(summarizeTones([])).toBe("");
  });
});

describe("watchlist edits", () => {
  const a = asset("EQUITY:NASDAQ:AAPL", "AAPL"), b = asset("CRYPTO:COINBASE:BTC-USD:SPOT", "BTC", "crypto", "Coinbase spot (USD)"), c = asset("ETF:ARCA:BTC", "BTC", "etf", "NYSE Arca");
  it("moves one place at a time and stops at the ends", () => {
    expect(moveId(["a", "b", "c"], "b", "up")).toEqual(["b", "a", "c"]);
    expect(moveId(["a", "b", "c"], "b", "down")).toEqual(["a", "c", "b"]);
    const ids = ["a", "b"];
    expect(moveId(ids, "a", "up")).toBe(ids);
    expect(moveId(ids, "b", "down")).toBe(ids);
    expect(moveId(ids, "zzz", "up")).toBe(ids);
  });
  it("keeps two assets that share a ticker apart because it works on ids", () => {
    const w = applyAdd(applyAdd(wl(a), b), c);
    expect(idsOf(w)).toEqual([a.id, b.id, c.id]);
    expect(w.items.filter((r) => r.asset.symbol === "BTC")).toHaveLength(2);
    expect(applyAdd(w, b)).toBe(w);                                                   // adding the same id again changes nothing
    expect(idsOf(applyRemove(w, b.id))).toEqual([a.id, c.id]);                       // removing the crypto BTC leaves the ETF BTC
    expect(w.items[2].asset.type).toBe("etf");
  });
  it("shows a just-added asset as loading, not as a failed price, until the server answers", () => {
    const w = applyAdd(wl(a), b);
    expect(w.items[1].loading).toBe(true);
    expect(w.items[0].loading).toBeUndefined();
    expect(idsOf({ ...w, items: settledRows(w.items) })).toEqual([a.id]);               // placeholders never count towards "N unavailable"
  });
  it("applies an order only when it is a full permutation", () => {
    const w = wl(a, b, c);
    expect(idsOf(applyReorder(w, [c.id, a.id, b.id]))).toEqual([c.id, a.id, b.id]);
    expect(applyReorder(w, [c.id]).items).toBe(w.items);
    expect(applyReorder(w, [c.id, a.id, "unknown"]).items).toBe(w.items);
    expect(applyRemove(w, a.id).count).toBe(2);
  });
});

describe("recent searches", () => {
  it("keeps one entry per asset id, newest first, capped", () => {
    const btc = asset("CRYPTO:COINBASE:BTC-USD:SPOT", "BTC", "crypto"), etf = asset("ETF:ARCA:BTC", "BTC", "etf");
    let r = pushRecent([], btc);
    r = pushRecent(r, etf);
    expect(r.map((x) => x.id)).toEqual([etf.id, btc.id]);                           // both BTCs are kept: ids, not tickers
    expect(pushRecent(r, btc).map((x) => x.id)).toEqual([btc.id, etf.id]);
    let long: Asset[] = [];
    for (let i = 0; i < 20; i++) long = pushRecent(long, asset(`EQUITY:NASDAQ:T${i}`, `T${i}`));
    expect(long).toHaveLength(MAX_RECENTS);
    expect(long[0].symbol).toBe("T19");
  });
  it("survives corrupt storage", () => {
    expect(parseRecents(null)).toEqual([]);
    expect(parseRecents("{not json")).toEqual([]);
    expect(parseRecents('{"a":1}')).toEqual([]);
    expect(parseRecents(JSON.stringify([asset("EQUITY:NASDAQ:AAPL", "AAPL"), { id: 5 }, null, { id: "x", symbol: "X", name: "X", type: "bogus" }]))).toHaveLength(1);
  });
});

describe("links", () => {
  it("only opens web links", () => {
    expect(safeUrl("https://example.com/a?b=1")).toBe("https://example.com/a?b=1");
    expect(safeUrl("http://example.com")).toBe("http://example.com/");
    for (const bad of ["javascript:alert(1)", "data:text/html,x", "file:///etc/passwd", "intent://x", "not a url", "", null, undefined]) expect(safeUrl(bad as string)).toBeNull();
  });
});

const finding = (agent: Finding["agent"], status: Finding["status"]): Finding => ({
  agent, status, stance: null, stance_rule: null, takeaway: "t", facts: [], interpretations: [], stories: [], levels: [], events: [], missing: [], sources: [], limitations: [], explanation: null,
  data_as_of: null, analyzed_at: null, ttl_seconds: 0, next_refresh_at: null, demo: false, error: null,
});
const briefing = (over: Partial<Briefing> = {}): Briefing => ({
  headline: "h", changed: [], supports: [], risks: [], watch: [], disagreements: [], generated_at: "2026-12-01T12:00:00Z", demo: false,
  coverage: { agents_ok: 4, agents_total: 4, partial: [], pending: [], unavailable: [], not_applicable: [] }, ...over,
});

describe("briefing view-model", () => {
  it("asks the four questions in order and keeps empty sections", () => {
    const s = briefingSections(briefing({ risks: [{ agent: "macro", text: "r", fact_keys: [], at_utc: null }] }));
    expect(s.map((x) => x.title)).toEqual(["What changed", "What supports it", "Main risks", "Watch next"]);
    expect(s[2].lines).toHaveLength(1);
    expect(s[0].lines).toHaveLength(0);
    expect(AGENT_ORDER).toEqual(["news", "technical", "macro", "fundamentals"]);
  });
  it("adds the viewer's local time and countdown to scheduled lines only", () => {
    const l = { agent: "macro" as const, text: "Next FOMC interest-rate decision.", fact_keys: [], at_utc: "2026-12-09T19:00:00Z" };
    expect(lineText(l, NOW, "America/New_York")).toMatch(/^Next FOMC interest-rate decision\. Dec 9, 2:00\s?PM EST \(in 8d 7h\)$/);
    expect(lineText({ ...l, at_utc: null }, NOW)).toBe("Next FOMC interest-rate decision.");
  });
  it("says plainly when the briefing rests on fewer than four agents", () => {
    expect(coverageNote(briefing())).toBeNull();
    const n = coverageNote(briefing({ coverage: { agents_ok: 2, agents_total: 4, partial: ["news"], pending: ["fundamentals"], unavailable: [{ agent: "macro", reason: "x" }], not_applicable: [] } }));
    expect(n).toBe("Based on 3 of 4 agents: Fundamentals still loading; Macro unavailable; News partly available.");
    expect(coverageNote(briefing({ coverage: { agents_ok: 3, agents_total: 4, partial: ["technical"], pending: [], unavailable: [], not_applicable: [] } }))).toBe("All 4 agents contributed; Technical is only partly available (open its row to see what is missing).");
  });
  it("maps finding status to a row state", () => {
    expect(rowKind(undefined)).toBe("pending");
    expect(rowKind(finding("news", "ok"))).toBe("ready");
    expect(rowKind(finding("news", "partial"))).toBe("partial");
    expect(rowKind(finding("news", "unavailable"))).toBe("unavailable");
    expect(rowKind(finding("news", "pending"))).toBe("pending");
    expect(rowKind(finding("news", "not_applicable"))).toBe("not_applicable");
  });
});

describe("query keys", () => {
  it("never share a cached answer between two servers", () => {
    const demo = keys("http://demo.local:8000"), live = keys("https://signal.example.com");
    const all = (k: ReturnType<typeof keys>) => [k.meta, k.watchlist, k.search("btc"), k.asset("ETF:ARCA:BTC"), k.chart("ETF:ARCA:BTC", "1M"), k.research("ETF:ARCA:BTC")].map((x) => JSON.stringify(x));
    for (const [i, a] of all(demo).entries()) { expect(a).not.toBe(all(live)[i]); }
    expect(all(demo)).toEqual(all(keys("http://demo.local:8000")));                       // stable for one server
    expect(JSON.stringify(keys("x").chart("a", "1D"))).not.toBe(JSON.stringify(keys("x").chart("a", "1W")));
    expect(JSON.stringify(keys("x").asset("CRYPTO:COINBASE:BTC-USD:SPOT"))).not.toBe(JSON.stringify(keys("x").asset("ETF:ARCA:BTC")));      // two assets with one ticker
  });
});

describe("wide layout", () => {
  it("switches to three panes at 1000px and keeps the phone layout below", async () => {
    const { isWide, WIDE_MIN } = await import("./layout");
    expect(WIDE_MIN).toBe(1000);
    expect([390, 768, 999].map(isWide)).toEqual([false, false, false]);
    expect([1000, 1440].map(isWide)).toEqual([true, true]);
  });
});

describe("journal form helpers", () => {
  const entry = (o: Partial<import("../api/types").JournalEntry> = {}) => ({ id: "e:1", origin: "manual", editable: true, symbol: "AAPL", direction: "long", status: "closed", size: "10", entry_price: "100", exit_price: "110", entry_at: "2026-01-02T00:00:00Z", exit_at: null, fees: "0", planned_stop: null, note: null, thesis: null, risk_plan: null, outcome: null, screenshot: null, net_pnl_num: 100, return_pct: 10, pnl_missing: [], ...o }) as import("../api/types").JournalEntry;
  it("a new entry sends only what was filled in", () => {
    const f = { ...blankForm("2026-03-01"), symbol: " btc ", note: "idea" };
    expect(toBody(f, false)).toEqual({ symbol: "btc", direction: "long", entry_at: "2026-03-01", note: "idea" });
  });
  it("an edit sends emptied optional fields as null so they are cleared, but never clears the symbol or date", () => {
    const f = { ...fromEntry(entry({ note: "x" })), note: "", symbol: "" };
    const b = toBody(f, true);
    expect(b.note).toBeNull();
    expect(b.exit_price).toBe("110");
    expect("symbol" in b).toBe(false);
  });
  it("round-trips an entry through the form", () => {
    expect(fromEntry(entry({ fees: "0" })).fees).toBe("");
    expect(fromEntry(entry()).entry_at).toBe("2026-01-02");
  });
  it("signed uses a real minus and shows a dash for missing", () => {
    expect(signed(5)).toBe("+5.00");
    expect(signed(-5)).toBe("−5.00");
    expect(signed(null)).toBe("—");
  });
  it("result and missing text", () => {
    expect(resultText(entry())).toBe("+100.00");
    expect(resultText(entry({ status: "open", net_pnl_num: null }))).toBe("Open");
    expect(resultText(entry({ status: "note" }))).toBe("");
    expect(missingText(entry({ status: "open", pnl_missing: ["exit price"] }))).toBe("P&L needs the exit price.");
    expect(missingText(entry({ status: "note", pnl_missing: ["size"] }))).toBeNull();
  });
});
