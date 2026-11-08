import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, errText } from "../api";
import { CalEvent, KIND_LABEL } from "../calendar";
import { ErrorBox, Panel } from "../ui";

const KINDS = ["", "earnings", "economy", "rates", "dividend", "auction"] as const;
const SCOPES: [string, string][] = [["major", "Major companies"], ["watchlist", "My watchlist"], ["all", "Everything"]];
const DOT: Record<string, string> = { high: "#ff5a66", medium: "#f5a524", low: "#6c7380" };
const money = (x: number | null | undefined) => (typeof x === "number" ? `$${x.toFixed(2)}` : "n/a");
const dayLabel = (iso: string, today: string) => {
  const d = new Date(iso + "T12:00:00Z");
  const w = d.toLocaleDateString([], { weekday: "long", month: "short", day: "numeric", timeZone: "UTC" });
  return iso === today ? `Today · ${w}` : w;
};
const clock = (e: CalEvent) => (e.at_utc ? new Date(e.at_utc).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : e.time_label ?? "");

function Detail({ e }: { e: CalEvent }) {
  const d = e.details;
  if (e.kind === "earnings") return <span className="dim small">{d.quarter_ending ? `quarter ending ${d.quarter_ending} · ` : ""}estimate {money(d.eps_estimate as number | null)}{d.analysts ? ` (${d.analysts} analysts)` : ""} · a year ago {money(d.last_year_eps as number | null)}{e.market_cap ? ` · value $${(e.market_cap / 1e9).toFixed(0)}B` : ""}</span>;
  if (e.kind === "dividend") return <span className="dim small">{money(d.amount as number | null)} per share · pays {String(d.pay_date ?? "n/a")}{d.record_date ? ` · record ${String(d.record_date)}` : ""}</span>;
  if (e.kind === "auction") return <span className="dim small">issued {String(d.issue_date ?? "n/a")}</span>;
  return <span className="dim small">{String(d.release ?? d.meeting ?? "")}</span>;
}

/** Earnings, economic data (CPI, jobs, GDP, PCE), Fed decisions, dividends and Treasury auctions in one list, grouped by day. */
export function CalendarWidget() {
  const qc = useQueryClient();
  const [days, setDays] = useState(14);
  const [kind, setKind] = useState("");
  const [scope, setScope] = useState("major");
  const q = new URLSearchParams({ days: String(days), scope, ...(kind && { kinds: kind }) }).toString();
  const cal = useQuery({ queryKey: ["calendar", q], queryFn: () => api.calendar(q), staleTime: 10 * 60_000, retry: 0 });
  const wls = useQuery({ queryKey: ["watchlists"], queryFn: api.watchlists });
  const wl = wls.data?.[0];
  const add = useMutation({ mutationFn: (id: string) => api.wlAdd(wl!.id, id), onSuccess: () => { qc.invalidateQueries({ queryKey: ["watchlists"] }); qc.invalidateQueries({ queryKey: ["calendar"] }); } });
  const d = cal.data;
  const today = new Date().toISOString().slice(0, 10);
  const groups = (d?.items ?? []).reduce<Record<string, CalEvent[]>>((a, e) => ({ ...a, [e.date]: [...(a[e.date] ?? []), e] }), {});
  return (
    <Panel title="CALENDAR · earnings, economy, rates, dividends" right={d && <span className={`pill ${d.demo ? "warn" : ""}`}>{d.demo ? "DEMO" : `${d.from} to ${d.to}`}</span>}>
      <div className="toolbar" data-testid="cal-controls">
        <span className="savedchip">{[7, 14, 21].map((n) => <button key={n} className={`mini ${days === n ? "on" : ""}`} onClick={() => setDays(n)}>{n}d</button>)}</span>
        <span className="savedchip">{KINDS.map((k) => <button key={k || "all"} className={`mini ${kind === k ? "on" : ""}`} onClick={() => setKind(k)} data-testid={`cal-kind-${k || "all"}`}>{k ? KIND_LABEL[k] : "All"}</button>)}</span>
        <select value={scope} onChange={(e) => setScope(e.target.value)} aria-label="Which companies">{SCOPES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
      </div>
      {cal.isLoading && <div className="note">Loading the calendar… the first load fetches several sources and can take a few seconds.</div>}
      {cal.isError && <ErrorBox error={cal.error} />}
      {d && <div data-testid="calendar">
        {d.sources.some((s) => !s.ok) && <div className="note warn">Some sources could not be loaded: {d.sources.filter((s) => !s.ok).map((s) => `${s.name} (${s.error})`).join("; ")}. The rest is shown.</div>}
        {d.notes.map((n, i) => <div key={i} className="note warn">{n}</div>)}
        {d.items.length === 0 && <div className="note">Nothing in this window for these filters.</div>}
        {Object.entries(groups).map(([day, evs]) => (
          <div key={day} style={{ marginBottom: 8 }}>
            <div className="ws-bar" style={{ paddingLeft: 0 }}><span>{dayLabel(day, today)}</span><span className="dim small">{evs.length} event{evs.length === 1 ? "" : "s"}</span></div>
            {evs.map((e, i) => (
              <div key={i} className="small" style={{ margin: "5px 0", display: "flex", gap: 8, alignItems: "baseline" }} data-testid={`cal-event-${e.kind}`}>
                <span style={{ color: DOT[e.importance] }} title={`${e.importance} importance`}>●</span>
                <span className="pill">{KIND_LABEL[e.kind]}</span>
                <span style={{ flex: 1 }}>
                  <b>{e.symbol ? <>{e.symbol} <span className="dim">{e.name}</span></> : e.title}</b>{e.symbol && e.kind === "dividend" ? " ex-dividend" : e.symbol ? " reports" : ""}{e.watch && <span title="On your watchlist"> ★</span>}
                  <div><Detail e={e} /><span className="dim small"> · {clock(e)}{clock(e) ? " · " : ""}{e.official ? "official" : "unofficial"}</span></div>
                </span>
                {e.instrument_id && wl && !wl.items.includes(e.instrument_id) && <button className="mini" onClick={() => add.mutate(e.instrument_id!)}>add to watchlist</button>}
              </div>))}
          </div>))}
        {add.isError && <div className="warnc small">{errText(add.error)}</div>}
        <div className="small dim">{d.importance_note} ● red = high, amber = medium, grey = low. Sources: {d.sources.map((s) => `${s.name}${s.ok ? "" : " (failed)"}`).join(", ")}. {d.labels.unofficial}</div>
      </div>}
    </Panel>);
}
