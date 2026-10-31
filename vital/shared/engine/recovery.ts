import type { DayRecord } from '../types';
import { clamp, mean, round, sd, sigmoid } from './math';
import type { Baselines, RecoveryResult, RecoveryZone, Stat } from './types';

/**
 * Recovery: how ready your body is today, 0–100, from last night's physiology
 * compared with YOUR rolling 30-day norm.
 *
 *   HRV (log)           50%   higher than usual is better
 *   Resting heart rate  25%   lower than usual is better
 *   Respiration          10%  lower than usual is better
 *   Sleep performance    15%  85% of need = neutral
 *
 * Each input becomes a z-score, the weighted mean is passed through a
 * logistic curve centred so an average night scores ~61.
 * Our own transparent model — NOT Whoop's proprietary algorithm.
 */
export const BASELINE_WINDOW = 30;
export const MIN_BASELINE_DAYS = 4;

const WEIGHTS = { hrv: 0.5, rhr: 0.25, resp: 0.1, sleep: 0.15 } as const;
/** Stops a very stable baseline from turning small wobbles into huge z-scores (day-to-day ln-HRV varies by ~0.1+ in real life). */
const SD_FLOOR = { hrvLn: 0.1, rhr: 1.5, resp: 0.4 } as const;
const Z_LIMIT = 3;

export function recoveryZone(score: number): RecoveryZone {
  if (score >= 67) return 'green';
  if (score >= 34) return 'yellow';
  return 'red';
}

function stat(values: number[]): Stat | null {
  if (values.length < MIN_BASELINE_DAYS) return null;
  return { mean: mean(values), sd: sd(values), n: values.length };
}

const present = (xs: (number | null)[]): number[] =>
  xs.filter((x): x is number => x != null && Number.isFinite(x) && x > 0);

/** `prior` = the days before the one being scored (up to BASELINE_WINDOW of them). */
export function computeBaselines(prior: DayRecord[]): Baselines {
  const hrvLn = stat(present(prior.map((d) => d.hrvMs)).map(Math.log));
  return {
    hrvLn,
    rhr: stat(present(prior.map((d) => d.restingHr))),
    resp: stat(present(prior.map((d) => d.respiration))),
    hrvMs: hrvLn ? Math.exp(hrvLn.mean) : null,
  };
}

const z = (value: number, s: Stat, floor: number) =>
  clamp((value - s.mean) / Math.max(s.sd, floor), -Z_LIMIT, Z_LIMIT);

/**
 * Returns null while calibrating (fewer than MIN_BASELINE_DAYS of history) or
 * when neither HRV nor resting HR was recorded.
 */
export function computeRecovery(
  day: DayRecord,
  prior: DayRecord[],
  sleepPerformance: number | null,
): RecoveryResult | null {
  const b = computeBaselines(prior);

  const parts: RecoveryResult['z'] = { hrv: null, rhr: null, resp: null, sleep: null };
  if (day.hrvMs && day.hrvMs > 0 && b.hrvLn) parts.hrv = z(Math.log(day.hrvMs), b.hrvLn, SD_FLOOR.hrvLn);
  if (day.restingHr && b.rhr) parts.rhr = -z(day.restingHr, b.rhr, SD_FLOOR.rhr);
  if (day.respiration && b.resp) parts.resp = -z(day.respiration, b.resp, SD_FLOOR.resp);

  // HRV or resting HR must be present — respiration/sleep alone aren't enough.
  if (parts.hrv == null && parts.rhr == null) return null;
  if (sleepPerformance != null) parts.sleep = clamp((sleepPerformance - 85) / 15, -Z_LIMIT, Z_LIMIT);

  let sum = 0;
  let weight = 0;
  for (const key of Object.keys(WEIGHTS) as (keyof typeof WEIGHTS)[]) {
    const v = parts[key];
    if (v == null) continue;
    sum += v * WEIGHTS[key];
    weight += WEIGHTS[key];
  }
  const combined = sum / weight;
  const score = clamp(round(100 * sigmoid(1.8 * (combined + 0.25))), 1, 99);
  return { score, zone: recoveryZone(score), z: parts };
}
