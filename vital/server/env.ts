import fs from 'node:fs';
import path from 'node:path';

export const ROOT = path.resolve(import.meta.dirname, '..');

/** Minimal .env loader so we don't need a dependency. Real environment variables win. */
function loadDotEnv(): void {
  const file = path.join(ROOT, '.env');
  if (!fs.existsSync(file)) return;
  for (const line of fs.readFileSync(file, 'utf8').split(/\r?\n/)) {
    const m = line.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*?)\s*$/);
    if (!m || line.trim().startsWith('#')) continue;
    let value = m[2];
    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
      value = value.slice(1, -1);
    }
    if (process.env[m[1]] === undefined) process.env[m[1]] = value;
  }
}

loadDotEnv();

const production = process.env.NODE_ENV === 'production';
const port = Number(process.env.PORT ?? 8787);

export const config = {
  production,
  port,
  /** Never bind beyond loopback: this server holds your tokens and credentials. */
  host: '127.0.0.1',
  stravaClientId: process.env.STRAVA_CLIENT_ID ?? '',
  stravaClientSecret: process.env.STRAVA_CLIENT_SECRET ?? '',
  garminEmail: process.env.GARMIN_EMAIL ?? '',
  garminPassword: process.env.GARMIN_PASSWORD ?? '',
  /** Where the browser app lives; OAuth sends the user back here. Empty = same origin as the server. */
  appOrigin: process.env.APP_ORIGIN ?? (production ? '' : 'http://localhost:5173'),
  stravaRedirectUri: `http://localhost:${port}/api/strava/callback`,
  /** Overridable so tests can point at a fake Strava. */
  stravaOrigin: process.env.STRAVA_ORIGIN ?? 'https://www.strava.com',
  /** Tokens and caches. Overridable for tests. */
  dataDir: process.env.VITAL_DATA_DIR ?? path.join(ROOT, '.data'),
};
