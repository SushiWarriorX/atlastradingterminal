import { fmtDuration } from '../format';
import type { DayScores, StrainTarget } from './types';

/** Recovery → how hard today should be. */
export function strainTarget(recovery: number): StrainTarget {
  if (recovery >= 67) return { low: 14, high: 18, label: 'Push' };
  if (recovery >= 34) return { low: 10, high: 14, label: 'Maintain' };
  return { low: 2, high: 9, label: 'Recover' };
}

export interface Coaching {
  headline: string;
  body: string;
  tone: 'green' | 'yellow' | 'red' | 'neutral';
}

const f1 = (n: number) => n.toFixed(1);

export function coach(day: DayScores): Coaching {
  if (day.recoveryStatus === 'no-data') {
    return {
      tone: 'neutral',
      headline: 'No overnight data yet',
      body: 'Recovery needs HRV and resting heart rate from a night of sleep. Wear your watch to bed and sync it.',
    };
  }
  if (day.recoveryStatus === 'calibrating' || !day.recovery || !day.target) {
    const left = day.calibrationDaysLeft;
    return {
      tone: 'neutral',
      headline: 'Learning your baseline',
      body: `Recovery compares each night with your own norm. ${left} more night${left === 1 ? '' : 's'} of HRV needed.`,
    };
  }

  const { score, zone } = day.recovery;
  const { low, high } = day.target;
  const strain = day.strain;

  let headline: string;
  let body: string;
  if (zone === 'green') {
    headline = 'Primed to perform';
    body = `Recovery is ${score}%. Your body can absorb a hard session — aim for strain ${low}–${high}.`;
  } else if (zone === 'yellow') {
    headline = 'Steady day';
    body = `Recovery is ${score}%. Moderate effort suits you today — aim for strain ${low}–${high}.`;
  } else {
    headline = 'Prioritise recovery';
    body = `Recovery is only ${score}%. Keep it easy (strain under ${high}) and protect tonight's sleep.`;
  }

  if (strain >= high) body += ` You're at ${f1(strain)} — that's your target, so ease off now.`;
  else if (strain >= low) body += ` You're at ${f1(strain)} — already in range.`;
  else if (strain > 0) body += ` You're at ${f1(strain)} so far.`;

  const debt = day.sleep?.need.debtMin ?? 0;
  if (debt >= 20) body += ` You're carrying sleep debt — it added ${fmtDuration(debt)} to last night's need.`;

  return { tone: zone, headline, body };
}
