import { randomBytes } from 'node:crypto';
import type { Activity, Snapshot } from '../shared/types';
import { config } from './env';
import { histogramFromStream, mapStravaActivity, type RawStravaActivity } from './mappers/strava';
import { TtlCache, readJson, removeFile, writeJson } from './store';

const TOKENS_FILE = 'strava-tokens.json';
const HR_CACHE_FILE = 'strava-hr.json';
const API = `${config.stravaOrigin}/api/v3`;

interface Tokens {
  access_token: string;
  refresh_token: string;
  /** Epoch seconds. */
  expires_at: number;
  athleteName?: string;
}

export class StravaError extends Error {
  constructor(
    message: string,
    readonly status = 502,
  ) {
    super(message);
  }
}

export const stravaConfigured = (): boolean => Boolean(config.stravaClientId && config.stravaClientSecret);
const loadTokens = (): Tokens | null => readJson<Tokens | null>(TOKENS_FILE, null);
export const stravaConnected = (): boolean => loadTokens() !== null;
export const stravaAthlete = (): string | null => loadTokens()?.athleteName ?? null;

export function disconnectStrava(): void {
  removeFile(TOKENS_FILE);
  cache.clear();
}

// ---------------------------------------------------------------- OAuth

/** One-shot CSRF tokens for the authorise → callback round trip. */
const pendingStates = new Map<string, number>();
const STATE_TTL_MS = 10 * 60_000;

export function authorizeUrl(): string {
  const state = randomBytes(16).toString('hex');
  const now = Date.now();
  for (const [s, at] of pendingStates) if (now - at > STATE_TTL_MS) pendingStates.delete(s);
  pendingStates.set(state, now);
  const q = new URLSearchParams({
    client_id: config.stravaClientId,
    response_type: 'code',
    redirect_uri: config.stravaRedirectUri,
    approval_prompt: 'auto',
    scope: 'read,activity:read_all',
    state,
  });
  return `${config.stravaOrigin}/oauth/authorize?${q}`;
}

async function tokenRequest(body: Record<string, string>): Promise<Tokens> {
  const res = await fetch(`${config.stravaOrigin}/oauth/token`, {
    method: 'POST',
    headers: { 'content-type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({
      client_id: config.stravaClientId,
      client_secret: config.stravaClientSecret,
      ...body,
    }),
  });
  if (!res.ok) throw new StravaError(`Strava token request failed (${res.status})`, res.status === 400 ? 401 : 502);
  const json = (await res.json()) as {
    access_token: string;
    refresh_token: string;
    expires_at: number;
    athlete?: { firstname?: string; lastname?: string };
  };
  const name = [json.athlete?.firstname, json.athlete?.lastname].filter(Boolean).join(' ');
  return {
    access_token: json.access_token,
    refresh_token: json.refresh_token,
    expires_at: json.expires_at,
    athleteName: name || loadTokens()?.athleteName,
  };
}

export async function completeAuthorization(code: string, state: string): Promise<void> {
  const issued = pendingStates.get(state);
  pendingStates.delete(state);
  if (issued === undefined || Date.now() - issued > STATE_TTL_MS) throw new StravaError('Invalid or expired OAuth state', 400);
  writeJson(TOKENS_FILE, await tokenRequest({ code, grant_type: 'authorization_code' }));
}

async function accessToken(): Promise<string> {
  let tokens = loadTokens();
  if (!tokens) throw new StravaError('Strava is not connected', 401);
  if (tokens.expires_at - 60 <= Date.now() / 1000) {
    tokens = await tokenRequest({ grant_type: 'refresh_token', refresh_token: tokens.refresh_token });
    writeJson(TOKENS_FILE, tokens);
  }
  return tokens.access_token;
}

// ---------------------------------------------------------------- API

class RateLimited extends StravaError {
  constructor() {
    super('Strava rate limit reached — try again in 15 minutes', 429);
  }
}

async function api<T>(path: string): Promise<T> {
  const res = await fetch(`${API}${path}`, { headers: { authorization: `Bearer ${await accessToken()}` } });
  if (res.status === 429) throw new RateLimited();
  if (res.status === 401) throw new StravaError('Strava authorisation expired — reconnect Strava', 401);
  if (!res.ok) throw new StravaError(`Strava API error (${res.status})`);
  return (await res.json()) as T;
}

interface StreamResponse {
  time?: { data: number[] };
  heartrate?: { data: number[] };
}

type HrCache = Record<string, Record<number, number> | null>;

export interface StravaMeta {
  /** True if the rate limit stopped us fetching some HR streams (they fall back to average HR). */
  limited: boolean;
  activities: number;
}

const cache = new TtlCache<{ snapshot: Snapshot; meta: StravaMeta; days: number }>(5 * 60_000);

export async function fetchStrava(days: number): Promise<{ snapshot: Snapshot; meta: StravaMeta }> {
  const hit = cache.get();
  if (hit && hit.days === days) return hit;

  const after = Math.floor(Date.now() / 1000) - days * 86_400;
  const raws: RawStravaActivity[] = [];
  for (let page = 1; page <= 10; page++) {
    const list = await api<RawStravaActivity[]>(`/athlete/activities?after=${after}&per_page=100&page=${page}`);
    raws.push(...list);
    if (list.length < 100) break;
  }

  // Heart-rate streams: one request per activity, cached forever (past activities don't change).
  const hrCache = readJson<HrCache>(HR_CACHE_FILE, {});
  let limited = false;
  const missing = raws.filter((r) => r.has_heartrate && !(String(r.id) in hrCache));
  for (let i = 0; i < missing.length && !limited; i += 3) {
    await Promise.all(
      missing.slice(i, i + 3).map(async (r) => {
        try {
          const s = await api<StreamResponse>(`/activities/${r.id}/streams?keys=time,heartrate&key_by_type=true`);
          hrCache[String(r.id)] =
            s.time && s.heartrate ? histogramFromStream(s.time.data, s.heartrate.data) : null;
        } catch (e) {
          if (e instanceof RateLimited) limited = true;
          // Anything else: leave uncached so we retry next time.
        }
      }),
    );
  }
  writeJson(HR_CACHE_FILE, hrCache);

  const activities: Activity[] = raws.map((r) => mapStravaActivity(r, hrCache[String(r.id)] ?? null));
  const value = {
    snapshot: { days: [], activities } as Snapshot,
    meta: { limited, activities: activities.length },
    days,
  };
  cache.set(value);
  return value;
}
