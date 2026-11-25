// Words for the US jobs by industry card. Every number comes from the server (it checks the Bureau of Labor Statistics' figures and works out the changes, shares and sums); this only writes them out.
import type { UsIndustryJobsData } from "../api/types";
import { ymdLabel } from "./format";
import { move } from "./usNewHomes";

type Item = NonNullable<UsIndustryJobsData["total"]>;
type Month = NonNullable<UsIndustryJobsData["recent"]>[number];
type Detail = NonNullable<UsIndustryJobsData["detail"]>;

const list = (parts: string[]) => (parts.length < 2 ? parts.join("") : `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}`);

/** Thousands of jobs as a person reads them: 605 is "605,000", 159293 is "159,293,000". */
export const jobs = (k: number) => Math.round(k * 1000).toLocaleString("en-US");
/** A change in thousands of jobs with its direction: -3 is "down 3,000", 165 is "up 165,000", 0 is "unchanged". */
export const moveJobs = (k: number) => (k === 0 ? "unchanged" : `${k > 0 ? "up" : "down"} ${jobs(Math.abs(k))}`);

/** What each of the three big groups is called in the headline. */
const GROUP: Record<string, string> = { goods: "goods-producing industries", services: "private service-providing industries", government: "government" };

/** The headline: how many jobs were on payrolls in the month and how that splits over the three big groups (`month` is the month as a person reads it). */
export const headlineText = (total: Item, groups: Item[], month: string) =>
  `In ${month} US employers had ${jobs(total.thousands)} jobs on their payrolls: ${list(groups.map((g) => `${jobs(g.thousands)} in ${GROUP[g.key] ?? g.label.toLowerCase()}${g.share_pct == null ? "" : ` (${g.share_pct.toFixed(1)}%)`}`))}.`;

/** Total payrolls against the month before and against a year earlier. */
export const compareText = (t: Item) =>
  `Against the month before payrolls are ${moveJobs(t.change_month)} (${move(t.change_month_pct, t.change_month)}); against a year earlier they are ${moveJobs(t.change_year)} (${move(t.change_year_pct, t.change_year)}).`;

/** One line: how many jobs, their share of the whole (of all payroll jobs unless `of` says otherwise) and the two changes. */
export const itemText = (i: Item, of = "all payroll jobs") =>
  `${i.label}: ${jobs(i.thousands)}${i.share_pct == null ? "" : ` (${i.share_pct.toFixed(1)}% of ${of})`}; on the month ${moveJobs(i.change_month)} (${move(i.change_month_pct, i.change_month)}), on a year earlier ${moveJobs(i.change_year)} (${move(i.change_year_pct, i.change_year)}).`;

/** One of the last months. `label` is the month as a person reads it. */
export const monthText = (m: Month, label: string) => `${label}: ${jobs(m.thousands)} jobs, ${moveJobs(m.change)} on the month before`;

/** The sentence under the card that says what was checked, with the card's own counts (the backend rounds the gap to four decimals: no more is shown). */
export const checkText = (d: Detail) =>
  `Check: in each of the ${d.months_checked.toLocaleString("en-US")} months from ${ymdLabel(d.first_month)} to ${ymdLabel(d.last_month)} the 17 series covered the same months with none missing and every figure lay inside its range (plain checks, not the source's sums). `
  + `The Bureau's own arithmetic held to within the rounding, which shows that the series belong to one release, not that the figures are right: total payrolls equalled private plus government, private equalled goods-producing plus private service-providing, `
  + `goods-producing equalled mining, construction and manufacturing, manufacturing equalled durable plus nondurable, the seven private service industries added up to the private service total and the eleven industries added up to the total `
  + `(the largest gap in any month was ${+d.largest_sum_gap.toFixed(4)} thousand, and 1.5, 1.5, 2, 1.5, 4 and 6 are allowed for the six sums).`;
