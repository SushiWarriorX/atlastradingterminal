import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import { todayLocal, addDays } from '../shared/dates';
import { buildTimeline } from '../shared/engine/build';
import { fmtDay } from '../shared/format';
import { IconActivity, IconChevron, IconRefresh, IconSettings, IconSleep, IconToday, IconTrends } from './components/Icons';
import { useData } from './data/useData';
import { useSettings, type Mode } from './state/settings';
import { Activity } from './views/Activity';
import { Settings } from './views/Settings';
import { Sleep } from './views/Sleep';
import { Today } from './views/Today';
import { Trends } from './views/Trends';

const ROUTES = [
  { id: 'today', label: 'Today', icon: <IconToday /> },
  { id: 'sleep', label: 'Sleep', icon: <IconSleep /> },
  { id: 'activity', label: 'Activity', icon: <IconActivity /> },
  { id: 'trends', label: 'Trends', icon: <IconTrends /> },
  { id: 'settings', label: 'Settings', icon: <IconSettings /> },
] as const;
type Route = (typeof ROUTES)[number]['id'];
const DAY_ROUTES: Route[] = ['today', 'sleep', 'activity'];

function readRoute(): Route {
  const h = window.location.hash.replace(/^#\/?/, '');
  return ROUTES.some((r) => r.id === h) ? (h as Route) : 'today';
}

function useRoute(): Route {
  const [route, setRoute] = useState<Route>(readRoute);
  useEffect(() => {
    const on = () => setRoute(readRoute());
    window.addEventListener('hashchange', on);
    return () => window.removeEventListener('hashchange', on);
  }, []);
  return route;
}

type Notice = { tone: 'ok' | 'error'; text: string };

/** Picks up the result of the Strava OAuth round trip from the URL, then cleans it. */
function readOAuthNotice(): Notice | null {
  const q = new URLSearchParams(window.location.search);
  const result = q.get('connected');
  if (!result) return null;
  window.history.replaceState(null, '', `${window.location.pathname}${window.location.hash}`);
  return result === 'error'
    ? { tone: 'error', text: `Couldn't connect ${q.get('source') ?? 'service'}: ${q.get('reason') ?? 'unknown error'}` }
    : { tone: 'ok', text: `Connected ${result === 'strava' ? 'Strava' : result}.` };
}

export default function App() {
  const route = useRoute();
  const [settings, update] = useSettings();
  const [reloadKey, setReloadKey] = useState(0);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [picked, setPicked] = useState<string | null>(null);

  useEffect(() => {
    const n = readOAuthNotice();
    if (n) {
      setNotice(n);
      if (n.tone === 'ok') update((s) => ({ ...s, mode: 'live' }));
    }
  }, [update]);

  const data = useData(settings.mode, reloadKey);
  const reload = useCallback(() => setReloadKey((k) => k + 1), []);

  const timeline = useMemo(
    () => (data.snapshot ? buildTimeline(data.snapshot, settings.profile) : []),
    [data.snapshot, settings.profile],
  );

  const found = picked ? timeline.findIndex((d) => d.date === picked) : -1;
  const cur = found >= 0 ? found : timeline.length - 1;
  const day = timeline[cur];

  const setMode = (mode: Mode) => {
    setPicked(null);
    update((s) => ({ ...s, mode }));
  };

  const today = todayLocal();
  const relative = day
    ? day.date === today
      ? 'Today'
      : day.date === addDays(today, -1)
        ? 'Yesterday'
        : null
    : null;

  let body: ReactNode;
  if (route === 'settings') {
    body = (
      <Settings
        settings={settings}
        status={data.status}
        onMode={setMode}
        onProfile={(patch) => update((s) => ({ ...s, profile: { ...s.profile, ...patch } }))}
        onReload={reload}
      />
    );
  } else if (data.phase === 'loading' && !data.snapshot) {
    body = <div className="card empty" aria-busy="true"><p className="muted">Loading your data…</p></div>;
  } else if (data.phase === 'error') {
    body = (
      <div className="card empty">
        <h2>Couldn't load your data</h2>
        <p className="muted">{data.error}</p>
        <div className="actions center">
          <a className="btn primary" href="#/settings">Open settings</a>
          <button type="button" className="btn" onClick={() => setMode('demo')}>Use demo data</button>
        </div>
      </div>
    );
  } else if (!day) {
    body = (
      <div className="card empty">
        <h2>No data yet</h2>
        <p className="muted">Nothing came back from your connected sources for this period.</p>
      </div>
    );
  } else if (route === 'today') {
    body = <Today day={day} week={timeline.slice(Math.max(0, cur - 6), cur + 1)} onSelect={setPicked} />;
  } else if (route === 'sleep') {
    body = <Sleep day={day} recent={timeline.slice(Math.max(0, cur - 13), cur + 1)} />;
  } else if (route === 'activity') {
    body = <Activity days={timeline.slice(0, cur + 1)} maxHr={settings.profile.maxHr} />;
  } else {
    body = <Trends days={timeline} />;
  }

  const isDayRoute = DAY_ROUTES.includes(route);
  // On the Today screen the heading *is* the day ("Today", "Yesterday", "Wed 28 Oct").
  const title = route === 'today' && day ? (relative ?? fmtDay(day.date)) : ROUTES.find((r) => r.id === route)!.label;
  const subtitle =
    !isDayRoute || !day
      ? null
      : route === 'today'
        ? relative
          ? fmtDay(day.date)
          : null
        : `${relative ? `${relative} · ` : ''}${fmtDay(day.date)}`;

  return (
    <div className="app">
      <nav className="nav" aria-label="Main">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true" />
          Vital
        </div>
        {ROUTES.map((r) => (
          <a key={r.id} href={`#/${r.id}`} className={route === r.id ? 'active' : ''} aria-current={route === r.id ? 'page' : undefined}>
            {r.icon}
            <span>{r.label}</span>
          </a>
        ))}
        <div className="nav-foot">
          <span className={`badge ${settings.mode === 'demo' ? 'badge-idle' : 'badge-ok'}`}>
            {settings.mode === 'demo' ? 'Demo data' : 'Live data'}
          </span>
        </div>
      </nav>

      <main className="main">
        <header className="top">
          <div>
            <h1>{title}</h1>
            {subtitle && <p className="sub">{subtitle}</p>}
          </div>
          <div className="top-actions">
            {isDayRoute && timeline.length > 0 && (
              <div className="datenav" role="group" aria-label="Change day">
                <button type="button" aria-label="Previous day" disabled={cur <= 0} onClick={() => setPicked(timeline[cur - 1].date)}>
                  <IconChevron dir="left" />
                </button>
                <button
                  type="button"
                  className="datenav-today"
                  disabled={cur === timeline.length - 1}
                  onClick={() => setPicked(null)}
                >
                  Latest
                </button>
                <button type="button" aria-label="Next day" disabled={cur >= timeline.length - 1} onClick={() => setPicked(timeline[cur + 1].date)}>
                  <IconChevron dir="right" />
                </button>
              </div>
            )}
            {settings.mode === 'live' && route !== 'settings' && (
              <button type="button" className="icon-btn" aria-label="Refresh data" onClick={reload} disabled={data.phase === 'loading'}>
                <IconRefresh />
              </button>
            )}
          </div>
        </header>

        {notice && (
          <div className={`notice notice-${notice.tone}`} role="status">
            {notice.text}
            <button type="button" aria-label="Dismiss" onClick={() => setNotice(null)}>×</button>
          </div>
        )}
        {route !== 'settings' && data.notes.map((n) => (
          <div key={n} className="notice notice-warn" role="status">{n}</div>
        ))}

        {body}
      </main>
    </div>
  );
}
