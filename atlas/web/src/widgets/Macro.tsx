import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { fmtChange, fmtValue, MacroFact } from "../macro";
import { ErrorBox, Panel } from "../ui";

function FactRow({ f }: { f: MacroFact }) {
  if (f.error) return <tr><td><b>{f.label}</b></td><td colSpan={5} className="down small">Unavailable: {f.error}</td></tr>;
  const fr = f.freshness;
  return (
    <tr>
      <td><b>{f.label}</b>{f.id === "curve" && f.inverted && <span className="warnc small"> inverted</span>}{f.note && <div className="dim small">{f.note}</div>}</td>
      <td className="r mono">{fmtValue(f)}</td>
      <td className="small">{f.id === "fed" ? <span className="dim">{f.unchanged_since_is_lower_bound ? "unchanged since at least" : "unchanged since"} {f.unchanged_since}</span>
        : (f.changes ?? []).map((c) => <div key={c.label} title={`${c.label} (${c.ref_date})`}>{fmtChange(c)} <span className="dim">{c.label.replace("vs ", "")}</span></div>)}</td>
      <td className="mono small">{f.obs_date}{f.index_level !== undefined && <div className="dim">index {f.index_level.toFixed(1)}</div>}</td>
      <td className={`small ${fr?.state === "OVERDUE" ? "warnc" : "up"}`} title={fr?.rule}>{fr ? (fr.state === "CURRENT" ? "Current" : "Overdue") : ""}<div className="dim">{fr ? `${fr.age_days}d old` : ""}</div></td>
      <td className="dim small">{f.unit}</td>
    </tr>);
}

/** Facts (official FRED observations) and, separately, rule-based educational notes. Not signals, not a score. */
export function MacroDashboard() {
  const q = useQuery({ queryKey: ["macro"], queryFn: api.macroOverview, staleTime: 10 * 60_000, refetchInterval: 30 * 60_000 });
  const d = q.data;
  return (
    <Panel title="MACRO DASHBOARD">
      {q.isError && <ErrorBox error={q.error} />}
      {q.isLoading && <div className="note">Loading FRED observations…</div>}
      {d?.demo && <div className="note warn">{d.notice}</div>}
      {d && !d.demo && <>
        <div className="ws-bar" style={{ paddingLeft: 0 }}><span>FACTS · official observations</span></div>
        <table className="tbl"><thead><tr><th>Indicator</th><th className="r">Latest</th><th>Change</th><th>Observed</th><th title="Judged against how often each series is published">Freshness</th><th>Unit</th></tr></thead>
          <tbody>{d.facts.map((f) => <FactRow key={f.id} f={f} />)}</tbody></table>
        <div className="note">{d.source} Dates are observation dates, not release dates.</div>
        <div className="ws-bar" style={{ paddingLeft: 0 }}><span>INTERPRETATION · educational, rule-based, not a signal</span></div>
        {d.interpretations.length === 0 && <div className="note">Nothing in the facts above triggers a note right now.</div>}
        {d.interpretations.map((n) => (
          <div key={n.id} className="card" style={{ borderColor: "var(--border)", marginBottom: 4 }}>
            <div className="small">{n.text}</div>
            <div className="dim small">Keep in mind: {n.caveat} <span title="Facts this note is based on">· based on {n.based_on.join(", ")}</span></div>
          </div>))}
        <div className="note">{d.interpretation_note}</div>
      </>}
    </Panel>);
}
