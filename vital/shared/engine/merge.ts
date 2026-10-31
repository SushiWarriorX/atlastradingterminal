import { wallMs } from '../dates';
import type { Activity, DayRecord, HrBasis, Snapshot } from '../types';

const RANK: Record<HrBasis, number> = { stream: 3, zones: 2, average: 1, none: 0 };

const SAME_START_MS = 5 * 60_000;
const SAME_DURATION_RATIO = 0.25;

/** Garmin usually syncs to Strava, so the same workout can arrive from both. */
export function isSameWorkout(a: Activity, b: Activity): boolean {
  if (Math.abs(wallMs(a.startLocal) - wallMs(b.startLocal)) > SAME_START_MS) return false;
  const longest = Math.max(a.durationSec, b.durationSec, 1);
  return Math.abs(a.durationSec - b.durationSec) / longest <= SAME_DURATION_RATIO;
}

function fillMissing(primary: DayRecord, other: DayRecord): DayRecord {
  return {
    date: primary.date,
    sleep: primary.sleep ?? other.sleep,
    hrvMs: primary.hrvMs ?? other.hrvMs,
    restingHr: primary.restingHr ?? other.restingHr,
    respiration: primary.respiration ?? other.respiration,
  };
}

/**
 * Combine several sources. Earlier snapshots win for health data; for duplicate
 * workouts the one with the richest heart-rate data wins (ties go to the earlier source).
 */
export function mergeSnapshots(snaps: Snapshot[]): Snapshot {
  const days = new Map<string, DayRecord>();
  for (const snap of snaps) {
    for (const d of snap.days) {
      const cur = days.get(d.date);
      days.set(d.date, cur ? fillMissing(cur, d) : d);
    }
  }

  const kept: Activity[] = [];
  for (const a of snaps.flatMap((s) => s.activities)) {
    const idx = kept.findIndex((k) => isSameWorkout(k, a));
    if (idx === -1) kept.push(a);
    else if (RANK[a.hrBasis] > RANK[kept[idx].hrBasis]) kept[idx] = a;
  }

  return {
    days: [...days.values()].sort((x, y) => x.date.localeCompare(y.date)),
    activities: kept.sort((x, y) => x.startLocal.localeCompare(y.startLocal)),
  };
}
