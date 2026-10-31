# Vital

A clean recovery, strain and sleep dashboard in the spirit of Whoop, fed by your **Garmin** and **Strava** data.

- **Today** – sleep, recovery and strain rings, a coaching card with a target-strain range, vitals vs. your own baseline, a 7-day strip and the day's workouts.
- **Sleep** – hours vs. need (baseline + strain + debt), stages, efficiency, consistency, 14-night history.
- **Activity** – daily strain, every workout with time-in-zones and a heart-rate distribution.
- **Trends** – 14 / 30 / 90-day recovery, strain, HRV (with your usual range), resting HR and sleep.
- Dark and light themes (follows your OS), works on phones.

It runs on built-in **demo data** out of the box. Connect real sources when you're ready.

## Quick start

```bash
cd vital
npm install
npm run dev          # API on :8787, app on http://localhost:5173
```

Open http://localhost:5173 — you'll see demo data. Switch to **Live data** in Settings once a source is connected.

Other scripts: `npm test`, `npm run typecheck`, `npm run build`, `npm start` (serves the built app + API on one port).

## Live data

Copy `.env.example` to `.env` (gitignored) and fill in what you want. **Never paste credentials into chat, issues or commits.**

| Source | What it provides | How |
| --- | --- | --- |
| **Garmin Connect** | sleep, overnight HRV, resting HR, respiration, workouts | `GARMIN_EMAIL` / `GARMIN_PASSWORD`. Unofficial sign-in via the [`garmin-connect`](https://www.npmjs.com/package/garmin-connect) library. |
| **Strava** | workouts and second-by-second heart rate | Official OAuth. Create an app at <https://www.strava.com/settings/api>, set *Authorization Callback Domain* to `localhost`, add `STRAVA_CLIENT_ID` / `STRAVA_CLIENT_SECRET`, restart, then press **Connect Strava** in Settings. |

When both are connected the data is merged: Garmin supplies the health metrics, and a workout that appears in both (Garmin syncs to Strava) is de-duplicated, keeping the copy with the richer heart-rate data.

> **Garmin caveats.** Garmin has no public personal-data API. The sign-in used here is unofficial, can break whenever Garmin changes things, and Garmin's terms don't permit it — personal use only. Accounts with multi-factor authentication aren't supported. Strava alone gives strain and workouts but **no recovery or sleep** (it has no HRV or sleep data).

## How the scores work

These are Vital's own transparent models. They are **not** Whoop's (or Garmin's) proprietary algorithms, so numbers won't match those apps. Not medical advice.

- **Recovery 0–100** – last night vs. your own 30-day baseline: HRV (log-space) 50%, resting HR 25%, respiration 10%, sleep performance 15%. Each becomes a z-score; the weighted mean goes through a logistic curve (an ordinary night ≈ 61). Green ≥ 67, yellow 34–66, red ≤ 33. Needs 4 nights of history.
- **Strain 0–21** – Banister TRIMP from each workout's heart-rate data (weighted by heart-rate reserve), summed per day, then squashed: `21 · (1 − e^(−load/150))`. An easy hour ≈ 8, a hard hour ≈ 15. Only logged workouts count — not all-day heart rate.
- **Sleep need** – your baseline + up to 45 min for yesterday's strain + ¼ of the last five nights' shortfall (max 60 min). **Performance** = asleep ÷ need.
- **Target strain** – green recovery → 14–18, yellow → 10–14, red → under 9.

The engine is pure TypeScript in `shared/engine/` with unit tests, so the formulas are easy to read and change.

## Architecture

```
shared/            pure TypeScript used by both sides
  engine/          recovery, strain, sleep, coaching, merging, timeline builder
  demo.ts          seeded synthetic data generator
server/            Express API (loopback only) – holds tokens/credentials
  mappers/         pure functions: Strava / Garmin payloads → normalised model
  strava.ts        OAuth, refresh, pagination, HR-stream cache, rate-limit fallback
  garmin.ts        sign-in, daily sleep/HRV, activities, time-in-zone cache
src/               React + Vite UI (hand-rolled SVG charts, no chart library)
tests/             engine, mappers, and the Strava client against a fake Strava
```

Providers return one normalised `Snapshot` (`days` + `activities`); the browser computes every score from it. Adding a source means writing a mapper and one fetch function.

## Security & privacy

- The API binds to `127.0.0.1` only, rejects requests whose `Host` isn't loopback (DNS-rebinding), and requires an `X-Requested-With` header on state-changing calls.
- Tokens, credentials and caches live on your machine: `.env` and `.data/` (both gitignored, `.data/` files are mode 600).
- Nothing is sent anywhere except to Strava / Garmin themselves.

## Known limits

- The Garmin adapter has **not been run against a live Garmin account** in development (no credentials in the build environment). Its payload mapping is unit-tested against hand-written payloads shaped like the library's types; the time-in-zone endpoint (`hrTimeInZones`) in particular should be verified on first real use. A failed zone lookup falls back to average heart rate.
- The Strava client is tested end-to-end against a local fake of Strava's API, not the real service.
- Strain ignores heart rate outside logged workouts; Whoop-style all-day strain would need Garmin's daily heart-rate series.
- Metric units only. Single user.

## Moving to its own repo

This folder is self-contained. To lift it out with history:

```bash
git subtree split --prefix=vital -b vital-only
git push git@github.com:<you>/<new-repo>.git vital-only:main
```
