// Words for the US international trade card. Every number comes from the server (it checks the agencies' figures and works out the changes); this only writes them out.
import type { UsTradeData } from "../api/types";
import { ymdLabel } from "./format";
import { move } from "./realSpending";

type Group = NonNullable<UsTradeData["total"]>;
type Month = NonNullable<UsTradeData["recent"]>[number];
type Detail = NonNullable<UsTradeData["detail"]>;
type Range = Group["range"];

const abs1 = (x: number) => Math.abs(x).toFixed(1);
const isZero = (x: number) => Number(abs1(x)) === 0;

/** A level in billions of dollars with one decimal: 321.511 becomes "$321.5 billion". */
export const billions = (x: number) => `$${abs1(x)} billion`;
/** A balance with its sign: "-$105.0 billion", "+$30.9 billion"; a balance that shows as 0.0 has no sign. */
export const signedBillions = (x: number) => (isZero(x) ? "$0.0 billion" : `${x > 0 ? "+" : "-"}$${abs1(x)} billion`);
/** A balance in words: "a deficit of $105.0 billion", "a surplus of $30.9 billion"; one that shows as 0.0 is "a balance of $0.0 billion", never a deficit or a surplus. */
export const balanceWords = (x: number) => (isZero(x) ? "a balance of $0.0 billion" : `a ${x < 0 ? "deficit" : "surplus"} of ${billions(x)}`);

/** The headline: what the country sold, what it bought and the difference, for the month named (`month` is the month as a person reads it). */
export const headlineText = (g: Group, month: string) =>
  `In ${month} the US sold ${billions(g.exports)} of goods and services to the rest of the world and bought ${billions(g.imports)}: ${balanceWords(g.balance)}.`;

/** The balance a month and a year earlier (the month before is worked out from the change), and how exports and imports grew over the year. */
export const compareText = (g: Group) =>
  `A month earlier it was ${balanceWords(g.balance - g.balance_change)}; a year earlier, ${balanceWords(g.balance_year_ago)}. Over the year exports are ${move(g.exports_change_year_pct)} and imports ${move(g.imports_change_year_pct)}.`;

/** One of the two parts (goods, services) in a line: what was sold and bought, the balance, and the year's change in each. */
export const groupText = (label: string, g: Omit<Group, "range">) =>
  `${label}: sold ${billions(g.exports)}, bought ${billions(g.imports)}: ${balanceWords(g.balance)}; exports ${move(g.exports_change_year_pct)} and imports ${move(g.imports_change_year_pct)} on a year earlier.`;

/** Where the total balance stands against its own record (the server counts only strictly lower months; a lower balance is a bigger deficit or a smaller surplus). */
export const rangeText = (r: Range) =>
  `Since ${ymdLabel(r.first)} (${r.months} months) the monthly balance ran from ${signedBillions(r.lowest.value)} (${ymdLabel(r.lowest.month)}) to ${signedBillions(r.highest.value)} (${ymdLabel(r.highest.month)}); it was lower than now in ${r.share_lower_pct}% of those months (a lower balance is a bigger deficit or a smaller surplus).`;

/** One of the last months: what was sold and bought and the balance. `label` is the month as a person reads it. */
export const monthText = (m: Month, label: string) => `${label}: sold ${billions(m.exports)}, bought ${billions(m.imports)}, ${balanceWords(m.balance)}`;

/** The sentence under the card that says what was checked, with the card's own counts (the backend rounds the largest gap to three decimals: no more are shown). */
export function checkText(d: Detail): string {
  return `Check: in each of the ${d.months_checked.toLocaleString("en-US")} months from ${ymdLabel(d.first_month)} to ${ymdLabel(d.last_month)} the nine series covered the same months with none missing, every figure lay inside its range and no month-on-month move of an export or import series was beyond 50% (plain checks). `
    + `The agencies' own accounting held, which shows that the series belong to one release, not that the figures are right: each balance equalled its exports minus its imports, total exports and total imports equalled goods plus services, and the total balance equalled the goods balance plus the services balance, in every month, to within 1.5 million dollars `
    + `(the published figures are each rounded to a million; the largest gap was ${+d.largest_gap_million.toFixed(3)} million dollars in ${ymdLabel(d.largest_gap_month)}).`;
}
