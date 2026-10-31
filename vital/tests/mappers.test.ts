import { describe, expect, it } from 'vitest';
import {
  histogramFromZones,
  mapGarminActivity,
  mapGarminDay,
  type RawGarminActivity,
  type RawGarminSleep,
} from '../server/mappers/garmin';
import { histogramFromStream, mapStravaActivity, type RawStravaActivity } from '../server/mappers/strava';

/**
 * NOTE: these payloads are hand-written to match the documented / library-typed
 * response shapes. They have not been captured from the live services.
 */

describe('strava mapper', () => {
  const raw: RawStravaActivity = {
    id: 123456789,
    name: 'Morning Run',
    sport_type: 'TrailRun',
    start_date_local: '2026-10-30T07:05:09Z',
    moving_time: 2710,
    elapsed_time: 2800,
    distance: 8123.4,
    has_heartrate: true,
    average_heartrate: 151.4,
    max_heartrate: 176,
  };

  it('treats start_date_local as wall-clock time despite the trailing Z', () => {
    const a = mapStravaActivity(raw, null);
    expect(a.startLocal).toBe('2026-10-30T07:05:09');
    expect(a.id).toBe('strava-123456789');
    expect(a.sport).toBe('run');
    expect(a.durationSec).toBe(2710);
    expect(a.avgHr).toBe(151);
  });

  it('labels HR detail by what we actually have', () => {
    expect(mapStravaActivity(raw, null).hrBasis).toBe('average');
    expect(mapStravaActivity(raw, { 150: 100 }).hrBasis).toBe('stream');
    expect(mapStravaActivity({ ...raw, average_heartrate: undefined, max_heartrate: undefined, has_heartrate: false }, null).hrBasis).toBe('none');
  });

  it('builds a histogram from streams and ignores auto-pause gaps', () => {
    const time = [0, 1, 2, 3, 600, 601];
    const hr = [140, 140, 150, 150, 150, 150];
    const hist = histogramFromStream(time, hr)!;
    // 140: samples at t=0,1 → 1s each. 150: t=2 →1s, t=3 → capped at 15s (the 597s pause), t=4 → 1s, t=5 → last sample 1s.
    expect(hist[140]).toBe(2);
    expect(hist[150]).toBe(1 + 15 + 1 + 1);
  });

  it('skips garbage heart-rate readings', () => {
    expect(histogramFromStream([0, 1, 2], [0, 300, 20])).toBeNull();
  });
});

describe('garmin mapper — sleep day', () => {
  // 2026-10-30 23:10 → 2026-10-31 06:55 local
  const start = Date.UTC(2026, 9, 30, 23, 10, 0);
  const end = Date.UTC(2026, 9, 31, 6, 55, 0);
  const raw: RawGarminSleep = {
    dailySleepDTO: {
      sleepTimeSeconds: 26_400,
      sleepStartTimestampLocal: start,
      sleepEndTimestampLocal: end,
      deepSleepSeconds: 4_800,
      lightSleepSeconds: 14_400,
      remSleepSeconds: 7_200,
      awakeSleepSeconds: 1_500,
      averageRespirationValue: 14.2,
    },
    avgOvernightHrv: 58,
    restingHeartRate: 51,
  };

  it('converts Garmin local-as-UTC timestamps into wall-clock strings', () => {
    const d = mapGarminDay('2026-10-31', raw);
    expect(d.date).toBe('2026-10-31');
    expect(d.sleep!.startLocal).toBe('2026-10-30T23:10:00');
    expect(d.sleep!.endLocal).toBe('2026-10-31T06:55:00');
    expect(d.sleep!.inBedMin).toBe(465);
    expect(d.sleep!.asleepMin).toBe(440);
    expect(d.sleep!.stages).toEqual({ deepMin: 80, lightMin: 240, remMin: 120, awakeMin: 25 });
    expect(d.hrvMs).toBe(58);
    expect(d.restingHr).toBe(51);
    expect(d.respiration).toBe(14.2);
  });

  it('returns an empty day when the watch recorded nothing', () => {
    expect(mapGarminDay('2026-10-31', null).sleep).toBeNull();
    const d = mapGarminDay('2026-10-31', { dailySleepDTO: { sleepTimeSeconds: 0 }, avgOvernightHrv: 0, restingHeartRate: null });
    expect(d.sleep).toBeNull();
    expect(d.hrvMs).toBeNull();
    expect(d.restingHr).toBeNull();
  });
});

describe('garmin mapper — activities', () => {
  const raw: RawGarminActivity = {
    activityId: 987654321,
    activityName: 'Intervals',
    startTimeLocal: '2026-10-30 17:45:00',
    activityType: { typeKey: 'running' },
    duration: 3001.7,
    distance: 9870.2,
    averageHR: 156,
    maxHR: 182,
    calories: 640,
  };
  const zones = [
    { zoneNumber: 1, secsInZone: 300, zoneLowBoundary: 95 },
    { zoneNumber: 2, secsInZone: 600, zoneLowBoundary: 114 },
    { zoneNumber: 3, secsInZone: 900, zoneLowBoundary: 133 },
    { zoneNumber: 4, secsInZone: 1000, zoneLowBoundary: 152 },
    { zoneNumber: 5, secsInZone: 200, zoneLowBoundary: 171 },
  ];

  it('maps the activity list entry', () => {
    const a = mapGarminActivity(raw, null);
    expect(a.id).toBe('garmin-987654321');
    expect(a.startLocal).toBe('2026-10-30T17:45:00');
    expect(a.sport).toBe('run');
    expect(a.durationSec).toBe(3002);
    expect(a.hrBasis).toBe('average');
    expect(a.hrSeconds).toBeNull();
  });

  it('spreads zone time over the zone bpm range without losing seconds', () => {
    const hist = histogramFromZones(zones, 182)!;
    const total = Object.values(hist).reduce((a, b) => a + b, 0);
    expect(total).toBeCloseTo(3000, 6);
    // Zone 3 is 133..151 → 19 bpm, 900s
    expect(hist[133]).toBeCloseTo(900 / 19, 6);
    expect(hist[151]).toBeCloseTo(900 / 19, 6);
    expect(hist[152]).toBeCloseTo(1000 / 19, 6); // zone 4 is 152..170 → 19 bpm
    // Zone 5 runs up to max HR (171..182)
    expect(hist[182]).toBeCloseTo(200 / 12, 6);
    expect(hist[183]).toBeUndefined();
    expect(mapGarminActivity(raw, zones).hrBasis).toBe('zones');
  });

  it('returns null when there is no zone time', () => {
    expect(histogramFromZones([], 180)).toBeNull();
    expect(histogramFromZones([{ zoneNumber: 1, secsInZone: 0, zoneLowBoundary: 95 }], 180)).toBeNull();
  });
});
