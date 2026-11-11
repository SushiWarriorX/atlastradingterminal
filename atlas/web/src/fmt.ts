export function num(x: number | null | undefined, d = 2): string {
  if (x === null || x === undefined || !Number.isFinite(x)) return "—";
  return x.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
}
export function px(x: number | null | undefined): string {
  if (x === null || x === undefined) return "—";
  return num(x, Math.abs(x) >= 1000 ? 2 : Math.abs(x) >= 1 ? 2 : 4);
}
export function pct(x: number | null | undefined): string {
  return x === null || x === undefined ? "—" : `${x >= 0 ? "+" : ""}${x.toFixed(2)}%`;
}
export function sgn(x: number | null | undefined, d = 2): string {
  return x === null || x === undefined ? "—" : `${x >= 0 ? "+" : ""}${num(x, d)}`;
}
export const dir = (x: number | null | undefined) => (x === null || x === undefined ? "" : x >= 0 ? "up" : "down");
export function ago(iso: string | null | undefined): string {
  if (!iso) return "—";
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  return s < 90 ? `${Math.round(s)}s ago` : s < 5400 ? `${Math.round(s / 60)}m ago` : s < 129600 ? `${Math.round(s / 3600)}h ago` : `${Math.round(s / 86400)}d ago`;
}
export function clock(tz: string, d = new Date()): string {
  return d.toLocaleTimeString("en-GB", { timeZone: tz, hour12: false });
}
export function nyDate(d = new Date()): string {
  return d.toLocaleDateString("en-US", { timeZone: "America/New_York", weekday: "short", month: "short", day: "2-digit", year: "numeric" });
}
/** A source date written in words ("Nov 6, 2026"). Takes the date part of an ISO string only; anything unreadable comes back unchanged so a bad value is visible, never hidden. */
export function ymdLabel(iso?: string | null): string {
  if (!iso) return "";
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (!m) return iso;
  const d = new Date(`${m[1]}-${m[2]}-${m[3]}T12:00:00Z`);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
}
/** Rewrites every ISO date inside a sentence the server wrote ("previous UTC day (2026-11-10)") into words ("previous UTC day (Nov 10, 2026)"). Text without dates is returned unchanged. */
export function wordDates(text?: string | null): string {
  return (text ?? "").replace(/\b(20\d\d-\d\d-\d\d)\b/g, (m) => ymdLabel(m));
}
