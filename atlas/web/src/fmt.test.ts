import { describe, expect, it } from "vitest";
import { ago, dir, num, pct, px } from "./fmt";

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
