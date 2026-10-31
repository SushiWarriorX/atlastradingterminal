import { coach } from '../../shared/engine/coach';
import type { DayScores } from '../../shared/engine/types';
import { fmtDayNum, fmtDuration, fmtTime, fmtWeekday } from '../../shared/format';
import { SPORT_LABEL } from '../../shared/sport';
import { Ring } from '../components/Ring';

const ZONE_NAME = { green: 'Primed', yellow: 'Steady', red: 'Low' } as const;
const MAX_STRAIN = 21;

interface TodayProps {
  day: DayScores;
  /** Up to seven days ending at `day`, oldest first. */
  week: DayScores[];
  onSelect: (date: string) => void;
}

export function Today({ day, week, onSelect }: TodayProps) {
  const c = coach(day);
  const rec = day.recovery;
  const sleep = day.sleep;

  return (
    <div className="stack-lg">
      <section className="card hero" aria-label="Daily scores">
        <div className="hero-item">
          <Ring
            value={(sleep?.performance ?? 0) / 100}
            color="var(--violet)"
            size={112}
            label={sleep ? `Sleep performance ${sleep.performance} percent` : 'No sleep recorded'}
          >
            <span className="big">{sleep ? `${sleep.performance}%` : '–'}</span>
          </Ring>
          <div className="hero-caption">
            <strong>Sleep</strong>
            <span>{sleep ? fmtDuration(sleep.asleepMin) : 'No sleep'}</span>
          </div>
        </div>

        <div className="hero-item hero-main">
          <Ring
            value={(rec?.score ?? 0) / 100}
            color={rec ? `var(--${rec.zone})` : 'var(--faint)'}
            size={156}
            stroke={8}
            label={rec ? `Recovery ${rec.score} percent, ${ZONE_NAME[rec.zone]}` : 'Recovery not available'}
          >
            <span className="huge" style={{ color: rec ? `var(--${rec.zone})` : undefined }}>
              {rec ? `${rec.score}%` : '–'}
            </span>
          </Ring>
          <div className="hero-caption">
            <strong>Recovery</strong>
            <span>
              {rec
                ? ZONE_NAME[rec.zone]
                : day.recoveryStatus === 'calibrating'
                  ? 'Calibrating'
                  : 'No data'}
            </span>
          </div>
        </div>

        <div className="hero-item">
          <Ring
            value={day.strain / MAX_STRAIN}
            color="var(--blue)"
            size={112}
            label={`Strain ${day.strain.toFixed(1)} out of 21`}
          >
            <span className="big">{day.strain.toFixed(1)}</span>
          </Ring>
          <div className="hero-caption">
            <strong>Strain</strong>
            <span>{day.target ? `Target ${day.target.low}–${day.target.high}` : 'of 21'}</span>
          </div>
        </div>
      </section>

      <section className={`card coach coach-${c.tone}`} aria-label="Coaching">
        <h2>{c.headline}</h2>
        <p>{c.body}</p>
        {day.target && (
          <div className="target" aria-hidden="true">
            <div className="target-track">
              <div
                className="target-band"
                style={{
                  left: `${(day.target.low / MAX_STRAIN) * 100}%`,
                  width: `${((day.target.high - day.target.low) / MAX_STRAIN) * 100}%`,
                }}
              />
              <div className="target-marker" style={{ left: `${(Math.min(day.strain, MAX_STRAIN) / MAX_STRAIN) * 100}%` }} />
            </div>
            <div className="target-scale">
              <span>0</span>
              <span>7</span>
              <span>14</span>
              <span>21</span>
            </div>
          </div>
        )}
      </section>

      <section aria-label="Vitals" className="vitals">
        <Vital
          label="HRV"
          unit="ms"
          value={day.record.hrvMs}
          decimals={0}
          base={day.baselines.hrvMs}
          relative
          upIsGood
        />
        <Vital
          label="Resting HR"
          unit="bpm"
          value={day.record.restingHr}
          decimals={0}
          base={day.baselines.rhr?.mean ?? null}
          tolerance={1.5}
        />
        <Vital
          label="Respiration"
          unit="rpm"
          value={day.record.respiration}
          decimals={1}
          base={day.baselines.resp?.mean ?? null}
        />
        <Vital label="Sleep efficiency" unit="%" value={sleep?.efficiency ?? null} decimals={0} base={null} />
      </section>

      <section className="card" aria-label="This week">
        <h3 className="section-title">Last 7 days</h3>
        <ol className="week">
          {week.map((d) => (
            <li key={d.date}>
              <button
                type="button"
                className={d.date === day.date ? 'week-day selected' : 'week-day'}
                onClick={() => onSelect(d.date)}
                aria-label={`${d.date}: recovery ${d.recovery?.score ?? 'n/a'}, strain ${d.strain.toFixed(1)}`}
                aria-pressed={d.date === day.date}
              >
                <span className="week-name">{fmtWeekday(d.date)}</span>
                <span
                  className="week-dot"
                  style={{
                    background: d.recovery ? `var(--${d.recovery.zone})` : 'transparent',
                    borderColor: d.recovery ? `var(--${d.recovery.zone})` : 'var(--border)',
                  }}
                >
                  {d.recovery?.score ?? ''}
                </span>
                <span className="week-strain">{d.strain > 0 ? d.strain.toFixed(1) : '–'}</span>
                <span className="week-num">{fmtDayNum(d.date)}</span>
              </button>
            </li>
          ))}
        </ol>
        <p className="legend-note">
          <span>
            Circle: recovery score · <b>Blue</b>: strain
          </span>
        </p>
      </section>

      <section className="card" aria-label="Workouts">
        <h3 className="section-title">Workouts</h3>
        {day.activities.length === 0 ? (
          <p className="muted">No workouts logged for this day.</p>
        ) : (
          <ul className="rows">
            {day.activities.map((a) => (
              <li key={a.activity.id} className="row">
                <span className={`chip sport-${a.activity.sport}`}>{SPORT_LABEL[a.activity.sport]}</span>
                <span className="row-main">
                  <strong>{a.activity.name}</strong>
                  <span className="muted">
                    {fmtTime(a.activity.startLocal)} · {fmtDuration(a.activity.durationSec / 60)}
                    {a.activity.avgHr ? ` · ${a.activity.avgHr} bpm avg` : ''}
                  </span>
                </span>
                <span className="pill" title="Strain from this workout alone">
                  {a.activity.hrBasis === 'none' ? 'No HR' : a.strain.toFixed(1)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function Vital({
  label,
  unit,
  value,
  decimals,
  base,
  relative = false,
  upIsGood = false,
  tolerance = relative ? 2 : 0.5,
}: {
  label: string;
  unit: string;
  value: number | null;
  decimals: number;
  base: number | null;
  relative?: boolean;
  upIsGood?: boolean;
  /** Differences smaller than this (% or absolute units) read as "in line with usual". */
  tolerance?: number;
}) {
  let delta: { text: string; tone: 'good' | 'bad' | 'flat' } | null = null;
  if (value != null && base != null) {
    const diff = relative ? (value / base - 1) * 100 : value - base;
    const small = Math.abs(diff) < tolerance;
    const better = upIsGood ? diff > 0 : diff < 0;
    const mag = relative ? `${Math.abs(diff).toFixed(0)}%` : `${Math.abs(diff).toFixed(decimals === 0 ? 0 : 1)} ${unit}`;
    delta = small
      ? { text: 'in line with usual', tone: 'flat' }
      : { text: `${diff > 0 ? '▲' : '▼'} ${mag} vs 30-day avg`, tone: better ? 'good' : 'bad' };
  }
  return (
    <div className="card vital">
      <span className="vital-label">{label}</span>
      <span className="vital-value">
        {value == null ? '–' : value.toFixed(decimals)}
        {value != null && <small>{unit}</small>}
      </span>
      <span className={`vital-delta ${delta?.tone ?? 'flat'}`}>{delta ? delta.text : value == null ? 'No reading' : ' '}</span>
    </div>
  );
}
