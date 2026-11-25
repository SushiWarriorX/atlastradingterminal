import { describe, expect, it } from "vitest";
import type { UsBankBalanceData, UsBankBalanceItem } from "../api/types";
import { checkText, compareText, headlineText, itemText, liabilitiesText, owedText, rangeText, residualText, securitiesText, weekText } from "./usBankBalance";

type Total = NonNullable<UsBankBalanceData["total"]>;
const range = { weeks: 520, first: "2016-11-30", lowest: { value: -0.8, date: "2023-08-09" }, highest: { value: 18.6, date: "2020-04-29" }, share_lower_pct: 81 };
const total: Total = { assets_billions: 26143.8881, change_week_billions: -27.5708, change_week_pct: -0.1, change_year_billions: 1677.297, change_year_pct: 6.9, growth_range: range };
const item = (key: string, label: string, billions: number, share_pct: number, cw: number, cwp: number | null, cy: number, cyp: number | null): UsBankBalanceItem =>
  ({ key, label, billions, share_pct, change_week_billions: cw, change_week_pct: cwp, change_year_billions: cy, change_year_pct: cyp });
const assets = [
  item("loans", "Loans and leases", 14264.2085, 54.6, 38.2202, 0.3, 1033.1284, 7.8), item("securities", "Securities", 5868.9758, 22.4, 24.0599, 0.4, 203.6223, 3.6),
  item("cash", "Cash assets", 3078.6685, 11.8, -68.2578, -2.2, 119.844, 4.1), item("rest", "Everything else", 2932.0353, 11.2, -21.5931, -0.7, 320.7022, 12.3),
];
const liabilities = {
  total_billions: 23671.469, change_week_billions: -10.079, change_week_pct: 0.0, change_year_billions: 1692.0113, change_year_pct: 7.7,
  items: [item("deposits", "Deposits", 19825.171, 83.8, -37.7014, -0.2, 1300.6152, 7.0), item("other", "Everything else", 3846.298, 16.2, 27.6224, 0.7, 391.3961, 11.3)],
};
const residual = { billions: 2472.4192, share_of_assets_pct: 9.5, change_year_billions: -14.7142, change_year_pct: -0.6 };
const securities = [{ key: "treasury_agency", label: "Treasury and agency securities", billions: 4852.899, share_pct: 82.7 }, { key: "other", label: "Other securities", billions: 1016.0768, share_pct: 17.3 }];

describe("the sentences of the bank balance sheet card", () => {
  it("says what the banks held on the Wednesday and how it splits into loans, securities, cash and the rest", () => {
    expect(headlineText(total, assets, "Nov 11, 2026")).toBe("In the week ending Nov 11, 2026 US commercial banks held $26.144 trillion in assets: $14.264 trillion of loans and leases (54.6%), $5.869 trillion of securities (22.4%), $3.079 trillion of cash assets (11.8%) and $2.932 trillion of everything else (11.2%).");
  });
  it("says what they owed and what is left", () => {
    expect(owedText(liabilities, residual)).toBe("They owed $23.671 trillion: $19.825 trillion of deposits (83.8%) and $3.846 trillion of everything else (16.2%). What is left, assets less liabilities, is $2.472 trillion (9.5% of assets).");
  });
  it("compares total assets with the week before and with a year earlier", () => {
    expect(compareText(total)).toBe("Against the week before total assets are down $27.6 billion (down 0.1%); against a year earlier they are up $1.677 trillion (up 6.9%).");
    expect(compareText({ ...total, change_week_billions: 0.02, change_week_pct: 0, change_year_billions: 5, change_year_pct: null })).toBe("Against the week before total assets are unchanged (unchanged); against a year earlier they are up $5.0 billion (not available).");
  });
  it("says where the growth of total assets on a year earlier stands among the last ten years, with signs and the Wednesdays as a person reads them", () => {
    expect(rangeText(range)).toBe("Over the last 10 years (520 weeks) the growth of total assets on a year earlier ran from -0.8% (Aug 9, 2023) to +18.6% (Apr 29, 2020); 81% of those weeks were lower than now.");
  });
  it("writes one line of the asset side with its share of total assets and the two changes", () => {
    expect(itemText(assets[0], "total assets")).toBe("Loans and leases: $14.264 trillion (54.6% of total assets); on the week up $38.2 billion (up 0.3%), on a year earlier up $1.033 trillion (up 7.8%).");
    expect(itemText(assets[2], "total assets")).toBe("Cash assets: $3.079 trillion (11.8% of total assets); on the week down $68.3 billion (down 2.2%), on a year earlier up $119.8 billion (up 4.1%).");
    expect(itemText(assets[3], "total assets")).toBe("Everything else: $2.932 trillion (11.2% of total assets); on the week down $21.6 billion (down 0.7%), on a year earlier up $320.7 billion (up 12.3%).");
  });
  it("writes the liability lines with their share of total liabilities, a move that rounds to nothing in per cent as under 0.1%", () => {
    expect(itemText(liabilities.items[0], "total liabilities")).toBe("Deposits: $19.825 trillion (83.8% of total liabilities); on the week down $37.7 billion (down 0.2%), on a year earlier up $1.301 trillion (up 7.0%).");
    expect(itemText(liabilities.items[1], "total liabilities")).toBe("Everything else: $3.846 trillion (16.2% of total liabilities); on the week up $27.6 billion (up 0.7%), on a year earlier up $391.4 billion (up 11.3%).");
    expect(liabilitiesText(liabilities)).toBe("Total liabilities: $23.671 trillion; on the week down $10.1 billion (under 0.1%), on a year earlier up $1.692 trillion (up 7.7%).");
  });
  it("splits the securities into Treasury and agency securities and the others", () => {
    expect(securitiesText(securities)).toBe("Of the securities, $4.853 trillion (82.7%) are Treasury and agency securities and $1.016 trillion (17.3%) are other securities.");
  });
  it("writes the residual with its share of total assets and its change on a year earlier", () => {
    expect(residualText(residual)).toBe("Assets less liabilities (the residual): $2.472 trillion (9.5% of total assets); on a year earlier down $14.7 billion (down 0.6%).");
    expect(residualText({ ...residual, change_year_billions: 3.1, change_year_pct: 0.1 })).toContain("on a year earlier up $3.1 billion (up 0.1%).");
  });
  it("writes a week in a line with its total assets and the change on the week before", () => {
    expect(weekText({ date: "2026-10-07", total_billions: 26091.2622, change_billions: 78.1464 }, "Oct 7, 2026")).toBe("Oct 7, 2026: total assets $26.091 trillion, up $78.1 billion on the week before");
    expect(weekText({ date: "2026-10-28", total_billions: 26083.3245, change_billions: -1.25 }, "Oct 28, 2026")).toBe("Oct 28, 2026: total assets $26.083 trillion, down $1.3 billion on the week before");
  });
  it("says what was checked with the card's own counts and the largest gap without trailing zeros", () => {
    const text = checkText({ weeks_checked: 619, first_week: "2015-01-07", last_week: "2026-11-11", largest_sum_gap: 0.0001 });
    expect(text).toContain("Check: in each of the 619 weeks from Jan 7, 2015 to Nov 11, 2026 the 10 series covered the same Wednesdays");
    expect(text).toContain("the largest gap was 0.0001 billion");
    expect(text).toContain("not that the figures are right");
    expect(text).toContain("the residual is the Fed's own difference, so that last sum only shows that the weeks line up");
    expect(text).toContain("total assets never fell below bank credit plus cash assets, nor total liabilities below deposits.");
    expect(checkText({ weeks_checked: 1234, first_week: "2000-01-05", last_week: "2026-11-11", largest_sum_gap: 0 })).toContain("1,234 weeks from Jan 5, 2000");
    expect(checkText({ weeks_checked: 619, first_week: "2015-01-07", last_week: "2026-11-11", largest_sum_gap: 0.00023 })).toContain("the largest gap was 0.00023 billion");
  });
});
