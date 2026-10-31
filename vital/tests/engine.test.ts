import { describe, expect, it } from 'vitest';
import { addDays, dateRange, daysBetween, weekday } from '../shared/dates';
import { generateDemo } from '../shared/demo';
import { buildTimeline } from '../shared/engine/build';
import { coach, strainTarget } from '../shared/engine/coach';
import { mergeSnapshots } from '../shared/engine/merge';
import { computeRecovery, recoveryZone } from '../shared/engine/recovery';
import { sleepConsistency, sleepDebt, sleepNeed, sleepPerformance } from '../shared/engine/sleep';
import { strainFromLoad, trimp, zoneSplit } from '../shared/engine/strain';
import { normaliseSport } from '../shared/sport';
import { DEFAULT_PROFILE, emptyDay, type Activity, type DayRecord, type SleepRecord } from '../shared/types';

const TODAY = '2026-10-31';

describe('dates', () => {
  it('does calendar arithmetic across month and DST boundaries', () => {
    expect(addDays('2026-10-31', 1)).toBe('2026-11-01');
    expect(addDays('2026-03-01', -1)).toBe('2026-02-28');
    expect(daysBetween('2026-10-25', '2026-11-02')).toBe(8);
    expect(dateRange('2026-10-30', '2026-11-01')).toEqual(['2026-10-30', '2026-10-31', '2026-11-01']);
    expect(weekday('2026-10-31')).toBe(6); // Saturday
  });
});

describe('strain', () => {
  it('is zero without load and always below the 21 ceiling', () => {
    expect(strainFromLoad(0)).toBe(0);
    expect(strainFromLoad(-5)).toBe(0);
    expect(strainFromLoad(1e9)).toBeLessThan(21.0001);
  });

  it('rises monotonically with load, with diminishing returns', () => {
    const a = strainFromLoad(100);
    const b = strainFromLoad(200);
    const c = strainFromLoad(300);
    expect(b).toBeGreaterThan(a);
    expect(c).toBeGreaterThan(b);
    expect(c - b).toBeLessThan(b - a);
  });

  it('puts an hour at moderate effort around 8 and a hard hour around 15', () => {
    const rest = 52;
    const max = 190;
    const easy = trimp({ 135: 3600 }, rest, max, 'male'); // ~60% reserve
    const hard = trimp({ 176: 3600 }, rest, max, 'male'); // ~90% reserve
    expect(strainFromLoad(easy)).toBeGreaterThan(6);
    expect(strainFromLoad(easy)).toBeLessThan(10);
    expect(strainFromLoad(hard)).toBeGreaterThan(13);
    expect(strainFromLoad(hard)).toBeLessThan(17);
  });

  it('ignores heart rates at or below resting', () => {
    expect(trimp({ 40: 3600, 52: 3600 }, 52, 190, 'male')).toBe(0);
  });

  it('splits time into zones by % of max HR', () => {
    const z = zoneSplit({ 80: 60, 100: 60, 125: 60, 145: 60, 160: 60, 180: 60 }, 190);
    expect(z).toEqual([60, 60, 60, 60, 60, 60]);
  });
});

describe('recovery', () => {
  const baseline = (n: number, hrv = 60, rhr = 52): DayRecord[] =>
    Array.from({ length: n }, (_, i) => ({
      ...emptyDay(addDays('2026-10-01', i)),
      hrvMs: hrv + (i % 2 === 0 ? 2 : -2),
      restingHr: rhr + (i % 2 === 0 ? 1 : -1),
      respiration: 14.5 + (i % 2 === 0 ? 0.2 : -0.2),
    }));

  it('maps scores to red / yellow / green at 34 and 67', () => {
    expect(recoveryZone(33)).toBe('red');
    expect(recoveryZone(34)).toBe('yellow');
    expect(recoveryZone(66)).toBe('yellow');
    expect(recoveryZone(67)).toBe('green');
  });

  it('is calibrating until there are 4 nights of history', () => {
    const day = { ...emptyDay('2026-10-10'), hrvMs: 60, restingHr: 52 };
    expect(computeRecovery(day, baseline(3), 90)).toBeNull();
    expect(computeRecovery(day, baseline(4), 90)).not.toBeNull();
  });

  it('needs HRV or resting HR on the day', () => {
    const day = { ...emptyDay('2026-10-20'), respiration: 14.5 };
    expect(computeRecovery(day, baseline(14), 90)).toBeNull();
  });

  it('scores a high-HRV, low-RHR night green and the opposite red', () => {
    const prior = baseline(14);
    const great = computeRecovery({ ...emptyDay('x'), hrvMs: 78, restingHr: 49, respiration: 14.0 }, prior, 100)!;
    const awful = computeRecovery({ ...emptyDay('x'), hrvMs: 38, restingHr: 59, respiration: 15.8 }, prior, 55)!;
    const typical = computeRecovery({ ...emptyDay('x'), hrvMs: 60, restingHr: 52, respiration: 14.5 }, prior, 88)!;
    expect(great.zone).toBe('green');
    expect(awful.zone).toBe('red');
    expect(typical.score).toBeGreaterThan(awful.score);
    expect(typical.score).toBeLessThan(great.score);
    expect(great.score).toBeLessThanOrEqual(99);
    expect(awful.score).toBeGreaterThanOrEqual(1);
  });

  it('lets poor sleep pull an otherwise average night down', () => {
    const prior = baseline(14);
    const day = { ...emptyDay('x'), hrvMs: 60, restingHr: 52, respiration: 14.5 };
    expect(computeRecovery(day, prior, 50)!.score).toBeLessThan(computeRecovery(day, prior, 100)!.score);
  });

  it('copes with missing optional inputs', () => {
    const r = computeRecovery({ ...emptyDay('x'), hrvMs: 60 }, baseline(14), null)!;
    expect(r.z.rhr).toBeNull();
    expect(r.z.sleep).toBeNull();
    expect(Number.isFinite(r.score)).toBe(true);
  });
});

describe('sleep', () => {
  it('adds strain and debt to the baseline need', () => {
    const calm = sleepNeed(DEFAULT_PROFILE, 0, 0);
    expect(calm.totalMin).toBe(480);
    const strained = sleepNeed(DEFAULT_PROFILE, 21, 0);
    expect(strained.strainMin).toBe(45);
    expect(strained.totalMin).toBe(525);
    const indebted = sleepNeed(DEFAULT_PROFILE, 0, 200);
    expect(indebted.debtMin).toBe(50);
    expect(sleepNeed(DEFAULT_PROFILE, 0, 1000).debtMin).toBe(60); // capped
  });

  it('only counts shortfalls from the last five nights', () => {
    const nights = [
      { asleepMin: 300, needMin: 480 }, // too old once we add five more
      ...Array.from({ length: 5 }, () => ({ asleepMin: 450, needMin: 480 })),
    ];
    expect(sleepDebt(nights)).toBe(150);
    expect(sleepDebt([{ asleepMin: 600, needMin: 480 }])).toBe(0); // surplus is not banked
    expect(sleepDebt([{ asleepMin: null, needMin: 480 }])).toBe(0);
  });

  it('caps performance at 100', () => {
    expect(sleepPerformance(540, 480)).toBe(100);
    expect(sleepPerformance(240, 480)).toBe(50);
  });

  const night = (bed: string, wake: string): SleepRecord => ({
    startLocal: bed,
    endLocal: wake,
    inBedMin: 480,
    asleepMin: 440,
    stages: null,
  });

  it('rates identical schedules 100 and drifting ones lower, across midnight', () => {
    const steady = ['23:00', '23:00', '23:00'].map((b) => night(`2026-10-01T${b}:00`, '2026-10-02T07:00:00'));
    expect(sleepConsistency(steady)).toBe(100);
    const drifting = [night('2026-10-01T22:00:00', '2026-10-02T06:00:00'), night('2026-10-02T00:30:00', '2026-10-02T09:00:00'), night('2026-10-03T23:00:00', '2026-10-04T07:30:00')];
    expect(sleepConsistency(drifting)!).toBeLessThan(80);
    // 23:30 and 00:30 are 1 h apart, not 23 h
    const cross = [night('2026-10-01T23:30:00', '2026-10-02T07:00:00'), night('2026-10-03T00:30:00', '2026-10-03T07:00:00'), night('2026-10-03T23:30:00', '2026-10-04T07:00:00')];
    expect(sleepConsistency(cross)!).toBeGreaterThan(70);
  });

  it('needs three nights', () => {
    expect(sleepConsistency([night('2026-10-01T23:00:00', '2026-10-02T07:00:00')])).toBeNull();
  });
});

describe('coach', () => {
  it('sets harder targets for better recovery', () => {
    expect(strainTarget(80).low).toBeGreaterThan(strainTarget(50).low);
    expect(strainTarget(50).low).toBeGreaterThan(strainTarget(20).low);
    expect(strainTarget(20).label).toBe('Recover');
  });
});

describe('merge', () => {
  const act = (id: string, source: Activity['source'], start: string, dur: number, basis: Activity['hrBasis']): Activity => ({
    id,
    source,
    name: id,
    sport: 'run',
    startLocal: start,
    durationSec: dur,
    distanceM: null,
    avgHr: 150,
    maxHr: 170,
    calories: null,
    hrSeconds: null,
    hrBasis: basis,
  });

  it('collapses the same workout from two sources and keeps the richer HR data', () => {
    const garmin = { days: [], activities: [act('g', 'garmin', '2026-10-30T07:00:10', 3000, 'zones')] };
    const strava = { days: [], activities: [act('s', 'strava', '2026-10-30T07:00:40', 3010, 'stream')] };
    const merged = mergeSnapshots([garmin, strava]);
    expect(merged.activities).toHaveLength(1);
    expect(merged.activities[0].id).toBe('s');
  });

  it('keeps different workouts apart', () => {
    const a = { days: [], activities: [act('a', 'garmin', '2026-10-30T07:00:00', 3000, 'zones'), act('b', 'strava', '2026-10-30T18:00:00', 3000, 'stream')] };
    expect(mergeSnapshots([a]).activities).toHaveLength(2);
  });

  it('prefers the first source for health data and fills the gaps from others', () => {
    const garmin = { days: [{ ...emptyDay('2026-10-30'), hrvMs: 55 }], activities: [] };
    const other = { days: [{ ...emptyDay('2026-10-30'), hrvMs: 99, restingHr: 50 }], activities: [] };
    const [day] = mergeSnapshots([garmin, other]).days;
    expect(day.hrvMs).toBe(55);
    expect(day.restingHr).toBe(50);
  });
});

describe('sport', () => {
  it('normalises Strava and Garmin names', () => {
    expect(normaliseSport('TrailRun')).toBe('run');
    expect(normaliseSport('treadmill_running')).toBe('run');
    expect(normaliseSport('VirtualRide')).toBe('ride');
    expect(normaliseSport('mountain_biking')).toBe('ride');
    expect(normaliseSport('WeightTraining')).toBe('strength');
    expect(normaliseSport('strength_training')).toBe('strength');
    expect(normaliseSport('Kitesurf')).toBe('other');
    expect(normaliseSport(undefined)).toBe('other');
  });
});

describe('timeline on demo data', () => {
  const snapshot = generateDemo(TODAY);
  const timeline = buildTimeline(snapshot, DEFAULT_PROFILE);

  it('is deterministic', () => {
    expect(generateDemo(TODAY)).toEqual(snapshot);
    expect(generateDemo(TODAY, 120, 8)).not.toEqual(snapshot);
  });

  it('covers every day up to today with sane values', () => {
    expect(timeline).toHaveLength(120);
    expect(timeline.at(-1)!.date).toBe(TODAY);
    for (const d of timeline) {
      expect(d.strain).toBeGreaterThanOrEqual(0);
      expect(d.strain).toBeLessThan(21);
      expect(Number.isFinite(d.load)).toBe(true);
      if (d.recovery) {
        expect(d.recovery.score).toBeGreaterThanOrEqual(1);
        expect(d.recovery.score).toBeLessThanOrEqual(99);
      }
      if (d.sleep) {
        expect(d.sleep.performance).toBeLessThanOrEqual(100);
        expect(d.sleep.efficiency).toBeLessThanOrEqual(100);
      }
    }
  });

  it('calibrates first, then scores', () => {
    expect(timeline[0].recoveryStatus).toBe('calibrating');
    expect(timeline[0].calibrationDaysLeft).toBe(4);
    expect(timeline[3].recoveryStatus).toBe('calibrating');
    expect(timeline[4].recoveryStatus).toBe('ok');
    expect(timeline[10].calibrationDaysLeft).toBe(0);
  });

  it('produces a healthy spread of red, yellow and green days', () => {
    const scored = timeline.filter((d) => d.recovery);
    const count = (z: string) => scored.filter((d) => d.recovery!.zone === z).length / scored.length;
    expect(count('green')).toBeGreaterThan(0.2);
    expect(count('yellow')).toBeGreaterThan(0.2);
    expect(count('red')).toBeGreaterThan(0.03);
    expect(count('red')).toBeLessThan(0.35);
  });

  it('recovers worse the day after a hard day than after a rest day', () => {
    const after = (pick: (prev: number) => boolean) => {
      const xs = timeline.filter((d, i) => i > 4 && d.recovery && pick(timeline[i - 1].strain)).map((d) => d.recovery!.score);
      return xs.reduce((a, b) => a + b, 0) / xs.length;
    };
    expect(after((s) => s >= 13)).toBeLessThan(after((s) => s < 4));
  });

  it('gives every day with a workout a positive strain and zone time', () => {
    const trained = timeline.filter((d) => d.activities.length > 0);
    expect(trained.length).toBeGreaterThan(40);
    for (const d of trained) {
      expect(d.strain).toBeGreaterThan(0);
      expect(d.zones.reduce((a, b) => a + b, 0)).toBeGreaterThan(0);
    }
  });

  it('explains itself in plain language', () => {
    const today = timeline.at(-1)!;
    const c = coach(today);
    expect(c.headline.length).toBeGreaterThan(3);
    expect(c.body.length).toBeGreaterThan(20);
  });
});

describe('timeline on sparse live data', () => {
  it('returns nothing for an empty snapshot', () => {
    expect(buildTimeline({ days: [], activities: [] }, DEFAULT_PROFILE)).toEqual([]);
  });

  it('handles activities with no health data (Strava only)', () => {
    const a: Activity = {
      id: '1',
      source: 'strava',
      name: 'Run',
      sport: 'run',
      startLocal: '2026-10-30T07:00:00',
      durationSec: 3000,
      distanceM: 9000,
      avgHr: 150,
      maxHr: 170,
      calories: null,
      hrSeconds: null,
      hrBasis: 'average',
    };
    const tl = buildTimeline({ days: [], activities: [a] }, DEFAULT_PROFILE);
    expect(tl).toHaveLength(1);
    expect(tl[0].recoveryStatus).toBe('no-data');
    expect(tl[0].sleep).toBeNull();
    expect(tl[0].strain).toBeGreaterThan(0);
    expect(coach(tl[0]).headline).toMatch(/no overnight data/i);
  });

  it('leaves a gap day empty instead of inventing data', () => {
    const tl = buildTimeline(
      { days: [{ ...emptyDay('2026-10-01'), hrvMs: 60 }, { ...emptyDay('2026-10-04'), hrvMs: 61 }], activities: [] },
      DEFAULT_PROFILE,
    );
    expect(tl.map((d) => d.date)).toEqual(['2026-10-01', '2026-10-02', '2026-10-03', '2026-10-04']);
    expect(tl[1].recoveryStatus).toBe('no-data');
  });
});
