import { normaliseSport } from '../../shared/sport';
import type { Activity } from '../../shared/types';

/** The subset of Strava's SummaryActivity that we read. */
export interface RawStravaActivity {
  id: number;
  name: string;
  sport_type?: string;
  type?: string;
  /** Local wall-clock time but, confusingly, suffixed with "Z". */
  start_date_local: string;
  moving_time: number;
  elapsed_time?: number;
  distance?: number;
  has_heartrate?: boolean;
  average_heartrate?: number;
  max_heartrate?: number;
  calories?: number;
}

/** Longest gap we'll credit to a single sample, so auto-pauses don't count as effort. */
const MAX_SAMPLE_GAP_SEC = 15;

/** Seconds spent at each bpm from Strava's parallel `time` and `heartrate` streams. */
export function histogramFromStream(time: number[], heartrate: number[]): Record<number, number> | null {
  const hist: Record<number, number> = {};
  let samples = 0;
  const n = Math.min(time.length, heartrate.length);
  for (let i = 0; i < n; i++) {
    const hr = Math.round(heartrate[i]);
    if (!(hr > 30 && hr < 250)) continue;
    const gap = i + 1 < n ? time[i + 1] - time[i] : 1;
    const dt = Math.min(Math.max(gap, 0), MAX_SAMPLE_GAP_SEC);
    if (dt <= 0) continue;
    hist[hr] = (hist[hr] ?? 0) + dt;
    samples++;
  }
  return samples > 0 ? hist : null;
}

export function mapStravaActivity(raw: RawStravaActivity, hist: Record<number, number> | null): Activity {
  const avg = raw.average_heartrate ?? null;
  return {
    id: `strava-${raw.id}`,
    source: 'strava',
    name: raw.name,
    sport: normaliseSport(raw.sport_type ?? raw.type),
    startLocal: raw.start_date_local.replace(/Z$/, '').slice(0, 19),
    durationSec: raw.moving_time,
    distanceM: raw.distance != null && raw.distance > 0 ? raw.distance : null,
    avgHr: avg != null ? Math.round(avg) : null,
    maxHr: raw.max_heartrate != null ? Math.round(raw.max_heartrate) : null,
    calories: raw.calories ?? null,
    hrSeconds: hist,
    hrBasis: hist ? 'stream' : avg != null ? 'average' : 'none',
  };
}
