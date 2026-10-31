import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ColorType, createChart, LineSeries, UTCTimestamp } from "lightweight-charts";
import { api, ApiFailure, RiskLimits } from "../api";
import { dir, num } from "../fmt";
import { useStore } from "../store";
import { Badge, ErrorBox, Panel } from "../ui";
import { usePortfolioId } from "./Trading";

const err = (e: unknown) => (e instanceof ApiFailure ? `${e.code}: ${e.message}` : String(e));
const css = (v: string) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const f2 = (x: number | null | undefined, d = 2) => (x === null || x === undefined ? "—" : num(x, d));

export function RiskLimitsWidget() {
  const qc = useQueryClient();
  const { pid } = usePortfolioId();
  const limits = useQuery({ queryKey: ["risk-limits"], queryFn: api.riskLimits });
  const port = useQuery({ queryKey: ["portfolio", pid], queryFn: () => api.portfolio(pid), enabled: pid !== undefined, refetchInterval: 5000 });
  const [draft, setDraft] = useState<Partial<RiskLimits>>({});
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [cancelOpen, setCancelOpen] = useState(true);
  const rec = useMutation({ mutationFn: () => api.reconcile(pid), onSuccess: (r) => setMsg(!r.applicable ? { ok: true, text: `Nothing to reconcile: ${r.reason}.` } : { ok: !!r.consistent, text: r.consistent ? `Ledger reconciles with stored cash and positions (${r.fills_checked} fills checked).` : `MISMATCH: ${JSON.stringify(r.issues)}` }), onError: (e) => setMsg({ ok: false, text: err(e) }) });
  const save = useMutation({ mutationFn: () => api.setRiskLimits(draft), onSuccess: () => { setDraft({}); setMsg({ ok: true, text: "Limits saved. They apply to the next order check." }); qc.invalidateQueries({ queryKey: ["risk-limits"] }); }, onError: (e) => setMsg({ ok: false, text: err(e) }) });
  const halt = useMutation({
    mutationFn: (h: boolean) => api.tradingHalt(h, cancelOpen),
    onSuccess: (r) => { setMsg({ ok: true, text: r.halted ? `Trading HALTED${r.cancelled_orders.length ? `; cancelled ${r.cancelled_orders.length} open order(s)` : ""}.` : "Trading resumed." }); for (const k of ["status", "portfolio", "orders"]) qc.invalidateQueries({ queryKey: [k] }); },
    onError: (e) => setMsg({ ok: false, text: err(e) }),
  });
  const L = limits.data;
  const halted = !!port.data?.halted;
  const field = (k: keyof RiskLimits, label: string, tip: string, step = 0.1) => (
    <tr key={k} title={tip}><td>{label}</td><td className="r"><input className="w80" type="number" step={step} value={(draft[k] as number | undefined) ?? (L?.[k] as number | null | undefined) ?? ""}
      onChange={(e) => setDraft({ ...draft, [k]: e.target.value === "" ? null : Number(e.target.value) })} aria-label={label} /></td></tr>);
  return (
    <Panel title="RISK LIMITS & CONTROLS" right={<span className="env-tag">ENFORCED IN BACKEND CODE</span>}>
      <div className={`killbox ${halted ? "halted" : ""}`}>
        <div><b>{halted ? "⛔ TRADING HALTED" : "Trading enabled (paper)"}</b><div className="dim small">The kill switch blocks every new order. Closing orders are blocked too while halted.</div></div>
        <label className="small"><input type="checkbox" checked={cancelOpen} onChange={(e) => setCancelOpen(e.target.checked)} /> cancel open orders</label>
        {halted ? <button className="mini on" onClick={() => halt.mutate(false)}>Resume trading</button>
          : <button className="mini kill" onClick={() => confirm(`Halt all trading${cancelOpen ? " and cancel open orders" : ""}?`) && halt.mutate(true)}>HALT TRADING</button>}
      </div>
      {limits.isError && <ErrorBox error={limits.error} />}
      {L && (
        <table className="tbl kv"><tbody>
          {field("max_risk_per_trade_pct", "Max planned risk / trade (% equity)", "Stop-based planned risk of a single new trade. Gaps and slippage can exceed it.")}
          {field("max_aggregate_risk_pct", "Max aggregate planned risk (% equity)", "Sum of planned risk across open positions with stops.")}
          {field("max_position_pct", "Max single position (% equity)", "Post-trade value of one instrument.", 1)}
          {field("daily_loss_warning_pct", "Daily loss warning (%)", "Warns once the day's equity change passes this.")}
          {field("max_daily_loss_pct", "Max daily loss (%)", "Blocks new risk-increasing orders once breached (exits stay allowed).")}
          {field("max_order_notional", "Max order notional (currency)", "Blank = no cap.", 100)}
          <tr><td>Require a planned stop on buys</td><td className="r"><input type="checkbox" checked={draft.require_stop ?? L.require_stop} onChange={(e) => setDraft({ ...draft, require_stop: e.target.checked })} aria-label="Require stop" /></td></tr>
          <tr><td>Allow fractional equity shares</td><td className="r"><input type="checkbox" checked={draft.allow_fractional_equities ?? L.allow_fractional_equities} onChange={(e) => setDraft({ ...draft, allow_fractional_equities: e.target.checked })} aria-label="Allow fractional" /></td></tr>
          <tr title="Comma separated"><td>Blocked symbols</td><td className="r"><input className="w100" value={(draft.blocked_symbols ?? L.blocked_symbols).join(",")} onChange={(e) => setDraft({ ...draft, blocked_symbols: e.target.value.split(",").map((x) => x.trim().toUpperCase()).filter(Boolean) })} aria-label="Blocked symbols" /></td></tr>
          <tr><td>Leverage / margin</td><td className="r dim">not supported (cash only)</td></tr>
        </tbody></table>)}
      <div className="toolbar"><button className="mini on" disabled={!Object.keys(draft).length || save.isPending} onClick={() => save.mutate()}>Save limits</button>
        <button className="mini" disabled={!Object.keys(draft).length} onClick={() => setDraft({})}>discard</button>
        <button className="mini" onClick={() => rec.mutate()} title="Recompute cash and positions from the fill ledger and compare">reconcile ledger</button></div>
      {msg && <div className={`note ${msg.ok ? "" : "warn"}`} onClick={() => setMsg(null)}>{msg.text}</div>}
      <div className="note">Event risk (CPI, FOMC, earnings) is NOT checked: there is no economic-calendar integration yet.</div>
    </Panel>
  );
}

export function RiskAnalyticsWidget() {
  const [bench, setBench] = useState("SPY");
  const { pid, current } = usePortfolioId();
  const q = useQuery({ queryKey: ["portfolio-risk", pid, bench], queryFn: () => api.portfolioRisk(pid, bench), enabled: pid !== undefined, refetchInterval: 60_000, retry: 0 });
  const d = q.data;
  return (
    <Panel title={`PORTFOLIO RISK${current ? ` · ${current.name}` : ""}`} right={<span className="dim">benchmark <select value={bench} onChange={(e) => setBench(e.target.value)} aria-label="Risk benchmark"><option>SPY</option><option>QQQ</option><option>IWM</option><option value="none">none</option></select></span>}>
      {q.isError && <ErrorBox error={q.error} />}
      {q.isLoading && <div className="note">Computing…</div>}
      {d && !d.available && <div className="note warn">Risk analytics unavailable: {d.reason}</div>}
      {d?.available && (
        <>
          <div className="stats">
            <div><span className="dim">VOL (ann.)</span><b className="mono">{f2(d.volatility_ann_pct, 1)}%</b></div>
            <div><span className="dim">MAX DRAWDOWN</span><b className="mono down">{f2(d.max_drawdown_pct, 1)}%</b></div>
            <div title={d.var_95_1d ? "Historical simulation, 5th percentile" : ""}><span className="dim">VaR 95% 1d</span><b className="mono">{d.var_95_1d ? `${f2(d.var_95_1d.pct)}% · ${num(d.var_95_1d.amount, 0)}` : "—"}</b></div>
            <div><span className="dim">ES 95% 1d</span><b className="mono">{d.es_95_1d?.pct !== undefined ? `${f2(d.es_95_1d.pct)}% · ${num(d.es_95_1d.amount ?? 0, 0)}` : <span className="dim small">n/a</span>}</b></div>
            <div><span className="dim">BETA{d.beta ? ` vs ${d.beta.benchmark}` : ""}</span><b className="mono">{d.beta ? f2(d.beta.value) : "—"}</b></div>
            <div><span className="dim">OBS</span><b className="mono">{d.observations}</b></div>
          </div>
          {d.es_95_1d?.reason && <div className="note">ES unavailable: {d.es_95_1d.reason}</div>}
          {d.var_99_1d?.reason && <div className="note">VaR 99% unavailable: {d.var_99_1d.reason}</div>}
          {d.concentration && <div className="note">Top position {d.concentration.top_position} = {f2(d.concentration.top_position_pct_of_equity, 1)}% of equity · HHI {f2(d.concentration.hhi_invested)} ({d.concentration.note})</div>}
          {d.correlation && d.correlation.symbols.length > 1 && (
            <table className="tbl"><thead><tr><th>ρ</th>{d.correlation.symbols.map((s) => <th key={s} className="r">{s}</th>)}</tr></thead>
              <tbody>{d.correlation.symbols.map((s, i) => <tr key={s}><td><b>{s}</b></td>{d.correlation!.matrix[i].map((c, j) => <td key={j} className={`r mono ${c !== null && Math.abs(c) > 0.7 && i !== j ? "warnc" : ""}`}>{f2(c)}</td>)}</tr>)}</tbody></table>)}
          {d.liquidity && (
            <table className="tbl"><thead><tr><th>Liquidity</th><th className="r">Value</th><th className="r">ADV$ (20d)</th><th className="r">% of ADV</th><th className="r">Days to exit</th></tr></thead>
              <tbody>{d.liquidity.positions.map((p) => <tr key={p.symbol}><td><b>{p.symbol}</b></td><td className="r mono">{num(p.value, 0)}</td><td className="r mono">{p.adv_usd_20d ? num(p.adv_usd_20d, 0) : "—"}</td><td className="r mono">{f2(p.pct_of_adv, 3)}</td><td className="r mono">{f2(p.days_to_exit_at_10pct, 3)}</td></tr>)}</tbody></table>)}
          <div className="note">{d.assumptions.join(" ")}</div>
        </>)}
    </Panel>
  );
}

export function ScenarioWidget() {
  const { pid } = usePortfolioId();
  const port = useQuery({ queryKey: ["portfolio", pid], queryFn: () => api.portfolio(pid), enabled: pid !== undefined, refetchInterval: 15_000 });
  const [shocks, setShocks] = useState<Record<string, string>>({});
  const [bench, setBench] = useState("");
  const [bshock, setBshock] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const run = useMutation({
    mutationFn: () => api.scenario({ portfolio_id: pid, shocks: Object.fromEntries(Object.entries(shocks).filter(([, v]) => v !== "").map(([k, v]) => [k, Number(v)])), ...(bench && bshock !== "" ? { benchmark: bench, benchmark_shock: Number(bshock) } : {}) }),
    onError: (e) => setMsg(err(e)), onSuccess: () => setMsg(null),
  });
  const r = run.data;
  return (
    <Panel title="SCENARIO LAB">
      <div className="note">Deterministic shocks on current marks. Enter a % move per position, and/or a benchmark move applied through each position's estimated beta.</div>
      <table className="tbl"><thead><tr><th>Position</th><th className="r">Value</th><th className="r">Shock %</th></tr></thead>
        <tbody>{port.data?.positions.map((p) => <tr key={p.symbol}><td><b>{p.symbol}</b></td><td className="r mono">{num(Number(p.value), 0)}</td>
          <td className="r"><input className="w60" type="number" value={shocks[p.symbol] ?? ""} onChange={(e) => setShocks({ ...shocks, [p.symbol]: e.target.value })} aria-label={`Shock ${p.symbol}`} placeholder="0" /></td></tr>)}</tbody></table>
      <div className="frow"><span className="dim small">benchmark</span>
        <select value={bench} onChange={(e) => setBench(e.target.value)} aria-label="Scenario benchmark"><option value="">none</option><option>SPY</option><option>QQQ</option></select>
        <input className="w60" type="number" value={bshock} onChange={(e) => setBshock(e.target.value)} placeholder="move %" aria-label="Benchmark shock" />
        <button className="mini on" disabled={run.isPending} onClick={() => run.mutate()}>Run scenario</button></div>
      {msg && <div className="note warn">{msg}</div>}
      {r && (
        <>
          <div className="stats"><div><span className="dim">P&L</span><b className={`mono ${dir(Number(r.pnl))}`}>{num(Number(r.pnl), 2)}</b></div>
            <div><span className="dim">% OF EQUITY</span><b className={`mono ${dir(r.pnl_pct_of_equity)}`}>{f2(r.pnl_pct_of_equity)}%</b></div>
            <div><span className="dim">EQUITY AFTER</span><b className="mono">{num(Number(r.equity_after), 2)}</b></div></div>
          <table className="tbl"><tbody>{r.positions.map((p) => <tr key={p.symbol}><td><b>{p.symbol}</b></td><td className="r mono">{p.shock_pct === null ? "—" : `${f2(p.shock_pct)}%`}</td><td className={`r mono ${dir(Number(p.pnl))}`}>{num(Number(p.pnl), 2)}</td><td className="dim small">{p.source}</td></tr>)}</tbody></table>
          {r.ignored_shocks.length > 0 && <div className="note warn">Ignored (not held): {r.ignored_shocks.join(", ")}</div>}
          {r.note && <div className="note warn">{r.note}</div>}
          <div className="note">{r.caveats.join(" ")}</div>
        </>)}
    </Panel>
  );
}

export function PerformanceWidget() {
  const theme = useStore((s) => s.theme);
  const host = useRef<HTMLDivElement>(null);
  const { pid } = usePortfolioId();
  const q = useQuery({ queryKey: ["performance", pid], queryFn: () => api.performance(pid), enabled: pid !== undefined, refetchInterval: 30_000 });
  const d = q.data;
  useEffect(() => {
    if (!host.current || !d || d.points.length < 2) return;
    const c = createChart(host.current, { autoSize: true, layout: { background: { type: ColorType.Solid, color: css("--panel") }, textColor: css("--dim"), fontSize: 11 },
      grid: { vertLines: { color: css("--grid") }, horzLines: { color: css("--grid") } }, rightPriceScale: { borderColor: css("--border") }, timeScale: { borderColor: css("--border"), timeVisible: true } });
    const s = c.addSeries(LineSeries, { color: css("--accent"), lineWidth: 2 });
    s.setData(d.points.map((p) => ({ time: Math.floor(new Date(p.ts).getTime() / 1000) as UTCTimestamp, value: Number(p.equity) })));
    c.timeScale().fitContent();
    return () => c.remove();
  }, [d, theme]);
  return (
    <Panel title="EQUITY CURVE">
      {q.isError && <ErrorBox error={q.error} />}
      {d && d.points.length >= 2 ? (
        <>
          <div className="stats"><div><span className="dim">TOTAL RETURN</span><b className={`mono ${dir(d.total_return_pct)}`}>{f2(d.total_return_pct)}%</b></div>
            <div><span className="dim">MAX DRAWDOWN</span><b className="mono down">{f2(d.max_drawdown_pct)}%</b></div><div><span className="dim">SAMPLES</span><b className="mono">{d.samples}</b></div></div>
          <div className="chart-host" ref={host} />
        </>) : <div className="note">{d?.reason ?? "Loading…"}: equity is sampled about once a minute while the server runs.</div>}
      {d && <div className="note">{d.note} <Badge status="HISTORICAL" title="Sampled history" /></div>}
    </Panel>
  );
}
