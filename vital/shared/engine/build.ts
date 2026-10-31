import { dateOf, dateRange } from '../dates';
import { emptyDay, type Activity, type DayRecord, type Profile, type SleepRecord, type Snapshot } from '../types';
import { strainTarget } from './coach';
import { BASELINE_WINDOW, MIN_BASELINE_DAYS, computeBaselines, computeRecovery } from './recovery';
import {
  baseNeedMin,
  sleepConsistency,
  sleepDebt,
  sleepEfficiency,
  sleepNeed,
  sleepPerformance,
} from './sleep';
import { activityHistogram, strainFromLoad, trimp, zoneSplit } from './strain';
import type { DayScores, ScoredActivity, SleepScores, ZoneSplit } from './types';

/** Used for load until we've seen enough resting-HR readings. */
const DEFAULT_REST_HR = 60;
const CONSISTENCY_NIGHTS = 5;

function scoreActivity(a: Activity, restHr: number, profile: Profile): ScoredActivity {
  const hist = activityHistogram(a);
  const load = hist ? trimp(hist, restHr, profile.maxHr, profile.sex) : 0;
  return { activity: a, load, strain: strainFromLoad(load), zones: zoneSplit(hist, profile.maxHr) };
}

const addZones = (a: ZoneSplit, b: ZoneSplit): ZoneSplit =>
  a.map((v, i) => v + b[i]) as ZoneSplit;

/**
 * Turns raw days + activities into a dense, day-by-day timeline of scores.
 * Every calendar date between the first and last data point appears, even if empty.
 */
export function buildTimeline(snapshot: Snapshot, profile: Profile): DayScores[] {
  const dayMap = new Map<string, DayRecord>(snapshot.days.map((d) => [d.date, d]));
  const actMap = new Map<string, Activity[]>();
  for (const a of snapshot.activities) {
    const key = dateOf(a.startLocal);
    const list = actMap.get(key);
    if (list) list.push(a);
    else actMap.set(key, [a]);
  }

  const known = [...dayMap.keys(), ...actMap.keys()].sort();
  if (known.length === 0) return [];
  const dates = dateRange(known[0], known[known.length - 1]);
  const records = dates.map((d) => dayMap.get(d) ?? emptyDay(d));

  const out: DayScores[] = [];
  /** Per night: how much we slept, and the debt-free need — used to compute debt. */
  const nights: { asleepMin: number | null; needMin: number }[] = [];

  records.forEach((record, i) => {
    const prior = records.slice(Math.max(0, i - BASELINE_WINDOW), i);
    const baselines = computeBaselines(prior);
    const restHr = Math.round(baselines.rhr?.mean ?? record.restingHr ?? DEFAULT_REST_HR);

    // --- strain
    const activities = (actMap.get(record.date) ?? [])
      .slice()
      .sort((a, b) => a.startLocal.localeCompare(b.startLocal))
      .map((a) => scoreActivity(a, restHr, profile));
    const load = activities.reduce((s, a) => s + a.load, 0);
    const strain = strainFromLoad(load);
    const zones = activities.reduce<ZoneSplit>((z, a) => addZones(z, a.zones), [0, 0, 0, 0, 0, 0]);

    // --- sleep
    const prevStrain = i > 0 ? out[i - 1].strain : null;
    const { baselineMin, strainMin } = baseNeedMin(profile, prevStrain);
    const night: SleepRecord | null = record.sleep;
    const debt = sleepDebt(nights);
    const need = sleepNeed(profile, prevStrain, debt);
    nights.push({ asleepMin: night?.asleepMin ?? null, needMin: baselineMin + strainMin });

    let sleep: SleepScores | null = null;
    if (night) {
      const recent = records
        .slice(Math.max(0, i - CONSISTENCY_NIGHTS + 1), i + 1)
        .map((r) => r.sleep)
        .filter((s): s is SleepRecord => s != null);
      sleep = {
        startLocal: night.startLocal,
        endLocal: night.endLocal,
        asleepMin: night.asleepMin,
        inBedMin: night.inBedMin,
        need,
        performance: sleepPerformance(night.asleepMin, need.totalMin),
        efficiency: sleepEfficiency(night),
        consistency: sleepConsistency(recent),
        stages: night.stages,
      };
    }

    // --- recovery
    const recovery = computeRecovery(record, prior, sleep?.performance ?? null);
    const hasPhysiology = record.hrvMs != null || record.restingHr != null;
    const priorWithHrv = prior.filter((d) => d.hrvMs != null || d.restingHr != null).length;

    out.push({
      date: record.date,
      record,
      recovery,
      recoveryStatus: recovery ? 'ok' : hasPhysiology ? 'calibrating' : 'no-data',
      calibrationDaysLeft: Math.max(0, MIN_BASELINE_DAYS - priorWithHrv),
      strain,
      load,
      activities,
      zones,
      sleep,
      target: recovery ? strainTarget(recovery.score) : null,
      baselines,
    });
  });

  return out;
}
