import { describe, expect, it } from "vitest";
import type { UsConsumerCreditData } from "../api/types";
import { checkText, compareText, headlineText, kindText, level, monthText, move, moveMillions, rangeText, signedPct } from "./usConsumerCredit";

type Total = NonNullable<UsConsumerCreditData["total"]>;
const range = { months: 120, first: "2016-10", lowest: { value: -1.1, month: "2025-02" }, highest: { value: 10.1, month: "2022-04" }, share_lower_pct: 38 };
const total: Total = { total_millions: 5224415.99, revolving_millions: 1368452.96, nonrevolving_millions: 3855963.04, revolving_share_pct: 26.2, change_month_millions: 27838.63, change_month_pct: 0.5, change_year_millions: 152452.56, change_year_pct: 3.0, growth_range: range };

describe("amounts, changes and growth rates", () => {
  it("writes millions of dollars owed as trillions with three decimals from a trillion, as whole billions from a billion and as millions below", () => {
    expect(level(5224415.99)).toBe("$5.224 trillion");
    expect(level(1_000_000)).toBe("$1.000 trillion");
    expect(level(999_999)).toBe("$1,000 billion");
    expect(level(976044)).toBe("$976 billion");
    expect(level(1000)).toBe("$1 billion");
    expect(level(999)).toBe("$999 million");
    expect(level(640)).toBe("$640 million");
  });
  it("words a change in millions with its direction: billions with one decimal from a billion, millions below, and unchanged under half a million", () => {
    expect(moveMillions(27838.63)).toBe("up $27.8 billion");
    expect(moveMillions(-4100)).toBe("down $4.1 billion");
    expect(moveMillions(1000)).toBe("up $1.0 billion");
    expect(moveMillions(999.5)).toBe("up $1.0 billion");
    expect(moveMillions(999.4)).toBe("up $999 million");
    expect(moveMillions(-640)).toBe("down $640 million");
    expect(moveMillions(0.5)).toBe("up $1 million");
    expect(moveMillions(0.49)).toBe("unchanged");
    expect(moveMillions(-0.49)).toBe("unchanged");
    expect(moveMillions(0)).toBe("unchanged");
  });
  it("words a percentage change with one decimal and its direction, and nothing to compare with as not available", () => {
    expect(move(3.0)).toBe("up 3.0%");
    expect(move(-1.1)).toBe("down 1.1%");
    expect(move(0)).toBe("unchanged");
    expect(move(0.04)).toBe("unchanged");
    expect(move(-0.04)).toBe("unchanged");
    expect(move(null)).toBe("not available");
    expect(move(undefined)).toBe("not available");
  });
  it("writes a growth rate with its sign and no sign for a figure that shows as zero", () => {
    expect(signedPct(10.1)).toBe("+10.1%");
    expect(signedPct(-1.1)).toBe("-1.1%");
    expect(signedPct(0)).toBe("0.0%");
    expect(signedPct(0.04)).toBe("0.0%");
    expect(signedPct(-0.04)).toBe("0.0%");
  });
});

describe("the sentences of the card", () => {
  it("says what was owed at the end of the month and how it splits", () => {
    expect(headlineText(total, "September 2026")).toBe("In September 2026 US consumers owed $5.224 trillion in consumer credit at the end of the month (mortgages are not counted): $1.368 trillion revolving (26.2% of the total) and $3.856 trillion nonrevolving.");
  });
  it("compares the total with the month before and with a year earlier", () => {
    expect(compareText(total)).toBe("Against the month before the total is up $27.8 billion (up 0.5%); against a year earlier it is up $152.5 billion (up 3.0%).");
    expect(compareText({ ...total, change_month_millions: -4100, change_month_pct: -0.1, change_year_millions: 0, change_year_pct: null })).toBe("Against the month before the total is down $4.1 billion (down 0.1%); against a year earlier it is unchanged (not available).");
  });
  it("says where the growth on a year earlier stands among the last ten years, with signs and the months as a person reads them", () => {
    expect(rangeText(range)).toBe("Over the last 10 years (120 months) the total's growth on a year earlier ran from -1.1% (February 2025) to +10.1% (April 2022); 38% of those months were lower than now.");
    expect(rangeText({ ...range, lowest: { value: 0.2, month: "2025-02" } })).toContain("ran from +0.2% (February 2025)");
  });
  it("writes one kind of credit in a line with its share of the total and the two changes", () => {
    const revolving = { key: "revolving", label: "Revolving credit (credit cards and other revolving plans)", millions: 1368452.96, share_pct: 26.2, change_month_millions: 16298.61, change_month_pct: 1.2, change_year_millions: 55739.39, change_year_pct: 4.2 };
    expect(kindText(revolving)).toBe("Revolving credit (credit cards and other revolving plans): $1.368 trillion (26.2% of the total). Against the month before it is up $16.3 billion (up 1.2%); against a year earlier it is up $55.7 billion (up 4.2%).");
    expect(kindText({ ...revolving, change_month_millions: -2000, change_month_pct: -0.1 })).toContain("Against the month before it is down $2.0 billion (down 0.1%);");
  });
  it("writes a month in a line with its parts and the change on the month before", () => {
    expect(monthText({ month: "2026-04", total_millions: 5152692.28, revolving_millions: 1349979.48, nonrevolving_millions: 3802712.79, change_millions: 21263.4 }, "April 2026")).toBe("April 2026: total $5.153 trillion (revolving $1.350 trillion, nonrevolving $3.803 trillion), up $21.3 billion on the month before");
  });
  it("says what was checked with the card's own counts and the largest gap without trailing zeros", () => {
    const text = checkText({ months_checked: 441, first_month: "1990-01", last_month: "2026-09", largest_sum_gap: 0.01 });
    expect(text).toContain("Check: in each of the 441 months from January 1990 to September 2026 the 3 series covered the same months");
    expect(text).toContain("the largest gap was 0.01 million, and 0.015 is allowed");
    expect(text).toContain("not that the figures are right");
    expect(checkText({ months_checked: 1234, first_month: "2000-01", last_month: "2026-09", largest_sum_gap: 0 })).toContain("1,234 months from January 2000");
    expect(checkText({ months_checked: 1234, first_month: "2000-01", last_month: "2026-09", largest_sum_gap: 0 })).toContain("the largest gap was 0 million");
    expect(checkText({ months_checked: 441, first_month: "1990-01", last_month: "2026-09", largest_sum_gap: 0.0123 })).toContain("the largest gap was 0.0123 million");
  });
});
