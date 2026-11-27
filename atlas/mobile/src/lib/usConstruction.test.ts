import { describe, expect, it } from "vitest";
import type { UsConstructionData } from "../api/types";
import { checkText, compareText, headlineText, itemText, money, monthText, move, moveMillions, rangeText, signedPct } from "./usConstruction";

type Total = NonNullable<UsConstructionData["total"]>;
const range = { months: 120, first: "2016-10", lowest: { value: -4.2, month: "2026-04" }, highest: { value: 18.5, month: "2022-04" }, share_lower_pct: 5 };
const total: Total = { millions: 2186145, change_month_millions: -41229, change_month_pct: -1.9, change_year_millions: -59654, change_year_pct: -2.7, growth_range: range };
const item = (key: string, label: string, millions: number, share_pct: number, cm: number, cmp: number | null, cy: number, cyp: number | null) =>
  ({ key, label, millions, share_pct, change_month_millions: cm, change_month_pct: cmp, change_year_millions: cy, change_year_pct: cyp });
const owners = [item("private", "Private", 1639330, 75.0, -40937, -2.4, -65040, -3.8), item("public", "Public", 546815, 25.0, -293, -0.1, 5386, 1.0)];
const publicResidential = item("public_residential", "Public residential", 12415, 0.6, 222, 1.8, -605, -4.6);

describe("amounts, changes and growth rates", () => {
  it("writes millions of dollars as trillions with three decimals from a trillion and as billions with one decimal below", () => {
    expect(money(2186145)).toBe("$2.186 trillion");
    expect(money(1639330)).toBe("$1.639 trillion");
    expect(money(1000000)).toBe("$1.000 trillion");
    expect(money(999950)).toBe("$1.000 trillion");
    expect(money(999949)).toBe("$999.9 billion");
    expect(money(861192)).toBe("$861.2 billion");
    expect(money(12415)).toBe("$12.4 billion");
    expect(money(5709)).toBe("$5.7 billion");
  });
  it("words a change in millions with its direction in billions with one decimal, trillions from a thousand billion, and unchanged under a twentieth of a billion", () => {
    expect(moveMillions(-41229)).toBe("down $41.2 billion");
    expect(moveMillions(43348)).toBe("up $43.3 billion");
    expect(moveMillions(-293)).toBe("down $0.3 billion");
    expect(moveMillions(222)).toBe("up $0.2 billion");
    expect(moveMillions(50)).toBe("up $0.1 billion");
    expect(moveMillions(-50)).toBe("down $0.1 billion");
    expect(moveMillions(49)).toBe("unchanged");
    expect(moveMillions(-49)).toBe("unchanged");
    expect(moveMillions(0)).toBe("unchanged");
    expect(moveMillions(999949)).toBe("up $999.9 billion");
    expect(moveMillions(999950)).toBe("up $1.000 trillion");
    expect(moveMillions(-1200000)).toBe("down $1.200 trillion");
  });
  it("words a percentage change with one decimal and its direction, and nothing to compare with as not available", () => {
    expect(move(-1.9, -41229)).toBe("down 1.9%");
    expect(move(18.5, 800000)).toBe("up 18.5%");
    expect(move(0.1, 3000)).toBe("up 0.1%");
    expect(move(null, 5000)).toBe("not available");
    expect(move(undefined, 0)).toBe("not available");
  });
  it("calls a percentage that rounds to nothing under 0.1% while the dollars moved, and unchanged only when they did not", () => {
    expect(move(0, 300)).toBe("under 0.1%");
    expect(move(-0, -200)).toBe("under 0.1%");
    expect(move(0.04, 60)).toBe("under 0.1%");
    expect(move(-0.04, -60)).toBe("under 0.1%");
    expect(move(0, 49)).toBe("unchanged");
    expect(move(0, 0)).toBe("unchanged");
    expect(move(0.04, 20)).toBe("unchanged");
  });
  it("writes a growth rate with its sign and no sign for a figure that shows as zero", () => {
    expect(signedPct(18.5)).toBe("+18.5%");
    expect(signedPct(-4.2)).toBe("-4.2%");
    expect(signedPct(0)).toBe("0.0%");
    expect(signedPct(0.04)).toBe("0.0%");
    expect(signedPct(-0.04)).toBe("0.0%");
  });
});

describe("the sentences of the card", () => {
  it("says how much construction work was done in the month and how it splits between private and public owners", () => {
    expect(headlineText(total, owners, "September 2026")).toBe("In September 2026 construction work in the US was done at a seasonally adjusted annual rate of $2.186 trillion: $1.639 trillion private (75.0%) and $546.8 billion public (25.0%).");
    expect(headlineText(total, owners.slice(0, 1), "September 2026")).toContain("trillion: $1.639 trillion private (75.0%).");
  });
  it("compares the total with the month before and with a year earlier", () => {
    expect(compareText(total)).toBe("Against the month before spending is down $41.2 billion (down 1.9%); against a year earlier it is down $59.7 billion (down 2.7%).");
    expect(compareText({ ...total, change_month_millions: 43348, change_month_pct: 2.0, change_year_millions: 0, change_year_pct: null })).toBe("Against the month before spending is up $43.3 billion (up 2.0%); against a year earlier it is unchanged (not available).");
    expect(compareText({ ...total, change_month_millions: 300, change_month_pct: 0.0, change_year_millions: 20, change_year_pct: 0.0 })).toBe("Against the month before spending is up $0.3 billion (under 0.1%); against a year earlier it is unchanged (unchanged).");
  });
  it("says where the growth on a year earlier stands among the last ten years, with signs and the months as a person reads them", () => {
    expect(rangeText(range)).toBe("Over the last 10 years (120 months) the growth of spending on a year earlier ran from -4.2% (April 2026) to +18.5% (April 2022); 5% of those months were lower than now.");
    expect(rangeText({ ...range, lowest: { value: 0.2, month: "2025-02" } })).toContain("ran from +0.2% (February 2025)");
  });
  it("writes one owner, use or part in a line with its share of all spending and the two changes", () => {
    expect(itemText(owners[0])).toBe("Private: $1.639 trillion (75.0% of all spending); on the month down $40.9 billion (down 2.4%), on a year earlier down $65.0 billion (down 3.8%).");
    expect(itemText(publicResidential)).toBe("Public residential: $12.4 billion (0.6% of all spending); on the month up $0.2 billion (up 1.8%), on a year earlier down $0.6 billion (down 4.6%).");
    expect(itemText(owners[1])).toContain("on the month down $0.3 billion (down 0.1%), on a year earlier up $5.4 billion (up 1.0%).");
    expect(itemText({ ...publicResidential, change_month_millions: 0, change_month_pct: 0, change_year_millions: 400, change_year_pct: 0 })).toContain("on the month unchanged (unchanged), on a year earlier up $0.4 billion (under 0.1%).");
  });
  it("writes a month in a line with the spending and the change on the month before", () => {
    expect(monthText({ month: "2026-08", millions: 2227374, change_millions: 43348 }, "August 2026")).toBe("August 2026: $2.227 trillion, up $43.3 billion on the month before");
    expect(monthText({ month: "2026-09", millions: 2186145, change_millions: -41229 }, "September 2026")).toBe("September 2026: $2.186 trillion, down $41.2 billion on the month before");
  });
  it("says what was checked with the card's own counts and the largest gap without trailing zeros", () => {
    const text = checkText({ months_checked: 141, first_month: "2015-01", last_month: "2026-09", largest_sum_gap: 1 });
    expect(text).toContain("Check: in each of the 141 months from January 2015 to September 2026 the 9 series covered the same months");
    expect(text).toContain("the largest gap was 1 million, and 1.5 is allowed");
    expect(text).toContain("not that the figures are right");
    expect(text).toContain("total spending equalled private plus public and residential plus nonresidential spending, private and public spending each equalled their residential plus nonresidential parts, and residential and nonresidential spending each equalled their private plus public parts");
    expect(checkText({ months_checked: 1234, first_month: "2000-01", last_month: "2026-09", largest_sum_gap: 1 })).toContain("1,234 months from January 2000");
    expect(checkText({ months_checked: 141, first_month: "2015-01", last_month: "2026-09", largest_sum_gap: 1.5 })).toContain("the largest gap was 1.5 million");
    expect(checkText({ months_checked: 141, first_month: "2015-01", last_month: "2026-09", largest_sum_gap: 0.0123 })).toContain("the largest gap was 0.0123 million");
  });
});
