// Words for the US new home sales card. Every number comes from the server (it checks the Census Bureau's figures and works out the changes, shares and ranges); this only writes them out.
import type { JoltsRange, UsNewHomesData } from "../api/types";
import { ymdLabel } from "./format";

type Sales = NonNullable<UsNewHomesData["sales"]>;
type Item = NonNullable<UsNewHomesData["regions"]>[number];
type Stock = NonNullable<UsNewHomesData["stock"]>;
type Prices = NonNullable<UsNewHomesData["prices"]>;
type Month = NonNullable<UsNewHomesData["recent"]>[number];
type Detail = NonNullable<UsNewHomesData["detail"]>;

/** Thousands of houses as a person reads them: 676 is "676,000", 1031 is "1,031,000". */
export const houses = (k: number) => Math.round(k * 1000).toLocaleString("en-US");
/** A change in thousands of houses with its direction: -4 is "down 4,000", 38 is "up 38,000", 0 is "unchanged". */
export const moveHouses = (k: number) => (k === 0 ? "unchanged" : `${k > 0 ? "up" : "down"} ${houses(Math.abs(k))}`);
/** A change in months of supply with its direction, one decimal as the server rounds it: -0.1 is "down 0.1", 0.2 is "up 0.2", 0 is "unchanged". */
export const moveMonths = (m: number) => (m === 0 ? "unchanged" : `${m > 0 ? "up" : "down"} ${Math.abs(m).toFixed(1)}`);
/** Dollars as a person reads them: 400400 is "$400,400". */
export const dollars = (d: number) => `$${Math.round(d).toLocaleString("en-US")}`;
/** A change in dollars with its direction: -16400 is "down $16,400", 12000 is "up $12,000", 0 is "unchanged". */
export const moveDollars = (d: number) => (d === 0 ? "unchanged" : `${d > 0 ? "up" : "down"} ${dollars(Math.abs(d))}`);
/** A change in per cent that goes with a change in an amount, one decimal as the server rounds it: "up 3.0%", "down 1.1%". A change that rounds to nothing while the amount did move is "under 0.1%" (so a line never reads "up 1,000 (unchanged)"), and "unchanged" only when the amount did not move either; a figure with nothing to compare with is "not available". */
export const move = (x: number | null | undefined, amount: number) =>
  x == null ? "not available" : Number(Math.abs(x).toFixed(1)) !== 0 ? `${x > 0 ? "up" : "down"} ${Math.abs(x).toFixed(1)}%` : amount === 0 ? "unchanged" : "under 0.1%";
/** A growth rate with its sign and one decimal: "+51.4%", "-33.2%"; a figure that shows as zero has no sign. */
export const signedPct = (x: number) => (Number(Math.abs(x).toFixed(1)) === 0 ? "0.0%" : `${x > 0 ? "+" : "-"}${Math.abs(x).toFixed(1)}%`);

const list = (parts: string[]) => (parts.length < 2 ? parts.join("") : `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}`);
const years = (r: JoltsRange) => `${Math.round(r.months / 12)} years (${r.months} months)`;

/** The headline: how fast new houses were being sold in the month and how that splits over the four regions (`month` is the month as a person reads it). */
export const headlineText = (s: Sales, regions: Item[], month: string) =>
  `In ${month} new houses were being sold at a seasonally adjusted annual rate of ${houses(s.thousands)}: ${list(regions.map((i) => `${houses(i.thousands)} in the ${i.label} (${i.share_pct.toFixed(1)}%)`))}.`;

/** Sales against the month before and against a year earlier. */
export const compareText = (s: Sales) =>
  `Against the month before sales are ${moveHouses(s.change_month)} (${move(s.change_month_pct, s.change_month)}); against a year earlier they are ${moveHouses(s.change_year)} (${move(s.change_year_pct, s.change_year)}).`;

/** Where the growth of sales on a year earlier stands among the last ten years (the server counts only strictly lower months). */
export const rangeText = (r: JoltsRange) =>
  `Over the last ${years(r)} the growth of sales on a year earlier ran from ${signedPct(r.lowest.value)} (${ymdLabel(r.lowest.month)}) to ${signedPct(r.highest.value)} (${ymdLabel(r.highest.month)}); ${r.share_lower_pct}% of those months were lower than now.`;

/** One region in a line: how many, its share of all sales and the two changes. */
export const itemText = (i: Item) =>
  `${i.label}: ${houses(i.thousands)} (${i.share_pct.toFixed(1)}% of all sales); on the month ${moveHouses(i.change_month)} (${move(i.change_month_pct, i.change_month)}), on a year earlier ${moveHouses(i.change_year)} (${move(i.change_year_pct, i.change_year)}).`;

/** The new houses for sale at the end of the month and the months of sales they would last. */
export const stockText = (s: Stock) =>
  `For sale at the end of the month: ${houses(s.for_sale)} new houses (${moveHouses(s.for_sale_change_month)} on the month, ${moveHouses(s.for_sale_change_year)} on a year earlier). `
  + `That is ${s.months_supply.toFixed(1)} months' supply at the pace of sales (${moveMonths(s.supply_change_month)} on the month, ${moveMonths(s.supply_change_year)} on a year earlier).`;

/** Where the months' supply stands among the last ten years. */
export const supplyRangeText = (r: JoltsRange) =>
  `Over the last ${years(r)} the months' supply ran from ${r.lowest.value.toFixed(1)} (${ymdLabel(r.lowest.month)}) to ${r.highest.value.toFixed(1)} (${ymdLabel(r.highest.month)}); ${r.share_lower_pct}% of those months were lower than now.`;

/** The two prices against a year earlier (they are not seasonally adjusted, so a month is not compared with the month before). */
export const pricesText = (p: Prices) =>
  `The median price of a new house sold was ${dollars(p.median)} (${moveDollars(p.median_change_year)}, ${move(p.median_change_year_pct, p.median_change_year)}, on a year earlier) and the average price ${dollars(p.average)} (${moveDollars(p.average_change_year)}, ${move(p.average_change_year_pct, p.average_change_year)}, on a year earlier).`;

/** Where the median price stands among the last ten years. */
export const priceRangeText = (r: JoltsRange) =>
  `Over the last ${years(r)} the median price ran from ${dollars(r.lowest.value)} (${ymdLabel(r.lowest.month)}) to ${dollars(r.highest.value)} (${ymdLabel(r.highest.month)}); ${r.share_lower_pct}% of those months were lower than now.`;

/** One of the last months. `label` is the month as a person reads it. */
export const monthText = (m: Month, label: string) => `${label}: ${houses(m.thousands)}, ${moveHouses(m.change)} on the month before, with ${m.months_supply.toFixed(1)} months' supply`;

/** The sentence under the card that says what was checked, with the card's own counts (the backend rounds the gaps to four decimals: no more are shown). */
export function checkText(d: Detail): string {
  return `Check: in each of the ${d.months_checked.toLocaleString("en-US")} months from ${ymdLabel(d.first_month)} to ${ymdLabel(d.last_month)} the 9 series covered the same months with none missing and every figure lay inside its range (plain checks, not the source's sums). `
    + `The Census Bureau's own arithmetic held to within the rounding, which shows that the series belong to one release, not that the figures are right: the four regions added up to the sales total (the largest gap was ${+d.largest_sum_gap.toFixed(4)} thousand, and 2.5 is allowed), `
    + `the months' supply agreed with 12 times the houses for sale divided by the sales rate (the largest gap was ${+d.largest_supply_gap.toFixed(4)} of a month, and 0.1 is allowed), `
    + `and the average price was never below the median price (the smallest gap was ${dollars(d.smallest_price_gap)}).`;
}
