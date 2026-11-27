import { describe, expect, it } from "vitest";
import type { JoltsFlowsData } from "../api/types";
import { amount, checkText, compareText, headlineText, industryText, monthText, move, netText, rangeText, sectorText } from "./joltsFlows";

type Total = NonNullable<JoltsFlowsData["total"]>;
const range = { months: 120, first: "2016-10", lowest: { value: 1555, month: "2020-04" }, highest: { value: 4499, month: "2022-04" }, share_lower_pct: 87 };
const total: Total = { hires_thousands: 5402, quits_thousands: 3365, layoffs_thousands: 1641, other_thousands: 313, separations_thousands: 5319, net_thousands: 83, quits_share_pct: 63.3,
  hires_change_year_pct: 3.1, quits_change_year_pct: -2.0, layoffs_change_year_pct: 0, separations_change_year_pct: 1.5, hires_range: range, quits_range: range, layoffs_range: range };

describe("amounts and changes", () => {
  it("writes a count in thousands as thousands below a million and as millions with three decimals from a million", () => {
    expect(amount(5402)).toBe("5.402 million");
    expect(amount(1000)).toBe("1.000 million");
    expect(amount(999)).toBe("999 thousand");
    expect(amount(33)).toBe("33 thousand");
    expect(amount(1234.4)).toBe("1.234 million");
  });
  it("words a change with one decimal and its direction, and nothing to compare with as not available", () => {
    expect(move(3.1)).toBe("up 3.1%");
    expect(move(-0.4)).toBe("down 0.4%");
    expect(move(0)).toBe("unchanged");
    expect(move(0.04)).toBe("unchanged");
    expect(move(null)).toBe("not available");
    expect(move(undefined)).toBe("not available");
  });
  it("words the net of a month as more or fewer hires than separations, or as many", () => {
    expect(netText(83)).toBe("83 thousand more hires than separations");
    expect(netText(-28)).toBe("28 thousand fewer hires than separations");
    expect(netText(0)).toBe("as many hires as separations");
    expect(netText(-1500)).toBe("1.500 million fewer hires than separations");
  });
});

describe("the sentences", () => {
  it("writes the headline with the hires, the separations and the three ways of leaving", () => {
    expect(headlineText(total, "Sep 2026")).toBe("In Sep 2026 US employers hired 5.402 million people and 5.319 million left their jobs: 3.365 million quit, 1.641 million were laid off or discharged and 313 thousand left for other reasons. Net, that is 83 thousand more hires than separations.");
  });
  it("compares the four flows with a year earlier and says how much of the leaving was quitting", () => {
    expect(compareText(total)).toBe("Against a year earlier hires are up 3.1%, quits down 2.0%, layoffs and discharges unchanged and total separations up 1.5%. Quits were 63.3% of all separations.");
    expect(compareText({ ...total, quits_share_pct: null })).toBe("Against a year earlier hires are up 3.1%, quits down 2.0%, layoffs and discharges unchanged and total separations up 1.5%.");
  });
  it("writes where a flow stands among the last ten years", () => {
    expect(rangeText("quits", range)).toBe("Over the last 10 years (120 months) quits ran from 1.555 million (April 2020) to 4.499 million (April 2022); 87% of those months were lower than now.");
  });
  it("writes a sector with its three ways of leaving, the net and the year's change in hires and quits", () => {
    const s = { key: "government", label: "Government", hires_thousands: 324, quits_thousands: 178, layoffs_thousands: 82, other_thousands: 62, separations_thousands: 322, net_thousands: 2, quits_share_pct: 55.3, hires_change_year_pct: -1.2, quits_change_year_pct: 4.5 };
    expect(sectorText(s)).toBe("Government: hired 324 thousand; 322 thousand left (178 thousand quit, 82 thousand laid off or discharged, 62 thousand other), 2 thousand more hires than separations. Against a year earlier hires are down 1.2% and quits up 4.5%.");
  });
  it("writes an industry with the share of its leaving that was quitting, and marks a figure worked out by subtraction", () => {
    const r = { key: "construction", label: "Construction", derived: false, hires_thousands: 356, quits_thousands: 198, separations_thousands: 359, net_thousands: -3, quits_share_pct: 55.2, hires_change_year_pct: 0.3, quits_change_year_pct: null };
    expect(industryText(r)).toBe("Construction: hired 356 thousand; 359 thousand left, 198 thousand of them by quitting (55.2%): 3 thousand fewer hires than separations. Against a year earlier hires are up 0.3% and quits not available.");
    expect(industryText({ ...r, label: "Everything else", derived: true, quits_share_pct: null })).toBe("Everything else, by subtraction: hired 356 thousand; 359 thousand left, 198 thousand of them by quitting: 3 thousand fewer hires than separations. Against a year earlier hires are up 0.3% and quits not available.");
  });
  it("writes one of the last months", () => {
    expect(monthText({ month: "2026-08", hires_thousands: 5300, quits_thousands: 3300, layoffs_thousands: 1700, separations_thousands: 5350, net_thousands: -50 }, "Aug 2026")).toBe("Aug 2026: hired 5.300 million, 3.300 million quit, 1.700 million laid off or discharged, 5.350 million left in all: 50 thousand fewer hires than separations");
  });
  it("writes the check with the counts of the card and no more than three decimals of the gap", () => {
    const t = checkText({ months_checked: 310, first_month: "2000-12", last_month: "2026-09", largest_sum_gap: 1, closest_part_margin: 102, smallest_rest_of_private: 154 });
    expect(t).toMatch(/^Check: in each of the 310 months from December 2000 to September 2026 the 33 series covered the same months with none missing and every figure lay inside its range \(plain checks, not the source's sums\)\. /);
    expect(t).toContain("not that the figures are right");
    expect(t).toContain("the largest gap was 1 thousand, and 1.5 and 2 are allowed");
    expect(t).toContain("the closest margin was 102 thousand");
    expect(t).toContain("at least 154 thousand in hires, in quits and in separations");
    expect(checkText({ months_checked: 1234, first_month: "2000-12", last_month: "2026-09", largest_sum_gap: 1.23456, closest_part_margin: 2, smallest_rest_of_private: 3 })).toContain("the largest gap was 1.235 thousand");
    expect(checkText({ months_checked: 1234, first_month: "2000-12", last_month: "2026-09", largest_sum_gap: 1, closest_part_margin: 2, smallest_rest_of_private: 3 })).toContain("in each of the 1,234 months");
  });
});
