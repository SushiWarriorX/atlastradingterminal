// Words for the US real consumer spending card. Every number comes from the server (it checks the Bureau's figures and works out the changes); this only writes them out.
import type { UsRealSpendingData, UsRealSpendingRange } from "../api/types";
import { ymdLabel } from "./format";

type Year = NonNullable<UsRealSpendingData["year"]>;
type Month = NonNullable<UsRealSpendingData["recent"]>[number];
type Detail = NonNullable<UsRealSpendingData["detail"]>;

const abs2 = (x: number) => Math.abs(x).toFixed(2);
const isZero = (x: number) => Number(abs2(x)) === 0;

/** A level in billions of dollars as trillions: 16977.6 becomes "$16.98 trillion". */
export const trillions = (billions: number) => `$${(billions / 1000).toFixed(2)} trillion`;
/** "up 2.54%", "down 0.10%" or "unchanged": a change that shows as 0.00 is never given a direction. */
export const move = (x: number) => (isZero(x) ? "unchanged" : `${x > 0 ? "up" : "down"} ${abs2(x)}%`);
/** A change with its sign and none for a figure that shows as zero: "+0.76%", "-0.10%", "0.00%". */
export const signedPct = (x: number) => (isZero(x) ? "0.00%" : `${x > 0 ? "+" : "-"}${abs2(x)}%`);

const verb = (subject: string, x: number) => (isZero(x) ? `${subject} did not change` : `${subject} ${x > 0 ? "rose" : "fell"} ${abs2(x)}%`);
const factor = (x: number) => (x < 0 && !isZero(x) ? `1 - ${abs2(x)}%` : `1 + ${abs2(x)}%`);

/** The year's change in spending in dollars split into prices and the amount bought, with the identity the three figures obey and its gap (the server works the gap out from the unrounded figures). */
export function yearText(y: Year): string {
  return `Over the year, ${verb("spending in dollars", y.nominal_pct)}. ${verb("Prices", y.prices_pct)} (the PCE price index; ${move(y.core_prices_pct)} without food and energy), so ${verb("the amount of goods and services bought", y.real_pct)}. `
    + `The three figures come from three separate series and fit each other: ${factor(y.nominal_pct)} = (${factor(y.real_pct)}) × (${factor(y.prices_pct)}), with a gap of ${y.gap_points.toFixed(3)} points.`;
}

/** One of the last months: the three changes on the month before, each with its sign. `label` is the month as a person reads it. */
export const monthText = (m: Month, label: string) =>
  `${label}: spending in dollars ${signedPct(m.nominal_change_pct)}, prices ${signedPct(m.prices_change_pct)}, real spending ${signedPct(m.real_change_pct)} on the month before`;

/** Where the year-on-year growth of real spending stands against its own record (the server counts only strictly lower months). */
export const rangeText = (r: UsRealSpendingRange) =>
  `Since ${ymdLabel(r.first)} (${r.months} months) the year-on-year growth of real spending ran from ${signedPct(r.lowest.value)} (${ymdLabel(r.lowest.month)}) to ${signedPct(r.highest.value)} (${ymdLabel(r.highest.month)}); ${r.share_lower_pct}% of those months were lower than now.`;

/** The sentence under the card that says what was checked, with the card's own counts (the backend rounds the largest gap to four decimals: no more are shown). */
export function checkText(d: Detail): string {
  return `Check: in each of the ${d.months_checked.toLocaleString("en-US")} months from ${ymdLabel(d.first_month)} to ${ymdLabel(d.last_month)} the four series covered the same months with none missing, every figure lay inside its range and no month-on-month move was beyond 25% for spending or 5% for prices (plain checks). `
    + `The Bureau's own accounting held, which shows that the series belong to one release, not that the figures are right: real spending times the price index over 100 equalled spending in dollars in every month, to within 0.098% of spending (the largest gap was ${+d.largest_identity_gap_pct.toFixed(4)}% in ${ymdLabel(d.largest_identity_gap_month)}); `
    + `the Bureau chain-weights real spending and prices, so the sum is approximate, not exact.`;
}
