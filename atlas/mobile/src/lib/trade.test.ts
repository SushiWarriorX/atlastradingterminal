import { describe, expect, it } from "vitest";
import type { UsTradeData } from "../api/types";
import { balanceWords, billions, checkText, compareText, groupText, headlineText, monthText, rangeText, signedBillions } from "./trade";

type Group = NonNullable<UsTradeData["total"]>;
type Detail = NonNullable<UsTradeData["detail"]>;
const range = { months: 417, first: "1992-01", lowest: { value: -132.98, month: "2025-03" }, highest: { value: -0.83, month: "1992-02" }, share_lower_pct: 1 };
const total = (over: Partial<Group> = {}): Group => ({ exports: 321.511, imports: 426.558, balance: -105.047, balance_change: 0.69, balance_year_ago: -59.392, exports_change_year_pct: 9.97, imports_change_year_pct: 21.27, range, ...over });
const detail = (over: Partial<Detail> = {}): Detail => ({ months_checked: 417, first_month: "1992-01", last_month: "2026-09", largest_gap_million: 1, largest_gap_month: "1992-07", ...over });

describe("the international trade card's words", () => {
  it("writes a level in billions of dollars with one decimal, and rounds at the half", () => {
    expect(billions(321.511)).toBe("$321.5 billion");
    expect(billions(426.558)).toBe("$426.6 billion");
    expect(billions(-105.047)).toBe("$105.0 billion");                                                                           // a level has no sign: the words say deficit or surplus
    expect(billions(99.94)).toBe("$99.9 billion");
    expect(billions(99.96)).toBe("$100.0 billion");
  });

  it("writes a balance with its sign, and none for a balance that shows as zero", () => {
    expect(signedBillions(-105.047)).toBe("-$105.0 billion");
    expect(signedBillions(30.865)).toBe("+$30.9 billion");
    expect(signedBillions(0)).toBe("$0.0 billion");
    expect(signedBillions(0.04)).toBe("$0.0 billion");
    expect(signedBillions(-0.04)).toBe("$0.0 billion");
    expect(signedBillions(0.06)).toBe("+$0.1 billion");
    expect(signedBillions(-0.06)).toBe("-$0.1 billion");
  });

  it("calls a negative balance a deficit and a positive one a surplus, and never names a balance that shows as zero", () => {
    expect(balanceWords(-105.047)).toBe("a deficit of $105.0 billion");
    expect(balanceWords(30.865)).toBe("a surplus of $30.9 billion");
    expect(balanceWords(0)).toBe("a balance of $0.0 billion");
    expect(balanceWords(-0.04)).toBe("a balance of $0.0 billion");
    expect(balanceWords(0.04)).toBe("a balance of $0.0 billion");
    expect(balanceWords(-0.06)).toBe("a deficit of $0.1 billion");
    expect(balanceWords(0.06)).toBe("a surplus of $0.1 billion");
  });

  it("states what the country sold, what it bought and the difference", () => {
    expect(headlineText(total(), "September 2026")).toBe("In September 2026 the US sold $321.5 billion of goods and services to the rest of the world and bought $426.6 billion: a deficit of $105.0 billion.");
    expect(headlineText(total({ exports: 500, imports: 450, balance: 50 }), "May 2030")).toBe("In May 2030 the US sold $500.0 billion of goods and services to the rest of the world and bought $450.0 billion: a surplus of $50.0 billion.");
  });

  it("gives the balance a month and a year earlier, and the year's change in exports and imports", () => {
    expect(compareText(total())).toBe("A month earlier it was a deficit of $105.7 billion; a year earlier, a deficit of $59.4 billion. Over the year exports are up 9.97% and imports up 21.27%.");
    // the month before is the balance less the change: a deficit that turned into a surplus is worded as such
    expect(compareText(total({ balance: 12.3, balance_change: 20.0, balance_year_ago: -4.0, exports_change_year_pct: -1.5, imports_change_year_pct: 0 })))
      .toBe("A month earlier it was a deficit of $7.7 billion; a year earlier, a deficit of $4.0 billion. Over the year exports are down 1.50% and imports unchanged.");
  });

  it("writes goods and services in a line each, with the year's change", () => {
    const goods = { exports: 210.968, imports: 346.879, balance: -135.911, balance_change: 0.716, balance_year_ago: -87.897, exports_change_year_pct: 13.14, imports_change_year_pct: 26.43 };
    const services = { exports: 110.543, imports: 79.678, balance: 30.865, balance_change: -0.026, balance_year_ago: 28.505, exports_change_year_pct: 4.4, imports_change_year_pct: 2.97 };
    expect(groupText("Goods", goods)).toBe("Goods: sold $211.0 billion, bought $346.9 billion: a deficit of $135.9 billion; exports up 13.14% and imports up 26.43% on a year earlier.");
    expect(groupText("Services", services)).toBe("Services: sold $110.5 billion, bought $79.7 billion: a surplus of $30.9 billion; exports up 4.40% and imports up 2.97% on a year earlier.");
  });

  it("words the range of the monthly balance with its lowest, its highest and the share of lower months", () => {
    const t = rangeText(range);
    expect(t).toBe("Since January 1992 (417 months) the monthly balance ran from -$133.0 billion (March 2025) to -$0.8 billion (February 1992); it was lower than now in 1% of those months (a lower balance is a bigger deficit or a smaller surplus).");
    expect(t).not.toMatch(/\b(?:19|20)\d\d-\d\d\b/);                                                                           // no raw ISO month on screen
    expect(rangeText({ ...range, lowest: { value: 4.3, month: "2003-03" }, highest: { value: 32.46, month: "2026-03" } })).toContain("ran from +$4.3 billion (March 2003) to +$32.5 billion (March 2026)");
  });

  it("states a month in the same three terms", () => {
    expect(monthText({ month: "2026-09", exports: 321.511, imports: 426.558, balance: -105.047 }, "Sep 2026")).toBe("Sep 2026: sold $321.5 billion, bought $426.6 billion, a deficit of $105.0 billion");
    expect(monthText({ month: "2030-05", exports: 500, imports: 450, balance: 50 }, "May 2030")).toBe("May 2030: sold $500.0 billion, bought $450.0 billion, a surplus of $50.0 billion");
  });

  it("states the check with the card's own counts and the largest gap with its month, written out", () => {
    const t = checkText(detail());
    expect(t.startsWith("Check: in each of the 417 months from January 1992 to September 2026 the nine series covered the same months with none missing, every figure lay inside its range and no month-on-month move of an export or import series was beyond 50% (plain checks). ")).toBe(true);
    expect(t).toMatch(/not that the figures are right: each balance equalled its exports minus its imports/);
    expect(t).toContain("total exports and total imports equalled goods plus services, and the total balance equalled the goods balance plus the services balance, in every month, to within 1.5 million dollars");
    expect(t).toContain("(the published figures are each rounded to a million; the largest gap was 1 million dollars in July 1992).");
    expect(t).not.toMatch(/\b(?:19|20)\d\d-\d\d\b/);
    expect(checkText(detail({ largest_gap_million: 1.5, largest_gap_month: "2024-03" }))).toContain("the largest gap was 1.5 million dollars in March 2024)");
    expect(checkText(detail({ largest_gap_million: 0.3333 }))).toContain("the largest gap was 0.333 million dollars");
    expect(checkText(detail({ months_checked: 1234 }))).toContain("in each of the 1,234 months");
  });
});
