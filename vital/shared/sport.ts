import type { Sport } from './types';

/** Maps Strava `sport_type` / Garmin `typeKey` strings onto a small, stable set. */
export function normaliseSport(raw: string | null | undefined): Sport {
  const s = (raw ?? '').toLowerCase().replace(/[^a-z]/g, '');
  if (s.includes('run')) return 'run';
  if (/(ride|cycl|bik)/.test(s)) return 'ride';
  if (s.includes('swim')) return 'swim';
  if (/(weight|strength|crossfit)/.test(s)) return 'strength';
  if (s.includes('walk')) return 'walk';
  if (s.includes('hik')) return 'hike';
  if (/(yoga|pilates|stretch)/.test(s)) return 'yoga';
  return 'other';
}

export const SPORT_LABEL: Record<Sport, string> = {
  run: 'Run',
  ride: 'Ride',
  swim: 'Swim',
  strength: 'Strength',
  walk: 'Walk',
  hike: 'Hike',
  yoga: 'Yoga',
  other: 'Workout',
};
