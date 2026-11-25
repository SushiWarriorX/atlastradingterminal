import { describe, expect, it } from "vitest";
import type { UsNewHomesData } from "../api/types";
import { checkText, compareText, dollars, headlineText, houses, itemText, monthText, move, moveDollars, moveHouses, moveMonths, priceRangeText, pricesText, rangeText, signedPct, stockText, supplyRangeText } from "./usNewHomes";

type Sales = NonNullable<UsNewHomesData["sales"]>;
const range = { months: 120, first: "2016-10", lowest: { value: -33.2, month: "2021-10" }, highest: { value: 51.4, month: "2020-07" }, share_lower_pct: 29 };
const sales: Sales = { thousands: 676, change_month: -4, change_month_pct: -0.6, change_year: -38, change_year_pct: -5.3, growth_range: range };
const item = (key: string, label: string, thousands: number, share_pct: number, cm: number, cmp: number | null, cy: number, cyp: number | null) =>
  ({ key, label, thousands, share_pct, change_month: cm, change_month_pct: cmp, change_year: cy, change_year_pct: cyp });
const regions = [item("northeast", "Northeast", 32, 4.7, 7, 28.0, 3, 10.3), item("midwest", "Midwest", 89, 13.2, -7, -7.3, -8, -8.2), item("south", "South", 413, 61.1, -29, -6.6, -3, -0.7), item("west", "West", 142, 21.0, 25, 21.4, -30, -17.4)];
const stock = { for_sale: 476, for_sale_change_month: -5, for_sale_change_year: -11, months_supply: 8.4, supply_change_month: -0.1, supply_change_year: 0.2,
  supply_range: { months: 120, first: "2016-10", lowest: { value: 3.3, month: "2020-10" }, highest: { value: 10.3, month: "2022-07" }, share_lower_pct: 73 } };
const prices = { median: 400400, median_change_year: -16400, median_change_year_pct: -3.9, average: 472800, average_change_year: -34000, average_change_year_pct: -6.7,
  median_range: { months: 120, first: "2016-10", lowest: { value: 298000, month: "2017-02" }, highest: { value: 460300, month: "2022-10" }, share_lower_pct: 53 } };

describe("houses, dollars, changes and growth rates", () => {
  it("writes thousands of houses as whole houses with thousands separators", () => {
    expect(houses(676)).toBe("676,000");
    expect(houses(1031)).toBe("1,031,000");
    expect(houses(32)).toBe("32,000");
    expect(houses(117.375)).toBe("117,375");
    expect(houses(0.4)).toBe("400");
    expect(houses(0)).toBe("0");
  });
  it("words a change in thousands of houses with its direction and unchanged only for nothing", () => {
    expect(moveHouses(-4)).toBe("down 4,000");
    expect(moveHouses(38)).toBe("up 38,000");
    expect(moveHouses(0)).toBe("unchanged");
    expect(moveHouses(0.4)).toBe("up 400");
    expect(moveHouses(-0.4)).toBe("down 400");
    expect(moveHouses(1031)).toBe("up 1,031,000");
  });
  it("words a change in months of supply with one decimal and its direction", () => {
    expect(moveMonths(-0.1)).toBe("down 0.1");
    expect(moveMonths(0.2)).toBe("up 0.2");
    expect(moveMonths(0.5)).toBe("up 0.5");
    expect(moveMonths(-2)).toBe("down 2.0");
    expect(moveMonths(0)).toBe("unchanged");
  });
  it("writes dollars with a sign of currency and thousands separators and a change in dollars with its direction", () => {
    expect(dollars(400400)).toBe("$400,400");
    expect(dollars(1234567.4)).toBe("$1,234,567");
    expect(dollars(1234567.6)).toBe("$1,234,568");
    expect(moveDollars(-16400)).toBe("down $16,400");
    expect(moveDollars(12000)).toBe("up $12,000");
    expect(moveDollars(0)).toBe("unchanged");
  });
  it("words a percentage change with one decimal and its direction, and nothing to compare with as not available", () => {
    expect(move(-0.6, -4)).toBe("down 0.6%");
    expect(move(28.0, 7)).toBe("up 28.0%");
    expect(move(0.1, 3)).toBe("up 0.1%");
    expect(move(null, 5)).toBe("not available");
    expect(move(undefined, 0)).toBe("not available");
  });
  it("calls a percentage that rounds to nothing under 0.1% while the amount moved, and unchanged only when it did not", () => {
    expect(move(0, 3)).toBe("under 0.1%");
    expect(move(-0, -1)).toBe("under 0.1%");
    expect(move(0.04, 0.6)).toBe("under 0.1%");
    expect(move(-0.04, -0.6)).toBe("under 0.1%");
    expect(move(0, 0)).toBe("unchanged");
    expect(move(0.04, 0)).toBe("unchanged");
  });
  it("writes a growth rate with its sign and no sign for a figure that shows as zero", () => {
    expect(signedPct(51.4)).toBe("+51.4%");
    expect(signedPct(-33.2)).toBe("-33.2%");
    expect(signedPct(0)).toBe("0.0%");
    expect(signedPct(0.04)).toBe("0.0%");
    expect(signedPct(-0.04)).toBe("0.0%");
  });
});

describe("the sentences of the card", () => {
  it("writes the headline with the four regions and their shares", () => {
    expect(headlineText(sales, regions, "September 2026")).toBe(
      "In September 2026 new houses were being sold at a seasonally adjusted annual rate of 676,000: 32,000 in the Northeast (4.7%), 89,000 in the Midwest (13.2%), 413,000 in the South (61.1%) and 142,000 in the West (21.0%).");
  });
  it("compares sales with the month before and a year earlier, each change with its own percentage", () => {
    expect(compareText(sales)).toBe("Against the month before sales are down 4,000 (down 0.6%); against a year earlier they are down 38,000 (down 5.3%).");
    expect(compareText({ ...sales, change_month: 0, change_month_pct: 0, change_year: 12, change_year_pct: 0 })).toBe("Against the month before sales are unchanged (unchanged); against a year earlier they are up 12,000 (under 0.1%).");
  });
  it("says where the growth of sales stands among the last ten years", () => {
    expect(rangeText(range)).toBe("Over the last 10 years (120 months) the growth of sales on a year earlier ran from -33.2% (October 2021) to +51.4% (July 2020); 29% of those months were lower than now.");
  });
  it("writes one region in a line with its share and both changes", () => {
    expect(itemText(regions[0])).toBe("Northeast: 32,000 (4.7% of all sales); on the month up 7,000 (up 28.0%), on a year earlier up 3,000 (up 10.3%).");
    expect(itemText(regions[2])).toBe("South: 413,000 (61.1% of all sales); on the month down 29,000 (down 6.6%), on a year earlier down 3,000 (down 0.7%).");
    expect(itemText(item("west", "West", 142, 21.0, 0, 0, 5, null))).toBe("West: 142,000 (21.0% of all sales); on the month unchanged (unchanged), on a year earlier up 5,000 (not available).");
  });
  it("writes the houses for sale and the months' supply with their changes", () => {
    expect(stockText(stock)).toBe("For sale at the end of the month: 476,000 new houses (down 5,000 on the month, down 11,000 on a year earlier). That is 8.4 months' supply at the pace of sales (down 0.1 on the month, up 0.2 on a year earlier).");
    expect(stockText({ ...stock, for_sale_change_month: 0, supply_change_month: 0 })).toContain("(unchanged on the month, down 11,000 on a year earlier)");
    expect(stockText({ ...stock, supply_change_month: 0 })).toContain("(unchanged on the month, up 0.2 on a year earlier)");
  });
  it("says where the months' supply and the median price stand among the last ten years", () => {
    expect(supplyRangeText(stock.supply_range)).toBe("Over the last 10 years (120 months) the months' supply ran from 3.3 (October 2020) to 10.3 (July 2022); 73% of those months were lower than now.");
    expect(priceRangeText(prices.median_range)).toBe("Over the last 10 years (120 months) the median price ran from $298,000 (February 2017) to $460,300 (October 2022); 53% of those months were lower than now.");
  });
  it("writes both prices against a year earlier and never against the month before", () => {
    expect(pricesText(prices)).toBe("The median price of a new house sold was $400,400 (down $16,400, down 3.9%, on a year earlier) and the average price $472,800 (down $34,000, down 6.7%, on a year earlier).");
    expect(pricesText({ ...prices, median_change_year: 0, median_change_year_pct: 0 })).toContain("(unchanged, unchanged, on a year earlier)");
  });
  it("writes one of the last months with its change and its months' supply", () => {
    expect(monthText({ month: "2026-09", thousands: 676, change: -4, months_supply: 8.4 }, "September 2026")).toBe("September 2026: 676,000, down 4,000 on the month before, with 8.4 months' supply");
    expect(monthText({ month: "2026-06", thousands: 680, change: 44, months_supply: 8.5 }, "June 2026")).toBe("June 2026: 680,000, up 44,000 on the month before, with 8.5 months' supply");
  });
  it("writes the check line with the card's own counts and says it does not prove the figures", () => {
    expect(checkText({ months_checked: 141, first_month: "2015-01", last_month: "2026-09", largest_sum_gap: 0, largest_supply_gap: 0.05, smallest_price_gap: 33800 })).toBe(
      "Check: in each of the 141 months from January 2015 to September 2026 the 9 series covered the same months with none missing and every figure lay inside its range (plain checks, not the source's sums). "
      + "The Census Bureau's own arithmetic held to within the rounding, which shows that the series belong to one release, not that the figures are right: the four regions added up to the sales total (the largest gap was 0 thousand, and 2.5 is allowed), "
      + "the months' supply agreed with 12 times the houses for sale divided by the sales rate (the largest gap was 0.05 of a month, and 0.1 is allowed), and the average price was never below the median price (the smallest gap was $33,800).");
    const c = checkText({ months_checked: 1234, first_month: "2015-02", last_month: "2026-09", largest_sum_gap: 2.5, largest_supply_gap: 0.0001, smallest_price_gap: 0 });
    expect(c).toContain("each of the 1,234 months from February 2015");
    expect(c).toContain("(the largest gap was 2.5 thousand, and 2.5 is allowed)");
    expect(c).toContain("(the largest gap was 0.0001 of a month, and 0.1 is allowed)");
    expect(c).toContain("(the smallest gap was $0)");
  });
});
