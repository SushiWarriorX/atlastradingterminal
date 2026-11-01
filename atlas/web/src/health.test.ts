import { describe, expect, it } from "vitest";
import { CheckState, STATE_HELP, STATE_TEXT, stateClass, stepText } from "./health";

describe("provider check labels", () => {
  const all: CheckState[] = ["OK", "STALE", "DEGRADED", "INVALID", "UNAVAILABLE", "NOT_CONFIGURED", "DEMO"];
  it("every state has text and help, and the three 'no data' states read differently", () => {
    for (const s of all) { expect(STATE_TEXT[s]).toBeTruthy(); expect(STATE_HELP[s]).toBeTruthy(); }
    expect(new Set(["NOT_CONFIGURED", "UNAVAILABLE", "DEMO"].map((s) => STATE_TEXT[s as CheckState])).size).toBe(3);
  });
  it("styles failures red, healthy green and not-set-up neutral", () => {
    expect(stateClass("OK")).toBe("up"); expect(stateClass("UNAVAILABLE")).toBe("down"); expect(stateClass("INVALID")).toBe("down");
    expect(stateClass("NOT_CONFIGURED")).toBe("dim"); expect(stateClass("DEMO")).toBe("dim"); expect(stateClass("STALE")).toBe("warnc");
  });
  it("renders step marks", () => { expect(stepText("pass")).toBe("✓"); expect(stepText("fail")).toBe("✗"); expect(stepText("skipped")).toBe("–"); });
});
