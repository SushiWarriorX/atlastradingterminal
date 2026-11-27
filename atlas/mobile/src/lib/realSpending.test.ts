import { describe, expect, it } from "vitest";
import type { UsRealSpendingData } from "../api/types";
import { checkText, monthText, move, rangeText, signedPct, trillions, yearText } from "./realSpending";

type Year = NonNullable<UsRealSpendingData["year"]>;
type Detail = NonNullable<UsRealSpendingData["detail"]>;
const year = (over: Partial<Year> = {}): Year => ({ nominal_pct: 6.28, real_pct: 2.54, prices_pct: 3.65, core_prices_pct: 3.12, gap_points: 0, ...over });
const detail = (over: Partial<Detail> = {}): Detail => ({ months_checked: 237, first_month: "2007-01", last_month: "2026-09", largest_identity_gap_pct: 0.0378, largest_identity_gap_month: "2021-03", ...over });

describe("the real consumer spending card's words", () => {
  it("writes a level in trillions of dollars with two decimals", () => {
    expect(trillions(16977.6)).toBe("$16.98 trillion");
    expect(trillions(22452.8)).toBe("$22.45 trillion");
    expect(trillions(9994.9)).toBe("$9.99 trillion");                                                                          // rounds down below half a hundredth
    expect(trillions(9995.1)).toBe("$10.00 trillion");                                                                         // and up above it
  });

  it("says whether a figure rose, fell or stayed, and never names a change that rounds to zero", () => {
    expect(move(2.54)).toBe("up 2.54%");
    expect(move(-0.1)).toBe("down 0.10%");
    expect(move(0)).toBe("unchanged");
    expect(move(0.004)).toBe("unchanged");
    expect(move(-0.004)).toBe("unchanged");
    expect(move(0.005)).toBe("up 0.01%");
    expect(move(-0.006)).toBe("down 0.01%");
  });

  it("writes a change with its sign and no sign for zero", () => {
    expect(signedPct(0.76)).toBe("+0.76%");
    expect(signedPct(-0.1)).toBe("-0.10%");
    expect(signedPct(0)).toBe("0.00%");
    expect(signedPct(-0.004)).toBe("0.00%");
    expect(signedPct(0.004)).toBe("0.00%");
  });

  it("splits the year's change in spending in dollars into prices and goods and services bought", () => {
    expect(yearText(year())).toBe(
      "Over the year, spending in dollars rose 6.28%. Prices rose 3.65% (the PCE price index; up 3.12% without food and energy), so the amount of goods and services bought rose 2.54%. The three figures come from three separate series and fit each other: 1 + 6.28% = (1 + 2.54%) × (1 + 3.65%), with a gap of 0.000 points.");
  });

  it("words a fall, a rise in prices with a fall in the amount bought, and a gap", () => {
    const t = yearText(year({ nominal_pct: -1.2, real_pct: -3.5, prices_pct: 2.4, core_prices_pct: -0.5, gap_points: 0.0289 }));
    expect(t).toContain("spending in dollars fell 1.20%");
    expect(t).toContain("Prices rose 2.40% (the PCE price index; down 0.50% without food and energy)");
    expect(t).toContain("goods and services bought fell 3.50%");
    expect(t).toContain("1 - 1.20% = (1 - 3.50%) × (1 + 2.40%), with a gap of 0.029 points.");
    expect(yearText(year({ prices_pct: -0.4 }))).toContain("Prices fell 0.40%");
    expect(yearText(year({ real_pct: 0, nominal_pct: 3.65, prices_pct: 3.65 }))).toContain("goods and services bought did not change");
  });

  it("states a month in the same three terms", () => {
    expect(monthText({ month: "2026-09", real_change_pct: 0.02, prices_change_pct: 0.49, nominal_change_pct: 0.51 }, "Sep 2026"))
      .toBe("Sep 2026: spending in dollars +0.51%, prices +0.49%, real spending +0.02% on the month before");
    expect(monthText({ month: "2026-06", real_change_pct: 0.41, prices_change_pct: -0.1, nominal_change_pct: 0.31 }, "Jun 2026"))
      .toBe("Jun 2026: spending in dollars +0.31%, prices -0.10%, real spending +0.41% on the month before");
  });

  it("words the range of the year's growth with the lowest, the highest and the share of lower months", () => {
    const t = rangeText({ months: 225, first: "2008-01", lowest: { value: -14.66, month: "2020-04" }, highest: { value: 25.45, month: "2021-04" }, share_lower_pct: 61 });
    expect(t).toBe("Since January 2008 (225 months) the year-on-year growth of real spending ran from -14.66% (April 2020) to +25.45% (April 2021); 61% of those months were lower than now.");
    expect(t).not.toMatch(/\b20\d\d-\d\d\b/);                                                                                  // no raw ISO month on screen
  });

  it("states the check with the card's own counts and the largest gap with its month, written out", () => {
    const t = checkText(detail());
    expect(t.startsWith("Check: in each of the 237 months from January 2007 to September 2026 the four series covered the same months with none missing, every figure lay inside its range and no month-on-month move was beyond 25% for spending or 5% for prices (plain checks). ")).toBe(true);
    expect(t).toContain("real spending times the price index over 100 equalled spending in dollars in every month, to within 0.098% of spending (the largest gap was 0.0378% in March 2021)");
    expect(t).toContain("the Bureau chain-weights real spending and prices, so the sum is approximate, not exact");
    expect(t).toMatch(/not that the figures are right: real spending times/);
    expect(t).not.toMatch(/\b20\d\d-\d\d\b/);
    expect(checkText(detail({ largest_identity_gap_pct: 0.0078, largest_identity_gap_month: "2024-03" }))).toContain("(the largest gap was 0.0078% in March 2024)");
    expect(checkText(detail({ months_checked: 1234 }))).toContain("in each of the 1,234 months");
  });
});
