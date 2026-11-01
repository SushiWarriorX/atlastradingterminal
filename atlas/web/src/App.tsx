import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "./api";
import { useStore } from "./store";
import { NAV } from "./workspaces";
import { TopBar } from "./TopBar";
import { Workspace } from "./Workspace";

// Ctrl+1..7 follow the sidebar order, so the ^n labels shown there are always right
const HOTKEYS: Record<string, string> = Object.fromEntries(NAV.slice(0, 7).map((n, i) => [String(i + 1), n.view]));
const HELP = [
  ["BTC", "BTC desk"], ["SPX", "indices and macro series open on the Overview chart"], ["AAPL", "equity desk for AAPL"], ["NVDA TECH", "technical levels for NVDA"],
  ["AI BTC", "AI technical brief on BTC (AI panel on Overview)"], ["MACRO", "macro desk (yields)"], ["COMPARE BTC QQQ", "overlay on the Overview chart, rebased to 100 + correlation (daily/weekly)"], ["BTC MTF / NVDA MTF", "multi-timeframe structure and score"],
  ["SCAN BREAKOUT", "run a preset: BREAKOUT PULLBACK VOLUME RS REVERSAL COMPRESSION BREAKDOWN"], ["NEWS / AAPL NEWS", "RSS headlines (polled, DELAYED), near-duplicates grouped, feeds editable"], ["natural language", "5+ words routes to the AI desk"],
];

export function App() {
  const { hydrate, hydrated, workspace, setWorkspace, notice, setNotice, helpOpen, setHelp } = useStore();
  const views = useQuery({ queryKey: ["views"], queryFn: api.views, staleTime: Infinity });
  const st = useQuery({ queryKey: ["status"], queryFn: api.status, refetchInterval: 15_000 });
  useEffect(() => { hydrate(); }, [hydrate]);
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && HOTKEYS[e.key]) { e.preventDefault(); setWorkspace(HOTKEYS[e.key]); }
      if (e.key === "Escape") { setHelp(false); setNotice(null); }
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, [setWorkspace, setHelp, setNotice]);
  if (!hydrated) return <div className="boot">Loading…</div>;
  const lastSync = st.dataUpdatedAt ? new Date(st.dataUpdatedAt).toLocaleTimeString("en-GB") : "—";
  return (
    <div className="app">
      <TopBar />
      <div className="body">
        <nav className="side" aria-label="Main navigation">
          {NAV.map((n, i) => {
            const m = views.data?.[n.view];
            return (
              <button key={n.view} className={`nav ${workspace === n.view ? "on" : ""}`} onClick={() => setWorkspace(n.view)} title={m && !m.implemented ? `Not built yet (Phase ${m.phase})` : n.label}>
                <span>{n.label}</span>{m && !m.implemented ? <span className="ph">P{m.phase}</span> : i < 7 ? <span className="hk">^{i + 1}</span> : null}
              </button>);
          })}
        </nav>
        <main className="main">
          {notice && <div className="notice" onClick={() => setNotice(null)}>{notice} <span className="dim">(click to dismiss)</span></div>}
          <Workspace view={workspace} />
        </main>
      </div>
      <footer className="statusbar">
        <span>DATA HEALTH: {st.isError ? <b className="down">API DOWN</b> : st.data ? Object.entries(st.data.providers).map(([n, p]) => `${n}:${p.consecutive_failures ? "FAIL" : p.ok ? "ok" : "idle"}`).join(" ") : "…"}</span>
        <span>LAST SYNC {lastSync}</span>
        <span>AGENT: {st.data?.ai.configured ? "ready" : "off"}</span>
        <span className="env">{st.data?.broker_env ?? "—"} MODE · live trading unavailable</span>
      </footer>
      {helpOpen && (
        <div className="modal" onClick={() => setHelp(false)}><div className="modal-b" onClick={(e) => e.stopPropagation()}>
          <h3>COMMANDS</h3>
          <table className="tbl"><tbody>{HELP.map(([c, d]) => <tr key={c}><td className="mono"><b>{c}</b></td><td className="dim">{d}</td></tr>)}</tbody></table>
          <h3>KEYS</h3>
          <p className="dim small">/ or Ctrl+K focus the command bar · Ctrl+1..7 jump to workspaces · Tab autocompletes · Esc closes</p>
          <button className="mini" onClick={() => setHelp(false)}>close</button>
        </div></div>)}
    </div>
  );
}
