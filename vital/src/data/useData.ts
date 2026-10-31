import { useEffect, useState } from 'react';
import { todayLocal } from '../../shared/dates';
import { generateDemo } from '../../shared/demo';
import { mergeSnapshots } from '../../shared/engine/merge';
import type { Snapshot } from '../../shared/types';
import type { Mode } from '../state/settings';
import { getGarmin, getStatus, getStrava, type Status } from './api';

const LIVE_DAYS = 90;

export interface DataState {
  phase: 'loading' | 'ready' | 'error';
  snapshot: Snapshot | null;
  /** Non-fatal problems worth showing (rate limits, one source failing…). */
  notes: string[];
  error: string | null;
  /** Last known server status (null if the API is unreachable, e.g. a static build). */
  status: Status | null;
}

const INITIAL: DataState = { phase: 'loading', snapshot: null, notes: [], error: null, status: null };

export function useData(mode: Mode, reloadKey: number): DataState {
  const [state, setState] = useState<DataState>(INITIAL);

  useEffect(() => {
    let cancelled = false;
    const set = (s: DataState) => {
      if (!cancelled) setState(s);
    };
    setState((prev) => ({ ...prev, phase: 'loading', error: null }));

    (async () => {
      let status: Status | null = null;
      try {
        status = await getStatus();
      } catch {
        // no server — fine for demo mode
      }

      if (mode === 'demo') {
        set({ phase: 'ready', snapshot: generateDemo(todayLocal()), notes: [], error: null, status });
        return;
      }

      if (!status) {
        set({
          phase: 'error',
          snapshot: null,
          notes: [],
          status,
          error: "Can't reach the Vital server. Start it with `npm run dev` (or switch to demo data in Settings).",
        });
        return;
      }

      const jobs: { name: string; run: Promise<{ snapshot: Snapshot; note?: string }> }[] = [];
      if (status.garmin.ready) {
        jobs.push({
          name: 'Garmin',
          run: getGarmin(LIVE_DAYS).then((r) => ({
            snapshot: r.snapshot,
            note: r.meta.failures > 0 ? `${r.meta.failures} Garmin request(s) failed; some days may be missing.` : undefined,
          })),
        });
      }
      if (status.strava.ready) {
        jobs.push({
          name: 'Strava',
          run: getStrava(LIVE_DAYS).then((r) => ({
            snapshot: r.snapshot,
            note: r.meta.limited
              ? 'Strava rate limit reached — some workouts use average heart rate until the limit resets.'
              : undefined,
          })),
        });
      }

      if (jobs.length === 0) {
        set({
          phase: 'error',
          snapshot: null,
          notes: [],
          status,
          error: 'No data source is connected yet. Connect Strava or Garmin in Settings, or use demo data.',
        });
        return;
      }

      const results = await Promise.allSettled(jobs.map((j) => j.run));
      const snaps: Snapshot[] = [];
      const notes: string[] = [];
      const failures: string[] = [];
      results.forEach((r, i) => {
        if (r.status === 'fulfilled') {
          snaps.push(r.value.snapshot);
          if (r.value.note) notes.push(r.value.note);
        } else {
          failures.push(`${jobs[i].name}: ${r.reason instanceof Error ? r.reason.message : 'failed'}`);
        }
      });

      if (snaps.length === 0) {
        set({ phase: 'error', snapshot: null, notes: [], status, error: failures.join(' · ') });
        return;
      }
      set({ phase: 'ready', snapshot: mergeSnapshots(snaps), notes: [...failures, ...notes], error: null, status });
    })();

    return () => {
      cancelled = true;
    };
  }, [mode, reloadKey]);

  return state;
}
