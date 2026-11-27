// Words for the US bank loans card. Every number comes from the server (it checks the Federal Reserve's figures and works out the changes, shares and ranges); this only writes them out.
import type { UsBankLoansData, UsBankLoansEstate, UsBankLoansKind, UsBankLoansRange } from "../api/types";
import { ymdLabel } from "./format";

type Total = NonNullable<UsBankLoansData["total"]>;
type Week = NonNullable<UsBankLoansData["recent"]>[number];
type Detail = NonNullable<UsBankLoansData["detail"]>;
type Other = NonNullable<UsBankLoansData["other"]>;

/** A level in billions of dollars as a person reads it: 14264.2085 is "$14.264 trillion", 292.308 is "$292 billion". */
export const level = (b: number) => (b >= 1000 ? `$${(b / 1000).toFixed(3)} trillion` : `$${Math.round(b).toLocaleString("en-US")} billion`);
/** A change in billions of dollars with its direction: 38.2202 is "up $38.2 billion", -0.3062 is "down $0.3 billion", 1033.1284 is "up $1.033 trillion", and under a twentieth of a billion is "unchanged". */
export const moveBillions = (b: number) => {
  const a = Math.abs(b);
  if (a < 0.05) return "unchanged";
  return `${b > 0 ? "up" : "down"} ${a >= 999.95 ? `$${(a / 1000).toFixed(3)} trillion` : `$${a.toFixed(1)} billion`}`;
};
/** A change in per cent that goes with a change in billions, one decimal as the server rounds it: "up 7.8%", "down 1.1%". A change that rounds to nothing while the dollars did move is "under 0.1%" (so the line never reads "up $1.9 billion (unchanged)"); when no dollars moved it is "unchanged"; with nothing to compare with it is "not available". */
export const move = (x: number | null | undefined, billions: number) =>
  x == null ? "not available" : Number(Math.abs(x).toFixed(1)) !== 0 ? `${x > 0 ? "up" : "down"} ${Math.abs(x).toFixed(1)}%` : Math.abs(billions) < 0.05 ? "unchanged" : "under 0.1%";
/** A growth rate with its sign and one decimal: "+12.4%", "-4.8%"; a figure that shows as zero has no sign. */
export const signedPct = (x: number) => (Number(Math.abs(x).toFixed(1)) === 0 ? "0.0%" : `${x > 0 ? "+" : "-"}${Math.abs(x).toFixed(1)}%`);
const lower = (s: string) => s.charAt(0).toLowerCase() + s.slice(1);

/** The headline: what the banks held on the Wednesday and how it splits into the four kinds (`when` is the Wednesday as a person reads it). */
export const headlineText = (t: Total, kinds: UsBankLoansKind[], when: string) => {
  const part = (k: UsBankLoansKind) => `${level(k.billions)} of ${k.key === "other" ? "other loans" : lower(k.label.replace(/ \(.*\)$/, ""))} (${k.share_pct.toFixed(1)}%)`;
  const [a, b, c, d] = kinds;
  return `In the week ending ${when} US commercial banks held ${level(t.loans_billions)} in loans and leases: ${part(a)}, ${part(b)}, ${part(c)} and ${part(d)}.`;
};

/** The total against the week before and against a year earlier. */
export const compareText = (t: Total) =>
  `Against the week before the total is ${moveBillions(t.change_week_billions)} (${move(t.change_week_pct, t.change_week_billions)}); against a year earlier it is ${moveBillions(t.change_year_billions)} (${move(t.change_year_pct, t.change_year_billions)}).`;

/** Where the total's growth on a year earlier stands among the last ten years (the server counts only strictly lower weeks). */
export const rangeText = (r: UsBankLoansRange) =>
  `Over the last ${Math.round(r.weeks / 52)} years (${r.weeks} weeks) the total's growth on a year earlier ran from ${signedPct(r.lowest.value)} (${ymdLabel(r.lowest.date)}) to ${signedPct(r.highest.value)} (${ymdLabel(r.highest.date)}); ${r.share_lower_pct}% of those weeks were lower than now.`;

/** One kind of loan in a line: the level, its share of the total and the two changes. */
export const kindText = (k: UsBankLoansKind) =>
  `${k.label}: ${level(k.billions)} (${k.share_pct.toFixed(1)}% of the total); on the week ${moveBillions(k.change_week_billions)} (${move(k.change_week_pct, k.change_week_billions)}), on a year earlier ${moveBillions(k.change_year_billions)} (${move(k.change_year_pct, k.change_year_billions)}).`;

/** Residential or commercial real estate in a line: the level, its share of the real estate loans and its parts. */
export const estateText = (e: UsBankLoansEstate) =>
  `${e.label}: ${level(e.billions)} (${e.share_pct.toFixed(1)}% of real estate loans): ${e.parts.map((p) => `${lower(p.label)} ${level(p.billions)}`).join(", ")}.`;

/** The loans to nondepository financial institutions inside the other loans. */
export const otherText = (o: Other) =>
  `Of the other loans, ${level(o.nondepository_billions)} (${o.share_of_other_pct.toFixed(1)}%) are loans to nondepository financial institutions, financial companies that do not take deposits.`;

/** One of the last weeks of the total. `label` is the Wednesday as a person reads it. */
export const weekText = (w: Week, label: string) => `${label}: total ${level(w.total_billions)}, ${moveBillions(w.change_billions)} on the week before`;

/** The sentence under the card that says what was checked, with the card's own counts (the backend rounds the largest gap to five decimals: no more are shown). */
export function checkText(d: Detail): string {
  return `Check: in each of the ${d.weeks_checked.toLocaleString("en-US")} weeks from ${ymdLabel(d.first_week)} to ${ymdLabel(d.last_week)} the 14 series covered the same Wednesdays with none missing and every figure lay inside its range (plain checks, not the source's sums). `
    + `The Federal Reserve's own arithmetic held, which shows that the series belong to one release, not that the figures are right: total loans equalled the four kinds, real estate loans equalled residential plus commercial, residential equalled closed-end loans plus home equity lines, `
    + `and commercial real estate equalled its four parts (the figures are kept to 0.0001 billion dollars, so a sum may be off by up to 0.00005 for each figure in it; the largest gap was ${+d.largest_sum_gap.toFixed(5)} billion), and loans to nondepository financial institutions never exceeded all other loans.`;
}
