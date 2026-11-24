// Words for the US consumer credit card. Every number comes from the server (it checks the Federal Reserve's figures and works out the changes, shares and ranges); this only writes them out.
import type { JoltsRange, UsConsumerCreditData } from "../api/types";
import { ymdLabel } from "./format";

type Total = NonNullable<UsConsumerCreditData["total"]>;
type Kind = NonNullable<UsConsumerCreditData["kinds"]>[number];
type Month = NonNullable<UsConsumerCreditData["recent"]>[number];
type Detail = NonNullable<UsConsumerCreditData["detail"]>;

/** An amount owed, in millions of dollars, as a person reads it: 5224415.99 is "$5.224 trillion", 976044 is "$976 billion", 640 is "$640 million". */
export const level = (m: number) => (m >= 1_000_000 ? `$${(m / 1_000_000).toFixed(3)} trillion` : m >= 1000 ? `$${Math.round(m / 1000).toLocaleString("en-US")} billion` : `$${Math.round(m).toLocaleString("en-US")} million`);
/** A change in the amount owed with its direction, in millions of dollars as the server gives it: 27838.63 is "up $27.8 billion", -4100 is "down $4.1 billion", 640 is "up $640 million", and under half a million is "unchanged". */
export const moveMillions = (m: number) => {
  const a = Math.abs(m);
  if (a < 0.5) return "unchanged";
  return `${m > 0 ? "up" : "down"} ${a >= 999.5 ? `$${(a / 1000).toFixed(1)} billion` : `$${Math.round(a)} million`}`;
};
/** A change with one decimal, as the server rounds it: "up 3.0%", "down 1.1%", "unchanged"; a figure with nothing to compare with is "not available". */
export const move = (x: number | null | undefined) => (x == null ? "not available" : Number(Math.abs(x).toFixed(1)) === 0 ? "unchanged" : `${x > 0 ? "up" : "down"} ${Math.abs(x).toFixed(1)}%`);
/** A growth rate with its sign and one decimal: "+10.1%", "-1.1%"; a figure that shows as zero has no sign. */
export const signedPct = (x: number) => (Number(Math.abs(x).toFixed(1)) === 0 ? "0.0%" : `${x > 0 ? "+" : "-"}${Math.abs(x).toFixed(1)}%`);

/** The headline: what was owed at the end of the month and how it splits (`month` is the month as a person reads it). */
export const headlineText = (t: Total, month: string) =>
  `In ${month} US consumers owed ${level(t.total_millions)} in consumer credit at the end of the month (mortgages are not counted): ${level(t.revolving_millions)} revolving (${t.revolving_share_pct.toFixed(1)}% of the total) and ${level(t.nonrevolving_millions)} nonrevolving.`;

/** The total against the month before and against a year earlier. */
export const compareText = (t: Total) =>
  `Against the month before the total is ${moveMillions(t.change_month_millions)} (${move(t.change_month_pct)}); against a year earlier it is ${moveMillions(t.change_year_millions)} (${move(t.change_year_pct)}).`;

/** Where the total's growth on a year earlier stands among the last ten years (the server counts only strictly lower months). */
export const rangeText = (r: JoltsRange) =>
  `Over the last ${Math.round(r.months / 12)} years (${r.months} months) the total's growth on a year earlier ran from ${signedPct(r.lowest.value)} (${ymdLabel(r.lowest.month)}) to ${signedPct(r.highest.value)} (${ymdLabel(r.highest.month)}); ${r.share_lower_pct}% of those months were lower than now.`;

/** One kind of credit in a line: what is owed, its share of the total and the two changes. */
export const kindText = (k: Kind) =>
  `${k.label}: ${level(k.millions)} (${k.share_pct.toFixed(1)}% of the total). Against the month before it is ${moveMillions(k.change_month_millions)} (${move(k.change_month_pct)}); against a year earlier it is ${moveMillions(k.change_year_millions)} (${move(k.change_year_pct)}).`;

/** One of the last months. `label` is the month as a person reads it. */
export const monthText = (m: Month, label: string) =>
  `${label}: total ${level(m.total_millions)} (revolving ${level(m.revolving_millions)}, nonrevolving ${level(m.nonrevolving_millions)}), ${moveMillions(m.change_millions)} on the month before`;

/** The sentence under the card that says what was checked, with the card's own counts (the backend rounds the largest gap to four decimals: no more are shown). */
export function checkText(d: Detail): string {
  return `Check: in each of the ${d.months_checked.toLocaleString("en-US")} months from ${ymdLabel(d.first_month)} to ${ymdLabel(d.last_month)} the 3 series covered the same months with none missing and every figure lay inside its range (plain checks, not the source's sum). `
    + `The Federal Reserve's own arithmetic held, which shows that the series belong to one release, not that the figures are right: total consumer credit equalled revolving plus nonrevolving credit `
    + `(the figures are rounded to 0.01 million dollars; the largest gap was ${+d.largest_sum_gap.toFixed(4)} million, and 0.015 is allowed).`;
}
