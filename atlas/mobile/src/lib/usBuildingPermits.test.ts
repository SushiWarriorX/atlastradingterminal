import { describe, expect, it } from "vitest";
import type { UsBuildingPermitsData } from "../api/types";
import { checkText, compareText, headlineText, homes, itemText, monthText, move, moveThousands, rangeText, signedPct } from "./usBuildingPermits";

type Total = NonNullable<UsBuildingPermitsData["total"]>;
const range = { months: 120, first: "2016-11", lowest: { value: -26.3, month: "2023-01" }, highest: { value: 58.5, month: "2021-04" }, share_lower_pct: 10 };
const total: Total = { thousands: 1295, change_month_thousands: -103, change_month_pct: -7.4, change_year_thousands: -123, change_year_pct: -8.7, growth_range: range };
const item = (key: string, label: string, thousands: number, share_pct: number, cm: number, cmp: number | null, cy: number, cyp: number | null) =>
  ({ key, label, thousands, share_pct, change_month_thousands: cm, change_month_pct: cmp, change_year_thousands: cy, change_year_pct: cyp });
const types = [item("single_family", "Single-family homes", 772, 59.6, -74, -8.7, -114, -12.9), item("two_to_four", "Homes in buildings of 2 to 4 units", 48, 3.7, -3, -5.9, -7, -12.7), item("five_or_more", "Homes in buildings of 5 or more units", 475, 36.7, -26, -5.2, -2, -0.4)];
const midwest = item("midwest", "Midwest", 213, 16.4, 1, 0.5, 16, 8.1);

describe("amounts, changes and growth rates", () => {
  it("writes thousands of homes as millions with three decimals from a thousand thousand and as whole thousands below", () => {
    expect(homes(1295)).toBe("1.295 million");
    expect(homes(1000)).toBe("1.000 million");
    expect(homes(999)).toBe("999 thousand");
    expect(homes(772)).toBe("772 thousand");
    expect(homes(48)).toBe("48 thousand");
    expect(homes(119.5)).toBe("120 thousand");
  });
  it("words a change in thousands with its direction: millions with three decimals from a million, thousands below, and unchanged under half a thousand", () => {
    expect(moveThousands(-103)).toBe("down 103 thousand");
    expect(moveThousands(59)).toBe("up 59 thousand");
    expect(moveThousands(1200)).toBe("up 1.200 million");
    expect(moveThousands(-1200)).toBe("down 1.200 million");
    expect(moveThousands(999.5)).toBe("up 1.000 million");
    expect(moveThousands(999.4)).toBe("up 999 thousand");
    expect(moveThousands(0.5)).toBe("up 1 thousand");
    expect(moveThousands(0.49)).toBe("unchanged");
    expect(moveThousands(-0.49)).toBe("unchanged");
    expect(moveThousands(0)).toBe("unchanged");
  });
  it("words a percentage change with one decimal and its direction, and nothing to compare with as not available", () => {
    expect(move(-7.4, -103)).toBe("down 7.4%");
    expect(move(58.5, 800)).toBe("up 58.5%");
    expect(move(0.1, 3)).toBe("up 0.1%");
    expect(move(null, 5)).toBe("not available");
    expect(move(undefined, 0)).toBe("not available");
  });
  it("calls a percentage that rounds to nothing under 0.1% while the homes moved, and unchanged only when they did not", () => {
    expect(move(0, 3)).toBe("under 0.1%");
    expect(move(-0, -2)).toBe("under 0.1%");
    expect(move(0.04, 0.5)).toBe("under 0.1%");
    expect(move(-0.04, -0.5)).toBe("under 0.1%");
    expect(move(0, 0.49)).toBe("unchanged");
    expect(move(0, 0)).toBe("unchanged");
    expect(move(0.04, 0.2)).toBe("unchanged");
  });
  it("writes a growth rate with its sign and no sign for a figure that shows as zero", () => {
    expect(signedPct(58.5)).toBe("+58.5%");
    expect(signedPct(-26.3)).toBe("-26.3%");
    expect(signedPct(0)).toBe("0.0%");
    expect(signedPct(0.04)).toBe("0.0%");
    expect(signedPct(-0.04)).toBe("0.0%");
  });
});

describe("the sentences of the card", () => {
  it("says how many homes were given permission in the month and how they split by type", () => {
    expect(headlineText(total, types, "October 2026")).toBe("In October 2026 local governments in the US gave permission to build 1.295 million homes at a seasonally adjusted annual rate: 772 thousand single-family homes (59.6%), 48 thousand homes in buildings of 2 to 4 units (3.7%) and 475 thousand homes in buildings of 5 or more units (36.7%).");
    expect(headlineText(total, types.slice(0, 1), "October 2026")).toContain("rate: 772 thousand single-family homes (59.6%).");
  });
  it("compares the total with the month before and with a year earlier", () => {
    expect(compareText(total)).toBe("Against the month before permits are down 103 thousand (down 7.4%); against a year earlier they are down 123 thousand (down 8.7%).");
    expect(compareText({ ...total, change_month_thousands: 59, change_month_pct: 4.3, change_year_thousands: 0, change_year_pct: null })).toBe("Against the month before permits are up 59 thousand (up 4.3%); against a year earlier they are unchanged (not available).");
    expect(compareText({ ...total, change_month_thousands: 3, change_month_pct: 0.0, change_year_thousands: 0.2, change_year_pct: 0.0 })).toBe("Against the month before permits are up 3 thousand (under 0.1%); against a year earlier they are unchanged (unchanged).");
  });
  it("says where the growth on a year earlier stands among the last ten years, with signs and the months as a person reads them", () => {
    expect(rangeText(range)).toBe("Over the last 10 years (120 months) the growth of permits on a year earlier ran from -26.3% (January 2023) to +58.5% (April 2021); 10% of those months were lower than now.");
    expect(rangeText({ ...range, lowest: { value: 0.2, month: "2025-02" } })).toContain("ran from +0.2% (February 2025)");
  });
  it("writes one type or region in a line with its share of all permits and the two changes", () => {
    expect(itemText(types[0])).toBe("Single-family homes: 772 thousand (59.6% of all permits); on the month down 74 thousand (down 8.7%), on a year earlier down 114 thousand (down 12.9%).");
    expect(itemText(midwest)).toBe("Midwest: 213 thousand (16.4% of all permits); on the month up 1 thousand (up 0.5%), on a year earlier up 16 thousand (up 8.1%).");
    expect(itemText({ ...midwest, change_month_thousands: 0, change_month_pct: 0, change_year_thousands: 4, change_year_pct: 0 })).toContain("on the month unchanged (unchanged), on a year earlier up 4 thousand (under 0.1%).");
  });
  it("writes a month in a line with the homes and the change on the month before", () => {
    expect(monthText({ month: "2026-07", thousands: 1433, change_thousands: 59 }, "July 2026")).toBe("July 2026: 1.433 million homes, up 59 thousand on the month before");
    expect(monthText({ month: "2026-06", thousands: 1374, change_thousands: -36 }, "June 2026")).toBe("June 2026: 1.374 million homes, down 36 thousand on the month before");
  });
  it("says what was checked with the card's own counts and the largest gap without trailing zeros", () => {
    const text = checkText({ months_checked: 142, first_month: "2015-01", last_month: "2026-10", largest_sum_gap: 0 });
    expect(text).toContain("Check: in each of the 142 months from January 2015 to October 2026 the 8 series covered the same months");
    expect(text).toContain("the largest gap was 0 thousand, and 2 and 2.5 are allowed");
    expect(text).toContain("not that the figures are right");
    expect(text).toContain("equalled single-family plus 2-4 unit plus 5+ unit permits, and equalled the four regions added up");
    expect(checkText({ months_checked: 1234, first_month: "2000-01", last_month: "2026-10", largest_sum_gap: 0 })).toContain("1,234 months from January 2000");
    expect(checkText({ months_checked: 142, first_month: "2015-01", last_month: "2026-10", largest_sum_gap: 1.5 })).toContain("the largest gap was 1.5 thousand");
    expect(checkText({ months_checked: 142, first_month: "2015-01", last_month: "2026-10", largest_sum_gap: 0.0123 })).toContain("the largest gap was 0.0123 thousand");
  });
});
