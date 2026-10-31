import fs from 'node:fs';
import http from 'node:http';
import type { AddressInfo } from 'node:net';
import os from 'node:os';
import path from 'node:path';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';

/**
 * Exercises the real Strava client (OAuth, refresh, pagination, stream caching,
 * rate limiting) against a local fake of Strava's HTTP API.
 * The fake mirrors Strava's documented request/response shapes — it is not Strava itself.
 */

interface Recorded {
  method: string;
  url: string;
  auth?: string;
  body: string;
}

const requests: Recorded[] = [];
const behaviour = { streamStatus: 200, activitiesStatus: 200 };

const ACTIVITY_COUNT = 103; // forces a second page
const activities = Array.from({ length: ACTIVITY_COUNT }, (_, i) => ({
  id: 1000 + i,
  name: `Run ${i}`,
  sport_type: 'Run',
  start_date_local: `2026-10-${String(1 + (i % 28)).padStart(2, '0')}T07:00:00Z`,
  moving_time: 1800,
  distance: 5000,
  has_heartrate: i < 4, // only a few have HR
  average_heartrate: i < 4 ? 150 : undefined,
  max_heartrate: i < 4 ? 170 : undefined,
}));

let server: http.Server;
let origin = '';
let dataDir = '';
let strava: typeof import('../server/strava');
let store: typeof import('../server/store');

function readBody(req: http.IncomingMessage): Promise<string> {
  return new Promise((resolve) => {
    let b = '';
    req.on('data', (c) => (b += c));
    req.on('end', () => resolve(b));
  });
}

beforeAll(async () => {
  server = http.createServer(async (req, res) => {
    const body = await readBody(req);
    const url = new URL(req.url ?? '/', 'http://x');
    requests.push({ method: req.method ?? '', url: req.url ?? '', auth: req.headers.authorization, body });
    const json = (status: number, data: unknown) => {
      res.writeHead(status, { 'content-type': 'application/json' });
      res.end(JSON.stringify(data));
    };

    if (url.pathname === '/oauth/token') {
      const form = new URLSearchParams(body);
      if (form.get('grant_type') === 'authorization_code') {
        if (form.get('code') !== 'good-code' || form.get('client_secret') !== 'shh') return json(400, { message: 'Bad Request' });
        return json(200, {
          access_token: 'access-1',
          refresh_token: 'refresh-1',
          expires_at: Math.floor(Date.now() / 1000) + 3600,
          athlete: { firstname: 'Sam', lastname: 'Runner' },
        });
      }
      if (form.get('grant_type') === 'refresh_token' && form.get('refresh_token') === 'refresh-1') {
        return json(200, { access_token: 'access-2', refresh_token: 'refresh-2', expires_at: Math.floor(Date.now() / 1000) + 3600 });
      }
      return json(400, { message: 'bad grant' });
    }

    if (url.pathname === '/api/v3/athlete/activities') {
      if (behaviour.activitiesStatus !== 200) return json(behaviour.activitiesStatus, { message: 'nope' });
      const page = Number(url.searchParams.get('page') ?? 1);
      const per = Number(url.searchParams.get('per_page') ?? 30);
      return json(200, activities.slice((page - 1) * per, page * per));
    }

    const stream = url.pathname.match(/^\/api\/v3\/activities\/(\d+)\/streams$/);
    if (stream) {
      if (behaviour.streamStatus !== 200) return json(behaviour.streamStatus, { message: 'Rate Limit Exceeded' });
      return json(200, {
        time: { data: [0, 1, 2, 3, 4, 5] },
        heartrate: { data: [140, 140, 150, 150, 150, 160] },
      });
    }
    json(404, {});
  });
  await new Promise<void>((r) => server.listen(0, '127.0.0.1', r));
  origin = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'vital-test-'));

  // Config is read at import time, so set the environment first.
  process.env.STRAVA_CLIENT_ID = '4242';
  process.env.STRAVA_CLIENT_SECRET = 'shh';
  process.env.STRAVA_ORIGIN = origin;
  process.env.VITAL_DATA_DIR = dataDir;
  strava = await import('../server/strava');
  store = await import('../server/store');
});

afterAll(async () => {
  await new Promise((r) => server.close(r));
  fs.rmSync(dataDir, { recursive: true, force: true });
});

const streamRequests = () => requests.filter((r) => r.url.includes('/streams')).length;

describe('strava client against a fake Strava', () => {
  it('is configured but not connected at first', () => {
    expect(strava.stravaConfigured()).toBe(true);
    expect(strava.stravaConnected()).toBe(false);
  });

  it('builds an authorise URL with scope, redirect and a one-shot state', async () => {
    const u = new URL(strava.authorizeUrl());
    expect(u.origin + u.pathname).toBe(`${origin}/oauth/authorize`);
    expect(u.searchParams.get('client_id')).toBe('4242');
    expect(u.searchParams.get('scope')).toBe('read,activity:read_all');
    expect(u.searchParams.get('redirect_uri')).toMatch(/\/api\/strava\/callback$/);
    const state = u.searchParams.get('state')!;
    expect(state).toHaveLength(32);

    await expect(strava.completeAuthorization('good-code', 'not-the-state')).rejects.toThrow(/state/i);
    expect(strava.stravaConnected()).toBe(false);

    await strava.completeAuthorization('good-code', state);
    expect(strava.stravaConnected()).toBe(true);
    expect(strava.stravaAthlete()).toBe('Sam Runner');

    // the state cannot be replayed
    await expect(strava.completeAuthorization('good-code', state)).rejects.toThrow(/state/i);
  });

  it('rejects a bad authorisation code without storing anything', async () => {
    strava.disconnectStrava();
    const state = new URL(strava.authorizeUrl()).searchParams.get('state')!;
    await expect(strava.completeAuthorization('wrong', state)).rejects.toThrow(/token request failed/i);
    expect(strava.stravaConnected()).toBe(false);
    // reconnect for the following tests
    const again = new URL(strava.authorizeUrl()).searchParams.get('state')!;
    await strava.completeAuthorization('good-code', again);
  });

  it('pages through activities, sends the bearer token and maps stream data', async () => {
    requests.length = 0;
    const { snapshot, meta } = await strava.fetchStrava(30);
    expect(snapshot.activities).toHaveLength(ACTIVITY_COUNT);
    expect(meta).toEqual({ limited: false, activities: ACTIVITY_COUNT });

    const listCalls = requests.filter((r) => r.url.startsWith('/api/v3/athlete/activities'));
    expect(listCalls).toHaveLength(2); // 100 + 3
    expect(listCalls.every((r) => r.auth === 'Bearer access-1')).toBe(true);

    expect(streamRequests()).toBe(4); // only activities with HR
    const withHr = snapshot.activities.find((a) => a.id === 'strava-1000')!;
    expect(withHr.hrBasis).toBe('stream');
    expect(withHr.hrSeconds).toEqual({ 140: 2, 150: 3, 160: 1 });
    expect(withHr.startLocal).toBe('2026-10-01T07:00:00');

    const noHr = snapshot.activities.find((a) => a.id === 'strava-1050')!;
    expect(noHr.hrBasis).toBe('none');
  });

  it('serves repeat requests from memory, and never re-downloads a cached stream', async () => {
    requests.length = 0;
    await strava.fetchStrava(30); // same window → in-memory cache
    expect(requests).toHaveLength(0);

    await strava.fetchStrava(31); // different window → refetches the list, but streams come from disk
    expect(requests.filter((r) => r.url.startsWith('/api/v3/athlete/activities')).length).toBeGreaterThan(0);
    expect(streamRequests()).toBe(0);
  });

  it('refreshes an expired token and uses the new one', async () => {
    const tokens = store.readJson<Record<string, unknown>>('strava-tokens.json', {});
    store.writeJson('strava-tokens.json', { ...tokens, expires_at: Math.floor(Date.now() / 1000) - 10 });
    requests.length = 0;
    await strava.fetchStrava(32);
    const refresh = requests.find((r) => r.url === '/oauth/token')!;
    expect(new URLSearchParams(refresh.body).get('grant_type')).toBe('refresh_token');
    const list = requests.find((r) => r.url.startsWith('/api/v3/athlete/activities'))!;
    expect(list.auth).toBe('Bearer access-2');
    expect(store.readJson<{ refresh_token: string }>('strava-tokens.json', { refresh_token: '' }).refresh_token).toBe('refresh-2');
  });

  it('degrades to average HR when Strava rate-limits the stream calls', async () => {
    // wipe the HR cache so streams are needed again
    store.writeJson('strava-hr.json', {});
    behaviour.streamStatus = 429;
    try {
      const { snapshot, meta } = await strava.fetchStrava(33);
      expect(meta.limited).toBe(true);
      const a = snapshot.activities.find((x) => x.id === 'strava-1000')!;
      expect(a.hrBasis).toBe('average');
      expect(a.hrSeconds).toBeNull();
      expect(a.avgHr).toBe(150);
    } finally {
      behaviour.streamStatus = 200;
    }
  });

  it('reports expired authorisation as a 401 the UI can act on', async () => {
    behaviour.activitiesStatus = 401;
    try {
      await expect(strava.fetchStrava(34)).rejects.toMatchObject({ status: 401 });
    } finally {
      behaviour.activitiesStatus = 200;
    }
  });

  it('forgets the tokens on disconnect', () => {
    strava.disconnectStrava();
    expect(strava.stravaConnected()).toBe(false);
    expect(fs.existsSync(path.join(dataDir, 'strava-tokens.json'))).toBe(false);
  });
});
