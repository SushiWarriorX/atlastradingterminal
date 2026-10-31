/** Normalised data model shared by the server adapters, the demo generator and the UI. */

export type Source = 'demo' | 'strava' | 'garmin';

export type Sport = 'run' | 'ride' | 'swim' | 'strength' | 'walk' | 'hike' | 'yoga' | 'other';

/**
 * How detailed the heart-rate data behind an activity is.
 *  - stream:  second-by-second samples (best)
 *  - zones:   time in each HR zone (coarse)
 *  - average: only the average HR is known
 *  - none:    no heart-rate data at all
 */
export type HrBasis = 'stream' | 'zones' | 'average' | 'none';

export interface SleepStages {
  lightMin: number;
  deepMin: number;
  remMin: number;
  awakeMin: number;
}

export interface SleepRecord {
  /** Local wall-clock time, 'YYYY-MM-DDTHH:mm:ss' (no timezone). */
  startLocal: string;
  endLocal: string;
  inBedMin: number;
  asleepMin: number;
  stages: SleepStages | null;
}

/** One cycle, keyed by the date you woke up on. */
export interface DayRecord {
  date: string; // 'YYYY-MM-DD'
  sleep: SleepRecord | null;
  /** Overnight average HRV (RMSSD, ms). */
  hrvMs: number | null;
  restingHr: number | null;
  /** Overnight respiration, breaths per minute. */
  respiration: number | null;
}

export interface Activity {
  id: string;
  source: Source;
  name: string;
  sport: Sport;
  startLocal: string;
  durationSec: number;
  distanceM: number | null;
  avgHr: number | null;
  maxHr: number | null;
  calories: number | null;
  /** Seconds spent at each heart rate (bpm -> seconds), or null when unknown. */
  hrSeconds: Record<number, number> | null;
  hrBasis: HrBasis;
}

export interface Snapshot {
  days: DayRecord[];
  activities: Activity[];
}

export interface Profile {
  maxHr: number;
  /** Hours of sleep you need on an average, unstrained day. */
  sleepBaselineHours: number;
  /** Selects the TRIMP weighting coefficient. */
  sex: 'male' | 'female';
}

export const DEFAULT_PROFILE: Profile = { maxHr: 190, sleepBaselineHours: 8, sex: 'male' };

export const emptyDay = (date: string): DayRecord => ({
  date,
  sleep: null,
  hrvMs: null,
  restingHr: null,
  respiration: null,
});
