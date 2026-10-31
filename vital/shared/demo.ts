import { addDays, dateRange, wallIso, wallMs, weekday } from './dates';
import { MAX_STRAIN, strainFromLoad, trimp } from './engine/strain';
import type { Activity, DayRecord, Snapshot, Sport } from './types';

/**
 * Deterministic synthetic data with realistic structure: hard training lowers
 * next-day HRV and raises resting HR, weekends shift bedtimes, and ~1 night in
 * 10 is disrupted (alcohol, illness, stress). Used for the demo mode and tests.
 */

function mulberry32(seed: number) {
  let a = seed;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

interface Template {
  sport: Sport;
  name: string;
  minutes: [number, number];
  /** Mixture of normal HR distributions the session spends its time in. */
  mix: { w: number; mean: number; sd: number }[];
  /** Seconds per km (run/walk) or km/h (ride) used to derive distance. */
  pace?: number;
  speedKmh?: number;
  startHour: number;
}

const EASY_RUN: Template = { sport: 'run', name: 'Easy run', minutes: [38, 55], mix: [{ w: 1, mean: 141, sd: 6 }], pace: 350, startHour: 6.5 };
const INTERVALS: Template = {
  sport: 'run',
  name: 'Intervals',
  minutes: [48, 58],
  mix: [{ w: 0.55, mean: 138, sd: 7 }, { w: 0.45, mean: 171, sd: 5 }],
  pace: 320,
  startHour: 17.75,
};
const TEMPO: Template = {
  sport: 'run',
  name: 'Tempo run',
  minutes: [50, 62],
  mix: [{ w: 0.25, mean: 140, sd: 6 }, { w: 0.75, mean: 163, sd: 5 }],
  pace: 305,
  startHour: 6.25,
};
const LONG_RIDE: Template = { sport: 'ride', name: 'Long ride', minutes: [105, 150], mix: [{ w: 1, mean: 140, sd: 10 }], speedKmh: 27, startHour: 8.5 };
const LONG_RUN: Template = { sport: 'run', name: 'Long run', minutes: [80, 105], mix: [{ w: 1, mean: 148, sd: 7 }], pace: 340, startHour: 8 };
const STRENGTH: Template = { sport: 'strength', name: 'Strength', minutes: [45, 60], mix: [{ w: 1, mean: 118, sd: 13 }], startHour: 18 };
const WALK: Template = { sport: 'walk', name: 'Evening walk', minutes: [30, 50], mix: [{ w: 1, mean: 98, sd: 8 }], pace: 660, startHour: 19 };

/** Sunday … Saturday */
const PLAN: Template[][] = [[LONG_RUN], [EASY_RUN], [INTERVALS], [STRENGTH], [TEMPO], [], [LONG_RIDE]];

const DEMO_REST_HR = 52;
const DEMO_MAX_HR = 190;

export function generateDemo(today: string, days = 120, seed = 7): Snapshot {
  const rnd = mulberry32(seed);
  const gauss = () => Math.sqrt(-2 * Math.log(1 - rnd())) * Math.cos(2 * Math.PI * rnd());
  const between = (lo: number, hi: number) => lo + (hi - lo) * rnd();

  const dates = dateRange(addDays(today, -(days - 1)), today);
  const outDays: DayRecord[] = [];
  const outActs: Activity[] = [];

  let fatigue = 1.25; // exponentially-weighted recent load, ~1.25 when training is steady

  dates.forEach((date, idx) => {
    const dow = weekday(date);
    const stressed = rnd() < 0.1;
    const s = stressed ? 1 : 0;
    const f = fatigue - 1.25;

    // ---- last night's physiology
    const hrvMs = Math.exp(
      Math.log(62) + 0.05 * Math.sin((2 * Math.PI * idx) / 28) - 0.2 * f - 0.2 * s + 0.09 * gauss(),
    );
    const restingHr = 52 + 3 * f + 3.5 * s + 1.2 * gauss();
    const respiration = 14.6 + 0.4 * f + 0.6 * s + 0.25 * gauss();

    const weekendNight = dow === 0 || dow === 6; // woke Sat/Sun → slept Fri/Sat night
    const asleepMin = Math.round(Math.min(560, Math.max(300, 462 + (weekendNight ? 25 : 0) - 40 * s + 35 * gauss())));
    const efficiency = Math.min(0.95, Math.max(0.8, 0.89 + 0.03 * gauss()));
    const inBedMin = Math.round(asleepMin / efficiency);
    const bedMinute = 22 * 60 + 45 + (weekendNight ? 45 : 0) + (stressed ? 60 : 0) + Math.round(25 * gauss());
    const startMs = wallMs(addDays(date, -1)) + bedMinute * 60_000;
    const deep = Math.round(asleepMin * (0.17 + 0.02 * gauss()));
    const rem = Math.round(asleepMin * (0.22 + 0.02 * gauss()));

    outDays.push({
      date,
      hrvMs: Math.round(hrvMs * 10) / 10,
      restingHr: Math.round(restingHr),
      respiration: Math.round(respiration * 10) / 10,
      sleep: {
        startLocal: wallIso(startMs),
        endLocal: wallIso(startMs + inBedMin * 60_000),
        inBedMin,
        asleepMin,
        stages: {
          deepMin: deep,
          remMin: rem,
          lightMin: asleepMin - deep - rem,
          awakeMin: inBedMin - asleepMin,
        },
      },
    });

    // ---- today's training
    const isToday = date === today;
    let sessions = PLAN[dow].filter(() => rnd() > 0.12);
    if (dow === 5 && rnd() < 0.5) sessions = [WALK]; // some rest days still include a walk
    if (isToday) sessions = sessions.filter((t) => t.startHour < 9); // only what's plausibly already happened

    const actHists: Record<number, number>[] = [];
    sessions.forEach((t, k) => {
      const minutes = Math.round(between(t.minutes[0], t.minutes[1]));
      const durationSec = minutes * 60;

      // Discretised mixture of normals → seconds at each bpm.
      const hist: Record<number, number> = {};
      let total = 0;
      for (let bpm = 60; bpm <= DEMO_MAX_HR + 5; bpm++) {
        let w = 0;
        for (const c of t.mix) w += (c.w / c.sd) * Math.exp(-0.5 * ((bpm - c.mean) / c.sd) ** 2);
        if (w > 1e-4) {
          hist[bpm] = w;
          total += w;
        }
      }
      let avg = 0;
      let max = 0;
      for (const key of Object.keys(hist)) {
        const bpm = Number(key);
        hist[bpm] = Math.round(((hist[bpm] / total) * durationSec) * 10) / 10;
        avg += bpm * hist[bpm];
        if (hist[bpm] >= 1) max = Math.max(max, bpm);
      }
      avg /= durationSec;
      actHists.push(hist);

      const startMin = Math.round(t.startHour * 60 + between(-10, 10));
      const distanceM = t.pace
        ? Math.round((durationSec / t.pace) * 1000)
        : t.speedKmh
          ? Math.round(((durationSec / 3600) * t.speedKmh) * 1000)
          : null;

      outActs.push({
        id: `demo-${date}-${k}`,
        source: 'demo',
        name: t.name,
        sport: t.sport,
        startLocal: wallIso(wallMs(date) + startMin * 60_000),
        durationSec,
        distanceM,
        avgHr: Math.round(avg),
        maxHr: max,
        calories: Math.round(minutes * (t.sport === 'walk' ? 4.5 : t.sport === 'strength' ? 6 : 10.5)),
        hrSeconds: hist,
        hrBasis: 'stream',
      });
    });

    // ---- carry today's load into tomorrow's fatigue
    const load = actHists.reduce((sum, h) => sum + trimp(h, DEMO_REST_HR, DEMO_MAX_HR, 'male'), 0);
    fatigue = 0.6 * fatigue + strainFromLoad(load) / MAX_STRAIN;
  });

  return { days: outDays, activities: outActs };
}
