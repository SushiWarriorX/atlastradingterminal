import { describe, expect, it } from "vitest";
import { moneyShort } from "./research";

describe("moneyShort", () => {
  it("keeps the unit honest at every size", () => {
    expect(moneyShort(12_300_000_000)).toBe("$12.30B");
    expect(moneyShort(450_000_000)).toBe("$450.0M");
    expect(moneyShort(12_500)).toBe("$12.5K");
    expect(moneyShort(340)).toBe("$340.00");
    expect(moneyShort(-1_500_000_000)).toBe("-$1.50B");
  });
  it("never turns a small non-zero amount into zero, and never turns missing into zero", () => {
    expect(moneyShort(500)).toBe("$500.00");
    expect(moneyShort(0.5)).toBe("$0.50");
    expect(moneyShort(null)).toBe("n/a");
    expect(moneyShort(undefined)).toBe("n/a");
    expect(moneyShort(Number.NaN)).toBe("n/a");
    expect(moneyShort(0)).toBe("$0.00");
  });
});
