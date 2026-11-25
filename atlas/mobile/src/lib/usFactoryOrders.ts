// Words for the US factory orders card. Every number comes from the server (it checks the Census Bureau's figures and works out the changes, shares and gaps); this only writes them out.
import type { UsFactoryOrdersData } from "../api/types";
import { ymdLabel } from "./format";
import { money, move, moveMillions } from "./usConstruction";

type Item = NonNullable<UsFactoryOrdersData["full"]>[number];
type Month = NonNullable<UsFactoryOrdersData["recent"]>[number];
type Detail = NonNullable<UsFactoryOrdersData["detail"]>;
type Newest = Detail["newest_common"];

const list = (parts: string[]) => (parts.length < 2 ? parts.join("") : `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}`);

/** What a line of the headline says about each of the four totals. */
const PHRASE: Record<string, (m: string) => string> = {
  orders: (m) => `took new orders of ${m}`,
  shipments: (m) => `shipped ${m}`,
  inventories: (m) => `held ${m} of inventories at the month end`,
  unfilled: (m) => `were still owed ${m} of unfilled orders`,
};
/** What a share is a share of. */
const SHARE_OF: Record<string, string> = { orders: "all new orders", inventories: "all inventories" };

/** The headline: what the four totals were in the month (`month` is the month as a person reads it). */
export const headlineText = (full: Item[], month: string) =>
  `In ${month} US manufacturers ${list(full.map((i) => (PHRASE[i.key] ?? ((m: string) => `had ${i.label.toLowerCase()} of ${m}`))(money(i.millions))))}.`;

/** One figure in a line: how much, its share where it has one, and the two changes. */
export const itemText = (i: Item) =>
  `${i.label}: ${money(i.millions)}${i.share_pct == null ? "" : ` (${i.share_pct.toFixed(1)}% of ${SHARE_OF[i.key] ?? "the total"})`}; on the month ${moveMillions(i.change_month_millions)} (${move(i.change_month_pct, i.change_month_millions)}), on a year earlier ${moveMillions(i.change_year_millions)} (${move(i.change_year_pct, i.change_year_millions)}).`;

/** Which month the durable goods figures are for, and why it can differ from the rest. */
export const durableText = (month: string, advance: boolean) =>
  advance
    ? `The durable goods figures are for ${month}, a month later than the rest: they come from the advance report, which is out before the full report for that month.`
    : `The durable goods figures are for ${month}, the same month as the rest.`;

const million = (g: number) => `$${Math.abs(g).toLocaleString("en-US")} million`;
const against = (g: number, what: string) => (g === 0 ? `equal to ${what}` : `${million(g)} ${g > 0 ? "above" : "below"} ${what}`);

/** The gaps in the newest month both reports cover, where the totals and the durable goods come from different releases (`month` is the month as a person reads it). */
export const gapsText = (n: Newest, month: string) =>
  [n.orders, n.shipments, n.inventories, n.unfilled].every((g) => g === 0)
    ? `In ${month}, the newest month both reports cover, the totals equalled the durable and nondurable figures added up and total unfilled orders equalled the durable ones.`
    : `In ${month}, the newest month both reports cover, total new orders were ${against(n.orders, "the durable and nondurable orders added up")}, total shipments ${against(n.shipments, "the durable and nondurable shipments added up")}, `
      + `total inventories ${against(n.inventories, "the durable and nondurable inventories added up")} and total unfilled orders ${against(n.unfilled, "the durable ones")}. The durable figures come from the later advance report, so this is a difference of date and not an error; these gaps are not part of the checks.`;

/** One of the last months. `label` is the month as a person reads it. */
export const monthText = (m: Month, label: string) => `${label}: new orders ${money(m.orders)} (${moveMillions(m.orders_change)} on the month before), shipments ${money(m.shipments)}`;

/** The sentence under the card that says what was checked, with the card's own counts (the backend rounds the gaps to four decimals: no more are shown). */
export function checkText(d: Detail): string {
  const durable = d.durable_last_month === d.last_month ? "the 6 durable series the same months" : `the 6 durable series the same months and ${ymdLabel(d.durable_last_month)} as well`;
  return `Check: in each of the ${d.months_checked.toLocaleString("en-US")} months from ${ymdLabel(d.first_month)} to ${ymdLabel(d.last_month)} the 7 series of the full report covered the same months with none missing, ${durable}, and every figure lay inside its range (plain checks, not the source's sums). `
    + `The Census Bureau's own arithmetic held to within the rounding, which shows that the series belong to one survey, not that the figures are right: total new orders, shipments and inventories each equalled their durable plus nondurable figure (the largest gap was ${+d.largest_sum_gap.toFixed(4)} million, and 1.5 is allowed), `
    + `nondurable goods orders equalled their shipments and total unfilled orders equalled the durable ones (the largest gap was ${+d.largest_equal_gap.toFixed(4)} million, and 1 is allowed), and orders excluding transportation and core capital goods orders never exceeded durable goods orders. `
    + `The newest month both reports cover is left out of the sums and the unfilled orders comparison (its gaps are shown above).`;
}
