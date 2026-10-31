import type { DayScores } from '../../shared/engine/types';
import { fmtDay, fmtDayNum, fmtDuration, fmtTime } from '../../shared/format';
import { BarChart } from '../components/Charts';
import { Ring } from '../components/Ring';
import { StackBar } from '../components/StackBar';

interface SleepProps {
  day: DayScores;
  /** Up to 14 days ending at `day`, oldest first. */
  recent: DayScores[];
}

const hours = (min: number) => min / 60;

export function Sleep({ day, recent }: SleepProps) {
  const s = day.sleep;

  if (!s) {
    return (
      <div className="card empty">
        <h2>No sleep recorded</h2>
        <p className="muted">There's no sleep data for the night ending {fmtDay(day.date)}. Wear your watch to bed and sync it.</p>
      </div>
    );
  }

  const stages = s.stages;
  const stageTotal = stages ? stages.lightMin + stages.deepMin + stages.remMin + stages.awakeMin : 0;
  const pct = (m: number) => (stageTotal > 0 ? `${Math.round((m / stageTotal) * 100)}%` : '');

  return (
    <div className="stack-lg">
      <section className="card sleep-hero" aria-label="Sleep performance">
        <Ring value={s.performance / 100} color="var(--violet)" size={132} label={`Sleep performance ${s.performance} percent`}>
          <span className="huge">{s.performance}%</span>
        </Ring>
        <div className="sleep-hero-text">
          <h2>{fmtDuration(s.asleepMin)} asleep</h2>
          <p className="muted">
            of {fmtDuration(s.need.totalMin)} needed · {fmtTime(s.startLocal)} → {fmtTime(s.endLocal)}
          </p>
          <ul className="need">
            <li>
              <span>Baseline</span>
              <b>{fmtDuration(s.need.baselineMin)}</b>
            </li>
            <li>
              <span>Yesterday's strain</span>
              <b>+{fmtDuration(s.need.strainMin)}</b>
            </li>
            <li>
              <span>Sleep debt</span>
              <b>+{fmtDuration(s.need.debtMin)}</b>
            </li>
          </ul>
        </div>
      </section>

      {stages && (
        <section className="card" aria-label="Sleep stages">
          <h3 className="section-title">Stages</h3>
          <StackBar
            ariaLabel="Time in each sleep stage"
            segments={[
              { label: 'Deep', value: stages.deepMin, color: 'var(--stage-deep)', display: `${fmtDuration(stages.deepMin)} · ${pct(stages.deepMin)}` },
              { label: 'REM', value: stages.remMin, color: 'var(--stage-rem)', display: `${fmtDuration(stages.remMin)} · ${pct(stages.remMin)}` },
              { label: 'Light', value: stages.lightMin, color: 'var(--stage-light)', display: `${fmtDuration(stages.lightMin)} · ${pct(stages.lightMin)}` },
              { label: 'Awake', value: stages.awakeMin, color: 'var(--stage-awake)', display: `${fmtDuration(stages.awakeMin)} · ${pct(stages.awakeMin)}` },
            ]}
          />
        </section>
      )}

      <section className="vitals" aria-label="Sleep metrics">
        <Metric label="Efficiency" value={`${s.efficiency}%`} hint="Time asleep ÷ time in bed" />
        <Metric
          label="Consistency"
          value={s.consistency == null ? '–' : `${s.consistency}%`}
          hint={s.consistency == null ? 'Needs 3 nights' : 'Regular bed & wake times'}
        />
        <Metric label="In bed" value={fmtDuration(s.inBedMin)} hint="Start to finish" />
        <Metric label="Respiration" value={day.record.respiration == null ? '–' : `${day.record.respiration.toFixed(1)} rpm`} hint="Overnight average" />
      </section>

      <section className="card" aria-label="Last two weeks">
        <h3 className="section-title">Last 14 nights</h3>
        <BarChart
          height={180}
          color="var(--violet)"
          ariaLabel="Hours asleep each night compared with hours needed"
          format={(v) => `${v.toFixed(v % 1 === 0 ? 0 : 1)}h`}
          data={recent.map((d) => ({
            label: fmtDayNum(d.date),
            title: fmtDay(d.date),
            value: d.sleep ? hours(d.sleep.asleepMin) : null,
            tip: d.sleep
              ? [`${fmtDuration(d.sleep.asleepMin)} asleep`, `${fmtDuration(d.sleep.need.totalMin)} needed`, `${d.sleep.performance}% performance`]
              : ['No sleep recorded'],
          }))}
          line={recent.map((d) => (d.sleep ? hours(d.sleep.need.totalMin) : null))}
        />
        <p className="legend-note">
          <i style={{ background: 'var(--violet)' }} /> hours asleep &nbsp; <span className="dash" /> hours needed
        </p>
      </section>
    </div>
  );
}

function Metric({ label, value, hint }: { label: string; value: string; hint: string }) {
  return (
    <div className="card vital">
      <span className="vital-label">{label}</span>
      <span className="vital-value">{value}</span>
      <span className="vital-delta flat">{hint}</span>
    </div>
  );
}
