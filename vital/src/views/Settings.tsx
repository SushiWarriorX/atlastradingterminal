import { useEffect, useState } from 'react';
import type { Profile } from '../../shared/types';
import { disconnect, type Status } from '../data/api';
import type { Mode, Settings as SettingsState } from '../state/settings';

interface SettingsProps {
  settings: SettingsState;
  status: Status | null;
  onMode: (mode: Mode) => void;
  onProfile: (patch: Partial<Profile>) => void;
  onReload: () => void;
}

export function Settings({ settings, status, onMode, onProfile, onReload }: SettingsProps) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = async (provider: 'strava' | 'garmin') => {
    setBusy(provider);
    setError(null);
    try {
      await disconnect(provider);
      onReload();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed');
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="stack-lg">
      <section className="card" aria-label="Data source">
        <h3 className="section-title">Data source</h3>
        <div className="segmented" role="group" aria-label="Data source">
          <button type="button" aria-pressed={settings.mode === 'demo'} onClick={() => onMode('demo')}>
            Demo data
          </button>
          <button type="button" aria-pressed={settings.mode === 'live'} onClick={() => onMode('live')}>
            Live data
          </button>
        </div>
        <p className="muted small">
          Demo data is simulated so you can explore the app. Live data comes from the sources below, merged: Garmin
          supplies sleep, HRV and resting heart rate; workouts from Strava and Garmin are de-duplicated.
        </p>
        {error && <p className="notice notice-error">{error}</p>}
      </section>

      <section className="card provider" aria-label="Strava">
        <div className="provider-head">
          <div>
            <h3>Strava</h3>
            <p className="muted small">Official API · workouts and heart-rate streams</p>
          </div>
          <StatusBadge
            state={!status ? 'offline' : status.strava.connected ? 'ok' : status.strava.configured ? 'idle' : 'todo'}
            text={
              !status
                ? 'Server offline'
                : status.strava.connected
                  ? `Connected${status.strava.athlete ? ` · ${status.strava.athlete}` : ''}`
                  : status.strava.configured
                    ? 'Ready to connect'
                    : 'Not set up'
            }
          />
        </div>
        {status && !status.strava.configured && (
          <ol className="steps small">
            <li>
              Create an app at <b>strava.com/settings/api</b> and set its <i>Authorization Callback Domain</i> to{' '}
              <code>localhost</code>.
            </li>
            <li>
              Copy <code>.env.example</code> to <code>.env</code> and fill in <code>STRAVA_CLIENT_ID</code> and{' '}
              <code>STRAVA_CLIENT_SECRET</code>.
            </li>
            <li>Restart the server, then come back and press Connect.</li>
          </ol>
        )}
        <div className="actions">
          {status?.strava.configured && !status.strava.connected && (
            <a className="btn primary" href="/api/strava/auth">
              Connect Strava
            </a>
          )}
          {status?.strava.connected && (
            <button type="button" className="btn" disabled={busy === 'strava'} onClick={() => run('strava')}>
              Disconnect
            </button>
          )}
        </div>
      </section>

      <section className="card provider" aria-label="Garmin">
        <div className="provider-head">
          <div>
            <h3>Garmin Connect</h3>
            <p className="muted small">Unofficial · sleep, HRV, resting heart rate, workouts</p>
          </div>
          <StatusBadge
            state={!status ? 'offline' : status.garmin.connected ? 'ok' : status.garmin.configured ? 'idle' : 'todo'}
            text={
              !status
                ? 'Server offline'
                : status.garmin.connected
                  ? 'Signed in'
                  : status.garmin.configured
                    ? 'Credentials set'
                    : 'Not set up'
            }
          />
        </div>
        {status && !status.garmin.configured && !status.garmin.connected && (
          <ol className="steps small">
            <li>
              Put <code>GARMIN_EMAIL</code> and <code>GARMIN_PASSWORD</code> in <code>.env</code>. They stay on this
              machine and are only used by the local server.
            </li>
            <li>Restart the server. Accounts with multi-factor authentication aren't supported.</li>
          </ol>
        )}
        <p className="muted small warn">
          This uses an unofficial sign-in that Garmin can change at any time, and Garmin's terms don't permit it.
          Personal use only.
        </p>
        <div className="actions">
          {status?.garmin.connected && (
            <button type="button" className="btn" disabled={busy === 'garmin'} onClick={() => run('garmin')}>
              Forget saved session
            </button>
          )}
        </div>
      </section>

      <section className="card" aria-label="Profile">
        <h3 className="section-title">Your profile</h3>
        <div className="fields">
          <NumberField
            label="Max heart rate"
            unit="bpm"
            value={settings.profile.maxHr}
            min={120}
            max={230}
            step={1}
            hint="The highest rate you've reached in a hard effort. Sets your zones and strain."
            onCommit={(v) => onProfile({ maxHr: Math.round(v) })}
          />
          <NumberField
            label="Baseline sleep need"
            unit="hours"
            value={settings.profile.sleepBaselineHours}
            min={5}
            max={11}
            step={0.25}
            hint="On a calm day. Strain and sleep debt add to this."
            onCommit={(v) => onProfile({ sleepBaselineHours: v })}
          />
          <label className="field">
            <span>Sex (strain weighting)</span>
            <select value={settings.profile.sex} onChange={(e) => onProfile({ sex: e.target.value === 'female' ? 'female' : 'male' })}>
              <option value="male">Male</option>
              <option value="female">Female</option>
            </select>
            <small>Only changes the TRIMP coefficient used for strain.</small>
          </label>
        </div>
      </section>

      <section className="card about" aria-label="How scores work">
        <h3 className="section-title">How the scores work</h3>
        <p className="muted small">
          Vital uses its own open, simple models. They are inspired by recovery-tracking wearables but are{' '}
          <b>not</b> the proprietary algorithms of Whoop, Garmin or anyone else, so numbers won't match those apps.
          This is not medical advice.
        </p>
        <details>
          <summary>Recovery (0–100)</summary>
          <p>
            Compares last night with your own 30-day norm: HRV (50%), resting heart rate (25%), respiration (10%) and
            sleep performance (15%). Each is converted to how many standard deviations you are from normal, combined,
            and mapped onto 0–100. An ordinary night lands around 60. Green ≥ 67, yellow 34–66, red ≤ 33. It needs four
            nights of data before it scores.
          </p>
        </details>
        <details>
          <summary>Strain (0–21)</summary>
          <p>
            Each workout's heart-rate data is turned into Banister TRIMP (minutes weighted by how close you are to your
            max heart rate), summed per day, then squashed onto 0–21 so each extra point is harder to earn. An easy hour
            is around 8, a hard hour around 15. Only logged workouts count, not all-day heart rate.
          </p>
        </details>
        <details>
          <summary>Sleep need &amp; performance</summary>
          <p>
            Need = your baseline + up to 45 min for yesterday's strain + a quarter of the last five nights' shortfall
            (max 60 min). Performance = hours asleep ÷ need. Efficiency = time asleep ÷ time in bed. Consistency
            measures how much your bed and wake times drift over five nights.
          </p>
        </details>
        <details>
          <summary>Target strain</summary>
          <p>Green recovery → 14–18, yellow → 10–14, red → under 9.</p>
        </details>
      </section>

      <p className="muted small center">
        Your data stays on this machine. Tokens and caches live in <code>.data/</code> and are gitignored.
      </p>
    </div>
  );
}

function StatusBadge({ state, text }: { state: 'ok' | 'idle' | 'todo' | 'offline'; text: string }) {
  return <span className={`badge badge-${state}`}>{text}</span>;
}

function NumberField({
  label,
  unit,
  value,
  min,
  max,
  step,
  hint,
  onCommit,
}: {
  label: string;
  unit: string;
  value: number;
  min: number;
  max: number;
  step: number;
  hint: string;
  onCommit: (v: number) => void;
}) {
  const [text, setText] = useState(String(value));
  useEffect(() => setText(String(value)), [value]);

  const commit = () => {
    const n = Number(text);
    if (!Number.isFinite(n) || text.trim() === '') {
      setText(String(value));
      return;
    }
    const clamped = Math.min(max, Math.max(min, n));
    setText(String(clamped));
    if (clamped !== value) onCommit(clamped);
  };

  return (
    <label className="field">
      <span>{label}</span>
      <div className="input-wrap">
        <input
          type="number"
          inputMode="decimal"
          value={text}
          min={min}
          max={max}
          step={step}
          onChange={(e) => setText(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => e.key === 'Enter' && commit()}
        />
        <em>{unit}</em>
      </div>
      <small>{hint}</small>
    </label>
  );
}
