/**
 * Date helpers. Everything is "local wall-clock" — strings like 2026-10-31 or
 * 2026-10-31T07:30:00 with no timezone — so there is no DST or UTC drift.
 * UTC is only used internally as a convenient calendar calculator.
 */

const pad = (n: number) => String(n).padStart(2, '0');

export function toDateString(d: Date): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

export const todayLocal = (now: Date = new Date()): string => toDateString(now);

function parts(date: string): [number, number, number] {
  const [y, m, d] = date.slice(0, 10).split('-').map(Number);
  return [y, m, d];
}

export function addDays(date: string, n: number): string {
  const [y, m, d] = parts(date);
  return new Date(Date.UTC(y, m - 1, d + n)).toISOString().slice(0, 10);
}

/** b - a, in whole days. */
export function daysBetween(a: string, b: string): number {
  const [y1, m1, d1] = parts(a);
  const [y2, m2, d2] = parts(b);
  return Math.round((Date.UTC(y2, m2 - 1, d2) - Date.UTC(y1, m1 - 1, d1)) / 86_400_000);
}

export function dateRange(from: string, to: string): string[] {
  const out: string[] = [];
  const n = daysBetween(from, to);
  for (let i = 0; i <= n; i++) out.push(addDays(from, i));
  return out;
}

export const dateOf = (local: string): string => local.slice(0, 10);

export function minuteOfDay(local: string): number {
  return Number(local.slice(11, 13)) * 60 + Number(local.slice(14, 16));
}

/** Treat a local wall-clock string as if it were UTC so differences are plain arithmetic. */
export function wallMs(local: string): number {
  return Date.parse(local.length <= 10 ? `${local}T00:00:00Z` : `${local.slice(0, 19)}Z`);
}

export function wallIso(ms: number): string {
  return new Date(ms).toISOString().slice(0, 19);
}

/** 0 = Sunday. */
export function weekday(date: string): number {
  const [y, m, d] = parts(date);
  return new Date(Date.UTC(y, m - 1, d)).getUTCDay();
}
