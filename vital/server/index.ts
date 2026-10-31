import express, { type NextFunction, type Request, type Response } from 'express';
import fs from 'node:fs';
import path from 'node:path';
import { config, ROOT } from './env';
import {
  GarminError,
  disconnectGarmin,
  fetchGarmin,
  garminConfigured,
  garminConnected,
} from './garmin';
import {
  StravaError,
  authorizeUrl,
  completeAuthorization,
  disconnectStrava,
  fetchStrava,
  stravaAthlete,
  stravaConfigured,
  stravaConnected,
} from './strava';

const app = express();
app.disable('x-powered-by');

// Anything that reaches this server can read your health data, so only answer
// requests addressed to loopback (blocks DNS-rebinding from a hostile web page).
app.use((req, res, next) => {
  const host = (req.headers.host ?? '').replace(/:\d+$/, '');
  if (host !== 'localhost' && host !== '127.0.0.1') {
    res.status(403).json({ error: 'Forbidden host' });
    return;
  }
  next();
});

app.use('/api', (_req, res, next) => {
  res.setHeader('Cache-Control', 'no-store');
  next();
});

// State-changing calls need a custom header, which cross-site forms and simple requests cannot send.
const requireAppHeader = (req: Request, res: Response, next: NextFunction) => {
  if (req.headers['x-requested-with'] !== 'vital') {
    res.status(403).json({ error: 'Missing X-Requested-With header' });
    return;
  }
  next();
};

const clampDays = (raw: unknown): number => {
  const n = Number(raw);
  return Number.isFinite(n) ? Math.min(180, Math.max(7, Math.round(n))) : 60;
};

app.get('/api/status', (_req, res) => {
  res.json({
    strava: {
      configured: stravaConfigured(),
      connected: stravaConnected(),
      ready: stravaConnected(),
      athlete: stravaAthlete(),
    },
    garmin: {
      configured: garminConfigured(),
      connected: garminConnected(),
      // Credentials in .env are enough: the server signs in on first fetch.
      ready: garminConfigured() || garminConnected(),
    },
  });
});

// ---- Strava
app.get('/api/strava/auth', (_req, res) => {
  if (!stravaConfigured()) {
    res.status(400).send('Set STRAVA_CLIENT_ID and STRAVA_CLIENT_SECRET in .env and restart the server.');
    return;
  }
  res.redirect(authorizeUrl());
});

app.get('/api/strava/callback', async (req, res) => {
  const back = (qs: string) => res.redirect(`${config.appOrigin}/?${qs}#/settings`);
  if (req.query.error) {
    back(`connected=error&source=strava&reason=${encodeURIComponent(String(req.query.error))}`);
    return;
  }
  try {
    await completeAuthorization(String(req.query.code ?? ''), String(req.query.state ?? ''));
    back('connected=strava');
  } catch (e) {
    back(`connected=error&source=strava&reason=${encodeURIComponent(e instanceof Error ? e.message : 'failed')}`);
  }
});

app.get('/api/strava/data', async (req, res, next) => {
  try {
    res.json(await fetchStrava(clampDays(req.query.days)));
  } catch (e) {
    next(e);
  }
});

app.post('/api/strava/disconnect', requireAppHeader, (_req, res) => {
  disconnectStrava();
  res.json({ ok: true });
});

// ---- Garmin
app.get('/api/garmin/data', async (req, res, next) => {
  try {
    res.json(await fetchGarmin(clampDays(req.query.days)));
  } catch (e) {
    next(e);
  }
});

app.post('/api/garmin/disconnect', requireAppHeader, (_req, res) => {
  disconnectGarmin();
  res.json({ ok: true });
});

// ---- Static app (production)
const dist = path.join(ROOT, 'dist');
if (config.production && fs.existsSync(dist)) {
  app.use(express.static(dist));
  app.get(/^\/(?!api\/).*/, (_req, res) => res.sendFile(path.join(dist, 'index.html')));
}

app.use('/api', (_req, res) => {
  res.status(404).json({ error: 'Not found' });
});

// eslint-disable-next-line @typescript-eslint/no-unused-vars
app.use((err: unknown, _req: Request, res: Response, _next: NextFunction) => {
  const status = err instanceof StravaError || err instanceof GarminError ? err.status : 500;
  const message = err instanceof Error ? err.message : 'Unexpected error';
  if (status >= 500) console.error(err);
  res.status(status).json({ error: message });
});

app.listen(config.port, config.host, () => {
  console.log(`Vital API listening on http://localhost:${config.port}`);
  console.log(`  Strava: ${stravaConfigured() ? (stravaConnected() ? 'connected' : 'configured — connect in Settings') : 'not configured'}`);
  console.log(`  Garmin: ${garminConfigured() ? 'credentials set' : 'not configured'}`);
});
