import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { countdown, fmtChange, fmtValue, localTime, OUTCOME_TEXT, FedRelease } from "../macro";
import { ErrorBox } from "../ui";
import { wordDates, ymdLabel as ymd } from "../fmt";

const TZ = Intl.DateTimeFormat().resolvedOptions().timeZone;
const Tag = ({ kind }: { kind: "Scheduled" | "Published fact" | "Interpretation" }) => <span className="pill neutral" style={{ marginRight: 6 }}>{kind}</span>;

function useNow(ms = 30_000) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), ms); return () => clearInterval(t); }, [ms]);
  return now;
}

function ReleaseRow({ f }: { f: FedRelease }) {
  if (f.error) return <tr><td><b>{f.label}</b></td><td colSpan={4} className="down small">Unavailable: {f.error}</td></tr>;
  const fr = f.freshness;
  return (
    <tr>
      <td><b>{f.label}</b><div className="dim small">{f.relevance}</div><div className="dim small">{f.consensus_note}</div></td>
      <td className="r mono">{f.value === undefined || f.value === null ? "n/a" : f.id === "payrolls" ? `${f.value >= 0 ? "+" : "−"}${Math.abs(f.value).toFixed(0)}k` : fmtValue(f)}<div className="dim small">{f.unit}</div></td>
      <td className="small">{(f.changes ?? []).map((c) => <div key={c.label}>{fmtChange(c)} <span className="dim">{wordDates(c.label.replace("vs ", ""))}</span></div>)}{f.note && <div className="dim">{f.note}</div>}</td>
      <td className="mono small">{ymd(f.obs_date)}</td>
      <td className={`small ${fr?.state === "OVERDUE" ? "warnc" : "up"}`} title={fr?.rule}>{fr?.state === "OVERDUE" ? "Overdue" : "Current"}<div className="dim">{fr ? `${fr.age_days}d old` : ""}</div></td>
    </tr>);
}

/** Scheduled events, published facts and rule-based scenarios, each labelled. Times are shown in the viewer's timezone. */
export function FedWatchTab() {
  const q = useQuery({ queryKey: ["macroFed"], queryFn: api.macroFed, staleTime: 10 * 60_000, refetchInterval: 15 * 60_000 });
  const now = useNow();
  const d = q.data;
  const [pick, setPick] = useState<"raised" | "cut" | "held" | null>(null);
  if (q.isError) return <ErrorBox error={q.error} />;
  if (!d) return <div className="note">Loading Federal Reserve data…</div>;
  const latest = d.decisions.find((x) => x.outcome);
  const scen = pick ?? latest?.outcome ?? "held";
  const next = d.upcoming.find((e) => e.type === "statement") ?? d.upcoming[0];
  return (
    <div>
      <div className="note">Times are shown in your timezone ({TZ}). Sources: federalreserve.gov, FRED mirrors of BLS/BEA data. Nothing here is a prediction or advice.{d.demo && ` ${d.notice}`}</div>

      <div className="ws-bar" style={{ paddingLeft: 0 }}><span><Tag kind="Scheduled" />UPCOMING</span></div>
      {d.calendar?.needs_update && <div className="note warn"><b>{d.calendar.message}</b> <a href={d.calendar.link} target="_blank" rel="noreferrer noopener">Official Fed calendar</a></div>}
      {next && <div className="bigpx mono" style={{ fontSize: 15 }}>{next.title}: <span className="up">{countdown(next.at_utc, now)}</span> <span className="dim small">· {localTime(next.at_utc)}</span></div>}
      <table className="tbl"><tbody>
        {d.upcoming.map((e) => (
          <tr key={e.id}><td><b>{e.title}</b><div className="dim small">{e.meeting}</div></td><td className="small">{localTime(e.at_utc)}</td><td className="small up">{countdown(e.at_utc, now)}</td>
            <td className="small"><a href={e.link} target="_blank" rel="noreferrer noopener">Fed calendar</a></td></tr>))}
        {d.release_schedule.map((e) => (
          <tr key={e.name + e.date}><td><b>{e.label} release</b><div className="dim small">{e.name}</div></td><td className="small">{e.at_utc ? localTime(e.at_utc) : e.date}</td>
            <td className="small up">{e.at_utc ? countdown(e.at_utc, now) : "time not listed"}</td><td className="small"><a href={d.links.bls_schedule} target="_blank" rel="noreferrer noopener">BLS schedule</a></td></tr>))}
      </tbody></table>
      <div className="note">FOMC dates are a hand-entered table; usual times are 2:00 pm ET for the statement and 2:30 pm ET for the press conference. {d.schedule_note} <a href={d.links.bea_schedule} target="_blank" rel="noreferrer noopener">BEA schedule (PCE, GDP)</a>.</div>

      <div className="ws-bar" style={{ paddingLeft: 0 }}><span><Tag kind="Published fact" />RATE DECISIONS</span></div>
      {d.decisions_error && <div className="note warn">{d.decisions_error}</div>}
      <table className="tbl"><thead><tr><th>Decision announced</th><th>Result</th><th title="The last FRED value before the meeting">Range before</th><th title="FRED dates are effective dates, not announcement times">Range after (first FRED date)</th><th>Announced at</th></tr></thead>
        <tbody>{d.decisions.map((x) => (
          <tr key={x.meeting_end}><td className="mono">{x.announced_date ?? x.meeting_end}</td>
            <td><b>{x.outcome ? OUTCOME_TEXT[x.outcome] : "n/a"}</b>{x.change_bps ? <span className="dim small"> {x.change_bps > 0 ? "+" : "−"}{Math.abs(x.change_bps).toFixed(0)} bps</span> : null}{x.note && <div className="dim small">{x.note}</div>}</td>
            <td className="mono small">{x.previous ? `${x.previous.lower.toFixed(2)}–${x.previous.upper.toFixed(2)}%` : "–"}{x.previous && <div className="dim">FRED {x.previous.obs_date}</div>}</td>
            <td className="mono small">{x.new ? `${x.new.lower.toFixed(2)}–${x.new.upper.toFixed(2)}%` : "–"}{x.new && <div className="dim">{x.effective_obs_date ? `effective in FRED ${x.effective_obs_date}` : "no change"}</div>}</td>
            <td className="small">{localTime(x.announced_utc)}</td></tr>))}</tbody></table>
      <div className="note">Computed from the Fed's published target-range series (FRED), compared before and after each meeting. {d.decisions.find((x) => x.date_note)?.date_note}</div>

      <div className="ws-bar" style={{ paddingLeft: 0 }}><span><Tag kind="Interpretation" />POSSIBLE SCENARIOS</span>
        {(["raised", "cut", "held"] as const).map((k) => <button key={k} className={`mini ${scen === k ? "on" : ""}`} onClick={() => setPick(k)}>{OUTCOME_TEXT[k]}</button>)}</div>
      <table className="tbl kv"><tbody>{(["equities", "bonds", "dollar", "crypto"] as const).map((a) => <tr key={a}><td className="dim" style={{ textTransform: "capitalize" }}>{a}</td><td className="small">{d.scenarios[scen][a]}</td></tr>)}</tbody></table>
      <div className="note">{d.scenario_note}</div>

      <div className="ws-bar" style={{ paddingLeft: 0 }}><span><Tag kind="Published fact" />FED ANNOUNCEMENTS &amp; SPEECHES</span></div>
      {d.feed_status.filter((s) => !s.ok).map((s) => <div key={s.feed} className="note warn">{s.feed}: unavailable ({s.error}). Items below may be incomplete.</div>)}
      {d.communications.length === 0 && <div className="note">No Fed announcements loaded.</div>}
      {d.communications.slice(0, 12).map((c) => (
        <div key={(c.link ?? c.title) + c.published_utc} className="card" style={{ borderColor: "var(--border)", marginBottom: 4 }}>
          <div className="small"><span className="pill neutral">{c.type_label}{c.type === "speech" && c.significant ? " · Chair/Vice Chair" : ""}</span> {c.link ? <a href={c.link} target="_blank" rel="noreferrer noopener"><b>{c.title}</b></a> : <b>{c.title}</b>} <span className="dim">· {localTime(c.published_utc)} · {c.feed}</span></div>
          {c.summary && <div className="dim small">“{c.summary}” <span>(Fed's own text)</span></div>}
          <div className="small"><Tag kind="Interpretation" />{c.why_it_matters}</div>
        </div>))}
      <div className="note">Items are matched to types by their titles. Dot-plot values are not extracted; open the Fed's projections page from the calendar link.</div>

      <div className="ws-bar" style={{ paddingLeft: 0 }}><span><Tag kind="Published fact" />RELATED RELEASES (BLS / BEA via FRED)</span></div>
      <table className="tbl"><thead><tr><th>Release and why the Fed cares</th><th className="r">Latest</th><th>Change</th><th>Observed</th><th>Freshness</th></tr></thead><tbody>{d.releases.map((f) => <ReleaseRow key={f.id} f={f} />)}</tbody></table>
      <div className="note">Observation dates are reference periods, not release times. Actual-versus-consensus is not shown: there is no reliable free consensus source.</div>

      {d.balance_sheet && <>
        <div className="ws-bar" style={{ paddingLeft: 0 }}><span><Tag kind="Published fact" />BALANCE SHEET (runoff / expansion)</span></div>
        {d.balance_sheet.error ? <div className="note warn">Unavailable: {d.balance_sheet.error}</div> : <>
          <div className="small"><b className="mono">${d.balance_sheet.value?.toFixed(2)} trillion</b> total assets, observed {ymd(d.balance_sheet.obs_date)}{d.balance_sheet.trend && <> · <b>{d.balance_sheet.trend}</b> over ~13 weeks</>}
            {(d.balance_sheet.changes ?? []).map((c) => <span key={c.label} className="dim"> · {fmtChange(c)} {wordDates(c.label.replace("vs ", ""))}</span>)}</div>
          <div className="dim small">{d.balance_sheet.trend_rule}</div>
          <div className="small"><Tag kind="Interpretation" />{d.balance_sheet.why_it_matters}</div></>}
      </>}
      {d.errors.length > 0 && <div className="note warn">Some sources failed: {d.errors.join("; ")}</div>}
      <div className="note">{d.interpretation_note}</div>
    </div>);
}
