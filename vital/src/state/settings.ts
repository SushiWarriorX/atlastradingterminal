import { useCallback, useState } from 'react';
import { DEFAULT_PROFILE, type Profile } from '../../shared/types';

export type Mode = 'demo' | 'live';

export interface Settings {
  mode: Mode;
  profile: Profile;
}

const KEY = 'vital.settings.v1';
const DEFAULTS: Settings = { mode: 'demo', profile: DEFAULT_PROFILE };

const bounded = (v: unknown, lo: number, hi: number, fallback: number) =>
  typeof v === 'number' && Number.isFinite(v) ? Math.min(hi, Math.max(lo, v)) : fallback;

function read(): Settings {
  try {
    const p = JSON.parse(localStorage.getItem(KEY) ?? 'null');
    if (p && typeof p === 'object') {
      return {
        mode: p.mode === 'live' ? 'live' : 'demo',
        profile: {
          maxHr: bounded(p.profile?.maxHr, 120, 230, DEFAULT_PROFILE.maxHr),
          sleepBaselineHours: bounded(p.profile?.sleepBaselineHours, 5, 11, DEFAULT_PROFILE.sleepBaselineHours),
          sex: p.profile?.sex === 'female' ? 'female' : 'male',
        },
      };
    }
  } catch {
    // private mode / corrupted JSON → defaults
  }
  return DEFAULTS;
}

export function useSettings() {
  const [settings, setSettings] = useState<Settings>(read);
  const update = useCallback((fn: (s: Settings) => Settings) => {
    setSettings((prev) => {
      const next = fn(prev);
      try {
        localStorage.setItem(KEY, JSON.stringify(next));
      } catch {
        // storage unavailable — keep working in memory
      }
      return next;
    });
  }, []);
  return [settings, update] as const;
}
