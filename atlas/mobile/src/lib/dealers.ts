// Words for the dealer card. Every number comes from the server (it compares the weekly changes with the source's own change figures); this only writes them out.
import type { DealersData } from "../api/types";

export const dayText = (iso?: string | null) => (iso ? new Date(`${iso}T12:00:00Z`).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" }) : "");
export const billions = (x: number) => `$${x.toLocaleString("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 })}B`;
const signedBillions = (x: number) => `${x < 0 ? "-" : ""}${billions(Math.abs(x))}`;

type Check = NonNullable<DealersData["check"]>;

/** The self-check line. Red, and the words "DOES NOT MATCH", only when the week the card shows is the one that disagrees with the source's own change figure (or the server is older and cannot say which week).
 *  When only older weeks disagree (the source revises old weeks, and it moved one level and a different amount of its change figure on 2026-11-24) the card says so in neutral words and names the week, so the
 *  disagreement is shown, not hidden and not a bare alarm. */
export function dealerCheck(c: Check): { text: string; red: boolean } {
  if (c.match) return { text: `Checked: the week-to-week changes equal the source's own change figures for the last ${c.weeks} weeks.`, red: false };
  const bad = c.bad_weeks ?? [];
  if (!c.latest_match || c.mismatches < 1) return { text: "DOES NOT MATCH: the week-to-week changes differ from the source's own change figures.", red: true };
  const named = bad.map((w) => `week of ${dayText(w.date)}: its levels give ${signedBillions(w.ours_billions)}, its change figure says ${signedBillions(w.source_billions)}`).join("; ");
  const more = c.mismatches > bad.length ? `; ${c.mismatches - bad.length} more` : "";
  return { text: `Checked: the latest week's change equals the source's own change figure. In ${c.mismatches} of the last ${c.weeks} weeks the source's own figures do not fit each other (${named}${more}); this card cannot tell which of the two is right.`, red: false };
}
