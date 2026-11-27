import { describe, expect, it } from "vitest";
import type { UsBankLoansData } from "../api/types";
import { checkText, compareText, estateText, headlineText, kindText, level, move, moveBillions, otherText, rangeText, signedPct, weekText } from "./usBankLoans";

type Total = NonNullable<UsBankLoansData["total"]>;
const range = { weeks: 520, first: "2016-11-30", lowest: { value: -4.8, date: "2021-05-05" }, highest: { value: 12.4, date: "2022-12-07" }, share_lower_pct: 85 };
const total: Total = { loans_billions: 14264.2085, change_week_billions: 38.2202, change_week_pct: 0.3, change_year_billions: 1033.1284, change_year_pct: 7.8, growth_range: range };
const kinds = [
  { key: "business", label: "Business loans (commercial and industrial)", billions: 3018.1473, share_pct: 21.2, change_week_billions: 26.0326, change_week_pct: 0.9, change_year_billions: 319.9448, change_year_pct: 11.9 },
  { key: "real_estate", label: "Real estate loans", billions: 5859.257, share_pct: 41.1, change_week_billions: 1.9421, change_week_pct: 0.0, change_year_billions: 146.5004, change_year_pct: 2.6 },
  { key: "consumer", label: "Consumer loans", billions: 1933.9418, share_pct: 13.6, change_week_billions: -0.3062, change_week_pct: 0.0, change_year_billions: 83.6384, change_year_pct: 4.5 },
  { key: "other", label: "All other loans and leases", billions: 3452.8624, share_pct: 24.2, change_week_billions: 10.5517, change_week_pct: 0.3, change_year_billions: 483.0449, change_year_pct: 16.3 },
];

describe("amounts, changes and growth rates", () => {
  it("writes billions of dollars as trillions with three decimals from a trillion and as whole billions below", () => {
    expect(level(14264.2085)).toBe("$14.264 trillion");
    expect(level(1000)).toBe("$1.000 trillion");
    expect(level(999.6)).toBe("$1,000 billion");
    expect(level(292.308)).toBe("$292 billion");
    expect(level(124.0525)).toBe("$124 billion");
  });
  it("words a change in billions with its direction: one decimal, trillions from a trillion, and unchanged under a twentieth of a billion", () => {
    expect(moveBillions(38.2202)).toBe("up $38.2 billion");
    expect(moveBillions(-0.3062)).toBe("down $0.3 billion");
    expect(moveBillions(1033.1284)).toBe("up $1.033 trillion");
    expect(moveBillions(-1500)).toBe("down $1.500 trillion");
    expect(moveBillions(999.94)).toBe("up $999.9 billion");
    expect(moveBillions(999.95)).toBe("up $1.000 trillion");
    expect(moveBillions(0.05)).toBe("up $0.1 billion");
    expect(moveBillions(0.0024)).toBe("unchanged");
    expect(moveBillions(-0.0049)).toBe("unchanged");
    expect(moveBillions(0)).toBe("unchanged");
  });
  it("words a percentage change with one decimal and its direction, and nothing to compare with as not available", () => {
    expect(move(7.8, 1033.1)).toBe("up 7.8%");
    expect(move(-1.1, -5)).toBe("down 1.1%");
    expect(move(0.1, 0.9)).toBe("up 0.1%");
    expect(move(null, 5)).toBe("not available");
    expect(move(undefined, 5)).toBe("not available");
  });
  it("calls a percentage that rounds to nothing under 0.1% while the dollars moved, and unchanged only when they did not", () => {
    expect(move(0, 1.9)).toBe("under 0.1%");
    expect(move(0.04, 1.9)).toBe("under 0.1%");
    expect(move(-0.04, -0.3)).toBe("under 0.1%");
    expect(move(0, -0.05)).toBe("under 0.1%");
    expect(move(0, 0.0499)).toBe("unchanged");
    expect(move(0, 0)).toBe("unchanged");
    expect(move(0.04, 0.0024)).toBe("unchanged");
    expect(move(-0.04, -0.0049)).toBe("unchanged");
  });
  it("writes a growth rate with its sign and no sign for a figure that shows as zero", () => {
    expect(signedPct(12.4)).toBe("+12.4%");
    expect(signedPct(-4.8)).toBe("-4.8%");
    expect(signedPct(0)).toBe("0.0%");
    expect(signedPct(-0.04)).toBe("0.0%");
  });
});

describe("the sentences of the card", () => {
  it("says what the banks held on the Wednesday and how it splits into the four kinds", () => {
    expect(headlineText(total, kinds, "Nov 11, 2026")).toBe("In the week ending Nov 11, 2026 US commercial banks held $14.264 trillion in loans and leases: $3.018 trillion of business loans (21.2%), $5.859 trillion of real estate loans (41.1%), $1.934 trillion of consumer loans (13.6%) and $3.453 trillion of other loans (24.2%).");
  });
  it("compares the total with the week before and with a year earlier", () => {
    expect(compareText(total)).toBe("Against the week before the total is up $38.2 billion (up 0.3%); against a year earlier it is up $1.033 trillion (up 7.8%).");
    expect(compareText({ ...total, change_week_billions: -4.1, change_week_pct: -0.1, change_year_billions: 0, change_year_pct: null })).toBe("Against the week before the total is down $4.1 billion (down 0.1%); against a year earlier it is unchanged (not available).");
  });
  it("says where the growth on a year earlier stands among the last ten years, with signs and the Wednesdays as a person reads them", () => {
    expect(rangeText(range)).toBe("Over the last 10 years (520 weeks) the total's growth on a year earlier ran from -4.8% (May 5, 2021) to +12.4% (Dec 7, 2022); 85% of those weeks were lower than now.");
  });
  it("writes one kind of loan in a line with its share of the total and the two changes, and a move that rounds to nothing in per cent as under 0.1%", () => {
    expect(kindText(kinds[0])).toBe("Business loans (commercial and industrial): $3.018 trillion (21.2% of the total); on the week up $26.0 billion (up 0.9%), on a year earlier up $319.9 billion (up 11.9%).");
    expect(kindText(kinds[1])).toBe("Real estate loans: $5.859 trillion (41.1% of the total); on the week up $1.9 billion (under 0.1%), on a year earlier up $146.5 billion (up 2.6%).");
    expect(kindText(kinds[2])).toBe("Consumer loans: $1.934 trillion (13.6% of the total); on the week down $0.3 billion (under 0.1%), on a year earlier up $83.6 billion (up 4.5%).");
    expect(kindText({ ...kinds[2], change_week_billions: 0.0024, change_week_pct: 0 })).toContain("on the week unchanged (unchanged), on a year earlier");
  });
  it("writes residential and commercial real estate with their share of the real estate loans and their parts", () => {
    const residential = { key: "residential", label: "Residential real estate", billions: 2696.714, share_pct: 46.0, parts: [{ key: "closed_end", label: "Closed-end residential loans", billions: 2404.406 }, { key: "home_equity", label: "Home equity lines of credit", billions: 292.308 }] };
    const commercial = { key: "commercial", label: "Commercial real estate", billions: 3162.543, share_pct: 54.0, parts: [{ key: "nonfarm_nonresidential", label: "Office, retail and other nonfarm nonresidential", billions: 1927.0805 }, { key: "farmland", label: "Farmland", billions: 124.0525 }] };
    expect(estateText(residential)).toBe("Residential real estate: $2.697 trillion (46.0% of real estate loans): closed-end residential loans $2.404 trillion, home equity lines of credit $292 billion.");
    expect(estateText(commercial)).toBe("Commercial real estate: $3.163 trillion (54.0% of real estate loans): office, retail and other nonfarm nonresidential $1.927 trillion, farmland $124 billion.");
  });
  it("writes the loans to nondepository financial institutions inside the other loans", () => {
    expect(otherText({ nondepository_billions: 2137.4087, share_of_other_pct: 61.9 })).toBe("Of the other loans, $2.137 trillion (61.9%) are loans to nondepository financial institutions, financial companies that do not take deposits.");
  });
  it("writes a week in a line with its total and the change on the week before", () => {
    expect(weekText({ date: "2026-10-07", total_billions: 14178.7012, change_billions: 32.8958 }, "Oct 7, 2026")).toBe("Oct 7, 2026: total $14.179 trillion, up $32.9 billion on the week before");
  });
  it("says what was checked with the card's own counts and the largest gap without trailing zeros", () => {
    const text = checkText({ weeks_checked: 619, first_week: "2015-01-07", last_week: "2026-11-11", largest_sum_gap: 0.0002 });
    expect(text).toContain("Check: in each of the 619 weeks from Jan 7, 2015 to Nov 11, 2026 the 14 series covered the same Wednesdays");
    expect(text).toContain("the largest gap was 0.0002 billion");
    expect(text).toContain("not that the figures are right");
    expect(checkText({ weeks_checked: 1234, first_week: "2000-01-05", last_week: "2026-11-11", largest_sum_gap: 0 })).toContain("1,234 weeks from Jan 5, 2000");
    expect(checkText({ weeks_checked: 1234, first_week: "2000-01-05", last_week: "2026-11-11", largest_sum_gap: 0 })).toContain("the largest gap was 0 billion");
    expect(checkText({ weeks_checked: 619, first_week: "2015-01-07", last_week: "2026-11-11", largest_sum_gap: 0.00023 })).toContain("the largest gap was 0.00023 billion");
  });
});
