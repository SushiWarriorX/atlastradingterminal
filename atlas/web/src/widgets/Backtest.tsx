import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ColorType, createChart, LineSeries, UTCTimestamp } from "lightweight-charts";
import { api, ApiFailure, BtGroupRow, BtResult, BtSpec, BtStats } from "../api";
import { dir, num, pct } from "../fmt";
import { useStore } from "../store";
import { Badge, ErrorBox, Panel } from "../ui";

const css = (v: string) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const rng = (x?: [number, number] | null, f = (v: number) => num(v * 100, 0) + "%") => (x ? `${f(x[0])} – ${f(x[1])}` : "—");
const sgn = (x: number | null | undefined, d = 2) => (x === null || x === undefined ? "—" : `${x >= 0 ? "+" : ""}${num(x, d)}`);

function Num({ label, value, onChange, step = 1, min, max, nullable }: { label: string; value: number | null; onChange: (v: number | null) => void; step?: number; min?: number; max?: number; nullable?: boolean }) {
  return (
    <label className="bt-f"><span className="dim small">{label}</span>
      <input className="w60" type="number" step={step} min={min} max={max} value={value ?? ""} aria-label={label}
        placeholder={nullable ? "none" : undefined} onChange={(e) => onChange(e.target.value === "" ? (nullable ? null : value) : Number(e.target.value))} /></label>
  );
}

function EquityChart({ r }: { r: BtResult }) {
  const host = useRef<HTMLDivElement>(null);
  const theme = useStore((s) => s.theme);
  useEffect(() => {
    if (!host.current || !r.portfolio.curve.length) return;
    const c = createChart(host.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: css("--panel") }, textColor: css("--dim"), fontFamily: "ui-monospace, Menlo, Consolas, monospace", fontSize: 11 },
      grid: { vertLines: { color: css("--grid") }, horzLines: { color: css("--grid") } },
      rightPriceScale: { borderColor: css("--border") }, timeScale: { borderColor: css("--border") },
    });
    const s = c.addSeries(LineSeries, { color: css("--accent"), lineWidth: 2, title: "strategy", priceFormat: { type: "price", precision: 0, minMove: 1 } });
    s.setData(r.portfolio.curve.map((p) => ({ time: p.t as UTCTimestamp, value: p.equity })));
    if (r.benchmark) {
      const b = c.addSeries(LineSeries, { color: css("--info"), lineWidth: 1, title: `${r.benchmark.symbol} buy&hold`, priceFormat: { type: "price", precision: 0, minMove: 1 } });
      b.setData(r.benchmark.curve.map((p) => ({ time: p.t as UTCTimestamp, value: p.equity })));
    }
    c.timeScale().fitContent();
    return () => c.remove();
  }, [r, theme]);
  return <div className="chart-host bt-chart" ref={host} />;
}

const Stat = ({ k, v, tip, cls }: { k: string; v: React.ReactNode; tip?: string; cls?: string }) => (
  <div className="bt-stat" title={tip}><div className="dim small">{k}</div><div className={`mono ${cls ?? ""}`}>{v}</div></div>
);

function Groups({ title, rows, limit, note }: { title: string; rows: BtGroupRow[]; limit?: number; note?: string }) {
  return (
    <div className="bt-grp">
      <b className="small">{title}</b>
      <table className="tbl">
        <thead><tr><th>{title.replace("By ", "")}</th><th className="r">n</th><th className="r">Win</th><th className="r" title="Mean net return per trade, %">Exp %</th><th className="r">PF</th><th className="r">Σ %</th></tr></thead>
        <tbody>{rows.slice(0, limit ?? 99).map((g) => (
          <tr key={g.key} className={g.reliable ? "" : "dim"} title={g.reliable ? "" : "Fewer than 30 trades: anecdotal"}>
            <td>{g.key}{g.reliable ? "" : " ·"}</td><td className="r mono">{g.n}</td><td className="r mono">{g.win_rate === null ? "—" : num(g.win_rate * 100, 0) + "%"}</td>
            <td className={`r mono ${dir(g.expectancy)}`}>{sgn(g.expectancy)}</td><td className="r mono">{g.profit_factor === null ? "—" : num(g.profit_factor, 2)}</td>
            <td className={`r mono ${dir(g.net_pnl)}`}>{sgn(g.net_pnl, 1)}</td></tr>))}</tbody>
      </table>
      {note && <div className="note">{note}</div>}
    </div>
  );
}

const Half = ({ name, s }: { name: string; s: BtStats }) => (
  <tr className={s.reliable ? "" : "dim"}><td>{name}</td><td className="r mono">{s.n}</td><td className="r mono">{s.win_rate === undefined ? "—" : num(s.win_rate * 100, 0) + "%"}</td>
    <td className={`r mono ${dir(s.expectancy)}`}>{sgn(s.expectancy)}</td><td className="r mono">{rng(s.expectancy_ci95, (v) => sgn(v))}</td>
    <td className="r mono">{s.profit_factor === null || s.profit_factor === undefined ? "—" : num(s.profit_factor, 2)}</td><td>{s.reliable ? "ok" : `n<${s.min_sample}`}</td></tr>
);

export function BacktestWidget() {
  const qc = useQueryClient();
  const { select, setNotice } = useStore();
  const pending = useStore((s) => s.pendingBacktest);
  const setPending = useStore((s) => s.setPendingBacktest);
  const presets = useQuery({ queryKey: ["bt-presets"], queryFn: api.btPresets, staleTime: Infinity });
  const runs = useQuery({ queryKey: ["bt-runs"], queryFn: api.btRuns });
  const [spec, setSpec] = useState<BtSpec | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [saved, setSaved] = useState<BtResult | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const [fields, setFields] = useState<Record<string, { label: string }>>({});

  useEffect(() => { api.scanFields().then((f) => setFields(f)).catch(() => undefined); }, []);
  const job = useQuery({
    queryKey: ["bt-job", jobId], queryFn: () => api.btJob(jobId!), enabled: !!jobId,
    refetchInterval: (q) => (q.state.data?.status === "running" || !q.state.data ? 800 : false),
  });
  const running = !!jobId && (!job.data || job.data.status === "running");
  useEffect(() => { if (job.data?.status === "done") qc.invalidateQueries({ queryKey: ["bt-runs"] }); }, [job.data?.status]);

  const pick = (id: string) => {
    const p = presets.data?.presets.find((x) => x.id === id);
    if (p) { setSpec(p.spec); setJobId(null); setSaved(null); setErr(null); }
  };
  useEffect(() => { if (pending && presets.data) { pick(pending); setPending(null); } }, [pending, presets.data]);

  const start = async () => {
    if (!spec) return;
    setErr(null); setSaved(null);
    try { setJobId((await api.btRun({ spec })).job_id); } catch (e) { setErr(e); setJobId(null); }
  };
  const open = useMutation({ mutationFn: (id: number) => api.btGet(id), onSuccess: (d) => { setSaved(d.result); setSpec(d.result.meta.spec); setJobId(null); }, onError: setErr });
  const del = useMutation({ mutationFn: (id: number) => api.btDelete(id), onSuccess: () => { qc.invalidateQueries({ queryKey: ["bt-runs"] }); setNotice("Backtest deleted"); } });

  const r: BtResult | null = saved ?? job.data?.result ?? null;
  const set = <K extends keyof BtSpec>(k: K, v: BtSpec[K]) => setSpec((s) => s && { ...s, [k]: v });
  const m = r?.portfolio.metrics;
  const S = r?.summary;
  const label = (f: string) => fields[f]?.label ?? f;

  return (
    <Panel title="BACKTESTER" className="scanner" right={presets.data && <span className="dim">{presets.data.demo ? "DEMO bars (synthetic)" : "Yahoo daily bars (5y)"}</span>}>
      <div className="toolbar">
        <span className="dim small">strategy</span>
        {presets.data?.presets.map((p) => <button key={p.id} className={`mini ${spec?.name === p.name ? "on" : ""}`} title={p.description} disabled={running} onClick={() => pick(p.id)}>{p.name.replace(/ \(.*\)/, "")}</button>)}
        {runs.data && runs.data.length > 0 && <span className="sep" />}
        {runs.data?.slice(0, 5).map((x) => (
          <span key={x.id} className="savedchip"><button className="mini" title={`saved ${x.ran_at}`} onClick={() => open.mutate(x.id)}>◷ {x.name} ({x.trades})</button>
            <button className="mini" aria-label={`Delete backtest ${x.name}`} onClick={() => confirm(`Delete saved backtest "${x.name}"?`) && del.mutate(x.id)}>✕</button></span>))}
      </div>

      {!spec && <div className="note">Pick a strategy. Each one is a scanner preset whose rules are tested over history: signal at a bar's close, fill at the next open, costs charged, stops resolved conservatively. Thresholds are not optimised.</div>}
      {spec && (
        <div className="rules">
          <div className="rules-h"><b>{spec.name}</b><span className="dim small">{spec.side.toUpperCase()} · universe {spec.universe} · benchmark {spec.benchmark}</span></div>
          <div className="note" title="Edit the rules in the Scanner">Entry (all true at a close): {spec.entry.map((f) => `${label(f.field)} ${f.op} ${Array.isArray(f.value) ? f.value.join("–") : String(f.value)}`).join("  ·  ")}</div>
          <div className="bt-form">
            <Num label="stop (ATR×)" value={spec.stop_atr} step={0.25} min={0.25} max={20} nullable onChange={(v) => set("stop_atr", v)} />
            <Num label="target (R)" value={spec.target_r} step={0.5} min={0.5} max={50} nullable onChange={(v) => set("target_r", v)} />
            <Num label="max hold (bars)" value={spec.max_hold_bars} min={1} max={250} onChange={(v) => set("max_hold_bars", v ?? 20)} />
            <Num label="commission (bps/side)" value={spec.commission_bps} step={0.5} min={0} onChange={(v) => set("commission_bps", v ?? 0)} />
            <Num label="slippage (bps/side)" value={spec.slippage_bps} step={1} min={0} onChange={(v) => set("slippage_bps", v ?? 0)} />
            <Num label="risk % / trade" value={spec.risk_pct} step={0.25} min={0.1} max={10} onChange={(v) => set("risk_pct", v ?? 1)} />
            <Num label="max position %" value={spec.max_position_pct} step={5} min={1} max={100} onChange={(v) => set("max_position_pct", v ?? 20)} />
            <Num label="max positions" value={spec.max_positions} min={1} max={100} onChange={(v) => set("max_positions", v ?? 10)} />
            <Num label="hold-out %" value={Math.round(spec.oos_fraction * 100)} step={5} min={0} max={80} onChange={(v) => set("oos_fraction", (v ?? 30) / 100)} />
            <Num label="symbols" value={spec.max_symbols} step={10} min={1} max={200} onChange={(v) => set("max_symbols", v ?? 60)} />
            <button className="mini on" disabled={running} onClick={start}>{running ? "running…" : "Run backtest"}</button>
          </div>
          {spec.target_r !== null && spec.stop_atr === null && <div className="note warn">A target needs a stop (it is a multiple of the stop distance).</div>}
        </div>)}

      {err ? <ErrorBox error={err instanceof ApiFailure ? err : String(err)} /> : null}
      {running && <div className="progress" role="progressbar"><div style={{ width: `${job.data && job.data.total ? (job.data.done / job.data.total) * 100 : 3}%` }} /><span>{job.data?.done ?? 0} / {job.data?.total || "…"} symbols</span></div>}
      {job.data?.status === "failed" && <ErrorBox error={job.data.error} />}

      {r && S && m && (
        <div className="bt-res">
          <div className="scanmeta">
            <Badge status={r.meta.status} /> {r.meta.provider} · bars {r.meta.bars_from} → {r.meta.bars_to} · {r.meta.with_data}/{r.meta.universe_size} symbols with data · {r.symbols_traded} traded
            · {(r.meta.duration_ms / 1000).toFixed(1)}s ({r.compute_mode})
            {r.meta.notes.map((n) => <div key={n} className="note warn">⚠ {n}</div>)}
            {r.meta.status === "DEMO" && <div className="note warn">⚠ Synthetic demo bars: these results say nothing about any market.</div>}
          </div>

          <div className="bt-stats">
            <Stat k="Trades" v={S.n} tip="Closed trades only. Open positions at the end are excluded." cls={S.reliable ? "" : "warn"} />
            <Stat k="Win rate" v={S.win_rate === undefined ? "—" : `${num(S.win_rate * 100, 0)}%`} tip={`95% interval ${rng(S.win_rate_ci95)}`} />
            <Stat k="Expectancy" v={`${sgn(S.expectancy)}%`} tip={`Mean net return per trade. 95% bootstrap interval ${S.expectancy_ci95 ? rng(S.expectancy_ci95, (v) => sgn(v)) : "n/a (needs 30+ trades)"}`} cls={dir(S.expectancy)} />
            <Stat k="Profit factor" v={S.profit_factor === null || S.profit_factor === undefined ? "—" : num(S.profit_factor, 2)} />
            <Stat k="Avg R" v={S.r?.avg_r === null || S.r?.avg_r === undefined ? "—" : sgn(S.r.avg_r)} tip="Net return / planned stop distance" />
            <Stat k="Avg hold" v={S.avg_hold_bars ? `${num(S.avg_hold_bars, 1)} bars` : "—"} />
            <Stat k="Return" v={pct(m.total_return_pct)} tip="Account return with position sizing, costs and capacity limits" cls={dir(m.total_return_pct)} />
            <Stat k="CAGR" v={m.cagr_pct === null ? "—" : pct(m.cagr_pct)} tip="Not shown for spans under 3 months" />
            <Stat k="Max drawdown" v={pct(m.max_drawdown_pct)} tip="Daily mark-to-market peak-to-trough" cls="down" />
            <Stat k="Sharpe" v={m.sharpe === null ? "—" : num(m.sharpe, 2)} tip="Daily returns, risk-free rate 0, annualised ×√252" />
            <Stat k="Exposure" v={r.portfolio.exposure_avg_pct === null ? "—" : `${num(r.portfolio.exposure_avg_pct, 0)}%`} tip="Average gross exposure / equity" />
            {r.benchmark && <Stat k={`${r.benchmark.symbol} buy&hold`} v={`${pct(r.benchmark.total_return_pct)} · DD ${pct(r.benchmark.max_drawdown_pct)}`} tip="Same dates, fully invested" />}
          </div>
          {S.note && <div className="note warn">⚠ {S.note}</div>}
          {S.expectancy_note && <div className="note">{S.expectancy_note}</div>}
          {Object.values(r.portfolio.skipped).some((x) => x > 0) && <div className="note">Skipped by account limits: {Object.entries(r.portfolio.skipped).filter(([, v]) => v > 0).map(([k, v]) => `${v} ${k.replace(/_/g, " ")}`).join(", ")} (trades still counted in the trade statistics above).</div>}

          <EquityChart r={r} />

          <div className="bt-two">
            <div>
              <b className="small">Stability: first part vs hold-out</b>
              <table className="tbl"><thead><tr><th>Period</th><th className="r">n</th><th className="r">Win</th><th className="r">Exp %</th><th className="r">95% interval</th><th className="r">PF</th><th /></tr></thead>
                <tbody><Half name="In-sample" s={r.in_sample} /><Half name={`Hold-out${r.split.cutoff_date ? ` (from ${r.split.cutoff_date})` : ""}`} s={r.out_of_sample} /></tbody></table>
              <div className="note">{r.split.note}</div>
            </div>
            <Groups title="By year" rows={r.groups.year ?? []} />
            <Groups title="By exit" rows={r.groups.exit_reason ?? []} note="Grouped by outcome: it shows how trades ended (targets always win, stops always lose). It is not a rule you could filter on in advance." />
          </div>
          <Groups title="By symbol" rows={r.groups.symbol ?? []} limit={8} />

          {r.pending_signals.length > 0 && <div className="note">Signals on the latest bar (would enter at the next open): {r.pending_signals.map((p) => p.symbol).join(", ")}. A candidate list, not a recommendation.</div>}
          {r.open_at_end.length > 0 && <div className="note">{r.open_at_end.length} position(s) still open at the end of the data and excluded from statistics: {r.open_at_end.map((o) => `${o.symbol} ${pct(o.unrealized_pct)}`).join(", ")}.</div>}

          <b className="small">Trades (latest 150)</b>
          <div className="results bt-trades">
            <table className="tbl">
              <thead><tr><th>Symbol</th><th>Side</th><th>Entry</th><th className="r">Px</th><th>Exit</th><th className="r">Px</th><th>Why</th><th className="r">Bars</th><th className="r">Net %</th><th className="r">R</th></tr></thead>
              <tbody>{[...r.trades].reverse().slice(0, 150).map((t, i) => (
                <tr key={i} onClick={() => select(t.instrument_id)} title="click to chart">
                  <td><b>{t.symbol}</b></td><td>{t.side}</td><td className="dim">{t.entry_date}</td><td className="r mono">{num(t.entry_px)}</td><td className="dim">{t.exit_date}</td>
                  <td className="r mono">{num(t.exit_px)}</td><td>{t.exit_reason}</td><td className="r mono">{t.bars_held}</td>
                  <td className={`r mono ${dir(t.net_pct)}`}>{sgn(t.net_pct)}</td><td className="r mono">{t.r_multiple === null ? "—" : sgn(t.r_multiple)}</td></tr>))}</tbody>
            </table>
          </div>
          <details className="bt-cav"><summary>How to read this (limits)</summary>
            <ul>{r.meta.caveats.map((c) => <li key={c}>{c}</li>)}</ul></details>
        </div>)}
    </Panel>
  );
}
