import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, StripItem } from "./api";
import { clock, dir, nyDate, num, pct, px } from "./fmt";
import { useStore } from "./store";
import { CommandBar } from "./CommandBar";
import { Badge } from "./ui";

function useNow() {
  const [n, setN] = useState(new Date());
  useEffect(() => { const t = setInterval(() => setN(new Date()), 1000); return () => clearInterval(t); }, []);
  return n;
}

function StripCell({ it }: { it: StripItem }) {
  const select = useStore((s) => s.select);
  const q = it.quote;
  const yld = it.symbol.startsWith("US");
  return (
    <button className="cell" onClick={() => select(it.instrument_id)} title={it.error ?? it.name}>
      <span className="sym">{it.symbol}</span>
      {q ? <>
        <span className="mono">{yld ? `${num(q.price, 2)}%` : px(q.price)}</span>
        <span className={`mono ${dir(q.change_pct)}`}>{yld ? `${((q.change ?? 0) * 100).toFixed(0)}bp` : pct(q.change_pct)}</span>
        <Badge status={q.prov.status} /></> : <><span className="dim">—</span><Badge status="UNAVAILABLE" title={it.error} /></>}
    </button>
  );
}

export function TopBar() {
  const now = useNow();
  const every = useStore((s) => s.updateSeconds) * 1000;
  const setWorkspace = useStore((s) => s.setWorkspace);
  const strip = useQuery({ queryKey: ["strip"], queryFn: api.strip, refetchInterval: every });
  const st = useQuery({ queryKey: ["status"], queryFn: api.status, refetchInterval: 15_000 });
  const provs = st.data ? Object.values(st.data.providers) : [];
  const down = provs.filter((p) => p.consecutive_failures > 0).length;
  const conn = st.isError ? "bad" : down > 0 ? "warn" : provs.some((p) => p.ok > 0) ? "good" : "idle";
  const nf = useQuery({ queryKey: ["news-feeds"], queryFn: api.newsFeeds, refetchInterval: 30_000, retry: 0 });
  const on = nf.data?.feeds.filter((f) => f.enabled) ?? [];
  const okN = on.filter((f) => f.last_ok && !f.last_error).length, badN = on.filter((f) => f.last_error).length;
  const newsDot = nf.isError ? "bad" : badN ? "warn" : okN ? "good" : "idle";
  const newsTip = nf.isError ? "News service unreachable" : !on.length ? "No news feed is enabled" : okN || badN
    ? `${okN} of ${on.length} feeds fetched OK${badN ? `, ${badN} failing` : ""}. RSS is polled, not real time.` : "No feed has been fetched yet: open NEWS and press refresh";
  const sess = st.data?.ny.state ?? "—";
  return (
    <header className="topbar">
      <div className="row1">
        <div className="logo">ATLAS<span> TERMINAL</span></div>
        <CommandBar />
        <div className="times mono" title="Current time">
          <span>{nyDate(now)}</span><span>UTC {clock("UTC", now)}</span><span>NY {clock("America/New_York", now)}</span>
        </div>
        <span className={`chip sess ${sess}`} title={st.data ? `Next open ${st.data.ny.next_open}` : ""}>US {sess.replace("_", " ")}{st.data?.ny.early_close ? " · early close" : ""}</span>
        <span className="chip" title={provs.map((p, i) => `${Object.keys(st.data!.providers)[i]}: ${p.consecutive_failures ? "failing" : p.ok ? "ok" : "idle"}`).join("\n")}><span className={`dot ${conn}`} /> DATA</span>
        <button className="chip" onClick={() => setWorkspace("news")} title={newsTip}><span className={`dot ${newsDot}`} /> NEWS {on.length ? `${okN}/${on.length}` : "—"}</button>
        {st.data?.trading_halted && <span className="chip halted" title="Kill switch is on: no new orders">⛔ HALTED</span>}
        <span className="chip env" title="Paper trading only. No live broker connection exists in this build.">{st.data?.broker_env ?? "—"}</span>
        <span className="chip ai" title={st.data?.ai.model ?? "Set ANTHROPIC_API_KEY"}>AI {st.data?.ai.configured ? "READY" : "OFF"}</span>
        {st.data?.demo_mode && <span className="chip demo">DEMO DATA</span>}
      </div>
      <div className="row2">
        {strip.isError && <span className="down small">Backend unreachable: {(strip.error as Error).message}</span>}
        {strip.data?.map((it) => <StripCell key={it.instrument_id} it={it} />)}
        <span className="dim small spacer">Index levels from Yahoo (delayed). Yields: FRED daily.</span>
      </div>
    </header>
  );
}
