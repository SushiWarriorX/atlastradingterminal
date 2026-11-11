import { describe, expect, it } from "vitest";
import { ago, dir, num, pct, px, ymdLabel } from "./fmt";

describe("fmt", () => {
  it("never renders missing values as numbers", () => {
    expect(num(null)).toBe("—");
    expect(num(NaN)).toBe("—");
    expect(px(undefined)).toBe("—");
    expect(pct(null)).toBe("—");
    expect(ago(null)).toBe("—");
    expect(dir(null)).toBe("");
  });
  it("formats prices and signed percentages", () => {
    expect(px(69866.664)).toBe("69,866.66");
    expect(px(0.12345)).toBe("0.1235");
    expect(pct(1.234)).toBe("+1.23%");
    expect(pct(-0.5)).toBe("-0.50%");
    expect(dir(0)).toBe("up");
    expect(dir(-1)).toBe("down");
  });
  it("describes age", () => {
    expect(ago(new Date(Date.now() - 30_000).toISOString())).toBe("30s ago");
    expect(ago(new Date(Date.now() - 600_000).toISOString())).toBe("10m ago");
  });
});

describe("ymdLabel", () => {
  it("writes source dates in words and never shifts the day", () => {
    expect(ymdLabel("2026-11-06")).toBe("Nov 6, 2026");
    expect(ymdLabel("2026-01-01")).toBe("Jan 1, 2026");
    expect(ymdLabel("2026-12-31T23:59:00Z")).toBe("Dec 31, 2026");
  });
  it("shows empty as empty and unreadable values unchanged", () => {
    expect(ymdLabel(null)).toBe("");
    expect(ymdLabel(undefined)).toBe("");
    expect(ymdLabel("soon")).toBe("soon");
    expect(ymdLabel("2026-13-45")).toBe("2026-13-45");
  });
});
