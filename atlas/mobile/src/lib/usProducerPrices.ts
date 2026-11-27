// Words for the US producer prices card. Every number comes from the server (it checks the Bureau of Labor Statistics' indexes and works out the changes and the range); this only writes them out.
import type { JoltsRange, UsProducerPricesData } from "../api/types";
import { ymdLabel } from "./format";

type Headline = NonNullable<UsProducerPricesData["headline"]>;
type Item = NonNullable<UsProducerPricesData["groups"]>[number]["items"][number];
type Month = NonNullable<UsProducerPricesData["recent"]>[number];
type Detail = NonNullable<UsProducerPricesData["detail"]>;

/** A change in per cent with its direction, as the server rounds it (two decimals): 6.52 is "up 6.52%", -3.08 is "down 3.08%", and a change of exactly zero is "unchanged". */
export const moveText = (x: number) => (x === 0 ? "unchanged" : `${x > 0 ? "up" : "down"} ${Math.abs(x).toFixed(2)}%`);
/** A growth rate with its sign and two decimals: "+11.59%", "-1.35%"; zero has no sign. */
export const signedPct = (x: number) => (x === 0 ? "0.00%" : `${x > 0 ? "+" : "-"}${Math.abs(x).toFixed(2)}%`);
/** An index as a person reads it, to one decimal ("160.3"); the server keeps three. */
export const indexText = (x: number) => x.toFixed(1);

/** The headline: where final demand prices stand, against the month before and a year earlier, and the core on a year (`month` is the month as a person reads it). */
export const headlineText = (h: Headline, month: string) =>
  `In ${month} the producer price index for final demand was ${indexText(h.index)} (${h.base}): ${moveText(h.change_pct)} on the month before and ${moveText(h.change_year_pct)} on a year earlier; without foods and energy it was ${moveText(h.core_change_year_pct)} on a year earlier.`;

/** Where final demand's growth on a year earlier stands among the last ten years (the server counts only strictly lower months). */
export const rangeText = (r: JoltsRange) =>
  `Over the last ${Math.round(r.months / 12)} years (${r.months} months) the growth of final demand prices on a year earlier ran from ${signedPct(r.lowest.value)} (${ymdLabel(r.lowest.month)}) to ${signedPct(r.highest.value)} (${ymdLabel(r.highest.month)}); ${r.share_lower_pct}% of those months were lower than now.`;

/** One series in a line: its index with its base and the two changes. */
export const itemText = (i: Item) =>
  `${i.label}: ${indexText(i.index)} (${i.base}); on the month ${moveText(i.change_pct)}, on a year earlier ${moveText(i.change_year_pct)}.`;

/** One of the last months. `label` is the month as a person reads it. */
export const monthText = (m: Month, label: string) =>
  `${label}: final demand ${moveText(m.change_pct)} on the month before, without foods and energy ${moveText(m.core_change_pct)}.`;

/** The sentence under the card that says what was checked, with the card's own counts. */
export function checkText(d: Detail): string {
  return `Check: in each of the ${d.months_checked.toLocaleString("en-US")} months from ${ymdLabel(d.first_month)} to ${ymdLabel(d.last_month)} the 9 series covered the same months with none missing, every index lay inside its range and no month moved by more than its limit `
    + `(plain checks only: producer price indexes have no sums to check against, so this shows that the series are lined up and plausible, not that the figures are right).`;
}
