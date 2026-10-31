export function fmtDuration(min: number): string {
  const t = Math.max(0, Math.round(min));
  const h = Math.floor(t / 60);
  const m = t % 60;
  return h > 0 ? `${h}h ${String(m).padStart(2, '0')}m` : `${m}m`;
}

export function fmtDistance(meters: number | null): string {
  if (meters == null) return '–';
  const km = meters / 1000;
  return `${km.toFixed(km < 10 ? 2 : 1)} km`;
}

/** Pace in min/km from distance and time. */
export function fmtPace(meters: number | null, seconds: number): string {
  if (!meters || meters < 100 || seconds <= 0) return '–';
  const perKm = seconds / (meters / 1000);
  const m = Math.floor(perKm / 60);
  const s = Math.round(perKm % 60);
  return s === 60 ? `${m + 1}:00 /km` : `${m}:${String(s).padStart(2, '0')} /km`;
}

export function fmtTime(local: string): string {
  return local.slice(11, 16);
}

const dayFmt = new Intl.DateTimeFormat('en-GB', { weekday: 'short', day: 'numeric', month: 'short', timeZone: 'UTC' });
const weekdayFmt = new Intl.DateTimeFormat('en-GB', { weekday: 'short', timeZone: 'UTC' });

export const fmtDay = (date: string): string => dayFmt.format(new Date(`${date}T00:00:00Z`));
export const fmtWeekday = (date: string): string => weekdayFmt.format(new Date(`${date}T00:00:00Z`));
export const fmtDayNum = (date: string): string => String(Number(date.slice(8, 10)));
