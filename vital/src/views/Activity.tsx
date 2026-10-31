import { useState } from 'react';
import type { DayScores, ScoredActivity } from '../../shared/engine/types';
import { fmtDay, fmtDayNum, fmtDistance, fmtDuration, fmtPace, fmtTime } from '../../shared/format';
import { SPORT_LABEL } from '../../shared/sport';
import { BarChart } from '../components/Charts';
import { StackBar } from '../components/StackBar';

interface ActivityProps {
  /** Days up to and including the selected one, oldest first. */
  days: DayScores[];
  maxHr: number;
}

const ZONE_LABELS = ['Zone 1 · 50–60%', 'Zone 2 · 60–70%', 'Zone 3 · 70–80%', 'Zone 4 · 80–90%', 'Zone 5 · 90–100%'];
const BASIS_NOTE: Record<string, string> = {
  stream: 'Second-by-second heart rate.',
  zones: 'Based on time-in-zone from Garmin (coarser than a full heart-rate stream).',
  average: 'Only average heart rate is available, so intensity is estimated and probably understated for interval sessions.',
  none: 'No heart-rate data — this workout does not count towards strain.',
};

export function Activity({ days, maxHr }: ActivityProps) {
  const [open, setOpen] = useState<string | null>(null);
  const last14 = days.slice(-14);
  const feed = days
    .slice(-30)
    .reverse()
    .filter((d) => d.activities.length > 0);

  return (
    <div className="stack-lg">
      <section className="card" aria-label="Strain history">
        <h3 className="section-title">Daily strain · last 14 days</h3>
        <BarChart
          height={180}
          max={21}
          ticks={[0, 7, 14, 21]}
          color="var(--blue)"
          ariaLabel="Daily strain for the last 14 days"
          format={(v) => v.toFixed(0)}
          data={last14.map((d) => ({
            label: fmtDayNum(d.date),
            title: fmtDay(d.date),
            value: d.strain > 0 ? d.strain : null,
            tip: [`Strain ${d.strain.toFixed(1)}`, ...(d.target ? [`Target ${d.target.low}–${d.target.high}`] : [])],
          }))}
        />
      </section>

      <section className="card" aria-label="Workouts">
        <h3 className="section-title">Workouts · last 30 days</h3>
        {feed.length === 0 ? (
          <p className="muted">No workouts in this period.</p>
        ) : (
          feed.map((d) => (
            <div key={d.date} className="feed-day">
              <h4>{fmtDay(d.date)}</h4>
              <ul className="rows">
                {d.activities.map((a) => (
                  <li key={a.activity.id}>
                    <button
                      type="button"
                      className="row row-button"
                      aria-expanded={open === a.activity.id}
                      onClick={() => setOpen(open === a.activity.id ? null : a.activity.id)}
                    >
                      <span className={`chip sport-${a.activity.sport}`}>{SPORT_LABEL[a.activity.sport]}</span>
                      <span className="row-main">
                        <strong>{a.activity.name}</strong>
                        <span className="muted">
                          {fmtTime(a.activity.startLocal)} · {fmtDuration(a.activity.durationSec / 60)}
                          {a.activity.distanceM ? ` · ${fmtDistance(a.activity.distanceM)}` : ''}
                        </span>
                      </span>
                      <span className="pill">{a.activity.hrBasis === 'none' ? 'No HR' : a.strain.toFixed(1)}</span>
                    </button>
                    {open === a.activity.id && <Detail a={a} maxHr={maxHr} />}
                  </li>
                ))}
              </ul>
            </div>
          ))
        )}
      </section>
    </div>
  );
}

function Detail({ a, maxHr }: { a: ScoredActivity; maxHr: number }) {
  const act = a.activity;
  const zoneTotal = a.zones.reduce((s, v) => s + v, 0);
  const pct = (sec: number) => (zoneTotal > 0 ? `${Math.round((sec / zoneTotal) * 100)}%` : '');

  // Minutes per 5-bpm bucket, for the distribution chart.
  const buckets = new Map<number, number>();
  if (act.hrSeconds) {
    for (const [bpm, secs] of Object.entries(act.hrSeconds)) {
      const b = Math.floor(Number(bpm) / 5) * 5;
      buckets.set(b, (buckets.get(b) ?? 0) + secs / 60);
    }
  }
  const keys = [...buckets.keys()].sort((x, y) => x - y);
  const range = keys.length ? Array.from({ length: (keys[keys.length - 1] - keys[0]) / 5 + 1 }, (_, i) => keys[0] + i * 5) : [];
  const zoneOf = (bpm: number) => {
    const f = bpm / maxHr;
    return f >= 0.9 ? 5 : f >= 0.8 ? 4 : f >= 0.7 ? 3 : f >= 0.6 ? 2 : f >= 0.5 ? 1 : 0;
  };

  const speed = act.distanceM && act.durationSec ? (act.distanceM / 1000) / (act.durationSec / 3600) : null;

  return (
    <div className="detail">
      <dl className="stats">
        <Stat label="Duration" value={fmtDuration(act.durationSec / 60)} />
        {act.distanceM != null && <Stat label="Distance" value={fmtDistance(act.distanceM)} />}
        {act.sport === 'run' && <Stat label="Pace" value={fmtPace(act.distanceM, act.durationSec)} />}
        {act.sport === 'ride' && speed != null && <Stat label="Speed" value={`${speed.toFixed(1)} km/h`} />}
        <Stat label="Avg HR" value={act.avgHr ? `${act.avgHr} bpm` : '–'} />
        <Stat label="Max HR" value={act.maxHr ? `${act.maxHr} bpm` : '–'} />
        <Stat label="Strain" value={act.hrBasis === 'none' ? '–' : a.strain.toFixed(1)} />
        {act.calories != null && <Stat label="Calories" value={`${act.calories} kcal`} />}
      </dl>

      {zoneTotal > 0 && (
        <>
          <h5>Time in zones</h5>
          <StackBar
            ariaLabel="Time spent in each heart-rate zone"
            segments={ZONE_LABELS.map((label, i) => ({
              label,
              value: a.zones[i + 1],
              color: `var(--z${i + 1})`,
              display: `${fmtDuration(a.zones[i + 1] / 60)} · ${pct(a.zones[i + 1])}`,
            }))}
          />
        </>
      )}

      {range.length > 1 && act.hrBasis === 'stream' && (
        <>
          <h5>Heart-rate distribution</h5>
          <BarChart
            height={130}
            ariaLabel="Minutes spent at each heart rate"
            format={(v) => `${Math.round(v)}m`}
            data={range.map((b) => ({
              label: String(b),
              title: `${b}–${b + 4} bpm`,
              value: buckets.get(b) ?? 0,
              color: `var(--z${Math.max(1, zoneOf(b + 2))})`,
              tip: [`${(buckets.get(b) ?? 0).toFixed(1)} min`],
            }))}
          />
        </>
      )}
      <p className="muted small">{BASIS_NOTE[act.hrBasis]}</p>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}
