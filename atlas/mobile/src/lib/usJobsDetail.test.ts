import { describe, expect, it } from "vitest";
import type { UsJobsDetailData } from "../api/types";
import { checkText, childText, parentText } from "./usJobsDetail";

type Item = NonNullable<UsJobsDetailData["groups"]>[number]["parent"];
const item = (key: string, label: string, thousands: number, cm: number, cmp: number | null, cy: number, cyp: number | null, share_pct?: number): Item =>
  ({ key, label, thousands, change_month: cm, change_month_pct: cmp, change_year: cy, change_year_pct: cyp, ...(share_pct == null ? {} : { share_pct }) });
const detail = { months_checked: 142, first_month: "2015-01", last_month: "2026-10", largest_sum_gap: 0.5 };

describe("an industry's own line", () => {
  it("writes the level and the two changes and no share", () => {
    expect(parentText(item("trade", "Trade, transportation and utilities", 28818, 22, 0.1, 104, 0.4))).toBe("Trade, transportation and utilities: 28,818,000; on the month up 22,000 (up 0.1%), on a year earlier up 104,000 (up 0.4%).");
    expect(parentText(item("construction", "Construction", 8367, -3, 0.0, 124, 1.5))).toBe("Construction: 8,367,000; on the month down 3,000 (under 0.1%), on a year earlier up 124,000 (up 1.5%).");
  });
});

describe("one part of an industry", () => {
  it("writes the level to the hundred, the share of its industry in lower case and the two changes", () => {
    expect(childText(item("retail", "Retail trade", 15501.3, 6.0, 0.0, 63.3, 0.4, 53.8), "Trade, transportation and utilities"))
      .toBe("Retail trade: 15,501,300 (53.8% of trade, transportation and utilities); on the month up 6,000 (under 0.1%), on a year earlier up 63,300 (up 0.4%).");
    expect(childText(item("wholesale", "Wholesale trade", 6068.8, -9.1, -0.1, 14.2, 0.2, 21.1), "Trade, transportation and utilities"))
      .toBe("Wholesale trade: 6,068,800 (21.1% of trade, transportation and utilities); on the month down 9,100 (down 0.1%), on a year earlier up 14,200 (up 0.2%).");
    expect(childText(item("federal", "Federal government", 2677, -1, 0.0, -71, -2.6, 11.5), "Government"))
      .toBe("Federal government: 2,677,000 (11.5% of government); on the month down 1,000 (under 0.1%), on a year earlier down 71,000 (down 2.6%).");
  });
  it("says unchanged for no move and writes no 'up 0 (unchanged)'", () => {
    expect(childText(item("utilities", "Utilities", 600, 0, 0, 0, 0, 2.1), "Trade, transportation and utilities")).toBe("Utilities: 600,000 (2.1% of trade, transportation and utilities); on the month unchanged (unchanged), on a year earlier unchanged (unchanged).");
  });
});

describe("the check line", () => {
  it("states the counts it was given, the tolerances and keeps the gap to four decimals", () => {
    expect(checkText(detail)).toBe("Check: in each of the 142 months from January 2015 to October 2026 the 26 series covered the same months with none missing and every figure lay inside its range (plain checks, not the source's sums). "
      + "The Bureau's own arithmetic held to within the rounding, which shows that the series belong to one release, not that the figures are right: each of the seven industries equalled the sum of its parts "
      + "(the largest gap in any month was 0.5 thousand; 0.75 is allowed for the six private industries, whose parts are given to a tenth of a thousand, and 2 for government, whose figures are whole thousands).");
    const t = checkText({ ...detail, months_checked: 1234, largest_sum_gap: 0.12345 });
    expect(t).toContain("each of the 1,234 months");
    expect(t).toContain("the largest gap in any month was 0.1235 thousand");
  });
  it("says the checks do not show that the figures are right", () => {
    expect(checkText(detail)).toContain("not that the figures are right");
    expect(checkText(detail).startsWith("Check:")).toBe(true);
  });
});
