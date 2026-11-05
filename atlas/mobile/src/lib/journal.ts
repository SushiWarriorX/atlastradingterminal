import type { JournalEntry } from "../api/types";

export const FORM_FIELDS = ["symbol", "direction", "size", "entry_price", "exit_price", "entry_at", "exit_at", "fees", "planned_stop", "note", "thesis", "risk_plan", "outcome"] as const;
export type JournalForm = Record<(typeof FORM_FIELDS)[number], string> & { screenshot: string | null };

export const blankForm = (today: string): JournalForm => ({ symbol: "", direction: "long", size: "", entry_price: "", exit_price: "", entry_at: today, exit_at: "", fees: "", planned_stop: "", note: "", thesis: "", risk_plan: "", outcome: "", screenshot: null });

const day = (iso: string | null) => (iso ? iso.slice(0, 10) : "");

export function fromEntry(e: JournalEntry): JournalForm {
  return {
    symbol: e.symbol, direction: e.direction, size: e.size ?? "", entry_price: e.entry_price ?? "", exit_price: e.exit_price ?? "", entry_at: day(e.entry_at), exit_at: day(e.exit_at),
    fees: e.fees && e.fees !== "0" ? e.fees : "", planned_stop: e.planned_stop ?? "", note: e.note ?? "", thesis: e.thesis ?? "", risk_plan: e.risk_plan ?? "", outcome: e.outcome ?? "", screenshot: e.screenshot ?? null,
  };
}

/** What to send. A new entry sends only the fields that were filled in; an edit also sends emptied optional fields as null so the server clears them. */
export function toBody(form: JournalForm, editing: boolean): Record<string, string | null> {
  const body: Record<string, string | null> = {};
  for (const k of FORM_FIELDS) {
    const v = form[k].trim();
    const required = k === "symbol" || k === "direction" || k === "entry_at";      // these can be changed but never cleared
    if (required || !editing) { if (v) body[k] = v; }
    else body[k] = v || null;
  }
  if (editing) body.screenshot = form.screenshot; else if (form.screenshot) body.screenshot = form.screenshot;
  return body;
}

export const signed = (x: number | null | undefined, digits = 2): string => (x === null || x === undefined ? "—" : `${x >= 0 ? "+" : "−"}${Math.abs(x).toFixed(digits)}`);

/** The one-line result shown in the list: a P&L for a closed trade, "Open" for one still running, nothing for a plain note. */
export function resultText(e: JournalEntry): string {
  return e.status === "closed" ? signed(e.net_pnl_num) : e.status === "open" ? "Open" : "";
}

/** Why a P&L is missing, in plain words, or null when there is one (or when it is just a note). */
export function missingText(e: JournalEntry): string | null {
  if (e.status === "closed" || e.status === "note" || !e.pnl_missing.length) return null;
  return `P&L needs the ${e.pnl_missing.join(" and ")}.`;
}
