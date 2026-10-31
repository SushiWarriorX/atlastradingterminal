import type { Profile, SleepRecord } from '../types';
import { minuteOfDay } from '../dates';
import { clamp, round, sd } from './math';
import { MAX_STRAIN } from './strain';
import type { SleepNeed } from './types';

/**
 * Sleep need = your baseline
 *            + up to 45 min for yesterday's strain (scaled by strain ÷ 21)
 *            + a quarter of the last five nights' shortfall (max 60 min).
 */
export const MAX_STRAIN_ADJ_MIN = 45;
export const MAX_DEBT_ADJ_MIN = 60;
export const DEBT_WINDOW = 5;

/** The part of tonight's need that doesn't depend on debt. */
export function baseNeedMin(profile: Profile, prevStrain: number | null): { baselineMin: number; strainMin: number } {
  const baselineMin = profile.sleepBaselineHours * 60;
  const strainMin = ((prevStrain ?? 0) / MAX_STRAIN) * MAX_STRAIN_ADJ_MIN;
  return { baselineMin, strainMin };
}

export function sleepNeed(profile: Profile, prevStrain: number | null, debtMin: number): SleepNeed {
  const { baselineMin, strainMin } = baseNeedMin(profile, prevStrain);
  const debtAdj = clamp(0.25 * debtMin, 0, MAX_DEBT_ADJ_MIN);
  return {
    baselineMin,
    strainMin: round(strainMin),
    debtMin: round(debtAdj),
    totalMin: round(baselineMin + strainMin + debtAdj),
  };
}

/** Sum of recent shortfalls against the (debt-free) need for each night. */
export function sleepDebt(recent: { asleepMin: number | null; needMin: number }[]): number {
  return recent
    .slice(-DEBT_WINDOW)
    .reduce((sum, n) => (n.asleepMin == null ? sum : sum + Math.max(0, n.needMin - n.asleepMin)), 0);
}

export const sleepPerformance = (asleepMin: number, needMin: number): number =>
  needMin > 0 ? clamp(round((asleepMin / needMin) * 100), 0, 100) : 0;

export const sleepEfficiency = (s: SleepRecord): number =>
  s.inBedMin > 0 ? clamp(round((s.asleepMin / s.inBedMin) * 100), 0, 100) : 0;

/**
 * 100 = identical bed and wake times, 0 = ±2 h of drift (std-dev). Needs ≥3 nights.
 * Bedtimes are shifted past midnight so 23:30 and 00:30 sit one hour apart.
 */
export function sleepConsistency(sleeps: SleepRecord[]): number | null {
  if (sleeps.length < 3) return null;
  const bed = sleeps.map((s) => {
    const m = minuteOfDay(s.startLocal);
    return m < 12 * 60 ? m + 24 * 60 : m;
  });
  const wake = sleeps.map((s) => minuteOfDay(s.endLocal));
  const drift = (sd(bed) + sd(wake)) / 2;
  return clamp(round(100 - (drift * 100) / 120), 0, 100);
}
