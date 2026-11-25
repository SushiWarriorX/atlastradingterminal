// Words for the US building permits card. Every number comes from the server (it checks the Census Bureau's figures and works out the changes, shares and ranges); this only writes them out.
import type { JoltsRange, UsBuildingPermitsData } from "../api/types";
import { ymdLabel } from "./format";

type Total = NonNullable<UsBuildingPermitsData["total"]>;
type Item = NonNullable<UsBuildingPermitsData["types"]>[number];
type Month = NonNullable<UsBuildingPermitsData["recent"]>[number];
type Detail = NonNullable<UsBuildingPermitsData["detail"]>;

/** A number of homes given in thousands as a person reads it: 1295 is "1.295 million", 772 is "772 thousand", 48 is "48 thousand". */
export const homes = (k: number) => (k >= 1000 ? `${(k / 1000).toFixed(3)} million` : `${Math.round(k).toLocaleString("en-US")} thousand`);
/** A change in thousands of homes with its direction: -103 is "down 103 thousand", 59 is "up 59 thousand", 1200 is "up 1.200 million", and under half a thousand is "unchanged". */
export const moveThousands = (k: number) => {
  const a = Math.abs(k);
  if (a < 0.5) return "unchanged";
  return `${k > 0 ? "up" : "down"} ${a >= 999.5 ? `${(a / 1000).toFixed(3)} million` : `${Math.round(a).toLocaleString("en-US")} thousand`}`;
};
/** A change in per cent that goes with a change in thousands, one decimal as the server rounds it: "up 3.0%", "down 1.1%". A change that rounds to nothing while the homes did move is "under 0.1%" (so a line never reads "up 3 thousand (unchanged)"), and "unchanged" only when the homes read unchanged too; a figure with nothing to compare with is "not available". */
export const move = (x: number | null | undefined, thousands: number) =>
  x == null ? "not available" : Number(Math.abs(x).toFixed(1)) !== 0 ? `${x > 0 ? "up" : "down"} ${Math.abs(x).toFixed(1)}%` : moveThousands(thousands) === "unchanged" ? "unchanged" : "under 0.1%";
/** A growth rate with its sign and one decimal: "+58.5%", "-26.3%"; a figure that shows as zero has no sign. */
export const signedPct = (x: number) => (Number(Math.abs(x).toFixed(1)) === 0 ? "0.0%" : `${x > 0 ? "+" : "-"}${Math.abs(x).toFixed(1)}%`);

const list = (parts: string[]) => (parts.length < 2 ? parts.join("") : `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}`);

/** The headline: how many homes were given permission in the month and how they split by type (`month` is the month as a person reads it). */
export const headlineText = (t: Total, types: Item[], month: string) =>
  `In ${month} local governments in the US gave permission to build ${homes(t.thousands)} homes at a seasonally adjusted annual rate: ${list(types.map((i) => `${homes(i.thousands)} ${i.label.toLowerCase()} (${i.share_pct.toFixed(1)}%)`))}.`;

/** The total against the month before and against a year earlier. */
export const compareText = (t: Total) =>
  `Against the month before permits are ${moveThousands(t.change_month_thousands)} (${move(t.change_month_pct, t.change_month_thousands)}); against a year earlier they are ${moveThousands(t.change_year_thousands)} (${move(t.change_year_pct, t.change_year_thousands)}).`;

/** Where the total's growth on a year earlier stands among the last ten years (the server counts only strictly lower months). */
export const rangeText = (r: JoltsRange) =>
  `Over the last ${Math.round(r.months / 12)} years (${r.months} months) the growth of permits on a year earlier ran from ${signedPct(r.lowest.value)} (${ymdLabel(r.lowest.month)}) to ${signedPct(r.highest.value)} (${ymdLabel(r.highest.month)}); ${r.share_lower_pct}% of those months were lower than now.`;

/** One type of home or one region in a line: how many, its share of all permits and the two changes. */
export const itemText = (i: Item) =>
  `${i.label}: ${homes(i.thousands)} (${i.share_pct.toFixed(1)}% of all permits); on the month ${moveThousands(i.change_month_thousands)} (${move(i.change_month_pct, i.change_month_thousands)}), on a year earlier ${moveThousands(i.change_year_thousands)} (${move(i.change_year_pct, i.change_year_thousands)}).`;

/** One of the last months. `label` is the month as a person reads it. */
export const monthText = (m: Month, label: string) => `${label}: ${homes(m.thousands)} homes, ${moveThousands(m.change_thousands)} on the month before`;

/** The sentence under the card that says what was checked, with the card's own counts (the backend rounds the largest gap to four decimals: no more are shown). */
export function checkText(d: Detail): string {
  return `Check: in each of the ${d.months_checked.toLocaleString("en-US")} months from ${ymdLabel(d.first_month)} to ${ymdLabel(d.last_month)} the 8 series covered the same months with none missing and every figure lay inside its range (plain checks, not the source's sums). `
    + `The Census Bureau's own arithmetic held, which shows that the series belong to one release, not that the figures are right: total permits equalled single-family plus 2-4 unit plus 5+ unit permits, and equalled the four regions added up `
    + `(the figures are whole thousands; the largest gap was ${+d.largest_sum_gap.toFixed(4)} thousand, and 2 and 2.5 are allowed).`;
}
