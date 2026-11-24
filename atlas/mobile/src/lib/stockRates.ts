// Words for the euro-area stock-rates card. Every number comes from the server (it checks the ECB's figures and works out the splits); this only writes them out.
import type { EuroStockRatesData, EuroStockRatesRow } from "../api/types";
import { ymdLabel } from "./format";

export const pct = (x: number) => `${x.toFixed(2)}%`;
/** A figure in points with its sign: "+0.27", "-0.01", "0.00" (no sign for a figure that shows as zero, whatever sign the number carries). */
export const points = (x: number) => {
  const t = Math.abs(x).toFixed(2);
  return Number(t) === 0 ? "0.00" : x > 0 ? `+${t}` : `-${t}`;
};
export const move = (x: number, vs: string) => {
  const t = Math.abs(x).toFixed(2);
  return Number(t) === 0 ? `unchanged on ${vs}` : x > 0 ? `up ${t} points on ${vs}` : `down ${t} points on ${vs}`;
};
export const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

/** The ECB's split of the change over the year and over the month into a rate part and a weight part; null when the source does not publish the split for this row. */
export function splitText(r: EuroStockRatesRow): string | null {
  if (!r.year_split || !r.month_split) return null;
  return `The ECB splits the change over the year into a rate part of ${points(r.year_split.rates_points)} points and a weight part of ${points(r.year_split.mix_points)}, and this month's change into ${points(r.month_split.rates_points)} and ${points(r.month_split.mix_points)}.`;
}

/** The rate on the same loans or deposits by maturity; `what` says which kind of maturity ("original maturity of the loan", "agreed maturity"). Null when there are no parts. */
export function partsText(r: EuroStockRatesRow, what: string): string | null {
  return r.parts.length ? `By ${what}: ${r.parts.map((p) => `${p.label} ${pct(p.rate_pct)}`).join(", ")}.` : null;
}

/** The sentence under the card that says what was checked, with the card's own counts (the backend rounds the largest gap to four decimals: no more are shown). */
export function checkText(d: NonNullable<EuroStockRatesData["detail"]>): string {
  const gap = d.largest_identity_gap_month ? ` (the largest gap: ${+d.largest_identity_gap_points.toFixed(4)} points for ${d.largest_identity_gap_series} in ${ymdLabel(d.largest_identity_gap_month)})` : "";
  return `Check: in each of the last ${d.months_checked} months every rate and every component lay inside its range and no rate moved by more than 1.5 points in a month (plain checks). `
    + `For the five rates the ECB splits, ${d.identities_checked.toLocaleString("en-US")} comparisons of its own figures held to 0.016 points: the month's change in the rate equalled its rate part plus its weight part, the running totals grew by each month's parts, `
    + `the accumulated change equalled the two running totals, and over the whole window the rate moved as far as the accumulated change did${gap}. `
    + `Each total rate also lay inside the range of its parts' rates, to 0.016 points (${d.between_checked.toLocaleString("en-US")} comparisons). `
    + `These are the ECB's own arithmetic and a bound between its own series, so they show the series belong together, not that the figures are right. The parts of a change can differ from its total by a hundredth or two: every figure is rounded.`;
}
