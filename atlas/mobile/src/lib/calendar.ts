import type { CalendarEvent } from "../api/types";

export const KIND_LABEL: Record<string, string> = { earnings: "Earnings", economy: "Economy", rates: "Fed and rates", dividend: "Dividends", auction: "Treasury" };

/** Group events by date, keeping their order. */
export function groupByDay(items: CalendarEvent[]): { day: string; events: CalendarEvent[] }[] {
  const out: { day: string; events: CalendarEvent[] }[] = [];
  for (const e of items) {
    const last = out[out.length - 1];
    if (last && last.day === e.date) last.events.push(e); else out.push({ day: e.date, events: [e] });
  }
  return out;
}

export function dayLabel(iso: string, today: string): string {
  const d = new Date(iso + "T12:00:00Z");
  const w = d.toLocaleDateString("en-US", { weekday: "long", month: "short", day: "numeric", timeZone: "UTC" });
  const tomorrow = new Date(new Date(today + "T12:00:00Z").getTime() + 86400000).toISOString().slice(0, 10);
  return iso === today ? `Today · ${w}` : iso === tomorrow ? `Tomorrow · ${w}` : w;
}

const usd = (x: unknown) => (typeof x === "number" ? `$${x.toFixed(2)}` : "n/a");

/** One plain line of detail for an event, using only what the source gave (n/a otherwise). */
export function detailLine(e: CalendarEvent): string {
  const d = e.details;
  if (e.kind === "earnings") return `Estimate ${usd(d.eps_estimate)}${d.analysts ? ` (${d.analysts} analysts)` : ""} · a year ago ${usd(d.last_year_eps)}${d.quarter_ending ? ` · quarter ending ${d.quarter_ending}` : ""}`;
  if (e.kind === "dividend") return `${usd(d.amount)} per share · pays ${d.pay_date ?? "n/a"}`;
  if (e.kind === "auction") return `Issued ${d.issue_date ?? "n/a"}`;
  return String(d.release ?? d.meeting ?? "");
}

export const importanceColor = (i: CalendarEvent["importance"], c: { down: string; warn: string; faint: string }) => (i === "high" ? c.down : i === "medium" ? c.warn : c.faint);
