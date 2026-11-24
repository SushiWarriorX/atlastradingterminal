import { describe, expect, it } from "vitest";
import type { DealersData } from "../api/types";
import { billions, dayText, dealerCheck } from "./dealers";

type Check = NonNullable<DealersData["check"]>;
const fits: Check = { weeks: 26, mismatches: 0, match: true, latest_match: true, bad_weeks: [], latest_ours_billions: 27.1, latest_source_billions: 27.1 };
// The real response of 2026-11-24: the source revised one older week, and the latest week still fits.
const older: Check = { weeks: 26, mismatches: 1, match: false, latest_match: true, bad_weeks: [{ date: "2026-10-21", ours_billions: -31.7, source_billions: -17.1 }], latest_ours_billions: -11.3, latest_source_billions: -11.3 };
const latest: Check = { weeks: 26, mismatches: 1, match: false, latest_match: false, bad_weeks: [{ date: "2026-10-28", ours_billions: 27.1, source_billions: 32.1 }], latest_ours_billions: 27.1, latest_source_billions: 32.1 };

describe("the dealer card's self-check line", () => {
  it("says it checked, quietly, when every week fits", () => {
    expect(dealerCheck(fits)).toEqual({ text: "Checked: the week-to-week changes equal the source's own change figures for the last 26 weeks.", red: false });
  });

  it("names the older week the source's own figures no longer fit, and is not red when the latest week fits", () => {
    const r = dealerCheck(older);
    expect(r.red).toBe(false);
    expect(r.text).toBe("Checked: the latest week's change equals the source's own change figure. In 1 of the last 26 weeks the source's own figures do not fit each other " +
                        "(week of Oct 21, 2026: its levels give -$31.7B, its change figure says -$17.1B); this card cannot tell which of the two is right.");
    expect(r.text).not.toMatch(/DOES NOT MATCH/);                                                                         // the browser suite fails a run on that phrase, so it is kept for the case the week shown disagrees
    expect(r.text).not.toMatch(/\b20\d\d-\d\d-\d\d\b/);                                                                   // dates are written out, never ISO
  });

  it("is red and says so plainly when the week shown is the one that disagrees", () => {
    expect(dealerCheck(latest)).toEqual({ text: "DOES NOT MATCH: the week-to-week changes differ from the source's own change figures.", red: true });
  });

  it("keeps the red line when an older server sends no latest_match field", () => {
    const { latest_match: _l, bad_weeks: _b, ...old } = older;                                                            // what the server sent before 2026-11-24
    expect(dealerCheck(old as Check)).toEqual({ text: "DOES NOT MATCH: the week-to-week changes differ from the source's own change figures.", red: true });
  });

  it("counts the weeks it does not list, newest named first", () => {
    const many: Check = { ...older, mismatches: 5, bad_weeks: [
      { date: "2026-10-28", ours_billions: 27.1, source_billions: 36.1 }, { date: "2026-10-21", ours_billions: -17.9, source_billions: -8.9 }, { date: "2026-10-14", ours_billions: -1.2, source_billions: 7.8 }] };
    const t = dealerCheck(many).text;
    expect(t).toContain("In 5 of the last 26 weeks");
    expect(t.indexOf("Oct 28, 2026")).toBeLessThan(t.indexOf("Oct 21, 2026"));
    expect(t.indexOf("Oct 21, 2026")).toBeLessThan(t.indexOf("Oct 14, 2026"));
    expect(t).toContain("; 2 more)");
    expect(t).toContain("-$17.9B, its change figure says -$8.9B; week of Oct 14, 2026");                                    // weeks are separated by a semicolon, so the two figures of one week read together
    expect(dealerCheck(many).red).toBe(false);
  });

  it("never says a negative number of more weeks, even from a server that listed more weeks than it counted", () => {
    const odd = dealerCheck({ ...older, mismatches: 1, bad_weeks: [older.bad_weeks![0], older.bad_weeks![0], older.bad_weeks![0]] }).text;
    expect(odd).not.toMatch(/more/);
  });

  it("writes a figure that rounds to zero as zero, never as minus zero", () => {
    const t = dealerCheck({ ...older, bad_weeks: [{ date: "2026-10-14", ours_billions: -0, source_billions: 0 }] }).text;       // the server rounds -0.04 to -0.0
    expect(t).toContain("its levels give $0.0B, its change figure says $0.0B");
  });

  it("writes a positive figure without a sign and a negative one with a minus", () => {
    const t = dealerCheck({ ...older, bad_weeks: [{ date: "2026-10-14", ours_billions: 7.8, source_billions: -1.2 }] }).text;
    expect(t).toContain("its levels give $7.8B, its change figure says -$1.2B");
  });

  it("treats a check that failed with no week to name as a failure, not as a quiet note", () => {
    expect(dealerCheck({ ...older, mismatches: 0, bad_weeks: [] }).red).toBe(true);
    expect(dealerCheck({ ...older, mismatches: 0, bad_weeks: [] }).text).toMatch(/^DOES NOT MATCH/);
  });
});

describe("the dealer card's figures and dates", () => {
  it("writes billions with one decimal and a thousands separator", () => {
    expect(billions(452)).toBe("$452.0B");
    expect(billions(1234.56)).toBe("$1,234.6B");
    expect(billions(0)).toBe("$0.0B");
  });
  it("writes a date out in full, as the rest of the app does, and a missing date as nothing", () => {
    expect(dayText("2026-10-21")).toBe("Oct 21, 2026");
    expect(dayText("2026-01-01")).toBe("Jan 1, 2026");
    expect(dayText(null)).toBe("");
    expect(dayText(undefined)).toBe("");
  });
  it("gives the same day wherever the phone is, even 14 hours ahead of UTC", () => {
    const before = process.env.TZ;
    try {
      process.env.TZ = "Pacific/Kiritimati";
      expect(dayText("2026-10-21")).toBe("Oct 21, 2026");
      process.env.TZ = "Pacific/Pago_Pago";
      expect(dayText("2026-10-21")).toBe("Oct 21, 2026");
    } finally {
      if (before === undefined) delete process.env.TZ; else process.env.TZ = before;
    }
  });
});
