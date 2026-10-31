import { useState } from 'react';
import type { DayScores } from '../../shared/engine/types';
import { fmtDay, fmtDayNum, fmtDuration } from '../../shared/format';
import { BarChart, LineChart } from '../components/Charts';

const RANGES = [14, 30, 90] as const;

const avg = (xs: number[]) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null);
const nums = (xs: (number | null | undefined)[]) => xs.filter((x): x is number => x != null);

export function Trends({ days }: { days: DayScores[] }) {
  const [range, setRange] = useState<(typeof RANGES)[number]>(30);
  const win = days.slice(-range);
  const labels = win.map((d) => fmtDayNum(d.date));
  const titles = win.map((d) => fmtDay(d.date));

  const recs = nums(win.map((d) => d.recovery?.score));
  const green = recs.filter((r) => r >= 67).length;
  const last = win[win.length - 1];

  // "Normal range" = the baseline as of the most recent day.
  const hrvBase = last?.baselines.hrvLn;
  const hrvBand = hrvBase ? { lo: Math.exp(hrvBase.mean - hrvBase.sd), hi: Math.exp(hrvBase.mean + hrvBase.sd) } : null;
  const rhrBase = last?.baselines.rhr;
  const rhrBand = rhrBase ? { lo: rhrBase.mean - rhrBase.sd, hi: rhrBase.mean + rhrBase.sd } : null;

  const sleepAvg = avg(nums(win.map((d) => d.sleep?.asleepMin)));
  const strainAvg = avg(win.map((d) => d.strain));
  const hrvAvg = avg(nums(win.map((d) => d.record.hrvMs)));

  return (
    <div className="stack-lg">
      <div className="segmented" role="group" aria-label="Time range">
        {RANGES.map((r) => (
          <button key={r} type="button" aria-pressed={range === r} onClick={() => setRange(r)}>
            {r} days
          </button>
        ))}
      </div>

      <section className="vitals" aria-label="Averages">
        <Summary label="Avg recovery" value={recs.length ? `${Math.round(avg(recs) ?? 0)}%` : '–'} hint={recs.length ? `${Math.round((green / recs.length) * 100)}% green days` : 'No data'} />
        <Summary label="Avg strain" value={strainAvg == null ? '–' : strainAvg.toFixed(1)} hint="per day, incl. rest" />
        <Summary label="Avg sleep" value={sleepAvg == null ? '–' : fmtDuration(sleepAvg)} hint="per night" />
        <Summary label="Avg HRV" value={hrvAvg == null ? '–' : `${Math.round(hrvAvg)} ms`} hint="overnight" />
      </section>

      <section className="card">
        <h3 className="section-title">Recovery</h3>
        <BarChart
          height={170}
          max={100}
          ticks={[0, 34, 67, 100]}
          ariaLabel={`Daily recovery score for the last ${range} days`}
          format={(v) => `${Math.round(v)}`}
          data={win.map((d, i) => ({
            label: labels[i],
            title: titles[i],
            value: d.recovery?.score ?? null,
            color: d.recovery ? `var(--${d.recovery.zone})` : undefined,
            tip: d.recovery ? [`${d.recovery.score}%`] : [d.recoveryStatus === 'calibrating' ? 'Calibrating' : 'No data'],
          }))}
        />
      </section>

      <section className="card">
        <h3 className="section-title">Strain</h3>
        <BarChart
          height={170}
          max={21}
          ticks={[0, 7, 14, 21]}
          color="var(--blue)"
          ariaLabel={`Daily strain for the last ${range} days`}
          data={win.map((d, i) => ({
            label: labels[i],
            title: titles[i],
            value: d.strain > 0 ? d.strain : null,
            tip: [`Strain ${d.strain.toFixed(1)}`],
          }))}
        />
      </section>

      <section className="card">
        <h3 className="section-title">Heart-rate variability</h3>
        <LineChart
          labels={labels}
          titles={titles}
          height={170}
          band={hrvBand}
          format={(v) => `${Math.round(v)}`}
          ariaLabel={`Overnight HRV for the last ${range} days`}
          series={[{ label: 'HRV (ms)', color: 'var(--green)', values: win.map((d) => d.record.hrvMs) }]}
        />
        <p className="legend-note">
          <span className="swatch-band" /> your usual range (±1 SD)
        </p>
      </section>

      <section className="card">
        <h3 className="section-title">Resting heart rate</h3>
        <LineChart
          labels={labels}
          titles={titles}
          height={170}
          band={rhrBand}
          format={(v) => `${Math.round(v)}`}
          ariaLabel={`Resting heart rate for the last ${range} days`}
          series={[{ label: 'Resting HR (bpm)', color: 'var(--red)', values: win.map((d) => d.record.restingHr) }]}
        />
      </section>

      <section className="card">
        <h3 className="section-title">Sleep</h3>
        <BarChart
          height={170}
          color="var(--violet)"
          ariaLabel={`Hours asleep each night for the last ${range} days`}
          format={(v) => `${v.toFixed(v % 1 === 0 ? 0 : 1)}h`}
          data={win.map((d, i) => ({
            label: labels[i],
            title: titles[i],
            value: d.sleep ? d.sleep.asleepMin / 60 : null,
            tip: d.sleep ? [`${fmtDuration(d.sleep.asleepMin)} asleep`, `${d.sleep.performance}% of need`] : ['No sleep recorded'],
          }))}
          line={win.map((d) => (d.sleep ? d.sleep.need.totalMin / 60 : null))}
        />
        <p className="legend-note">
          <i style={{ background: 'var(--violet)' }} /> hours asleep &nbsp; <span className="dash" /> hours needed
        </p>
      </section>
    </div>
  );
}

function Summary({ label, value, hint }: { label: string; value: string; hint: string }) {
  return (
    <div className="card vital">
      <span className="vital-label">{label}</span>
      <span className="vital-value">{value}</span>
      <span className="vital-delta flat">{hint}</span>
    </div>
  );
}
