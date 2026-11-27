import { describe, expect, it } from "vitest";
import type { UsIndustryJobsData } from "../api/types";
import { checkText, compareText, headlineText, itemText, jobs, monthText, moveJobs } from "./usIndustryJobs";

type Item = NonNullable<UsIndustryJobsData["total"]>;
const item = (key: string, label: string, thousands: number, cm: number, cmp: number | null, cy: number, cyp: number | null, share_pct?: number): Item =>
  ({ key, label, thousands, change_month: cm, change_month_pct: cmp, change_year: cy, change_year_pct: cyp, ...(share_pct == null ? {} : { share_pct }) });
const total = item("total", "Total nonfarm payrolls", 159293, 165, 0.1, 885, 0.6);
const groups = [item("goods", "Goods-producing", 21653, 15, 0.1, 201, 0.9, 13.6), item("services", "Private service-providing", 114308, 144, 0.1, 742, 0.7, 71.8), item("government", "Government", 23332, 6, 0.0, -58, -0.2, 14.6)];
const detail = { months_checked: 142, first_month: "2015-01", last_month: "2026-10", largest_sum_gap: 0 };

describe("jobs and their changes", () => {
  it("writes thousands of jobs the way a person reads them", () => {
    expect(jobs(605)).toBe("605,000");
    expect(jobs(159293)).toBe("159,293,000");
    expect(jobs(0.5)).toBe("500");
  });
  it("gives a change its direction and says unchanged for none", () => {
    expect(moveJobs(165)).toBe("up 165,000");
    expect(moveJobs(-3)).toBe("down 3,000");
    expect(moveJobs(0)).toBe("unchanged");
    expect(moveJobs(-0.5)).toBe("down 500");
  });
});

describe("the headline", () => {
  it("says what total payrolls were and how they split over the three groups, with the shares", () => {
    expect(headlineText(total, groups, "October 2026")).toBe("In October 2026 US employers had 159,293,000 jobs on their payrolls: 21,653,000 in goods-producing industries (13.6%), 114,308,000 in private service-providing industries (71.8%) and 23,332,000 in government (14.6%).");
  });
  it("falls back to the item's own label for a group it does not know, leaves out a missing share and ends with one full stop", () => {
    expect(headlineText(total, [item("other", "Other Things", 1000, 0, 0, 0, 0)], "May 2026")).toBe("In May 2026 US employers had 159,293,000 jobs on their payrolls: 1,000,000 in other things.");
    expect(headlineText(total, [groups[0], groups[1]], "May 2026")).toBe("In May 2026 US employers had 159,293,000 jobs on their payrolls: 21,653,000 in goods-producing industries (13.6%) and 114,308,000 in private service-providing industries (71.8%).");
  });
});

describe("total payrolls against the month before and a year earlier", () => {
  it("writes both changes with their direction and per cent", () => {
    expect(compareText(total)).toBe("Against the month before payrolls are up 165,000 (up 0.1%); against a year earlier they are up 885,000 (up 0.6%).");
    expect(compareText(item("total", "Total", 100000, -20, -0.0, -1500, -1.5))).toBe("Against the month before payrolls are down 20,000 (under 0.1%); against a year earlier they are down 1,500,000 (down 1.5%).");
    expect(compareText(item("total", "Total", 100000, 0, 0, 0, 0))).toBe("Against the month before payrolls are unchanged (unchanged); against a year earlier they are unchanged (unchanged).");
    expect(compareText(item("total", "Total", 100000, 5, null, 7, null))).toBe("Against the month before payrolls are up 5,000 (not available); against a year earlier they are up 7,000 (not available).");
  });
});

describe("one line", () => {
  it("writes the level, the share of all payroll jobs and the two changes", () => {
    expect(itemText(groups[0])).toBe("Goods-producing: 21,653,000 (13.6% of all payroll jobs); on the month up 15,000 (up 0.1%), on a year earlier up 201,000 (up 0.9%).");
    expect(itemText(item("construction", "Construction", 8367, -3, 0.0, 124, 1.5, 5.3))).toBe("Construction: 8,367,000 (5.3% of all payroll jobs); on the month down 3,000 (under 0.1%), on a year earlier up 124,000 (up 1.5%).");
    expect(itemText(item("information", "Information", 2734, -1, 0.0, -119, -4.2, 1.7))).toBe("Information: 2,734,000 (1.7% of all payroll jobs); on the month down 1,000 (under 0.1%), on a year earlier down 119,000 (down 4.2%).");
  });
  it("names what a share is a share of, and writes no share where there is none", () => {
    expect(itemText(item("durable", "Durable goods manufacturing", 7928, 25, 0.3, 123, 1.6, 62.5), "manufacturing")).toBe("Durable goods manufacturing: 7,928,000 (62.5% of manufacturing); on the month up 25,000 (up 0.3%), on a year earlier up 123,000 (up 1.6%).");
    expect(itemText(total)).toBe("Total nonfarm payrolls: 159,293,000; on the month up 165,000 (up 0.1%), on a year earlier up 885,000 (up 0.6%).");
  });
  it("says unchanged for no move and does not write 'up 0 (unchanged)'", () => {
    expect(itemText(item("mining", "Mining and logging", 605, 0, 0, 0, 0, 0.4))).toBe("Mining and logging: 605,000 (0.4% of all payroll jobs); on the month unchanged (unchanged), on a year earlier unchanged (unchanged).");
  });
});

describe("one of the last months", () => {
  it("writes the jobs and their change on the month before", () => {
    expect(monthText({ month: "2026-05", thousands: 158861, change: 63 }, "May 2026")).toBe("May 2026: 158,861,000 jobs, up 63,000 on the month before");
    expect(monthText({ month: "2026-07", thousands: 158882, change: -10 }, "July 2026")).toBe("July 2026: 158,882,000 jobs, down 10,000 on the month before");
    expect(monthText({ month: "2026-08", thousands: 159068, change: 0 }, "August 2026")).toBe("August 2026: 159,068,000 jobs, unchanged on the month before");
  });
});

describe("the check line", () => {
  it("states the counts it was given and keeps the gap to four decimals", () => {
    expect(checkText(detail)).toBe("Check: in each of the 142 months from January 2015 to October 2026 the 17 series covered the same months with none missing and every figure lay inside its range (plain checks, not the source's sums). "
      + "The Bureau's own arithmetic held to within the rounding, which shows that the series belong to one release, not that the figures are right: total payrolls equalled private plus government, private equalled goods-producing plus private service-providing, "
      + "goods-producing equalled mining, construction and manufacturing, manufacturing equalled durable plus nondurable, the seven private service industries added up to the private service total and the eleven industries added up to the total "
      + "(the largest gap in any month was 0 thousand, and 1.5, 1.5, 2, 1.5, 4 and 6 are allowed for the six sums).");
    const t = checkText({ ...detail, months_checked: 1234, largest_sum_gap: 1.23456 });
    expect(t).toContain("each of the 1,234 months");
    expect(t).toContain("the largest gap in any month was 1.2346 thousand");
  });
  it("says the checks do not show that the figures are right", () => {
    expect(checkText(detail)).toContain("not that the figures are right");
    expect(checkText(detail).startsWith("Check:")).toBe(true);
  });
});
