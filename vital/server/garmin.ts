import { createRequire } from 'node:module';
import type { GarminConnect as GarminClient } from 'garmin-connect';
import { addDays, dateRange, dateOf, todayLocal } from '../shared/dates';
import type { DayRecord, Snapshot } from '../shared/types';
import { config } from './env';
import {
  mapGarminActivity,
  mapGarminDay,
  type RawGarminActivity,
  type RawGarminSleep,
  type RawGarminZone,
} from './mappers/garmin';
import { TtlCache, readJson, removeFile, writeJson } from './store';

/**
 * Garmin has no public personal-data API. This uses the community `garmin-connect`
 * library, which signs in the same way the Garmin Connect web app does. It is
 * unofficial, can break whenever Garmin changes things, and is for personal use only.
 */

const TOKENS_FILE = 'garmin-tokens.json';
const DAYS_FILE = 'garmin-days.json';
const ZONES_FILE = 'garmin-zones.json';
const API = 'https://connectapi.garmin.com';

// garmin-connect is CommonJS and Node's ESM loader can't see its named exports, so load it explicitly.
const { GarminConnect } = createRequire(import.meta.url)('garmin-connect') as typeof import('garmin-connect');

type Tokens = ReturnType<GarminClient['exportToken']>;

export class GarminError extends Error {
  constructor(
    message: string,
    readonly status = 502,
  ) {
    super(message);
  }
}

export const garminConfigured = (): boolean => Boolean(config.garminEmail && config.garminPassword);
export const garminConnected = (): boolean => readJson<Tokens | null>(TOKENS_FILE, null) !== null;

let client: GarminClient | null = null;
let loginInFlight: Promise<GarminClient> | null = null;

export function disconnectGarmin(): void {
  client = null;
  removeFile(TOKENS_FILE);
  cache.clear();
}

async function getClient(): Promise<GarminClient> {
  if (client) return client;
  loginInFlight ??= (async () => {
    const c = new GarminConnect({ username: config.garminEmail, password: config.garminPassword });

    const saved = readJson<Tokens | null>(TOKENS_FILE, null);
    if (saved) {
      c.loadToken(saved.oauth1, saved.oauth2);
      try {
        await c.getUserProfile(); // cheap call that proves the saved tokens still work
        return c;
      } catch {
        // expired / revoked — fall through to a fresh login
      }
    }

    if (!garminConfigured()) {
      throw new GarminError('Set GARMIN_EMAIL and GARMIN_PASSWORD in .env, then restart the server', 400);
    }
    try {
      await c.login();
    } catch (e) {
      throw new GarminError(
        `Garmin sign-in failed (${e instanceof Error ? e.message : 'unknown error'}). Accounts with MFA are not supported.`,
        401,
      );
    }
    writeJson(TOKENS_FILE, c.exportToken());
    return c;
  })();
  try {
    client = await loginInFlight;
    return client;
  } finally {
    loginInFlight = null;
  }
}

/** Run `fn` over `items` with limited concurrency; stop early if `fn` throws StopSignal. */
class StopSignal extends Error {}

async function pool<T>(items: T[], size: number, fn: (item: T) => Promise<void>): Promise<boolean> {
  let stopped = false;
  for (let i = 0; i < items.length && !stopped; i += size) {
    await Promise.all(
      items.slice(i, i + size).map(async (item) => {
        try {
          await fn(item);
        } catch (e) {
          if (e instanceof StopSignal) stopped = true;
          else throw e;
        }
      }),
    );
  }
  return stopped;
}

export interface GarminMeta {
  days: number;
  activities: number;
  /** Days or workouts we couldn't load (rate limiting, transient errors). */
  failures: number;
}

const cache = new TtlCache<{ snapshot: Snapshot; meta: GarminMeta; days: number }>(5 * 60_000);

export async function fetchGarmin(days: number): Promise<{ snapshot: Snapshot; meta: GarminMeta }> {
  const hit = cache.get();
  if (hit && hit.days === days) return hit;

  const gc = await getClient();
  const today = todayLocal();
  const dates = dateRange(addDays(today, -(days - 1)), today);
  let failures = 0;

  // --- daily sleep / HRV / resting HR. Finished days are immutable, so cache them.
  const dayCache = readJson<Record<string, DayRecord>>(DAYS_FILE, {});
  const recentCutoff = addDays(today, -2);
  const toFetch = dates.filter((d) => !dayCache[d] || d > recentCutoff);
  await pool(toFetch, 3, async (date) => {
    try {
      const raw = await gc.get<RawGarminSleep>(`${API}/sleep-service/sleep/dailySleepData`, { params: { date } });
      dayCache[date] = mapGarminDay(date, raw);
    } catch (e) {
      failures++;
      if (/429|too many/i.test(e instanceof Error ? e.message : '')) throw new StopSignal();
    }
  });
  writeJson(DAYS_FILE, dayCache);
  const dayRecords = dates.map((d) => dayCache[d]).filter((d): d is DayRecord => Boolean(d));

  // --- activities (newest first), until we pass the window
  const rawActs: RawGarminActivity[] = [];
  const first = dates[0];
  for (let start = 0; start < 300; start += 100) {
    let page: RawGarminActivity[];
    try {
      page = (await gc.getActivities(start, 100)) as unknown as RawGarminActivity[];
    } catch {
      failures++;
      break;
    }
    rawActs.push(...page.filter((a) => dateOf(a.startTimeLocal) >= first));
    if (page.length < 100 || page.some((a) => dateOf(a.startTimeLocal) < first)) break;
  }

  // --- time-in-zone per activity (immutable → cached)
  const zoneCache = readJson<Record<string, RawGarminZone[] | null>>(ZONES_FILE, {});
  await pool(
    rawActs.filter((a) => !(String(a.activityId) in zoneCache)),
    3,
    async (a) => {
      try {
        zoneCache[String(a.activityId)] = await gc.get<RawGarminZone[]>(
          `${API}/activity-service/activity/${a.activityId}/hrTimeInZones`,
        );
      } catch (e) {
        failures++;
        if (/429|too many/i.test(e instanceof Error ? e.message : '')) throw new StopSignal();
      }
    },
  );
  writeJson(ZONES_FILE, zoneCache);

  const activities = rawActs.map((a) => mapGarminActivity(a, zoneCache[String(a.activityId)] ?? null));
  const value = {
    snapshot: { days: dayRecords, activities } as Snapshot,
    meta: { days: dayRecords.length, activities: activities.length, failures },
    days,
  };
  cache.set(value);
  return value;
}
