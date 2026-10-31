export function num(x: number | null | undefined, d = 2): string {
  if (x === null || x === undefined || Number.isNaN(x)) return "—";
  return x.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
}
export function px(x: number | null | undefined): string {
  if (x === null || x === undefined) return "—";
  return num(x, Math.abs(x) >= 1000 ? 2 : Math.abs(x) >= 1 ? 2 : 4);
}
export function pct(x: number | null | undefined): string {
  return x === null || x === undefined ? "—" : `${x >= 0 ? "+" : ""}${x.toFixed(2)}%`;
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
