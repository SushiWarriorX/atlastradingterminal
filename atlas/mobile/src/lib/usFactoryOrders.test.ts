import { describe, expect, it } from "vitest";
import type { UsFactoryOrdersData } from "../api/types";
import { checkText, durableText, gapsText, headlineText, itemText, monthText } from "./usFactoryOrders";

type Item = NonNullable<UsFactoryOrdersData["full"]>[number];
const item = (key: string, label: string, millions: number, cm: number, cmp: number | null, cy: number, cyp: number | null, share_pct?: number): Item =>
  ({ key, label, millions, change_month_millions: cm, change_month_pct: cmp, change_year_millions: cy, change_year_pct: cyp, ...(share_pct == null ? {} : { share_pct }) });
const full = [item("orders", "New orders", 677247, 12243, 1.8, 64373, 10.5), item("shipments", "Shipments", 668454, 8823, 1.3, 61932, 10.2),
  item("inventories", "Inventories", 976044, 3740, 0.4, 29350, 3.1), item("unfilled", "Unfilled orders", 1623818, 13781, 0.9, 133682, 9.0)];
const detail = { months_checked: 141, first_month: "2015-01", last_month: "2026-09", durable_last_month: "2026-10", largest_sum_gap: 0, largest_equal_gap: 0,
  newest_common: { month: "2026-09", orders: -270, shipments: 83, inventories: -516, unfilled: -326 } };

describe("the headline", () => {
  it("says what the four totals were, in billions and trillions", () => {
    expect(headlineText(full, "September 2026")).toBe("In September 2026 US manufacturers took new orders of $677.2 billion, shipped $668.5 billion, held $976.0 billion of inventories at the month end and were still owed $1.624 trillion of unfilled orders.");
  });
  it("falls back to the item's own label for a key it does not know and still ends with one full stop", () => {
    expect(headlineText([item("backlog", "Backlog", 5000, 0, 0, 0, 0)], "May 2026")).toBe("In May 2026 US manufacturers had backlog of $5.0 billion.");
    expect(headlineText([item("orders", "New orders", 5000, 0, 0, 0, 0), item("shipments", "Shipments", 4000, 0, 0, 0, 0)], "May 2026")).toBe("In May 2026 US manufacturers took new orders of $5.0 billion and shipped $4.0 billion.");
  });
});

describe("one figure in a line", () => {
  it("writes the level, the month change and the year change with their direction and per cent", () => {
    expect(itemText(full[0])).toBe("New orders: $677.2 billion; on the month up $12.2 billion (up 1.8%), on a year earlier up $64.4 billion (up 10.5%).");
    expect(itemText(full[3])).toBe("Unfilled orders: $1.624 trillion; on the month up $13.8 billion (up 0.9%), on a year earlier up $133.7 billion (up 9.0%).");
  });
  it("names what a share is a share of, by key", () => {
    expect(itemText(item("orders", "Nondurable goods orders and shipments", 331575, 5756, 1.8, 32848, 11.0, 49.0)))
      .toBe("Nondurable goods orders and shipments: $331.6 billion (49.0% of all new orders); on the month up $5.8 billion (up 1.8%), on a year earlier up $32.8 billion (up 11.0%).");
    expect(itemText(item("inventories", "Nondurable goods inventories", 365685, 1681, 0.5, 8783, 2.5, 37.5)))
      .toBe("Nondurable goods inventories: $365.7 billion (37.5% of all inventories); on the month up $1.7 billion (up 0.5%), on a year earlier up $8.8 billion (up 2.5%).");
    expect(itemText(item("other", "Other", 100000, 0, 0, 0, 0, 12.34))).toContain("(12.3% of the total)");
  });
  it("words a fall, a move too small to show and a figure with nothing to compare with", () => {
    expect(itemText(item("shipments", "Shipments", 653231, -7059, -1.1, 10000, 1.6))).toBe("Shipments: $653.2 billion; on the month down $7.1 billion (down 1.1%), on a year earlier up $10.0 billion (up 1.6%).");
    expect(itemText(item("shipments", "Shipments", 653231, 40, 0, 0, 0))).toBe("Shipments: $653.2 billion; on the month unchanged (unchanged), on a year earlier unchanged (unchanged).");
    expect(itemText(item("shipments", "Shipments", 653231, 775, 0, -300, 0))).toBe("Shipments: $653.2 billion; on the month up $0.8 billion (under 0.1%), on a year earlier down $0.3 billion (under 0.1%).");
    expect(itemText(item("shipments", "Shipments", 653231, 775, null, 775, null))).toBe("Shipments: $653.2 billion; on the month up $0.8 billion (not available), on a year earlier up $0.8 billion (not available).");
  });
});

describe("the month of the durable goods", () => {
  it("says it is a month later than the rest when the advance report is ahead, and the same month when it is not", () => {
    expect(durableText("October 2026", true)).toBe("The durable goods figures are for October 2026, a month later than the rest: they come from the advance report, which is out before the full report for that month.");
    expect(durableText("September 2026", false)).toBe("The durable goods figures are for September 2026, the same month as the rest.");
  });
});

describe("the gaps where the two reports meet", () => {
  it("states each gap in millions with the side it falls on, and says it is a difference of date and not an error", () => {
    expect(gapsText(detail.newest_common, "September 2026")).toBe("In September 2026, the newest month both reports cover, total new orders were $270 million below the durable and nondurable orders added up, "
      + "total shipments $83 million above the durable and nondurable shipments added up, total inventories $516 million below the durable and nondurable inventories added up and total unfilled orders $326 million below the durable ones. "
      + "The durable figures come from the later advance report, so this is a difference of date and not an error; these gaps are not part of the checks.");
  });
  it("keeps a decimal and a thousands separator, and says equal for a gap of nothing", () => {
    expect(gapsText({ month: "2026-09", orders: 1234.5, shipments: 0, inventories: -0.5, unfilled: 12000 }, "September 2026")).toContain("total new orders were $1,234.5 million above the durable and nondurable orders added up, total shipments equal to the durable and nondurable shipments added up, total inventories $0.5 million below");
    expect(gapsText({ month: "2026-09", orders: 1, shipments: 0, inventories: 0, unfilled: 0 }, "September 2026")).toContain("total unfilled orders equal to the durable ones");
  });
  it("is one short sentence when every gap is nothing", () => {
    expect(gapsText({ month: "2026-09", orders: 0, shipments: 0, inventories: 0, unfilled: 0 }, "September 2026")).toBe("In September 2026, the newest month both reports cover, the totals equalled the durable and nondurable figures added up and total unfilled orders equalled the durable ones.");
  });
});

describe("one of the last months", () => {
  it("writes the orders, their change on the month before and the shipments", () => {
    expect(monthText({ month: "2026-04", orders: 665895, orders_change: 33245, shipments: 642896 }, "April 2026")).toBe("April 2026: new orders $665.9 billion (up $33.2 billion on the month before), shipments $642.9 billion");
    expect(monthText({ month: "2026-05", orders: 658836, orders_change: -7059, shipments: 653231 }, "May 2026")).toBe("May 2026: new orders $658.8 billion (down $7.1 billion on the month before), shipments $653.2 billion");
    expect(monthText({ month: "2026-06", orders: 657790, orders_change: 0, shipments: 653505 }, "June 2026")).toBe("June 2026: new orders $657.8 billion (unchanged on the month before), shipments $653.5 billion");
  });
});

describe("the check line", () => {
  it("states the counts it was given, names the extra durable month and keeps the gaps to four decimals", () => {
    expect(checkText(detail)).toBe("Check: in each of the 141 months from January 2015 to September 2026 the 7 series of the full report covered the same months with none missing, the 6 durable series the same months and October 2026 as well, and every figure lay inside its range (plain checks, not the source's sums). "
      + "The Census Bureau's own arithmetic held to within the rounding, which shows that the series belong to one survey, not that the figures are right: total new orders, shipments and inventories each equalled their durable plus nondurable figure (the largest gap was 0 million, and 1.5 is allowed), "
      + "nondurable goods orders equalled their shipments and total unfilled orders equalled the durable ones (the largest gap was 0 million, and 1 is allowed), and orders excluding transportation and core capital goods orders never exceeded durable goods orders. "
      + "The newest month both reports cover is left out of the sums and the unfilled orders comparison (its gaps are shown above).");
    const t = checkText({ ...detail, months_checked: 1234, largest_sum_gap: 1.23456, largest_equal_gap: 0.5 });
    expect(t).toContain("each of the 1,234 months");
    expect(t).toContain("the largest gap was 1.2346 million, and 1.5 is allowed");
    expect(t).toContain("the largest gap was 0.5 million, and 1 is allowed");
  });
  it("does not name an extra durable month when the durable series end with the others", () => {
    const t = checkText({ ...detail, durable_last_month: "2026-09" });
    expect(t).toContain("covered the same months with none missing, the 6 durable series the same months, and every figure lay inside its range");
    expect(t).not.toContain("as well");
  });
  it("says the checks do not show that the figures are right", () => {
    expect(checkText(detail)).toContain("not that the figures are right");
    expect(checkText(detail).startsWith("Check:")).toBe(true);
  });
});
