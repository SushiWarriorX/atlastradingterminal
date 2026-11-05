import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import type { BriefIndicator } from "../macro";
import { ErrorBox } from "../ui";

const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "");
const fmt = (i: BriefIndicator) => (typeof i.value === "number" ? `${i.value.toFixed(2)}${i.unit === "%" || i.unit?.startsWith("%") ? "%" : ""}` : i.value ?? "n/a");

/** One page: what matters today, key indicators, what is coming, and headlines. Facts, rule-based interpretation and headlines are labelled differently. */
export function MacroToday() {
  const q = useQuery({ queryKey: ["macro-brief"], queryFn: api.macroBrief, staleTime: 5 * 60_000, refetchInterval: 10 * 60_000 });
  const [topic, setTopic] = useState("");
  const [open, setOpen] = useState<number | null>(null);
  const d = q.data;
  if (q.isError) return <ErrorBox error={q.error} />;
  if (!d) return <div className="note">Loading the macro briefing…</div>;
  const heads = d.headlines.filter((h) => !topic || h.topic === topic);
  return (
    <div data-testid="macro-today">
      {d.demo && <div className="note warn">{d.notice ?? "Demo mode: official indicators and live headlines are not shown."}</div>}
      {d.calendar_warning && <div className="note warn">{d.calendar_warning}</div>}
      <div className="ws-bar" style={{ paddingLeft: 0 }}><span>WHAT MATTERS TODAY</span><span className="dim small">updated {when(d.as_of)}</span></div>
      {d.today.length === 0 && <div className="note">Nothing scheduled in the next two days and no indicator crosses a rule threshold.</div>}
      {d.today.map((t, i) => (
        <div key={i} className="small" style={{ margin: "6px 0" }}>
          <span className={`pill ${t.kind === "fact" ? "" : "warn"}`}>{t.kind === "fact" ? "Fact" : "Interpretation"}</span> {t.title}
          <div className="dim">{t.detail} · {t.source}</div>
        </div>))}
      <div className="ws-bar" style={{ paddingLeft: 0 }}><span>KEY INDICATORS · official, with observation date</span></div>
      <table className="tbl"><tbody>{d.indicators.map((i) => i.available ? (
        <tr key={i.id}><td><b>{i.label}</b></td><td className="r mono">{fmt(i)}</td>
          <td className="small">{i.change ? `${i.change.value >= 0 ? "+" : "−"}${Math.abs(i.change.value).toFixed(2)} ${i.change.unit}` : ""} <span className="dim">{i.change?.label.replace("vs ", "")}</span></td>
          <td className="mono small">{i.obs_date}</td><td className={`small ${i.freshness === "OVERDUE" ? "warnc" : "dim"}`}>{i.freshness === "OVERDUE" ? "Overdue" : "Current"}</td></tr>
      ) : <tr key={i.id}><td><b>{i.label}</b></td><td colSpan={4} className="down small">Unavailable: {i.reason}</td></tr>)}</tbody></table>
      {d.indicators.length === 0 && <div className="note">No official indicators loaded (no FRED key or demo mode).</div>}
      <div className="ws-bar" style={{ paddingLeft: 0 }}><span>UPCOMING · scheduled dates</span></div>
      {d.upcoming.length === 0 ? <div className="note">No upcoming events could be loaded.</div> : d.upcoming.map((e, i) => (
        <div key={i} className="small" style={{ margin: "4px 0" }}><b className="mono">{e.at_utc ? when(e.at_utc) : e.date}</b> {e.title} <span className="dim">· {e.source}</span></div>))}
      <div className="ws-bar" style={{ paddingLeft: 0 }}><span>HEADLINES · titles and links as published</span>
        <select value={topic} onChange={(e) => setTopic(e.target.value)} aria-label="Topic filter"><option value="">all topics</option>{Object.entries(d.topics).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></div>
      {heads.length === 0 && <div className="note">No matching headlines in the last 72 hours from the feeds you follow.</div>}
      {heads.map((h, i) => (
        <div key={i} className="small" style={{ margin: "6px 0" }}>
          <span className="pill">{h.topic_label}</span> {h.link ? <a href={h.link} target="_blank" rel="noreferrer noopener">{h.title}</a> : h.title}
          <div className="dim">{h.feed} · {when(h.published)} <button className="mini" onClick={() => setOpen(open === i ? null : i)}>{open === i ? "hide" : "what it can mean"}</button></div>
          {open === i && <div className="note"><b>{h.implication_kind}:</b> {h.implication}</div>}
        </div>))}
      {d.errors.length > 0 && <div className="note warn">Some sources failed: {d.errors.join("; ")}</div>}
      <div className="note"><b>Not shown:</b> {d.gaps.join(" ")}</div>
    </div>
  );
}
