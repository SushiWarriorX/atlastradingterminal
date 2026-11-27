// Words for the US bank balance sheet card. Every number comes from the server (it checks the Federal Reserve's figures and works out the changes, shares and ranges); this only writes them out.
import type { UsBankBalanceData, UsBankBalanceItem, UsBankLoansRange } from "../api/types";
import { ymdLabel } from "./format";
import { level, move, moveBillions, signedPct } from "./usBankLoans";

type Total = NonNullable<UsBankBalanceData["total"]>;
type Liabilities = NonNullable<UsBankBalanceData["liabilities"]>;
type Residual = NonNullable<UsBankBalanceData["residual"]>;
type Detail = NonNullable<UsBankBalanceData["detail"]>;
type Week = NonNullable<UsBankBalanceData["recent"]>[number];
const lower = (s: string) => s.charAt(0).toLowerCase() + s.slice(1);

/** The headline: what the banks held on the Wednesday and how it splits (`when` is the Wednesday as a person reads it). */
export const headlineText = (t: Total, assets: UsBankBalanceItem[], when: string) => {
  const part = (a: UsBankBalanceItem) => `${level(a.billions)} of ${lower(a.label)} (${a.share_pct.toFixed(1)}%)`;
  const [a, b, c, d] = assets;
  return `In the week ending ${when} US commercial banks held ${level(t.assets_billions)} in assets: ${part(a)}, ${part(b)}, ${part(c)} and ${part(d)}.`;
};

/** What they owed, and what is left. */
export const owedText = (l: Liabilities, r: Residual) => {
  const [dep, other] = l.items;
  return `They owed ${level(l.total_billions)}: ${level(dep.billions)} of ${lower(dep.label)} (${dep.share_pct.toFixed(1)}%) and ${level(other.billions)} of ${lower(other.label)} (${other.share_pct.toFixed(1)}%). What is left, assets less liabilities, is ${level(r.billions)} (${r.share_of_assets_pct.toFixed(1)}% of assets).`;
};

/** Total assets against the week before and against a year earlier. */
export const compareText = (t: Total) =>
  `Against the week before total assets are ${moveBillions(t.change_week_billions)} (${move(t.change_week_pct, t.change_week_billions)}); against a year earlier they are ${moveBillions(t.change_year_billions)} (${move(t.change_year_pct, t.change_year_billions)}).`;

/** Where the growth of total assets on a year earlier stands among the last ten years (the server counts only strictly lower weeks). */
export const rangeText = (r: UsBankLoansRange) =>
  `Over the last ${Math.round(r.weeks / 52)} years (${r.weeks} weeks) the growth of total assets on a year earlier ran from ${signedPct(r.lowest.value)} (${ymdLabel(r.lowest.date)}) to ${signedPct(r.highest.value)} (${ymdLabel(r.highest.date)}); ${r.share_lower_pct}% of those weeks were lower than now.`;

/** One line of the asset or liability side: the level, its share of its side and the two changes (`of` names the side: "total assets" or "total liabilities"). */
export const itemText = (a: UsBankBalanceItem, of: string) =>
  `${a.label}: ${level(a.billions)} (${a.share_pct.toFixed(1)}% of ${of}); on the week ${moveBillions(a.change_week_billions)} (${move(a.change_week_pct, a.change_week_billions)}), on a year earlier ${moveBillions(a.change_year_billions)} (${move(a.change_year_pct, a.change_year_billions)}).`;

/** The securities split into Treasury and agency securities and the others. */
export const securitiesText = (parts: NonNullable<UsBankBalanceData["securities"]>) => {
  const [a, b] = parts;
  return `Of the securities, ${level(a.billions)} (${a.share_pct.toFixed(1)}%) are ${a.label} and ${level(b.billions)} (${b.share_pct.toFixed(1)}%) are ${lower(b.label)}.`;
};

/** Total liabilities in a line with its two changes. */
export const liabilitiesText = (l: Liabilities) =>
  `Total liabilities: ${level(l.total_billions)}; on the week ${moveBillions(l.change_week_billions)} (${move(l.change_week_pct, l.change_week_billions)}), on a year earlier ${moveBillions(l.change_year_billions)} (${move(l.change_year_pct, l.change_year_billions)}).`;

/** The residual in a line: its level, its share of total assets and its change on a year earlier. */
export const residualText = (r: Residual) =>
  `Assets less liabilities (the residual): ${level(r.billions)} (${r.share_of_assets_pct.toFixed(1)}% of total assets); on a year earlier ${moveBillions(r.change_year_billions)} (${move(r.change_year_pct, r.change_year_billions)}).`;

/** One of the last weeks of total assets. `label` is the Wednesday as a person reads it. */
export const weekText = (w: Week, label: string) => `${label}: total assets ${level(w.total_billions)}, ${moveBillions(w.change_billions)} on the week before`;

/** The sentence under the card that says what was checked, with the card's own counts (the backend rounds the largest gap to five decimals: no more are shown). */
export function checkText(d: Detail): string {
  return `Check: in each of the ${d.weeks_checked.toLocaleString("en-US")} weeks from ${ymdLabel(d.first_week)} to ${ymdLabel(d.last_week)} the 10 series covered the same Wednesdays with none missing and every figure lay inside its range (plain checks, not the source's sums). `
    + `The Federal Reserve's own arithmetic held, which shows that the series belong to one release, not that the figures are right: bank credit equalled loans and leases plus securities, securities equalled Treasury and agency securities plus other securities, `
    + `and total assets equalled total liabilities plus the residual (the figures are kept to 0.0001 billion dollars, so a sum may be off by up to 0.00005 for each figure in it; the largest gap was ${+d.largest_sum_gap.toFixed(5)} billion; the residual is the Fed's own difference, so that last sum only shows that the weeks line up), `
    + `and total assets never fell below bank credit plus cash assets, nor total liabilities below deposits.`;
}
