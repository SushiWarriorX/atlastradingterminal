import type { Activity, Profile } from '../types';
import { clamp } from './math';
import type { ZoneSplit } from './types';

/**
 * Strain: a 0–21 logarithmic-style score of cardiovascular load.
 *
 * Load is Banister's TRIMP (heart-rate-reserve weighted minutes), summed per
 * day, then squashed so each extra unit of strain costs more than the last.
 * This is our own transparent model — it is NOT Whoop's proprietary algorithm.
 */
export const MAX_STRAIN = 21;
/** Load at which strain reaches ~63% of the scale (≈13.3). */
export const STRAIN_SCALE = 150;

/** Zone lower bounds as a fraction of max HR: Z1 50%, Z2 60%, Z3 70%, Z4 80%, Z5 90%. */
export const ZONE_FLOORS = [0.5, 0.6, 0.7, 0.8, 0.9] as const;

export function trimp(
  hrSeconds: Record<number, number>,
  restHr: number,
  maxHr: number,
  sex: Profile['sex'],
): number {
  const b = sex === 'female' ? 1.67 : 1.92;
  const reserve = Math.max(1, maxHr - restHr);
  let total = 0;
  for (const [bpm, secs] of Object.entries(hrSeconds)) {
    const x = clamp((Number(bpm) - restHr) / reserve, 0, 1);
    if (x <= 0 || !(secs > 0)) continue;
    total += (secs / 60) * x * 0.64 * Math.exp(b * x);
  }
  return total;
}

/** The best available HR distribution for an activity (falls back to a flat average). */
export function activityHistogram(a: Activity): Record<number, number> | null {
  if (a.hrSeconds && Object.keys(a.hrSeconds).length > 0) return a.hrSeconds;
  if (a.avgHr && a.avgHr > 0 && a.durationSec > 0) return { [Math.round(a.avgHr)]: a.durationSec };
  return null;
}

export function strainFromLoad(load: number): number {
  if (!(load > 0)) return 0;
  return MAX_STRAIN * (1 - Math.exp(-load / STRAIN_SCALE));
}

export function zoneSplit(hr: Record<number, number> | null, maxHr: number): ZoneSplit {
  const out: ZoneSplit = [0, 0, 0, 0, 0, 0];
  if (!hr) return out;
  for (const [bpm, secs] of Object.entries(hr)) {
    const frac = Number(bpm) / maxHr;
    let zone = 0;
    for (const floor of ZONE_FLOORS) if (frac >= floor) zone++;
    out[zone] += secs;
  }
  return out;
}
