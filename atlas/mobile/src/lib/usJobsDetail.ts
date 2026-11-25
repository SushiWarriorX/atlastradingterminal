// Words for the US jobs in detail card. Every number comes from the server (it checks the Bureau of Labor Statistics' figures and works out the changes, shares and sums); this only writes them out.
import type { UsJobsDetailData } from "../api/types";
import { ymdLabel } from "./format";
import { itemText } from "./usIndustryJobs";

type Item = NonNullable<UsJobsDetailData["groups"]>[number]["parent"];
type Detail = NonNullable<UsJobsDetailData["detail"]>;

/** One industry's own line: how many jobs, and the two changes (it has no share: it is the whole its parts are shares of). */
export const parentText = (i: Item) => itemText(i);

/** One part of an industry: how many jobs, its share of that industry (named in lower case after the share) and the two changes. */
export const childText = (i: Item, parentLabel: string) => itemText(i, parentLabel.toLowerCase());

/** The sentence under the card that says what was checked, with the card's own counts (the backend rounds the gap to four decimals: no more is shown). */
export const checkText = (d: Detail) =>
  `Check: in each of the ${d.months_checked.toLocaleString("en-US")} months from ${ymdLabel(d.first_month)} to ${ymdLabel(d.last_month)} the 26 series covered the same months with none missing and every figure lay inside its range (plain checks, not the source's sums). `
  + `The Bureau's own arithmetic held to within the rounding, which shows that the series belong to one release, not that the figures are right: each of the seven industries equalled the sum of its parts `
  + `(the largest gap in any month was ${+d.largest_sum_gap.toFixed(4)} thousand; 0.75 is allowed for the six private industries, whose parts are given to a tenth of a thousand, and 2 for government, whose figures are whole thousands).`;
