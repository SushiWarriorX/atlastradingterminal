import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api, ApiFailure, TechReport } from "../api";
import { px } from "../fmt";
import { useStore } from "../store";
import { ErrorBox, Panel } from "../ui";

interface Msg { role: "user" | "ai" | "sys"; text: string; meta?: string }

export function AIWidget() {
  const selected = useStore((s) => s.selected);
  const inst = useQuery({ queryKey: ["instrument", selected], queryFn: () => api.instrument(selected), staleTime: 60_000 });
  const st = useQuery({ queryKey: ["aistatus"], queryFn: api.aiStatus, refetchInterval: 30_000 });
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [report, setReport] = useState<{ r: TechReport; sym: string; id: string } | null>(null);
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { end.current?.scrollIntoView({ block: "end" }); }, [msgs.length]);

  const chat = useMutation({
    mutationFn: (m: string) => api.aiChat(m, selected),
    onSuccess: (r) => setMsgs((x) => [...x, { role: "ai", text: r.answer, meta: `${r.tool_calls.map((c) => `${c.name}${c.ok ? "" : " ✕"}`).join(", ") || "no tools"} · ${r.usage.input_tokens + r.usage.output_tokens} tok · ${r.model}${r.status !== "completed" ? ` · ${r.status}` : ""}` }]),
    onError: (e) => setMsgs((x) => [...x, { role: "sys", text: e instanceof ApiFailure ? `${e.code}: ${e.message}` : String(e) }]),
  });
  const tech = useMutation({
    mutationFn: () => api.aiTechnical(selected),
    onSuccess: (r) => r.report ? setReport({ r: r.report, sym: inst.data?.symbol ?? selected, id: r.analysis_id })
      : setMsgs((x) => [...x, { role: "sys", text: `Technical analysis ${r.status}: ${r.error ?? "no data"}` }]),
    onError: (e) => setMsgs((x) => [...x, { role: "sys", text: e instanceof ApiFailure ? `${e.code}: ${e.message}` : String(e) }]),
  });
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
      <div className="chat">
        {!msgs.length && !report && <div className="dim small">Ask about the selected instrument. The desk calls read-only data tools; it cannot place orders.</div>}
        {report && <TechCard {...report} onClose={() => setReport(null)} />}
        {msgs.map((m, i) => <div key={i} className={`msg ${m.role}`}><div className="who">{m.role === "user" ? "YOU" : m.role === "ai" ? "DESK" : "SYSTEM"}</div><div className="txt">{m.text}</div>{m.meta && <div className="meta">{m.meta}</div>}</div>)}
        {chat.isPending && <div className="dim small">desk is working…</div>}
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
