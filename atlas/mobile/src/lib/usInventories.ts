// Words for the US business inventories and sales card. Every number comes from the server (it checks the release's figures and works out the changes, shares and ranges); this only writes them out.
import type { JoltsRange, UsInventoriesData } from "../api/types";
import { ymdLabel } from "./format";

type Total = NonNullable<UsInventoriesData["total"]>;
type Sector = NonNullable<UsInventoriesData["sectors"]>[number];
type Month = NonNullable<UsInventoriesData["recent"]>[number];
type Detail = NonNullable<UsInventoriesData["detail"]>;

/** An amount in millions of dollars as a person reads it: 2873438 is "$2.873 trillion", 976044 is "$976 billion", 640 is "$640 million". */
export const money = (m: number) => (m >= 1_000_000 ? `$${(m / 1_000_000).toFixed(3)} trillion` : m >= 1000 ? `$${Math.round(m / 1000).toLocaleString("en-US")} billion` : `$${Math.round(m).toLocaleString("en-US")} million`);
/** A ratio as the source prints it, two decimals: "1.33". */
export const ratio = (r: number) => r.toFixed(2);
/** A change with one decimal, as the server rounds it: "up 5.1%", "down 0.4%", "unchanged"; a figure with nothing to compare with is "not available". */
export const move = (x: number | null | undefined) => (x == null ? "not available" : Number(Math.abs(x).toFixed(1)) === 0 ? "unchanged" : `${x > 0 ? "up" : "down"} ${Math.abs(x).toFixed(1)}%`);

/** The headline: what the shelves held, what was sold and how many months of sales that is, against a year earlier (`month` is the month as a person reads it). */
export const headlineText = (t: Total, month: string) =>
  `In ${month} US businesses held ${money(t.inventories_millions)} of goods at the end of the month and sold ${money(t.sales_millions)} during it: ${ratio(t.ratio)} months of sales on the shelves, against ${ratio(t.ratio_year_ago)} a year earlier.`;

/** Inventories and sales against a year earlier and against the month before. */
export const compareText = (t: Total) =>
  `Against a year earlier inventories are ${move(t.inventories_change_year_pct)} and sales ${move(t.sales_change_year_pct)}; against the month before inventories are ${move(t.inventories_change_month_pct)} and sales ${move(t.sales_change_month_pct)}.`;

/** Where a ratio stands among the last ten years (the server counts only strictly lower months). */
export const rangeText = (label: string, r: JoltsRange) =>
  `Over the last ${Math.round(r.months / 12)} years (${r.months} months) ${label} ran from ${ratio(r.lowest.value)} (${ymdLabel(r.lowest.month)}) to ${ratio(r.highest.value)} (${ymdLabel(r.highest.month)}); ${r.share_lower_pct}% of those months were lower than now.`;

/** One kind of business in a line: what it holds, what it sold, its ratio, and the year's changes. */
export const sectorText = (s: Sector) =>
  `${s.label}: ${money(s.inventories_millions)} of inventories (${s.share_pct.toFixed(1)}% of the total) and ${money(s.sales_millions)} of sales: ${ratio(s.ratio)} months of sales, against ${ratio(s.ratio_year_ago)} a year earlier. Against a year earlier inventories are ${move(s.inventories_change_year_pct)} and sales ${move(s.sales_change_year_pct)}.`;

/** One of the last months of the total. `label` is the month as a person reads it. */
export const monthText = (m: Month, label: string) => `${label}: inventories ${money(m.inventories_millions)}, sales ${money(m.sales_millions)}, ${ratio(m.ratio)} months of sales`;

/** The sentence under the card that says what was checked, with the card's own counts (the backend rounds the gaps to five decimals: no more are shown). */
export function checkText(d: Detail): string {
  return `Check: in each of the ${d.months_checked.toLocaleString("en-US")} months from ${ymdLabel(d.first_month)} to ${ymdLabel(d.last_month)} the 12 series covered the same months with none missing and every figure lay inside its range (plain checks, not the source's sums). `
    + `The release's own arithmetic held, which shows that the series belong to one release, not that the figures are right: total inventories equalled manufacturers' plus wholesalers' plus retailers' inventories and total sales equalled the sum of the three kinds' sales `
    + `(the figures are rounded to a million; the largest gap was ${+d.largest_sum_gap.toFixed(3)} million, and 2 is allowed), and each of the four published ratios matched its inventories over its sales to its two decimals `
    + `(the largest difference was ${+d.largest_ratio_gap.toFixed(5)}, and 0.0051 is allowed).`;
}
