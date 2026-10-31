import { wallIso } from '../../shared/dates';
import { normaliseSport } from '../../shared/sport';
import type { Activity, DayRecord } from '../../shared/types';
import { emptyDay } from '../../shared/types';

/** The subset of Garmin's daily sleep payload that we read (see garmin-connect's SleepData). */
export interface RawGarminSleep {
  dailySleepDTO?: {
    sleepTimeSeconds?: number | null;
    /** Epoch ms of the *local* wall-clock time, i.e. "local as if it were UTC". */
    sleepStartTimestampLocal?: number | null;
    sleepEndTimestampLocal?: number | null;
    deepSleepSeconds?: number | null;
    lightSleepSeconds?: number | null;
    remSleepSeconds?: number | null;
    awakeSleepSeconds?: number | null;
    averageRespirationValue?: number | null;
  } | null;
  avgOvernightHrv?: number | null;
  restingHeartRate?: number | null;
}

const positive = (n: number | null | undefined): number | null => (n != null && Number.isFinite(n) && n > 0 ? n : null);
const min = (sec: number | null | undefined) => Math.round((sec ?? 0) / 60);

/** `date` is the wake-up date (Garmin's `calendarDate`). */
export function mapGarminDay(date: string, raw: RawGarminSleep | null): DayRecord {
  const day = emptyDay(date);
  if (!raw) return day;

  day.hrvMs = positive(raw.avgOvernightHrv);
  day.restingHr = positive(raw.restingHeartRate);

  const dto = raw.dailySleepDTO;
  if (!dto) return day;
  day.respiration = positive(dto.averageRespirationValue);

  const asleepSec = positive(dto.sleepTimeSeconds);
  const start = dto.sleepStartTimestampLocal;
  const end = dto.sleepEndTimestampLocal;
  if (asleepSec && start && end && end > start) {
    day.sleep = {
      startLocal: wallIso(start),
      endLocal: wallIso(end),
      inBedMin: Math.round((end - start) / 60_000),
      asleepMin: min(asleepSec),
      stages: {
        deepMin: min(dto.deepSleepSeconds),
        lightMin: min(dto.lightSleepSeconds),
        remMin: min(dto.remSleepSeconds),
        awakeMin: min(dto.awakeSleepSeconds),
      },
    };
  }
  return day;
}

/** The subset of a Garmin activity-list entry that we read. */
export interface RawGarminActivity {
  activityId: number;
  activityName?: string | null;
  /** "2026-10-30 07:00:12" */
  startTimeLocal: string;
  activityType?: { typeKey?: string } | null;
  duration?: number | null;
  distance?: number | null;
  averageHR?: number | null;
  maxHR?: number | null;
  calories?: number | null;
}

/** One entry of `/activity-service/activity/{id}/hrTimeInZones`. */
export interface RawGarminZone {
  zoneNumber: number;
  secsInZone: number;
  zoneLowBoundary: number;
}

/**
 * Garmin only gives time per zone, so spread each zone's seconds evenly across
 * its bpm range. Coarser than a stream, but captures intensity far better than an average.
 */
export function histogramFromZones(zones: RawGarminZone[], maxHr: number | null): Record<number, number> | null {
  const sorted = zones.filter((z) => z.secsInZone > 0 || z.zoneLowBoundary > 0).sort((a, b) => a.zoneNumber - b.zoneNumber);
  const hist: Record<number, number> = {};
  let total = 0;
  sorted.forEach((z, i) => {
    if (!(z.secsInZone > 0)) return;
    const lo = Math.round(z.zoneLowBoundary);
    const next = sorted[i + 1];
    const hi = next ? Math.round(next.zoneLowBoundary) - 1 : Math.max(lo, Math.round(maxHr ?? lo + 15));
    const width = Math.max(1, hi - lo + 1);
    for (let bpm = lo; bpm < lo + width; bpm++) hist[bpm] = (hist[bpm] ?? 0) + z.secsInZone / width;
    total += z.secsInZone;
  });
  return total > 0 ? hist : null;
}

export function mapGarminActivity(raw: RawGarminActivity, zones: RawGarminZone[] | null): Activity {
  const hist = zones ? histogramFromZones(zones, raw.maxHR ?? null) : null;
  const avg = positive(raw.averageHR);
  return {
    id: `garmin-${raw.activityId}`,
    source: 'garmin',
    name: raw.activityName || 'Workout',
    sport: normaliseSport(raw.activityType?.typeKey),
    startLocal: raw.startTimeLocal.replace(' ', 'T').slice(0, 19),
    durationSec: Math.round(raw.duration ?? 0),
    distanceM: positive(raw.distance),
    avgHr: avg != null ? Math.round(avg) : null,
    maxHr: positive(raw.maxHR) != null ? Math.round(raw.maxHR as number) : null,
    calories: positive(raw.calories) != null ? Math.round(raw.calories as number) : null,
    hrSeconds: hist,
    hrBasis: hist ? 'zones' : avg != null ? 'average' : 'none',
  };
}
