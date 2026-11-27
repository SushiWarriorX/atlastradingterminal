// Words for the US hires, quits and layoffs card. Every number comes from the server (it checks the survey's figures and works out the changes and the nets); this only writes them out.
import type { JoltsFlowsData, JoltsRange } from "../api/types";
import { ymdLabel } from "./format";

type Total = NonNullable<JoltsFlowsData["total"]>;
type Sector = NonNullable<JoltsFlowsData["sectors"]>[number];
type Industry = NonNullable<JoltsFlowsData["industries"]>[number];
type Month = NonNullable<JoltsFlowsData["recent"]>[number];
type Detail = NonNullable<JoltsFlowsData["detail"]>;

/** A count in thousands as a person reads it: 5402 is "5.402 million", 324 is "324 thousand". */
export const amount = (k: number) => (k >= 1000 ? `${(k / 1000).toFixed(3)} million` : `${Math.round(k).toLocaleString("en-US")} thousand`);
/** A change on a year ago with one decimal, as the server rounds it: "up 3.1%", "down 0.4%", "unchanged"; a figure with nothing to compare with is "not available". */
export const move = (x: number | null | undefined) => (x == null ? "not available" : Number(Math.abs(x).toFixed(1)) === 0 ? "unchanged" : `${x > 0 ? "up" : "down"} ${Math.abs(x).toFixed(1)}%`);
/** What hires minus separations comes to, in words: "83 thousand more hires than separations", "28 thousand fewer hires than separations", "as many hires as separations". */
export const netText = (k: number) => (k === 0 ? "as many hires as separations" : `${amount(Math.abs(k))} ${k > 0 ? "more" : "fewer"} hires than separations`);
const share = (x: number | null) => (x == null ? "" : ` (${x.toFixed(1)}%)`);

/** The headline: how many were hired, how many left and in which of three ways, and the difference (`month` is the month as a person reads it). */
export const headlineText = (t: Total, month: string) =>
  `In ${month} US employers hired ${amount(t.hires_thousands)} people and ${amount(t.separations_thousands)} left their jobs: ${amount(t.quits_thousands)} quit, ${amount(t.layoffs_thousands)} were laid off or discharged and ${amount(t.other_thousands)} left for other reasons. Net, that is ${netText(t.net_thousands)}.`;

/** The four headline flows against a year earlier, and how much of the leaving was quitting. */
export const compareText = (t: Total) =>
  `Against a year earlier hires are ${move(t.hires_change_year_pct)}, quits ${move(t.quits_change_year_pct)}, layoffs and discharges ${move(t.layoffs_change_year_pct)} and total separations ${move(t.separations_change_year_pct)}.${t.quits_share_pct == null ? "" : ` Quits were ${t.quits_share_pct.toFixed(1)}% of all separations.`}`;

/** Where one flow stands among the last ten years (the server counts only strictly lower months). */
export const rangeText = (label: string, r: JoltsRange) =>
  `Over the last ${Math.round(r.months / 12)} years (${r.months} months) ${label} ran from ${amount(r.lowest.value)} (${ymdLabel(r.lowest.month)}) to ${amount(r.highest.value)} (${ymdLabel(r.highest.month)}); ${r.share_lower_pct}% of those months were lower than now.`;

/** The private sector or government in one line: hires, the three ways of leaving, the net and the year's change in hires and quits. */
export const sectorText = (s: Sector) =>
  `${s.label}: hired ${amount(s.hires_thousands)}; ${amount(s.separations_thousands)} left (${amount(s.quits_thousands)} quit, ${amount(s.layoffs_thousands)} laid off or discharged, ${amount(s.other_thousands)} other), ${netText(s.net_thousands)}. Against a year earlier hires are ${move(s.hires_change_year_pct)} and quits ${move(s.quits_change_year_pct)}.`;

/** One industry in a line; by industry the source has hires, quits and total separations only, so "left" is the total and "by quitting" the part of it that quit. */
export const industryText = (r: Industry) =>
  `${r.label}${r.derived ? ", by subtraction" : ""}: hired ${amount(r.hires_thousands)}; ${amount(r.separations_thousands)} left, ${amount(r.quits_thousands)} of them by quitting${share(r.quits_share_pct)}: ${netText(r.net_thousands)}. Against a year earlier hires are ${move(r.hires_change_year_pct)} and quits ${move(r.quits_change_year_pct)}.`;

/** One of the last months of the nonfarm total. `label` is the month as a person reads it. */
export const monthText = (m: Month, label: string) =>
  `${label}: hired ${amount(m.hires_thousands)}, ${amount(m.quits_thousands)} quit, ${amount(m.layoffs_thousands)} laid off or discharged, ${amount(m.separations_thousands)} left in all: ${netText(m.net_thousands)}`;

/** The sentence under the card that says what was checked, with the card's own counts (the backend rounds the largest gap to three decimals: no more are shown). */
export function checkText(d: Detail): string {
  return `Check: in each of the ${d.months_checked.toLocaleString("en-US")} months from ${ymdLabel(d.first_month)} to ${ymdLabel(d.last_month)} the 33 series covered the same months with none missing and every figure lay inside its range (plain checks, not the source's sums). `
    + `The survey's own arithmetic held, which shows that the series belong to one release, not that the figures are right: total nonfarm equalled private plus government for hires, quits, layoffs, other separations and total separations, and in each of the three totals separations equalled quits plus layoffs plus other `
    + `(the figures are each rounded to a thousand; the largest gap was ${+d.largest_sum_gap.toFixed(3)} thousand, and 1.5 and 2 are allowed). In each of the six industries the quits were never more than the separations (the closest margin was ${+d.closest_part_margin.toFixed(3)} thousand), `
    + `and what is left of private after the six industries was at least ${+d.smallest_rest_of_private.toFixed(3)} thousand in hires, in quits and in separations.`;
}
