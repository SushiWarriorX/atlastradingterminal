import { describe, expect, it } from "vitest";
import type { UsInventoriesData } from "../api/types";
import { checkText, compareText, headlineText, money, monthText, move, rangeText, ratio, sectorText } from "./usInventories";

type Total = NonNullable<UsInventoriesData["total"]>;
const range = { months: 120, first: "2016-10", lowest: { value: 1.26, month: "2021-04" }, highest: { value: 1.74, month: "2020-04" }, share_lower_pct: 12 };
const total: Total = { inventories_millions: 2873438, sales_millions: 2162520, ratio: 1.33, inventories_change_month_pct: 0.5, sales_change_month_pct: 1.8, inventories_change_year_pct: 5.1, sales_change_year_pct: 12.5, ratio_year_ago: 1.42, ratio_range: range };

describe("amounts, ratios and changes", () => {
  it("writes millions of dollars as trillions with three decimals from a trillion, as whole billions from a billion and as millions below", () => {
    expect(money(2873438)).toBe("$2.873 trillion");
    expect(money(1_000_000)).toBe("$1.000 trillion");
    expect(money(999_999)).toBe("$1,000 billion");
    expect(money(976044)).toBe("$976 billion");
    expect(money(653943)).toBe("$654 billion");
    expect(money(1000)).toBe("$1 billion");
    expect(money(999)).toBe("$999 million");
    expect(money(640)).toBe("$640 million");
  });
  it("writes a ratio with two decimals, as the source prints it", () => {
    expect(ratio(1.33)).toBe("1.33");
    expect(ratio(1.1)).toBe("1.10");
    expect(ratio(2)).toBe("2.00");
  });
  it("words a change with one decimal and its direction, and nothing to compare with as not available", () => {
    expect(move(5.1)).toBe("up 5.1%");
    expect(move(-0.4)).toBe("down 0.4%");
    expect(move(0)).toBe("unchanged");
    expect(move(0.04)).toBe("unchanged");
    expect(move(-0.04)).toBe("unchanged");
    expect(move(null)).toBe("not available");
    expect(move(undefined)).toBe("not available");
  });
});

describe("the sentences of the card", () => {
  it("says what the shelves held, what was sold and the months of sales, against a year earlier", () => {
    expect(headlineText(total, "September 2026")).toBe("In September 2026 US businesses held $2.873 trillion of goods at the end of the month and sold $2.163 trillion during it: 1.33 months of sales on the shelves, against 1.42 a year earlier.");
  });
  it("compares inventories and sales with a year earlier and with the month before", () => {
    expect(compareText(total)).toBe("Against a year earlier inventories are up 5.1% and sales up 12.5%; against the month before inventories are up 0.5% and sales up 1.8%.");
    expect(compareText({ ...total, inventories_change_year_pct: -2.2, sales_change_month_pct: 0, inventories_change_month_pct: null })).toBe("Against a year earlier inventories are down 2.2% and sales up 12.5%; against the month before inventories are not available and sales unchanged.");
  });
  it("says where a ratio stands among the last ten years, with two decimals and the months as a person reads them", () => {
    expect(rangeText("the total ratio", range)).toBe("Over the last 10 years (120 months) the total ratio ran from 1.26 (April 2021) to 1.74 (April 2020); 12% of those months were lower than now.");
    expect(rangeText("its ratio", { ...range, lowest: { value: 1.1, month: "2021-04" } })).toBe("Over the last 10 years (120 months) its ratio ran from 1.10 (April 2021) to 1.74 (April 2020); 12% of those months were lower than now.");
  });
  it("writes one kind of business in a line with its share of the total and the year's changes", () => {
    const wholesalers = { key: "wholesalers", label: "Merchant wholesalers", inventories_millions: 1013103, sales_millions: 840123, ratio: 1.21, share_pct: 35.3, inventories_change_year_pct: 7.6, sales_change_year_pct: 19.8, ratio_year_ago: 1.34, ratio_range: range };
    expect(sectorText(wholesalers)).toBe("Merchant wholesalers: $1.013 trillion of inventories (35.3% of the total) and $840 billion of sales: 1.21 months of sales, against 1.34 a year earlier. Against a year earlier inventories are up 7.6% and sales up 19.8%.");
  });
  it("writes a month of the total in a line", () => {
    expect(monthText({ month: "2026-08", inventories_millions: 2858902, sales_millions: 2125174, ratio: 1.35 }, "August 2026")).toBe("August 2026: inventories $2.859 trillion, sales $2.125 trillion, 1.35 months of sales");
  });
  it("says what was checked with the card's own counts and the largest gaps without trailing zeros", () => {
    const text = checkText({ months_checked: 417, first_month: "1992-01", last_month: "2026-09", largest_sum_gap: 0, largest_ratio_gap: 0.005 });
    expect(text).toContain("Check: in each of the 417 months from January 1992 to September 2026 the 12 series covered the same months");
    expect(text).toContain("the largest gap was 0 million, and 2 is allowed");
    expect(text).toContain("the largest difference was 0.005, and 0.0051 is allowed");
    expect(text).toContain("not that the figures are right");
    expect(checkText({ months_checked: 1234, first_month: "2000-01", last_month: "2026-09", largest_sum_gap: 1.5, largest_ratio_gap: 0.00482 })).toContain("1,234 months from January 2000");
    expect(checkText({ months_checked: 1234, first_month: "2000-01", last_month: "2026-09", largest_sum_gap: 1.5, largest_ratio_gap: 0.00482 })).toContain("the largest difference was 0.00482, and");
  });
});
