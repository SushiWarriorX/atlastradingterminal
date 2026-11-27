import { describe, expect, it } from "vitest";
import type { EuroStockRatesData, EuroStockRatesRow } from "../api/types";
import { cap, checkText, move, partsText, pct, points, splitText } from "./stockRates";

const row = (over: Partial<EuroStockRatesRow> = {}): EuroStockRatesRow => ({
  id: "firms", label: "loans to firms", rate_pct: 3.58, change_month_points: 0.07, change_year_points: 0.28, window: null,
  month_split: { rates_points: 0.07, mix_points: 0 }, year_split: { rates_points: 0.27, mix_points: 0.01 },
  parts: [{ id: "F", label: "up to 1 year", rate_pct: 3.94 }, { id: "I", label: "1 to 5 years", rate_pct: 4.15 }, { id: "J", label: "over 5 years", rate_pct: 3.27 }], ...over,
});
const detail = (over: Partial<NonNullable<EuroStockRatesData["detail"]>> = {}): NonNullable<EuroStockRatesData["detail"]> => ({
  months_checked: 120, identities_checked: 2390, largest_identity_gap_points: 0.01, largest_identity_gap_month: "2016-12", largest_identity_gap_series: "loans to firms", between_checked: 720, ...over,
});

describe("the euro stock-rates card's words", () => {
  it("writes a rate with two decimals and a percent sign", () => {
    expect(pct(3.58)).toBe("3.58%");
    expect(pct(3.5)).toBe("3.50%");
    expect(pct(-0.07)).toBe("-0.07%");
    expect(pct(0)).toBe("0.00%");
  });

  it("writes a figure in points with its sign and none for zero", () => {
    expect(points(0.27)).toBe("+0.27");
    expect(points(-0.01)).toBe("-0.01");
    expect(points(0)).toBe("0.00");
    expect(points(-0)).toBe("0.00");
    expect(points(0.004)).toBe("0.00");                                                                                       // a figure that rounds to zero carries no sign
    expect(points(-0.004)).toBe("0.00");
    expect(points(0.005)).toBe("+0.01");
    expect(points(-0.006)).toBe("-0.01");
  });

  it("says whether a rate rose, fell or stayed", () => {
    expect(move(0.07, "a month earlier")).toBe("up 0.07 points on a month earlier");
    expect(move(-0.12, "a year earlier")).toBe("down 0.12 points on a year earlier");
    expect(move(0, "a year earlier")).toBe("unchanged on a year earlier");
    expect(move(0.004, "a year earlier")).toBe("unchanged on a year earlier");
    expect(move(-0.004, "a month earlier")).toBe("unchanged on a month earlier");
    expect(move(-0.01, "a month earlier")).toBe("down 0.01 points on a month earlier");
    expect(cap("loans to firms")).toBe("Loans to firms");
    expect(cap("")).toBe("");
  });

  it("words the ECB's split of the year's and the month's change, and says nothing when the source gives none", () => {
    expect(splitText(row())).toBe("The ECB splits the change over the year into a rate part of +0.27 points and a weight part of +0.01, and this month's change into +0.07 and 0.00.");
    expect(splitText(row({ year_split: { rates_points: 0.06, mix_points: -0.02 }, month_split: { rates_points: 0.04, mix_points: -0.01 } })))
      .toBe("The ECB splits the change over the year into a rate part of +0.06 points and a weight part of -0.02, and this month's change into +0.04 and -0.01.");
    expect(splitText(row({ year_split: null, month_split: null }))).toBeNull();
    expect(splitText(row({ year_split: null }))).toBeNull();
    expect(splitText(row({ month_split: null }))).toBeNull();
  });

  it("lists the rate by maturity in the order given, and nothing when there are no parts", () => {
    expect(partsText(row(), "original maturity of the loan")).toBe("By original maturity of the loan: up to 1 year 3.94%, 1 to 5 years 4.15%, over 5 years 3.27%.");
    expect(partsText(row({ parts: [{ id: "L", label: "up to 2 years", rate_pct: 2.38 }, { id: "H", label: "over 2 years", rate_pct: 3 }] }), "agreed maturity")).toBe("By agreed maturity: up to 2 years 2.38%, over 2 years 3.00%.");
    expect(partsText(row({ parts: [] }), "agreed maturity")).toBeNull();
  });

  it("states the check with the card's own counts and the largest gap with its series and month, written out", () => {
    const t = checkText(detail());
    expect(t.startsWith("Check: in each of the last 120 months every rate and every component lay inside its range and no rate moved by more than 1.5 points in a month (plain checks). ")).toBe(true);
    expect(t).toContain("For the five rates the ECB splits, 2,390 comparisons of its own figures held to 0.016 points");
    expect(t).toContain("and over the whole window the rate moved as far as the accumulated change did (the largest gap: 0.01 points for loans to firms in December 2016).");
    expect(t).toContain("Each total rate also lay inside the range of its parts' rates, to 0.016 points (720 comparisons).");
    expect(t).toMatch(/not that the figures are right\./);
    expect(t).not.toMatch(/\b20\d\d-\d\d\b/);                                                                                 // no raw ISO month on screen
  });

  it("leaves the gap out when every gap was exactly zero and keeps its four decimals when it has them", () => {
    expect(checkText(detail({ largest_identity_gap_points: 0, largest_identity_gap_month: null, largest_identity_gap_series: null }))).toContain("and over the whole window the rate moved as far as the accumulated change did. Each total rate");
    expect(checkText(detail({ largest_identity_gap_points: 0, largest_identity_gap_month: null, largest_identity_gap_series: null }))).not.toContain("the largest gap");
    expect(checkText(detail({ largest_identity_gap_points: 0.0078, largest_identity_gap_month: "2024-03", largest_identity_gap_series: "households' deposits" }))).toContain("(the largest gap: 0.0078 points for households' deposits in March 2024)");
    expect(checkText(detail({ identities_checked: 123456, between_checked: 1000 }))).toContain("123,456 comparisons of its own figures");
  });
});
