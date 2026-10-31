import type { Activity, DayRecord, SleepStages } from '../types';

export type RecoveryZone = 'green' | 'yellow' | 'red';

export interface Stat {
  mean: number;
  sd: number;
  n: number;
}

/** Rolling personal baselines. HRV is modelled in log space. */
export interface Baselines {
  hrvLn: Stat | null;
  rhr: Stat | null;
  resp: Stat | null;
  /** Geometric mean of recent HRV, for display. */
  hrvMs: number | null;
}

export interface RecoveryResult {
  score: number; // 0–100
  zone: RecoveryZone;
  /** Standardised contribution of each input (positive = better than your norm). */
  z: { hrv: number | null; rhr: number | null; resp: number | null; sleep: number | null };
}

/** Seconds: below zone 1, then zones 1–5. */
export type ZoneSplit = [number, number, number, number, number, number];

export interface StrainTarget {
  low: number;
  high: number;
  label: 'Push' | 'Maintain' | 'Recover';
}

export interface SleepNeed {
  baselineMin: number;
  strainMin: number;
  debtMin: number;
  totalMin: number;
}

export interface SleepScores {
  startLocal: string;
  endLocal: string;
  asleepMin: number;
  inBedMin: number;
  need: SleepNeed;
  /** Sleep ÷ need, capped at 100. */
  performance: number;
  /** Asleep ÷ in bed. */
  efficiency: number;
  /** Regularity of bed/wake times over the last few nights, or null with <3 nights. */
  consistency: number | null;
  stages: SleepStages | null;
}

export interface ScoredActivity {
  activity: Activity;
  load: number;
  /** Strain this activity would produce on its own. */
  strain: number;
  zones: ZoneSplit;
}

export interface DayScores {
  date: string;
  record: DayRecord;
  recovery: RecoveryResult | null;
  recoveryStatus: 'ok' | 'calibrating' | 'no-data';
  calibrationDaysLeft: number;
  /** 0–21 */
  strain: number;
  load: number;
  activities: ScoredActivity[];
  zones: ZoneSplit;
  sleep: SleepScores | null;
  target: StrainTarget | null;
  baselines: Baselines;
}
