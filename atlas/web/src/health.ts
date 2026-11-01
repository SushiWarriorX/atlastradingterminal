export type CheckState = "OK" | "STALE" | "DEGRADED" | "INVALID" | "UNAVAILABLE" | "NOT_CONFIGURED" | "DEMO";
export type Step = "pass" | "fail" | "skipped";
export interface CheckRow {
  provider: string; label: string; group: string; state: CheckState; connectivity: Step; structure: Step; quality: Step;
  freshness: string | null; observed_at: string | null; age_seconds: number | null; issues: string[]; error: string | null; action: string | null;
  estimated_requests: number | null; requests_note: string | null; detail: string | null; duration_ms?: number;
}
export interface CheckResult { checked_at: string; duration_ms: number; demo: boolean; estimated_requests: number; unknown_request_providers: string[]; cooldown_seconds: number; rows: CheckRow[]; note: string }
export interface CheckState_ { last: CheckResult | null; cooldown_left: number; running: boolean }

/** Plain-English names. NOT CONFIGURED (not set up), UNAVAILABLE (set up but not answering) and DEMO (synthetic) are deliberately different. */
export const STATE_TEXT: Record<CheckState, string> = {
  OK: "OK", STALE: "OK but old", DEGRADED: "Partly working", INVALID: "Bad data", UNAVAILABLE: "Unavailable", NOT_CONFIGURED: "Not configured", DEMO: "Demo (synthetic)",
};
export const STATE_HELP: Record<CheckState, string> = {
  OK: "Reachable, correctly shaped, valid numbers.", STALE: "Working, but the newest data is older than expected.",
  DEGRADED: "Some parts work and some do not.", INVALID: "It answered, but the content was wrong or unusable. Do not trust it.",
  UNAVAILABLE: "Set up, but we could not get an answer.", NOT_CONFIGURED: "Not switched on or not set up. Nothing is wrong.",
  DEMO: "Demo mode: synthetic data, no real check was made.",
};
export const stateClass = (s: CheckState): string => (s === "OK" ? "up" : s === "UNAVAILABLE" || s === "INVALID" ? "down" : s === "NOT_CONFIGURED" || s === "DEMO" ? "dim" : "warnc");
export const stepText = (s: Step): string => (s === "pass" ? "✓" : s === "fail" ? "✗" : "–");
