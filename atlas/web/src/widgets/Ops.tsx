import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, errText } from "../api";
import { ErrorBox, Panel } from "../ui";
import type { OpsJob } from "../whatif";

const mins = (s: number) => (s < 120 ? `${Math.round(s)}s` : s < 7200 ? `${Math.round(s / 60)} min` : `${(s / 3600).toFixed(1)} h`);
const ago = (iso: string | null) => (iso ? `${mins((Date.now() - new Date(iso).getTime()) / 1000)} ago` : "never");
const when = (iso: string | null) => (iso ? new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "n/a");
const num = (x: number) => x.toLocaleString("en-US", { maximumFractionDigits: 2 });

function JobRow({ j, act }: { j: OpsJob; act: (path: string, body?: unknown) => void }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <tr data-testid={`ops-job-${j.id}`}>
        <td><b>{j.title}</b>{j.running && <span className="pill"> running</span>}{j.paused && <span className="pill warn"> paused</span>}{!j.enabled && <span className="pill warn"> off</span>}</td>
        <td className={`small ${j.stale && j.enabled ? "warnc" : "dim"}`}>{ago(j.last_success_at)}{j.stale && j.enabled && j.last_success_at ? " · stale" : ""}</td>
        <td className="small">{when(j.next_run_at)}</td>
        <td className="small">{mins(j.effective_interval_s)}{j.differs ? <span className="warnc"> (you asked {mins(j.preferred_now_s)})</span> : ""}</td>
        <td className={`small ${j.last_status === "ok" ? "up" : j.last_status === "deferred" ? "warnc" : j.last_status ? "down" : "dim"}`}>{j.last_status ?? "not yet"}{j.failures > 0 ? ` · ${j.failures} failed in a row` : ""}</td>
        <td><button className="mini" onClick={() => act(`jobs/${j.id}/run`)} data-testid={`ops-run-${j.id}`}>run now</button> <button className="mini" onClick={() => setOpen(!open)}>{open ? "close" : "details"}</button></td>
      </tr>
      {open && <tr><td colSpan={6} className="small">
        <div className="dim">{j.description}</div>
        <div>Why this interval: {j.why_effective.join("; ")}.</div>
        {j.deferred_reason && <div className="warnc">Deferred: {j.deferred_reason}</div>}
        {j.last_error && <div className="down">Last error: {j.last_error}</div>}
        <div className="dim">Average per run: {j.avg_runtime_s ? `${j.avg_runtime_s.toFixed(1)}s` : "n/a"}{j.uses_ai ? `, ${j.avg_tokens ? Math.round(j.avg_tokens) : "n/a"} tokens (limit ${num(j.max_tokens)})` : ", no AI"} · {j.runs_total} successful runs · priority {j.priority}/5</div>
        <div className="toolbar">
          <label>market hours every <input defaultValue={Math.round(j.preferred_market_s / 60)} style={{ width: 54 }} onBlur={(e) => { const v = Math.round(Number(e.target.value) * 60); if (v >= 30) act(`jobs/${j.id}`, { interval_market_s: v }); }} /> min</label>
          <label>otherwise every <input defaultValue={Math.round(j.preferred_off_s / 60)} style={{ width: 54 }} onBlur={(e) => { const v = Math.round(Number(e.target.value) * 60); if (v >= 30) act(`jobs/${j.id}`, { interval_off_s: v }); }} /> min</label>
          <button className="mini" onClick={() => act(`jobs/${j.id}`, { enabled: !j.enabled })}>{j.enabled ? "turn off" : "turn on"}</button>
          <button className="mini" onClick={() => act(`jobs/${j.id}`, { paused: !j.paused })}>{j.paused ? "resume job" : "pause job"}</button>
        </div></td></tr>}
    </>);
}

/** Operations: is the background scheduler alive, what ran, what is next, why intervals differ, how much of each allowance is used, and the controls (pause, run now, emergency stop). */
export function OpsWidget() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["ops"], queryFn: api.opsOverview, refetchInterval: 20_000, retry: 0 });
  const m = useMutation({ mutationFn: ({ path, b }: { path: string; b?: unknown }) => api.opsPost(path, b), onSuccess: (d) => qc.setQueryData(["ops"], d) });
  const act = (path: string, b?: unknown) => m.mutate({ path, b });
  const d = q.data;
  return (
    <Panel title="OPERATIONS · scheduler, jobs and budgets" right={d && <span className={`pill ${d.emergency_stop || !d.scheduler_alive ? "warn" : ""}`}>{d.emergency_stop ? "EMERGENCY STOP" : d.paused ? "PAUSED" : d.scheduler_alive ? "scheduler running" : "scheduler not seen"}</span>}>
      {q.isLoading && <div className="note">Loading…</div>}
      {q.isError && <ErrorBox error={q.error} />}
      {m.isError && <div className="note warn">{errText(m.error)}</div>}
      {d && <div data-testid="ops">
        {!d.scheduler_alive && <div className="note warn">The scheduler has not checked in recently{d.scheduler_heartbeat_age_s != null ? ` (${mins(d.scheduler_heartbeat_age_s)} ago)` : ""}. Jobs only run while the app or its worker process is running.</div>}
        <div className="toolbar">
          {d.paused ? <button className="mini on" onClick={() => act("resume")}>resume all</button> : <button className="mini" onClick={() => act("pause")}>pause all</button>}
          {d.emergency_stop ? <button className="mini on" onClick={() => act("emergency-clear")} data-testid="ops-clear-stop">clear emergency stop</button> : <button className="mini" onClick={() => { if (window.confirm("Stop every job now? Nothing will run until you clear it.")) act("emergency-stop"); }} data-testid="ops-stop">EMERGENCY STOP</button>}
          <span className="dim small">Market {d.market_open ? "open" : "closed"} · reserve {d.reserve_pct}% · {d.max_concurrent} jobs at a time</span>
        </div>
        <div className="ws-bar" style={{ paddingLeft: 0 }}><span>JOBS</span></div>
        <table className="tbl"><thead><tr><th>Job</th><th>Last success</th><th>Next run</th><th>Effective interval</th><th>Status</th><th /></tr></thead><tbody>
          {d.jobs.map((j) => <JobRow key={j.id} j={j} act={act} />)}
        </tbody></table>
        <div className="small dim">{d.market_note}</div>
        <div className="ws-bar" style={{ paddingLeft: 0 }}><span>ALLOWANCES</span></div>
        <div className="note" data-testid="ops-claude"><b>Claude:</b> access {d.claude.access === "unknown" ? <b className="warnc">not set</b> : <b>{d.claude.access}</b>} · model {d.claude.model} · {d.claude.usage_note}{!d.claude.dollar_cost_known && " Dollar cost is unknown until you enter the current prices."}</div>
        <table className="tbl"><thead><tr><th>Budget</th><th className="r">Used</th><th className="r">Limit</th><th className="r">Left</th><th>Resets (UTC)</th></tr></thead><tbody>
          {d.budgets.map((b) => <tr key={b.bucket} title={b.note ?? ""}><td>{b.bucket} <span className="dim small">per {b.window}</span></td><td className="r mono">{num(b.used)} {b.unit}</td><td className="r mono">{b.limit == null ? "not set" : num(b.limit)}</td>
            <td className={`r mono ${b.remaining_fraction != null && b.remaining_fraction < 0.2 ? "down" : ""}`}>{b.remaining_fraction == null ? "n/a" : `${Math.round(b.remaining_fraction * 100)}%`}</td><td className="small dim">{b.resets_at.slice(5, 16).replace("T", " ")}</td></tr>)}
        </tbody></table>
        {d.dead_letters.length > 0 && <>
          <div className="ws-bar" style={{ paddingLeft: 0 }}><span>NEEDS ATTENTION · repeated failures</span></div>
          {d.dead_letters.map((x) => <div key={x.id} className="small down">{x.job_id}: {x.error} ({x.attempts} attempts) <button className="mini" onClick={() => act(`dead-letters/${x.id}/retry`)}>retry</button> <button className="mini" onClick={() => act(`dead-letters/${x.id}/dismiss`)}>dismiss</button></div>)}</>}
        <div className="ws-bar" style={{ paddingLeft: 0 }}><span>RECENT RUNS</span></div>
        <table className="tbl"><tbody>
          {d.runs.slice(0, 12).map((r) => <tr key={r.id}><td className="small">{when(r.started_at)}</td><td>{r.job_id}</td><td className={`small ${r.status === "ok" ? "up" : r.status === "deferred" ? "warnc" : "down"}`}>{r.status}</td>
            <td className="small dim">{r.reason ?? r.error ?? `${r.duration_s?.toFixed(1) ?? "?"}s${r.tokens_in + r.tokens_out ? ` · ${r.tokens_in + r.tokens_out} tokens` : ""}${r.provider_calls ? ` · ${r.provider_calls} calls` : ""}`}</td></tr>)}
        </tbody></table>
        {d.events.length > 0 && <>
          <div className="ws-bar" style={{ paddingLeft: 0 }}><span>NOTICES</span></div>
          {d.events.slice(0, 8).map((e, i) => <div key={i} className={`small ${e.severity === "critical" ? "down" : e.severity === "warn" ? "warnc" : "dim"}`}>{when(e.ts)} · {e.message}</div>)}</>}
      </div>}
    </Panel>);
}
