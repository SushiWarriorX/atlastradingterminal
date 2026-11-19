import type { PaperAccount } from "../api/types";

/** A ratio as a percentage with a real minus and thousands separators: 0.702 -> "+70.2%", 7.935 -> "+793.5%". A value that rounds to nothing is shown as a plain "0.0%", never as a gain or a loss. */
export function pctOf(ratio: number | null | undefined, digits = 1, signed = true): string {
  if (ratio === null || ratio === undefined || !Number.isFinite(ratio)) return "n/a";
  const v = ratio * 100;
  if (Number(Math.abs(v).toFixed(digits)) === 0) return `${(0).toFixed(digits)}%`;
  const body = Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
  return `${v < 0 ? "−" : signed ? "+" : ""}${body}%`;
}

export function money(x: number | null | undefined): string {
  if (x === null || x === undefined || !Number.isFinite(x)) return "n/a";
  const body = Math.abs(x).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return `${x < 0 ? "−" : ""}$${body}`;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "2026-11-15T00:00:00Z" -> "00:00 UTC · 15 Nov". The daily run works in UTC, so times are shown in UTC whatever the phone's zone. An unreadable time gives "". */
export function whenLabel(iso: string | null | undefined): string {
  const d = new Date(iso ?? "");
  if (Number.isNaN(d.getTime())) return "";
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(d.getUTCHours())}:${p(d.getUTCMinutes())} UTC · ${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]}`;
}

/** "2026-11-14" -> "14 Nov 2026" (no time zone shifting). Anything that is not a date is returned as it came. */
export function dayLabel(ymd: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(ymd);
  return m ? `${+m[3]} ${MONTHS[+m[2] - 1]} ${m[1]}` : ymd;
}

/** At most n values, evenly spread, always keeping the first and the last. */
export function sample(values: number[], n: number): number[] {
  if (n < 2 || values.length <= n) return values;
  return Array.from({ length: n }, (_, i) => values[Math.round((i * (values.length - 1)) / (n - 1))]);
}

const RUNNING = ["champion", "challenger", "monitor"];

/** The accounts in the order the page shows them: the main portfolio, the two benchmarks (hold first), and the strategies (champions, then challengers, then monitors, each by name). */
export function split(accounts: PaperAccount[]): { portfolio: PaperAccount | null; benchmarks: PaperAccount[]; strategies: PaperAccount[] } {
  const rank = (a: PaperAccount) => RUNNING.indexOf(a.stage);
  return {
    portfolio: accounts.find((a) => a.stage === "portfolio") ?? null,
    benchmarks: ["buy_hold", "cash"].map((id) => accounts.find((a) => a.id === id)).filter((a): a is PaperAccount => !!a),
    strategies: accounts.filter((a) => rank(a) >= 0).sort((a, b) => rank(a) - rank(b) || a.name.localeCompare(b.name) || a.id.localeCompare(b.id)),
  };
}

export type Tone = "up" | "down" | "warn" | "dim";
export function outcomeTone(outcome: string | null | undefined): Tone {
  return outcome === "admitted" ? "up" : outcome === "rejected" ? "down" : outcome === "too_thin" ? "warn" : "dim";
}

/** The random-timing result in words: p is the share of randomly shifted copies of the rule's own schedule that did at least as well on 2023-2024. */
export function chanceText(p: number | null | undefined): string {
  if (p === null || p === undefined || !Number.isFinite(p)) return "";
  return `About ${Math.round(p * 100)} of every 100 randomly shifted copies of its schedule did at least as well on 2023-2024 (5 or fewer was needed).`;
}

/** What the paper (forward) record of one account says so far. */
export function paperLine(a: Pick<PaperAccount, "days" | "return" | "trades">): string {
  if (a.days === 0) return "Paper: day 0, no trades yet";
  return `Paper: day ${a.days}, ${pctOf(a.return, 2)}, ${a.trades} trade${a.trades === 1 ? "" : "s"}`;
}

/** One line about one period of the research run: "2020-2022: +41.0% (holding: +130.3%)". */
export function periodLine(label: string, p: { return: number | null; hold_return: number | null } | null | undefined): string {
  return p ? `${label}: ${pctOf(p.return)} (holding: ${pctOf(p.hold_return)})` : `${label}: n/a`;
}

/** The paper account's equity since it opened as a line for a small chart (a ratio of its start, beginning at 1). Nothing to draw until it has two daily closes. */
export function forwardLine(a: Pick<PaperAccount, "forward">): number[] | null {
  return a.forward.length >= 2 ? [1, ...a.forward] : null;
}
