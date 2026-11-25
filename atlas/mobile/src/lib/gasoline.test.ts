import { describe, expect, it } from "vitest";
import { crudeText } from "./gasoline";

describe("the gasoline card's crude sentence", () => {
  it("says nothing about a date when the crude price is the Monday's own", () => {
    expect(crudeText({ wti: 90.4, date: "2026-11-09", per_barrel: 167.79, gap: 77.39 }, "2026-11-09"))
      .toBe("That is $167.79 a barrel-equivalent (the price times 42 gallons) against WTI crude at $90.40 a barrel: a gap of $77.39 for refining, distribution, marketing and taxes.");
  });
  it("names the day of the crude price when it is older than the Monday, as on the day before the weekly crude release", () => {
    expect(crudeText({ wti: 89.53, date: "2026-11-17", per_barrel: 152.96, gap: 63.43 }, "2026-11-23"))
      .toBe("That is $152.96 a barrel-equivalent (the price times 42 gallons) against WTI crude at $89.53 a barrel (the price of Nov 17, 2026, the newest there is: crude prices come once a week, after the gasoline price): a gap of $63.43 for refining, distribution, marketing and taxes.");
  });
  it("keeps the old wording when the server sends no day, and never prints a raw date", () => {
    const text = crudeText({ wti: 90.4, per_barrel: 167.79, gap: 77.39 }, "2026-11-09");
    expect(text).toBe("That is $167.79 a barrel-equivalent (the price times 42 gallons) against WTI crude at $90.40 a barrel: a gap of $77.39 for refining, distribution, marketing and taxes.");
    expect(crudeText({ wti: 90.4, per_barrel: 167.79, gap: 77.39 }, undefined)).toBe(text);
    expect(crudeText({ wti: 89.53, date: "2026-11-17", per_barrel: 152.96, gap: 63.43 }, "2026-11-23")).not.toMatch(/\d{4}-\d{2}-\d{2}/);
  });
  it("writes money with two decimals", () => {
    expect(crudeText({ wti: 100, date: "2026-11-09", per_barrel: 150.5, gap: 50.5 }, "2026-11-09")).toContain("$150.50 a barrel-equivalent");
    expect(crudeText({ wti: 100, date: "2026-11-09", per_barrel: 150.5, gap: 50.5 }, "2026-11-09")).toContain("WTI crude at $100.00 a barrel: a gap of $50.50");
  });
});
