import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api, errText, DeskResult, SpecialistRep, SpecialistResult, TechReport } from "../api";
import { px } from "../fmt";
import { useStore } from "../store";
import { useSelectedId } from "../scope";
import { ErrorBox, Panel } from "../ui";

interface Msg { role: "user" | "ai" | "sys"; text: string; meta?: string }

export function AIWidget() {
  const selected = useSelectedId();
  const inst = useQuery({ queryKey: ["instrument", selected], queryFn: () => api.instrument(selected), staleTime: 60_000 });
  const st = useQuery({ queryKey: ["aistatus"], queryFn: api.aiStatus, refetchInterval: 30_000 });
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [report, setReport] = useState<{ r: TechReport; sym: string; id: string } | null>(null);
  const [desk, setDesk] = useState<{ d: DeskResult; sym: string } | null>(null);
  const [spec, setSpec] = useState<{ agent: string; r: SpecialistResult; sym: string } | null>(null);
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { end.current?.scrollIntoView({ block: "end" }); }, [msgs.length]);

  const chat = useMutation({
    mutationFn: (m: string) => api.aiChat(m, selected),
    onSuccess: (r) => setMsgs((x) => [...x, { role: "ai", text: r.answer, meta: `${r.tool_calls.map((c) => `${c.name}${c.ok ? "" : " ✕"}`).join(", ") || "no tools"} · ${r.usage.input_tokens + r.usage.output_tokens} tok · ${r.model}${r.status !== "completed" ? ` · ${r.status}` : ""}` }]),
    onError: (e) => setMsgs((x) => [...x, { role: "sys", text: errText(e) }]),
  });
  const tech = useMutation({
    mutationFn: () => api.aiTechnical(selected),
    onSuccess: (r) => r.report ? setReport({ r: r.report, sym: inst.data?.symbol ?? selected, id: r.analysis_id })
      : setMsgs((x) => [...x, { role: "sys", text: `Technical analysis ${r.status}: ${r.error ?? "no data"}` }]),
    onError: (e) => setMsgs((x) => [...x, { role: "sys", text: errText(e) }]),
  });
  const sysMsg = (text: string) => setMsgs((x) => [...x, { role: "sys", text }]);
  const deskRun = useMutation({
    mutationFn: () => api.aiAnalyze<DeskResult>("chief", selected),
    onSuccess: (d) => { setDesk({ d, sym: inst.data?.symbol ?? selected }); setSpec(null); if (!d.chief) sysMsg(`Desk analysis ${d.status}: ${d.error ?? "no specialist produced a validated report"}`); },
    onError: (e) => sysMsg(errText(e)),
  });
  const specRun = useMutation({
    mutationFn: (agent: string) => api.aiAnalyze<SpecialistResult>(agent, selected).then((r) => ({ agent, r })),
    onSuccess: ({ agent, r }) => { setSpec({ agent, r, sym: inst.data?.symbol ?? selected }); setDesk(null); if (!r.report) sysMsg(`${agent} analysis ${r.status}: ${r.error ?? (r.data_limitations ?? []).join("; ") ?? "no data"}`); },
    onError: (e) => sysMsg(errText(e)),
  });
  const busy = tech.isPending || deskRun.isPending || specRun.isPending;
  const { pendingAsk, setPendingAsk, setNotice } = useStore();
  const send = (t: string) => { if (!t.trim()) return; setMsgs((x) => [...x, { role: "user", text: t }]); setInput(""); chat.mutate(t); };
  useEffect(() => {
    if (!pendingAsk || !st.data) return;
    if (st.data.configured) send(pendingAsk); else setNotice("AI is not configured: set ANTHROPIC_API_KEY on the backend.");
    setPendingAsk(null);
  }, [pendingAsk, st.data]);
  const sym = inst.data?.symbol ?? "…";
  const off = st.data && !st.data.configured;

  return (
    <Panel title="AI RESEARCH DESK" className="ai" right={<span className="ai-status">{st.data?.configured ? `● ${st.data.model}` : "○ not configured"}</span>}>
      {off && <div className="note warn">AI is off: set ANTHROPIC_API_KEY in the backend environment. Numbers always come from backend tools, never from the model.</div>}
      <div className="toolbar">
        <button className="mini ai" disabled={off || tech.isPending} onClick={() => tech.mutate()}>{tech.isPending ? "analysing…" : `Technical brief: ${sym}`}</button>
        <button className="mini ai" disabled={off || chat.isPending} onClick={() => send(`What is the current technical picture for ${sym}? Include bull and bear readings and invalidation.`)}>Ask: picture</button>
        <button className="mini ai" disabled={off || chat.isPending} onClick={() => send(`Challenge the bullish thesis on ${sym} using the data.`)}>Challenge thesis</button>
      </div>
      <div className="toolbar">
        <button className="mini on ai" disabled={off || busy} title="Runs the technical, fundamental, macro and risk agents in parallel, then a chief that must address every computed conflict between them" onClick={() => deskRun.mutate()}>{deskRun.isPending ? "desk working…" : `Full desk: ${sym}`}</button>
        {["fundamental", "macro"].map((a) => <button key={a} className="mini ai" disabled={off || busy} onClick={() => specRun.mutate(a)} title={a === "macro" ? "Rates, volatility and equity trend: not specific to the selected symbol" : "Computed ratios judged by the agent"}>{specRun.isPending && specRun.variables === a ? "…" : a}</button>)}
      </div>
      <div className="chat">
        {!msgs.length && !report && !desk && !spec && <div className="dim small">Ask about the selected instrument. The desk calls read-only data tools; it cannot place orders.</div>}
        {report && <TechCard {...report} onClose={() => setReport(null)} />}
        {desk?.d.chief && <DeskCard {...desk} onClose={() => setDesk(null)} />}
        {spec?.r.report && <SpecialistCard agent={spec.agent} rep={spec.r.report} sym={spec.sym} id={spec.r.analysis_id ?? ""} onClose={() => setSpec(null)} />}
        {msgs.map((m, i) => <div key={i} className={`msg ${m.role}`}><div className="who">{m.role === "user" ? "YOU" : m.role === "ai" ? "DESK" : "SYSTEM"}</div><div className="txt">{m.text}</div>{m.meta && <div className="meta">{m.meta}</div>}</div>)}
        {(chat.isPending || deskRun.isPending) && <div className="dim small">desk is working…</div>}
        {tech.isError && !msgs.length && <ErrorBox error={tech.error} />}
        <div ref={end} />
      </div>
      <form className="chatin" onSubmit={(e) => { e.preventDefault(); send(input); }}>
        <input value={input} onChange={(e) => setInput(e.target.value)} placeholder={`Ask about ${sym}…`} disabled={off} aria-label="Ask the AI desk" />
        <button disabled={off || chat.isPending || !input.trim()}>Send</button>
      </form>
    </Panel>
  );
}

function TechCard({ r, sym, id, onClose }: { r: TechReport; sym: string; id: string; onClose: () => void }) {
  return (
    <div className="card ai">
      <div className="card-h"><b>{sym} · TECHNICAL</b> <span className={`pill ${r.directional_assessment}`}>{r.directional_assessment.toUpperCase()}</span>
        <span className="dim small"> {r.time_horizon} · {r.analysis_timestamp.slice(0, 19)}Z</span><button className="mini" onClick={onClose}>✕</button></div>
      <p>{r.summary}</p>
      {r.mtf && <div className="small" title={`computed in code; source ${r.mtf.source_id}`}><b>MTF (computed):</b> {r.mtf.verdict} · score {r.mtf.score ?? "n/a"}{r.mtf.label ? ` (${r.mtf.label})` : ""}{r.mtf.benchmark ? ` vs ${r.mtf.benchmark}` : ""}<div className="dim">{r.mtf.text}</div></div>}
      {r.consistency_notes?.map((c) => <div key={c} className="note warn">⚠ {c}</div>)}
      {r.key_levels.length > 0 && <table className="tbl"><tbody>{r.key_levels.map((k) => <tr key={k.level_id}><td>{k.role}</td><td className="r mono">{px(k.price)}</td><td className="dim small">{k.derivation}</td></tr>)}</tbody></table>}
      {r.scenarios.map((s) => <div key={s.name} className="small"><b>{s.name}:</b> {s.conditions} <span className="dim">· invalidation: {s.invalidation}</span></div>)}
      {r.data_limitations.length > 0 && <div className="note">Limitations: {r.data_limitations.join("; ")}</div>}
      <div className="meta">analysis {id.slice(0, 8)} · key-level prices resolved server-side from computed snapshot; not model-generated</div>
    </div>
  );
}

const fmt = (v: number) => (Math.abs(v) >= 1e9 ? `${(v / 1e9).toFixed(2)}B` : Math.abs(v) >= 1e6 ? `${(v / 1e6).toFixed(1)}M` : v.toLocaleString("en-US", { maximumFractionDigits: 2 }));

function SpecialistCard({ agent, rep, sym, id, onClose }: { agent: string; rep: SpecialistRep; sym: string; id: string; onClose: () => void }) {
  return (
    <div className="card ai">
      <div className="card-h"><b>{agent === "macro" ? "MACRO" : `${sym} · ${agent.toUpperCase()}`}</b> <span className="pill neutral">{rep.assessment.replace(/_/g, " ").toUpperCase()}</span><button className="mini" onClick={onClose}>✕</button></div>
      <p>{rep.summary}</p>
      {rep.computed?.computed_tilt && <div className="small"><b>Reference tilt (computed):</b> {rep.computed.computed_tilt.label} (score {rep.computed.computed_tilt.score}) <span className="dim">{rep.computed.computed_tilt.note}</span>
        <div className="dim">{rep.computed.computed_tilt.signals.map((s) => s.text).join(" · ")}</div></div>}
      {rep.computed?.limit_breaches?.map((b) => <div key={b} className="note warn">⚠ Limit breach (computed): {b}</div>)}
      {rep.consistency_notes.map((c) => <div key={c} className="note warn">⚠ {c}</div>)}
      {rep.pillars.map((p) => (
        <div key={p.name} className="small"><b>{p.name.replace(/_/g, " ")}:</b> {p.rating.replace(/_/g, " ")}
          {p.evidence.map((e) => <div key={e.fact} className="dim" title={`fact key ${e.fact}: value attached by the server`}>· {e.fact} = <span className="mono">{fmt(e.value)}</span>: {e.comment}</div>)}</div>))}
      {rep.contradictory.length > 0 && <div className="small"><b>Against:</b>{rep.contradictory.map((e) => <div key={e.fact} className="dim">· {e.fact} = <span className="mono">{fmt(e.value)}</span>: {e.comment}</div>)}</div>}
      {rep.data_limitations.length > 0 && <div className="note">Limitations: {rep.data_limitations.join("; ")}</div>}
      <div className="meta">analysis {id.slice(0, 8)} · every cited number is looked up by the server from the computed snapshot, not written by the model · research, not advice</div>
    </div>
  );
}

function DeskCard({ d, sym, onClose }: { d: DeskResult; sym: string; onClose: () => void }) {
  const c = d.chief!;
  return (
    <div className="card ai">
      <div className="card-h"><b>{sym} · FULL DESK</b> <span className={`pill ${c.stance === "constructive" ? "bullish" : c.stance === "cautious" ? "bearish" : "neutral"}`}>{c.stance.replace(/_/g, " ").toUpperCase()}</span>
        {d.status === "partial" && <span className="pill neutral" title="At least one specialist did not produce a validated report">PARTIAL</span>}<button className="mini" onClick={onClose}>✕</button></div>
      <p>{c.summary}</p>
      <div className="small"><b>Specialists:</b> {Object.entries(d.specialists).map(([n, r]) => (
        <span key={n} className="dim" style={{ marginRight: 10 }} title={r.error ?? (r.data_limitations ?? []).join("; ")}>{n}: <b style={{ color: "var(--text)" }}>{d.views[n]?.replace(/_/g, " ") ?? r.status.replace(/_/g, " ")}</b></span>))}</div>
      {d.conflicts.length > 0 && <div className="note warn"><b>Conflicts (computed in code):</b>{d.conflicts.map((x) => <div key={x.text}>⚠ {x.text}</div>)}
        <b>How the chief weighs them:</b>{c.conflicts_addressed.map((x) => <div key={x}>→ {x}</div>)}</div>}
      {c.agreements.length > 0 && <div className="small"><b>Agreement:</b> {c.agreements.join("; ")}</div>}
      {c.what_would_change_my_mind.length > 0 && <div className="small"><b>Would change the view:</b> {c.what_would_change_my_mind.join("; ")}</div>}
      {c.consistency_notes.map((x) => <div key={x} className="note warn">⚠ {x}</div>)}
      {Object.entries(d.specialists).flatMap(([n, r]) => (r.report?.consistency_notes ?? []).map((x) => <div key={n + x} className="note warn">⚠ {n}: {x}</div>))}
      {[...c.data_limitations, ...Object.entries(d.specialists).filter(([, r]) => !r.report && r.status !== "not_applicable").map(([n, r]) => `${n}: ${r.status.replace(/_/g, " ")}${r.error ? ` (${r.error})` : (r.data_limitations ?? []).length ? ` (${r.data_limitations!.join("; ")})` : ""}`)].map((x) => <div key={x} className="note">{x}</div>)}
      <div className="meta">analysis {d.analysis_id.slice(0, 8)} · {d.usage.input_tokens + d.usage.output_tokens} tok · {d.model} · no agent can place or authorise an order · research, not advice</div>
    </div>
  );
}
