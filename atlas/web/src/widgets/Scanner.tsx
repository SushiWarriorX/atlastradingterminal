import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiFailure, NLResult, ScanFilter, ScanRow, ScanSpec } from "../api";
import { ago, dir, num, pct, px } from "../fmt";
import { useStore } from "../store";
import { Badge, ErrorBox, Panel } from "../ui";

type Field = { type: "number" | "bool" | "string"; label: string; unit: string };
const OPS: Record<string, string[]> = { number: [">", ">=", "<", "<=", "==", "between"], bool: ["=="], string: ["==", "!=", "in"] };

function parse(type: string, op: string, raw: string): ScanFilter["value"] {
  if (type === "bool") return raw === "true";
  if (type === "number") return op === "between" ? raw.split(",").map((x) => Number(x.trim())) : Number(raw);
  return op === "in" ? raw.split(",").map((x) => x.trim()).filter(Boolean) : raw;
}
const show = (v: ScanFilter["value"]) => (Array.isArray(v) ? v.join(", ") : String(v));

const COLS: { key: string; label: string; r?: boolean; tip?: string }[] = [
  { key: "symbol", label: "Symbol" }, { key: "price", label: "Price", r: true }, { key: "change_pct", label: "Chg%", r: true },
  { key: "rvol", label: "RVOL", r: true, tip: "Today's volume / mean of the prior 20 days. Partial while the market is open." },
  { key: "atr_pct", label: "ATR%", r: true }, { key: "rsi14", label: "RSI", r: true }, { key: "trend", label: "Trend", tip: "MA alignment: close vs SMA50 vs SMA200" },
  { key: "rs_21d", label: "RS 1m", r: true, tip: "1-month return minus benchmark 1-month return (percentage points)" },
  { key: "catalyst", label: "Catalyst", tip: "Always empty: headlines are shown in NEWS but never turned into a catalyst flag. Never inferred." },
  { key: "setup", label: "Setup", tip: "Deterministic condition label, not a prediction" },
  { key: "score", label: "Score", r: true, tip: "Weighted percentile rank among matches. Hover a score for the breakdown. Not a probability." },
  { key: "last_bar_date", label: "Updated" },
];

export function ScannerWidget() {
  const qc = useQueryClient();
  const { select, setNotice } = useStore();
  const pendingScan = useStore((s) => s.pendingScan);
  const setPendingScan = useStore((s) => s.setPendingScan);
  const selected = useStore((s) => s.selected);
  const presets = useQuery({ queryKey: ["scan-presets"], queryFn: api.scanPresets, staleTime: Infinity });
  const fields = useQuery({ queryKey: ["scan-fields"], queryFn: api.scanFields, staleTime: Infinity });
  const saved = useQuery({ queryKey: ["scan-saved"], queryFn: api.scanSaved });
  const [spec, setSpec] = useState<ScanSpec | null>(null);
  const [label, setLabel] = useState<string>("");
  const [nl, setNl] = useState("");
  const [interp, setInterp] = useState<NLResult | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [sort, setSort] = useState<{ key: string; desc: boolean } | null>(null);
  const [err, setErr] = useState<unknown>(null);

  const job = useQuery({
    queryKey: ["scan-job", jobId], queryFn: () => api.scanJob(jobId!), enabled: !!jobId,
    refetchInterval: (q) => (q.state.data?.status === "running" || !q.state.data ? 700 : false),
  });
  const running = !!jobId && (!job.data || job.data.status === "running");

  const run = async (x: { preset?: string; spec?: ScanSpec }, name: string, s: ScanSpec | null) => {
    setErr(null); setSort(null); setLabel(name);
    if (s) setSpec(s);
    try { setJobId((await api.scanRun(x)).job_id); } catch (e) { setErr(e); setJobId(null); }
  };
  const runPreset = (id: string) => {
    const p = presets.data?.presets.find((x) => x.id === id);
    if (p) { setInterp(null); run({ preset: id }, p.name, p.spec); }
  };
  useEffect(() => { if (pendingScan && presets.data) { runPreset(pendingScan); setPendingScan(null); } }, [pendingScan, presets.data]);

  const interpret = useMutation({ mutationFn: () => api.scanNL(nl), onSuccess: (r) => { setInterp(r); if (r.spec) setSpec(r.spec); }, onError: setErr });
  const save = useMutation({
    mutationFn: (name: string) => api.scanSave(name, spec!),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["scan-saved"] }); setNotice("Scan saved"); }, onError: setErr,
  });
  const del = useMutation({ mutationFn: (id: number) => api.scanDelete(id), onSuccess: () => qc.invalidateQueries({ queryKey: ["scan-saved"] }) });

  const result = job.data?.result;
  const rows = useMemo(() => {
    const r = [...(result?.results ?? [])];
    if (!sort) return r;
    return r.sort((a, b) => {
      const x = a[sort.key] as number | string | null, y = b[sort.key] as number | string | null;
      if (x === null || x === undefined) return 1;
      if (y === null || y === undefined) return -1;
      return (x < y ? -1 : x > y ? 1 : 0) * (sort.desc ? -1 : 1);
    });
  }, [result, sort]);

  const F = fields.data as Record<string, Field> | undefined;
  const upd = (i: number, f: Partial<ScanFilter>) => setSpec((s) => s && { ...s, filters: s.filters.map((x, j) => (j === i ? { ...x, ...f } : x)) });
  const cell = (r: ScanRow, k: string) => {
    switch (k) {
      case "symbol": return <b>{r.symbol}</b>;
      case "price": return px(r.price);
      case "change_pct": return <span className={dir(r.change_pct)}>{pct(r.change_pct)}</span>;
      case "rvol": return r.rvol === null ? "—" : `${num(r.rvol, 1)}x`;
      case "atr_pct": return r.atr_pct === null ? "—" : `${num(r.atr_pct, 1)}%`;
      case "rsi14": return num(r.rsi14, 0);
      case "trend": return <span className={r.trend === "bullish" ? "up" : r.trend === "bearish" ? "down" : "dim"}>{r.trend ?? "—"}</span>;
      case "rs_21d": return <span className={dir(r.rs_21d)}>{r.rs_21d === null ? "—" : `${r.rs_21d >= 0 ? "+" : ""}${num(r.rs_21d, 1)}`}</span>;
      case "catalyst": return <span className="dim">—</span>;
      case "setup": return r.setup === "—" ? <span className="dim">—</span> : r.setup;
      case "score": return r.score === null ? "—" : <span title={r.score_breakdown.map((p) => `${p.field} (w ${p.weight}): value ${p.value === null ? "n/a" : num(p.value, 2)}, pctile ${p.percentile === null ? "n/a" : num(p.percentile, 0)} → ${p.contribution}`).join("\n")}>{num(r.score, 0)}</span>;
      case "last_bar_date": return <span className="dim">{r.last_bar_date}</span>;
    }
  };

  const m = result?.meta;
  return (
    <Panel title="EQUITY SCANNER" right={presets.data && <span className="dim">{presets.data.data_source}</span>} className="scanner">
      <div className="toolbar">
        {presets.data?.presets.map((p) => <button key={p.id} className="mini" title={p.description} disabled={running} onClick={() => runPreset(p.id)}>{p.name.replace(/ \(.*\)/, "")}</button>)}
        {presets.data && Object.entries(presets.data.unavailable).map(([id, why]) => <button key={id} className="mini" disabled title={`Not built: ${why}`}>{id.replace(/_/g, " ")} ✕</button>)}
        {saved.data && saved.data.length > 0 && <span className="sep" />}
        {saved.data?.map((s) => (
          <span key={s.id} className="savedchip"><button className="mini on" title="Saved scan" onClick={() => { setSpec(s.spec); setInterp(null); run({ spec: s.spec }, s.name, s.spec); }}>★ {s.name}</button>
            <button className="mini" aria-label={`Delete saved scan ${s.name}`} onClick={() => confirm(`Delete "${s.name}"?`) && del.mutate(s.id)}>✕</button></span>))}
      </div>
      <form className="nlrow" onSubmit={(e) => { e.preventDefault(); if (nl.trim().length > 2) interpret.mutate(); }}>
        <input value={nl} onChange={(e) => setNl(e.target.value)} aria-label="Describe a scan in plain English"
          placeholder="Describe a scan: technology stocks above their 50-day moving average with relative volume above 2" />
        <button className="mini on" disabled={interpret.isPending}>Interpret</button>
      </form>
      {interp && !interp.ok && <div className="note warn">{interp.error}</div>}
      {interp?.ok && <div className="note">Interpreted as the rules below. {interp.note}</div>}
      {interp?.unsupported.map((u) => <div key={u} className="note warn">⚠ Ignored: {u}</div>)}

      {spec && F && (
        <div className="rules">
          <div className="rules-h"><b>{label || spec.name}</b>
            <span className="dim">universe</span>
            <select value={spec.universe} onChange={(e) => setSpec({ ...spec, universe: e.target.value })} aria-label="Universe">
              {Object.entries(presets.data?.universes ?? {}).map(([k, v]) => <option key={k} value={k} title={v}>{k}</option>)}</select>
            <span className="dim">benchmark</span>
            <input className="w60" value={spec.benchmark} onChange={(e) => setSpec({ ...spec, benchmark: e.target.value.toUpperCase() })} aria-label="Benchmark" />
            <span className="dim">limit</span>
            <input className="w60" type="number" min={1} max={500} value={spec.limit} onChange={(e) => setSpec({ ...spec, limit: Number(e.target.value) || 100 })} aria-label="Result limit" />
          </div>
          {spec.filters.map((f, i) => {
            const t = F[f.field]?.type ?? "number";
            return (
              <div key={i} className="frow">
                <select value={f.field} onChange={(e) => { const nt = F[e.target.value].type; upd(i, { field: e.target.value, op: OPS[nt][0], value: nt === "bool" ? true : nt === "number" ? 0 : "" }); }} aria-label="Field">
                  {Object.entries(F).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}</select>
                <select value={f.op} onChange={(e) => upd(i, { op: e.target.value })} aria-label="Operator">{OPS[t].map((o) => <option key={o}>{o}</option>)}</select>
                {t === "bool" ? <select value={String(f.value)} onChange={(e) => upd(i, { value: e.target.value === "true" })} aria-label="Value"><option>true</option><option>false</option></select>
                  : <input value={show(f.value)} onChange={(e) => upd(i, { value: parse(t, f.op, e.target.value) })} aria-label="Value" className="fval" />}
                <span className="dim small">{F[f.field]?.unit}</span>
                <button className="mini" onClick={() => setSpec({ ...spec, filters: spec.filters.filter((_, j) => j !== i) })} aria-label="Remove rule">✕</button>
              </div>);
          })}
          <div className="toolbar">
            <button className="mini" onClick={() => setSpec({ ...spec, filters: [...spec.filters, { field: "rvol", op: ">=", value: 1.5 }] })}>+ rule</button>
            <button className="mini on" disabled={running} onClick={() => run({ spec }, label || spec.name, null)}>{running ? "running…" : "Run"}</button>
            <button className="mini" onClick={() => { const n = prompt("Save scan as", label || spec.name); if (n?.trim()) save.mutate(n.trim()); }}>Save</button>
          </div>
        </div>)}

      {err ? <ErrorBox error={err instanceof ApiFailure ? err : String(err)} /> : null}
      {running && <div className="progress" role="progressbar"><div style={{ width: `${job.data && job.data.total ? (job.data.done / job.data.total) * 100 : 3}%` }} /><span>{job.data?.done ?? 0} / {job.data?.total ?? "…"} symbols</span></div>}
      {job.data?.status === "failed" && <ErrorBox error={job.data.error} />}
      {m && (
        <div className="scanmeta">
          <Badge status={m.status} /> <b>{m.matched}</b> matches · {m.with_data}/{m.universe_size} symbols with data ({m.coverage_pct}%) · {m.failed} failed · {m.insufficient_history} short history
          · bars to {m.latest_bar_date ?? "—"} · {m.provider} · {(m.duration_ms / 1000).toFixed(1)}s · ran {ago(m.ran_at)}
          {m.notes.map((n) => <div key={n} className="note warn">⚠ {n}</div>)}
          {m.failed > 0 && <div className="note" title={JSON.stringify(m.failed_sample, null, 1)}>Failed symbols are excluded, not guessed. Hover for samples.</div>}
        </div>)}
      {result && (
        <div className="results">
          <table className="tbl">
            <thead><tr>{COLS.map((c) => <th key={c.key} className={c.r ? "r" : ""} title={c.tip} style={{ cursor: c.key === "catalyst" ? "default" : "pointer" }}
              onClick={() => c.key !== "catalyst" && setSort({ key: c.key, desc: sort?.key === c.key ? !sort.desc : true })}>{c.label}{sort?.key === c.key ? (sort.desc ? " ▼" : " ▲") : ""}</th>)}</tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.symbol} className={r.instrument_id === selected ? "sel" : ""} onClick={() => select(r.instrument_id)} title={`${r.sector ?? "sector n/a"} · click to chart`}>
                  {COLS.map((c) => <td key={c.key} className={c.r ? "r mono" : ""}>{cell(r, c.key)}</td>)}
                </tr>))}
            </tbody>
          </table>
          {!rows.length && <div className="note">No symbol matched all rules. Candidates for investigation only; a match is not a trade recommendation.</div>}
        </div>)}
      {!spec && !jobId && <div className="note">Pick a preset or describe a scan. Scans use daily bars: no intraday time-of-day RVOL. A result is a candidate to investigate, not a recommendation.</div>}
    </Panel>
  );
}
