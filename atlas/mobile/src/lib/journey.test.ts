import { describe, expect, it } from "vitest";
import type { PaperAccount } from "../api/types";
import { chanceText, dayLabel, forwardLine, money, outcomeTone, paperLine, pctOf, periodLine, sample, split, whenLabel } from "./journey";

const acct = (o: Partial<PaperAccount>): PaperAccount => ({ id: "x", label: "x", stage: "monitor", family: "f", equity: 10_000, start_equity: 10_000, return: 0, day_pnl: 0, hold_return: null, matched_hold_return: null, exposure: 0, drawdown: 0, trades: 0, days: 0,
  halted: false, breaker_trips: 0, pending: null, opened_after: null, short: "X", name: "X", params_text: "", backtest: null, forward: [], ...o });

describe("percentages and money for the Journey page", () => {
  it("writes a ratio as a signed percentage with a real minus and thousands separators", () => {
    expect(pctOf(0.702)).toBe("+70.2%");
    expect(pctOf(-0.036)).toBe("−3.6%");
    expect(pctOf(7.935)).toBe("+793.5%");
    expect(pctOf(12.345)).toBe("+1,234.5%");
    expect(pctOf(0.0123, 2)).toBe("+1.23%");
    expect(pctOf(0.5, 0, false)).toBe("50%");
    expect(pctOf(-0.5, 0, false)).toBe("−50%");
  });
  it("shows what rounds to nothing as a plain zero, never as a gain or a loss", () => {
    expect(pctOf(0)).toBe("0.0%");
    expect(pctOf(0.00001)).toBe("0.0%");
    expect(pctOf(-0.00001, 2)).toBe("0.00%");
    expect(pctOf(0.0006, 1)).toBe("+0.1%");
  });
  it("says n/a for a missing or non-finite number", () => {
    for (const v of [null, undefined, NaN, Infinity]) { expect(pctOf(v)).toBe("n/a"); expect(money(v)).toBe("n/a"); }
  });
  it("writes dollars with two decimals and a real minus", () => {
    expect(money(10000)).toBe("$10,000.00");
    expect(money(64118.789)).toBe("$64,118.79");
    expect(money(-1234.5)).toBe("−$1,234.50");
    expect(money(0)).toBe("$0.00");
  });
});

describe("times and dates", () => {
  it("shows a time in UTC whatever the phone's zone", () => {
    expect(whenLabel("2026-11-15T00:00:00Z")).toBe("00:00 UTC · 15 Nov");
    expect(whenLabel("2026-01-05T23:59:59Z")).toBe("23:59 UTC · 5 Jan");
    expect(whenLabel("2026-11-15T10:34:08+02:00")).toBe("08:34 UTC · 15 Nov");
  });
  it("gives nothing for an unreadable time", () => {
    expect(whenLabel("")).toBe("");
    expect(whenLabel(null)).toBe("");
    expect(whenLabel("not a time")).toBe("");
  });
  it("writes a calendar day without zone shifting and leaves other text alone", () => {
    expect(dayLabel("2026-11-14")).toBe("14 Nov 2026");
    expect(dayLabel("2020-01-01")).toBe("1 Jan 2020");
    expect(dayLabel("soon")).toBe("soon");
  });
});

describe("sampling a curve for a small chart", () => {
  it("keeps short series as they are", () => {
    expect(sample([1, 2, 3], 5)).toEqual([1, 2, 3]);
    expect(sample([1, 2, 3], 3)).toEqual([1, 2, 3]);
  });
  it("spreads at most n points evenly and keeps the first and the last", () => {
    const v = Array.from({ length: 101 }, (_, i) => i);
    const s = sample(v, 11);
    expect(s).toEqual([0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100]);
    expect(sample(v, 2)).toEqual([0, 100]);
    expect(sample(v, 1)).toBe(v);
  });
});

describe("putting the accounts in order", () => {
  const all = [acct({ id: "b", name: "B", stage: "monitor" }), acct({ id: "cash", stage: "benchmark", name: "Cash" }), acct({ id: "portfolio", stage: "portfolio" }), acct({ id: "a", name: "A", stage: "monitor" }),
    acct({ id: "buy_hold", stage: "benchmark", name: "Hold" }), acct({ id: "c", name: "C", stage: "champion" }), acct({ id: "d", name: "D", stage: "challenger" })];
  it("puts the main portfolio and the two benchmarks apart from the strategies", () => {
    const s = split(all);
    expect(s.portfolio?.id).toBe("portfolio");
    expect(s.benchmarks.map((a) => a.id)).toEqual(["buy_hold", "cash"]);
    expect(s.strategies.map((a) => a.id)).toEqual(["c", "d", "a", "b"]);                   // champions, challengers, then monitors by name
  });
  it("copes with a lab that has no portfolio or no benchmark yet", () => {
    expect(split([])).toEqual({ portfolio: null, benchmarks: [], strategies: [] });
    expect(split([acct({ id: "cash", stage: "benchmark" })]).benchmarks.map((a) => a.id)).toEqual(["cash"]);
  });
  it("breaks a tie between equal names by id so the order never jumps", () => {
    expect(split([acct({ id: "z", name: "Same" }), acct({ id: "y", name: "Same" })]).strategies.map((a) => a.id)).toEqual(["y", "z"]);
  });
});

describe("words for the verdict", () => {
  it("colours each outcome: admitted green, rejected red, too thin amber, anything else grey", () => {
    expect([outcomeTone("admitted"), outcomeTone("rejected"), outcomeTone("too_thin"), outcomeTone(null), outcomeTone("whatever")]).toEqual(["up", "down", "warn", "dim", "dim"]);
  });
  it("puts the random-timing share in words and the 5 in 100 bar beside it", () => {
    expect(chanceText(0.402)).toBe("About 40 of every 100 randomly shifted copies of its schedule did at least as well on 2023-2024 (5 or fewer was needed).");
    expect(chanceText(0.05)).toContain("About 5 of every 100");
    expect(chanceText(null)).toBe("");
    expect(chanceText(NaN)).toBe("");
  });
  it("says what the paper record is so far, singular and plural", () => {
    expect(paperLine({ days: 0, return: 0, trades: 0 })).toBe("Paper: day 0, no trades yet");
    expect(paperLine({ days: 24, return: -0.0123, trades: 1 })).toBe("Paper: day 24, −1.23%, 1 trade");
    expect(paperLine({ days: 3, return: 0.05, trades: 2 })).toBe("Paper: day 3, +5.00%, 2 trades");
  });
  it("writes one line per period with the holding result beside it", () => {
    expect(periodLine("2020-2022", { return: 0.41, hold_return: 1.303 })).toBe("2020-2022: +41.0% (holding: +130.3%)");
    expect(periodLine("2023-2024", null)).toBe("2023-2024: n/a");
    expect(periodLine("2023-2024", { return: null, hold_return: 4.6 })).toBe("2023-2024: n/a (holding: +460.0%)");
  });
});

describe("the paper record as a line", () => {
  it("has nothing to draw until the account has two daily closes", () => {
    expect(forwardLine({ forward: [] })).toBeNull();
    expect(forwardLine({ forward: [1.01] })).toBeNull();
  });
  it("starts from 1, the account's starting equity, and then follows each close", () => {
    expect(forwardLine({ forward: [1.01, 0.99] })).toEqual([1, 1.01, 0.99]);
  });
});
