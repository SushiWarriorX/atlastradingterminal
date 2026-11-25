// Words for the US construction spending card. Every number comes from the server (it checks the Census Bureau's figures and works out the changes, shares and ranges); this only writes them out.
import type { JoltsRange, UsConstructionData } from "../api/types";
import { ymdLabel } from "./format";

type Total = NonNullable<UsConstructionData["total"]>;
type Item = NonNullable<UsConstructionData["owners"]>[number];
type Month = NonNullable<UsConstructionData["recent"]>[number];
type Detail = NonNullable<UsConstructionData["detail"]>;

/** Millions of dollars as a person reads them: 2186145 is "$2.186 trillion", 861192 is "$861.2 billion", 12415 is "$12.4 billion". */
export const money = (m: number) => (m >= 999_950 ? `$${(m / 1_000_000).toFixed(3)} trillion` : `$${(m / 1000).toFixed(1)} billion`);
/** A change in millions of dollars with its direction: -41229 is "down $41.2 billion", 43348 is "up $43.3 billion", and under $0.05 billion is "unchanged". */
export const moveMillions = (m: number) => {
  const b = Math.round(Math.abs(m) / 100) / 10;                          // billions to one decimal
  if (b === 0) return "unchanged";
  return `${m > 0 ? "up" : "down"} ${b >= 1000 ? `$${(b / 1000).toFixed(3)} trillion` : `$${b.toFixed(1)} billion`}`;
};
/** A change in per cent that goes with a change in millions of dollars, one decimal as the server rounds it: "up 3.0%", "down 1.1%". A change that rounds to nothing while the dollars did move is "under 0.1%" (so a line never reads "up $0.3 billion (unchanged)"), and "unchanged" only when the dollars read unchanged too; a figure with nothing to compare with is "not available". */
export const move = (x: number | null | undefined, millions: number) =>
  x == null ? "not available" : Number(Math.abs(x).toFixed(1)) !== 0 ? `${x > 0 ? "up" : "down"} ${Math.abs(x).toFixed(1)}%` : moveMillions(millions) === "unchanged" ? "unchanged" : "under 0.1%";
/** A growth rate with its sign and one decimal: "+18.5%", "-4.2%"; a figure that shows as zero has no sign. */
export const signedPct = (x: number) => (Number(Math.abs(x).toFixed(1)) === 0 ? "0.0%" : `${x > 0 ? "+" : "-"}${Math.abs(x).toFixed(1)}%`);

const list = (parts: string[]) => (parts.length < 2 ? parts.join("") : `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}`);

/** The headline: how much construction work was done in the month and how it splits between private and public owners (`month` is the month as a person reads it). */
export const headlineText = (t: Total, owners: Item[], month: string) =>
  `In ${month} construction work in the US was done at a seasonally adjusted annual rate of ${money(t.millions)}: ${list(owners.map((i) => `${money(i.millions)} ${i.label.toLowerCase()} (${i.share_pct.toFixed(1)}%)`))}.`;

/** The total against the month before and against a year earlier. */
export const compareText = (t: Total) =>
  `Against the month before spending is ${moveMillions(t.change_month_millions)} (${move(t.change_month_pct, t.change_month_millions)}); against a year earlier it is ${moveMillions(t.change_year_millions)} (${move(t.change_year_pct, t.change_year_millions)}).`;

/** Where the total's growth on a year earlier stands among the last ten years (the server counts only strictly lower months). */
export const rangeText = (r: JoltsRange) =>
  `Over the last ${Math.round(r.months / 12)} years (${r.months} months) the growth of spending on a year earlier ran from ${signedPct(r.lowest.value)} (${ymdLabel(r.lowest.month)}) to ${signedPct(r.highest.value)} (${ymdLabel(r.highest.month)}); ${r.share_lower_pct}% of those months were lower than now.`;

/** One owner, one use or one of the four parts in a line: how much, its share of all spending and the two changes. */
export const itemText = (i: Item) =>
  `${i.label}: ${money(i.millions)} (${i.share_pct.toFixed(1)}% of all spending); on the month ${moveMillions(i.change_month_millions)} (${move(i.change_month_pct, i.change_month_millions)}), on a year earlier ${moveMillions(i.change_year_millions)} (${move(i.change_year_pct, i.change_year_millions)}).`;

/** One of the last months. `label` is the month as a person reads it. */
export const monthText = (m: Month, label: string) => `${label}: ${money(m.millions)}, ${moveMillions(m.change_millions)} on the month before`;

/** The sentence under the card that says what was checked, with the card's own counts (the backend rounds the largest gap to four decimals: no more are shown). */
export function checkText(d: Detail): string {
  return `Check: in each of the ${d.months_checked.toLocaleString("en-US")} months from ${ymdLabel(d.first_month)} to ${ymdLabel(d.last_month)} the 9 series covered the same months with none missing and every figure lay inside its range (plain checks, not the source's sums). `
    + `The Census Bureau's own arithmetic held to within the rounding, which shows that the series belong to one release, not that the figures are right: total spending equalled private plus public and residential plus nonresidential spending, `
    + `private and public spending each equalled their residential plus nonresidential parts, and residential and nonresidential spending each equalled their private plus public parts `
    + `(the figures are whole millions of dollars, each rounded on its own; the largest gap was ${+d.largest_sum_gap.toFixed(4)} million, and 1.5 is allowed).`;
}
