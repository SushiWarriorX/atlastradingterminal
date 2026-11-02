// Display helpers. Prices and figures inside findings are already formatted by the server; these are only for values the device draws itself
// (the chart scrubber, times in the viewer's timezone). Price rules mirror the backend so both always agree.

export function formatPrice(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "n/a";
  const a = Math.abs(v);
  if (a >= 1) return `$${v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  if (a >= 0.01) return `$${v.toFixed(4)}`;
  if (a === 0) return "$0.00";
  return `$${v.toFixed(6).replace(/0+$/, "").replace(/\.$/, "")}`;
}

export function formatPct(v: number | null | undefined, digits = 2, signed = true): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "n/a";
  const s = Math.abs(v).toFixed(digits);
  return signed ? `${v < 0 ? "−" : "+"}${s}%` : `${v < 0 ? "−" : ""}${s}%`;
}

export function directionOf(v: number | null | undefined): "up" | "down" | "flat" {
  if (v === null || v === undefined || !Number.isFinite(v) || v === 0) return "flat";
  return v > 0 ? "up" : "down";
}

export function relativeTime(iso: string | null | undefined, nowMs: number): string {
  if (!iso) return "unknown time";
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return "unknown time";
  const s = Math.max(0, Math.floor((nowMs - t) / 1000));
  if (s < 45) return "just now";
  if (s < 3600) return `${Math.max(1, Math.round(s / 60))}m ago`;
  if (s < 86_400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86_400)}d ago`;
}

/** "in 4d 3h" / "in 2h 15m" / "in 12m" / "now or past". The caller passes the current time so this stays pure. */
export function countdown(iso: string | null | undefined, nowMs: number): string {
  if (!iso) return "";
  const s = Math.floor((Date.parse(iso) - nowMs) / 1000);
  if (!Number.isFinite(s)) return "";
  if (s <= 0) return "now or past";
  const d = Math.floor(s / 86_400), h = Math.floor((s % 86_400) / 3600), m = Math.floor((s % 3600) / 60);
  return d > 0 ? `in ${d}d ${h}h` : h > 0 ? `in ${h}h ${m}m` : `in ${Math.max(1, m)}m`;
}

/** A UTC timestamp in the viewer's own timezone (or the one given), with the zone abbreviation: "Dec 9, 2:00 PM EST". */
export function localDateTime(iso: string | null | undefined, tz?: string): string {
  if (!iso) return "n/a";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "n/a";
  return d.toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZoneName: "short", ...(tz ? { timeZone: tz } : {}) });
}

export function localClock(iso: string | null | undefined, tz?: string, seconds = false): string {
  if (!iso) return "n/a";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "n/a";
  return d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", ...(seconds ? { second: "2-digit" } : {}), ...(tz ? { timeZone: tz } : {}) });
}

/** A calendar date like "2026-12-09" shown as "Dec 9" without timezone shifting. */
export function dateOnly(ymd: string | null | undefined): string {
  if (!ymd) return "n/a";
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(ymd);
  if (!m) return ymd;
  return new Date(Date.UTC(+m[1], +m[2] - 1, +m[3])).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
}

export function initials(symbol: string): string {
  const s = symbol.replace(/[^A-Za-z0-9]/g, "").toUpperCase();
  return s.slice(0, s.length > 3 ? 2 : 3) || "?";
}

/** A stable hue (0-359) from an asset id, so the same asset always gets the same avatar colour. */
export function hueFor(id: string): number {
  let h = 0;
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) >>> 0;
  return h % 360;
}

export const TYPE_LABEL = { crypto: "Crypto", stock: "Stock", etf: "ETF" } as const;

const PROVIDERS: Record<string, string> = { yahoo: "Yahoo Finance", coinbase: "Coinbase", demo: "Demo data", ibkr: "Interactive Brokers", fred: "FRED" };
export function providerName(p: string | null | undefined): string {
  return p ? PROVIDERS[p] ?? p : "unknown source";
}
