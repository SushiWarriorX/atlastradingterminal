import { describe, expect, it } from "vitest";
import { fmtChange, fmtValue, MacroFact } from "./macro";

describe("macro formatting", () => {
  it("formats changes in their own units", () => {
    expect(fmtChange({ label: "", ref_date: "", value: 25, unit: "bps" })).toBe("+25 bps");
    expect(fmtChange({ label: "", ref_date: "", value: -0.4, unit: "percentage points" })).toBe("−0.40 pp");
    expect(fmtChange({ label: "", ref_date: "", value: 1.234, unit: "%" })).toBe("+1.23%");
    expect(fmtChange({ label: "", ref_date: "", value: null, unit: "bps" })).toBe("n/a");
  });
  it("formats values by indicator", () => {
    const f = (o: Partial<MacroFact>): MacroFact => ({ id: "x", label: "x", ...o });
    expect(fmtValue(f({ id: "fed", lower: 3.75, upper: 4 }))).toBe("3.75–4.00%");
    expect(fmtValue(f({ id: "curve", value: -35.4 }))).toBe("−35 bps");
    expect(fmtValue(f({ id: "cpi", unit: "% year-over-year", value: 3.04 }))).toBe("3.04%");
    expect(fmtValue(f({ id: "usd", unit: "index", value: 120.123 }))).toBe("120.12");
    expect(fmtValue(f({ id: "us10y" }))).toBe("n/a");
  });
});
