import { describe, expect, it } from "vitest";
import type { UsProducerPricesData } from "../api/types";
import { checkText, headlineText, indexText, itemText, monthText, moveText, rangeText, signedPct } from "./usProducerPrices";

type Headline = NonNullable<UsProducerPricesData["headline"]>;
const range = { months: 120, first: "2016-11", lowest: { value: -1.35, month: "2020-04" }, highest: { value: 11.59, month: "2022-03" }, share_lower_pct: 83 };
const headline: Headline = { key: "final", label: "Final demand", base: "November 2009 = 100", index: 160.254, change_pct: 0.35, change_year_pct: 6.52, core_change_year_pct: 5.04, range };

describe("changes, growth rates and index levels", () => {
  it("writes a change with its direction and two decimals, and exactly zero as unchanged", () => {
    expect(moveText(6.52)).toBe("up 6.52%");
    expect(moveText(-3.08)).toBe("down 3.08%");
    expect(moveText(0.1)).toBe("up 0.10%");
    expect(moveText(-0.01)).toBe("down 0.01%");
    expect(moveText(0.35)).toBe("up 0.35%");
    expect(moveText(0)).toBe("unchanged");
    expect(moveText(-0)).toBe("unchanged");
  });
  it("writes a growth rate with its sign and two decimals and zero without a sign", () => {
    expect(signedPct(11.59)).toBe("+11.59%");
    expect(signedPct(-1.35)).toBe("-1.35%");
    expect(signedPct(0)).toBe("0.00%");
    expect(signedPct(0.5)).toBe("+0.50%");
  });
  it("writes an index to one decimal", () => {
    expect(indexText(160.254)).toBe("160.3");
    expect(indexText(288.52)).toBe("288.5");
    expect(indexText(100)).toBe("100.0");
    expect(indexText(1234.56)).toBe("1234.6");
  });
});

describe("the sentences", () => {
  it("states where final demand prices stand, with the month, the base and the three changes", () => {
    expect(headlineText(headline, "October 2026")).toBe(
      "In October 2026 the producer price index for final demand was 160.3 (November 2009 = 100): up 0.35% on the month before and up 6.52% on a year earlier; without foods and energy it was up 5.04% on a year earlier.");
  });
  it("words a fall and an unchanged month the same way", () => {
    expect(headlineText({ ...headline, change_pct: -0.13, change_year_pct: 0, core_change_year_pct: -1.2 }, "June 2026")).toBe(
      "In June 2026 the producer price index for final demand was 160.3 (November 2009 = 100): down 0.13% on the month before and unchanged on a year earlier; without foods and energy it was down 1.20% on a year earlier.");
  });
  it("says where the growth on a year earlier stands among the last ten years, with the months in words", () => {
    expect(rangeText(range)).toBe("Over the last 10 years (120 months) the growth of final demand prices on a year earlier ran from -1.35% (April 2020) to +11.59% (March 2022); 83% of those months were lower than now.");
    expect(rangeText({ ...range, months: 132 })).toContain("Over the last 11 years (132 months)");
  });
  it("writes a series in one line with its label, index, base and the two changes", () => {
    const unprocessed = { key: "unprocessed", label: "Unprocessed goods for intermediate demand", base: "1982 = 100", index: 284.779, change_pct: -3.08, change_year_pct: 17.05 };
    expect(itemText(unprocessed)).toBe("Unprocessed goods for intermediate demand: 284.8 (1982 = 100); on the month down 3.08%, on a year earlier up 17.05%.");
    expect(itemText({ ...unprocessed, label: "Services for intermediate demand", base: "November 2009 = 100", index: 166.167, change_pct: 0, change_year_pct: 6.78 })).toBe(
      "Services for intermediate demand: 166.2 (November 2009 = 100); on the month unchanged, on a year earlier up 6.78%.");
  });
  it("writes one of the last months with both changes", () => {
    expect(monthText({ month: "2026-09", change_pct: 1.41, core_change_pct: 0.82 }, "September 2026")).toBe("September 2026: final demand up 1.41% on the month before, without foods and energy up 0.82%.");
    expect(monthText({ month: "2026-05", change_pct: 0.52, core_change_pct: -0.01 }, "May 2026")).toBe("May 2026: final demand up 0.52% on the month before, without foods and energy down 0.01%.");
  });
  it("says what was checked with the card's own counts and that it does not show the figures are right", () => {
    const t = checkText({ months_checked: 199, first_month: "2010-04", last_month: "2026-10" });
    expect(t).toBe("Check: in each of the 199 months from April 2010 to October 2026 the 9 series covered the same months with none missing, every index lay inside its range and no month moved by more than its limit "
      + "(plain checks only: producer price indexes have no sums to check against, so this shows that the series are lined up and plausible, not that the figures are right).");
    expect(checkText({ months_checked: 1234, first_month: "2010-04", last_month: "2026-10" })).toContain("in each of the 1,234 months from April 2010");
  });
});
