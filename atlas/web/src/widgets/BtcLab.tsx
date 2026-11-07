import { Fragment, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api, errText } from "../api";
import type { LabResult, LabRun, LabStrategy, Metrics } from "../btclab";
import { ErrorBox, Panel } from "../ui";

const pc = (x: number | null | undefined, d = 1) => (x === null || x === undefined ? "n/a" : `${x >= 0 ? "+" : "−"}${Math.abs(x).toFixed(d)}%`);
const n2 = (x: number | null | undefined) => (x === null || x === undefined ? "n/a" : x.toFixed(2));
const LEVEL: Record<string, string> = { none: "No reliable evidence", weak: "Weak evidence", moderate: "Moderate evidence" };

function Line({ a, b, h = 90, color = "#4aa3ff", split }: { a: number[]; b?: number[]; h?: number; color?: string; split?: number }) {
  const all = [...a, ...(b ?? [])].filter((x) => x > 0);
  const lo = Math.log(Math.min(...all, 1)), hi = Math.log(Math.max(...all, 1.0001));
  const pts = (s: number[]) => s.map((v, i) => `${(i / (s.length - 1)) * 100},${h - ((Math.log(Math.max(v, 1e-6)) - lo) / (hi - lo || 1)) * (h - 4) - 2}`).join(" ");
  return (
    <svg viewBox={`0 0 100 ${h}`} preserveAspectRatio="none" style={{ width: "100%", height: h }} role="img" aria-label="Equity curve, log scale">
      {split !== undefined && <rect x={split * 100} y={0} width={(1 - split) * 100} height={h} fill="rgba(255,255,255,0.05)" />}
      {b && <polyline points={pts(b)} fill="none" stroke="#777" strokeWidth={0.6} vectorEffect="non-scaling-stroke" />}
      <polyline points={pts(a)} fill="none" stroke={color} strokeWidth={1.2} vectorEffect="non-scaling-stroke" />
    </svg>);
}

function DD({ s, h = 50 }: { s: number[]; h?: number }) {
  const lo = Math.min(...s, -1);
  return <svg viewBox={`0 0 100 ${h}`} preserveAspectRatio="none" style={{ width: "100%", height: h }} role="img" aria-label="Drawdown"><polyline points={s.map((v, i) => `${(i / (s.length - 1)) * 100},${(v / lo) * (h - 2)}`).join(" ")} fill="none" stroke="#e5484d" strokeWidth={1} vectorEffect="non-scaling-stroke" /></svg>;
}

function Detail({ r, run }: { r: LabResult; run: LabRun }) {
  const m = (t: string, x: Metrics) => <tr><td>{t}</td><td className="r mono">{pc(x.net_return_pct)}</td><td className="r mono">{n2(x.sharpe)}</td><td className="r mono">{pc(x.max_drawdown_pct)}</td><td className="r mono">{x.trades}</td></tr>;
  return (
    <div className="note" data-testid={`lab-detail-${r.id}`}>
      <div className="small"><span className={`pill ${r.evidence.level === "none" ? "warn" : ""}`}>{LEVEL[r.evidence.level]}</span></div>
      {r.evidence.reasons.map((x, i) => <div key={i} className="small">• {x}</div>)}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(260px,1fr))", gap: 12, marginTop: 8 }}>
        <div><div className="dim small">Equity (log scale): strategy blue, buy and hold grey. Shaded = out of sample.</div><Line a={r.curve.strategy} b={r.curve.buy_and_hold} split={r.curve.oos_starts_at} /><div className="dim small">Drawdown</div><DD s={r.curve.drawdown} /><div className="dim small mono">{r.curve.from} to {r.curve.to}</div></div>
        <table className="tbl"><thead><tr><th /><th className="r">Return</th><th className="r">Sharpe</th><th className="r">Max DD</th><th className="r">Trades</th></tr></thead><tbody>
          {m("In sample (first 70%)", r.in_sample)}{m("Out of sample (last 30%)", r.out_of_sample)}{m("Walk-forward (re-tuned as you go)", r.walk_forward)}{m("Buy and hold, out of sample", r.buy_and_hold.out_of_sample)}</tbody></table>
      </div>
      <div className="small" style={{ marginTop: 6 }}><b>Robustness.</b> Out of sample, {Math.round(r.robustness.share_positive * 100)}% of five nearby values of "{r.robustness.param}" made money ({r.robustness.neighbours.map((x) => `${x[r.robustness.param]}: ${pc(x.oos_return_pct, 0)}`).join(", ")}). With fees and slippage doubled: {pc(r.robustness.doubled_costs_oos_return_pct)}.</div>
      <div className="small"><b>Costs paid over the history:</b> fees {r.costs.fees_paid_pct.toFixed(1)}% of equity-notional{run.settings.market === "perp" ? `, funding ${r.costs.funding_paid_pct >= 0 ? "paid" : "received"} ${Math.abs(r.costs.funding_paid_pct).toFixed(1)}%` : ""}{r.costs.liquidated ? ". LIQUIDATED." : "."}</div>
      <div className="small" style={{ marginTop: 6 }}><b>Right now ({r.now.as_of}):</b> the rule is <b>{r.now.rule_position}</b>. {r.now.conditions.map((c, i) => <span key={i}>{c.met === null ? "?" : c.met ? "✓" : "✗"} {c.rule} <span className="dim">({c.value})</span>{i < r.now.conditions.length - 1 ? "; " : ""}</span>)} <div className="dim">{r.now.note}</div></div>
      <details style={{ marginTop: 6 }}><summary className="small">Walk-forward folds ({r.walk_forward.folds.length})</summary>
        <table className="tbl"><tbody>{r.walk_forward.folds.map((f, i) => <tr key={i}><td className="mono">{f.from} to {f.to}</td><td>chose {Object.entries(f.chosen).map(([k, v]) => `${k}=${v}`).join(", ")}</td><td className="r mono">{pc(f.test_return_pct)}</td></tr>)}</tbody></table></details>
      <details style={{ marginTop: 6 }}><summary className="small">Recent trades ({r.trades.total} in all)</summary>
        <table className="tbl"><thead><tr><th>Entry</th><th>Exit</th><th>Side</th><th className="r">Entry px</th><th className="r">Exit px</th><th className="r">Net</th><th>Why</th></tr></thead><tbody>{r.trades.recent.slice(-15).reverse().map((t, i) => <tr key={i}><td className="mono">{t.entry}</td><td className="mono">{t.exit}{t.open ? " (open)" : ""}</td><td>{t.side}</td><td className="r mono">{t.entry_px.toFixed(0)}</td><td className="r mono">{t.exit_px.toFixed(0)}</td><td className="r mono">{pc(t.ret_pct)}</td><td className="dim">{t.reason}</td></tr>)}</tbody></table></details>
    </div>);
}

/** Compare BTC strategies on history they were not designed around. Defaults to five candidates; every figure is net of fees, slippage and (perps) funding. */
export function BtcLabWidget() {
  const lib = useQuery({ queryKey: ["lab-strategies"], queryFn: api.labStrategies, staleTime: 60 * 60_000 });
  const [picked, setPicked] = useState<string[] | null>(null);
  const [tf, setTf] = useState("1d");
  const [market, setMarket] = useState("spot");
  const [lev, setLev] = useState(1);
  const [ls, setLs] = useState(false);
  const [fee, setFee] = useState(5);
  const [slip, setSlip] = useState(5);
  const [more, setMore] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  const ids = picked ?? lib.data?.defaults ?? [];
  const run = useMutation({ mutationFn: () => api.labRun({ strategies: ids, timeframe: tf, market, leverage: market === "perp" ? lev : 1, long_short: market === "perp" && ls, fee_bps: fee, slippage_bps: slip }) });
  const toggle = (id: string) => setPicked(ids.includes(id) ? ids.filter((x) => x !== id) : ids.length < 8 ? [...ids, id] : ids);
  const d = run.data;
  const byFamily = (lib.data?.strategies ?? []).reduce<Record<string, LabStrategy[]>>((a, s) => ({ ...a, [s.family]: [...(a[s.family] ?? []), s] }), {});
  return (
    <Panel title="BTC STRATEGY LAB" right={d && <span className={`pill ${d.data.demo ? "warn" : ""}`}>{d.data.status}</span>}>
      {lib.isError && <ErrorBox error={lib.error} />}
      <div className="note">Research only. Each rule is fixed in advance and tested after fees, slippage and funding on history it was not tuned to. A rule being "on" now is a description, not a forecast.</div>
      <div className="toolbar" data-testid="lab-controls">
        <span className="savedchip">{["spot", "perp"].map((m) => <button key={m} className={`mini ${market === m ? "on" : ""}`} onClick={() => setMarket(m)}>{m === "spot" ? "spot" : "perpetual"}</button>)}</span>
        <span className="savedchip">{["1d", "4h", "1h"].map((x) => <button key={x} className={`mini ${tf === x ? "on" : ""}`} onClick={() => setTf(x)}>{x}</button>)}</span>
        {market === "perp" && <><span className="savedchip">{[1, 2, 3].map((x) => <button key={x} className={`mini ${lev === x ? "on" : ""}`} onClick={() => setLev(x)}>{x}x</button>)}</span>
          <label className="small"><input type="checkbox" checked={ls} onChange={(e) => setLs(e.target.checked)} /> allow shorts</label></>}
        <button className="mini" onClick={() => setMore(!more)}>{more ? "fewer options" : "more options"}</button>
        <button className="mini on" disabled={run.isPending || ids.length === 0} onClick={() => run.mutate()} data-testid="lab-run">{run.isPending ? "running…" : `compare ${ids.length}`}</button>
      </div>
      {more && <div className="jq-more" data-testid="lab-more">
        <label>Fee per side (bps)<input className="w80" type="number" min={0} max={50} value={fee} onChange={(e) => setFee(Number(e.target.value))} /></label>
        <label>Slippage per side (bps)<input className="w80" type="number" min={0} max={100} value={slip} onChange={(e) => setSlip(Number(e.target.value))} /></label>
        <div className="jq-wide small dim">Pick up to 8 strategies (five are chosen by default, one per style). Perpetual tests start in May 2023, when funding history begins. Leverage is capped at 3x.</div>
        {Object.entries(byFamily).map(([fam, list]) => <div key={fam} className="jq-wide small"><b>{fam}:</b> {list.map((s) => <label key={s.id} style={{ marginRight: 10 }} title={`${s.summary}\nEntry: ${s.entry}\nExit: ${s.exit}\nStop: ${s.stop}\nSizing: ${s.sizing}${s.notes.length ? "\n" + s.notes.join(" ") : ""}`}><input type="checkbox" checked={ids.includes(s.id)} onChange={() => toggle(s.id)} /> {s.name}</label>)}</div>)}
      </div>}
      {run.isError && <div className="warnc small" data-testid="lab-error">{errText(run.error)}</div>}
      {d && <div data-testid="lab-results">
        <div className="small dim">{d.period.from} to {d.period.to} · {d.period.bars.toLocaleString()} {d.settings.timeframe} bars · {d.data.source}{d.data.funding_source ? ` · ${d.data.funding_source}` : ""} · fees {d.settings.fee_bps} bps, slippage {d.settings.slippage_bps} bps per side{d.data.gap_count ? ` · ${d.data.gap_count} gaps in the saved bars` : ""}</div>
        {d.data.notes.map((x, i) => <div key={i} className="note warn">{x}</div>)}
        {d.notes.map((x, i) => <div key={i} className="note">{x}</div>)}
        <table className="tbl" data-testid="lab-table"><thead><tr><th>#</th><th>Strategy</th><th>Evidence</th><th className="r" title="Last 30% of history; rules were not tuned on it">OOS return</th><th className="r">OOS Sharpe</th><th className="r">Max DD</th><th className="r">Win rate</th><th className="r">Profit factor</th><th className="r">OOS trades</th><th className="r" title="Re-tuned on the past only, as you go">Walk-fwd</th><th className="r" title="Share of five nearby parameter values that made money out of sample">Robust</th></tr></thead>
          <tbody>
            <tr className="dim"><td /><td>Buy and hold BTC</td><td>baseline</td><td className="r mono">{pc(d.results[0]?.buy_and_hold.out_of_sample.net_return_pct)}</td><td className="r mono">{n2(d.results[0]?.buy_and_hold.out_of_sample.sharpe)}</td><td className="r mono">{pc(d.results[0]?.buy_and_hold.out_of_sample.max_drawdown_pct)}</td><td /><td /><td /><td /><td /></tr>
            {d.results.map((r, i) => (<Fragment key={r.id}>
              <tr onClick={() => setOpen(open === r.id ? null : r.id)} className={open === r.id ? "sel" : ""} style={{ cursor: "pointer" }} data-testid={`lab-row-${r.id}`}>
                <td>{i + 1}</td><td><b>{r.name}</b><div className="dim small">{r.family}</div></td><td><span className={`pill ${r.evidence.level === "none" ? "warn" : ""}`}>{LEVEL[r.evidence.level]}</span></td>
                <td className="r mono">{pc(r.out_of_sample.net_return_pct)}</td><td className="r mono">{n2(r.out_of_sample.sharpe)}</td><td className="r mono">{pc(r.out_of_sample.max_drawdown_pct)}</td>
                <td className="r mono">{r.out_of_sample.win_rate_pct === null ? "n/a" : `${r.out_of_sample.win_rate_pct.toFixed(0)}%`}</td><td className="r mono">{r.out_of_sample.profit_factor === null ? (r.out_of_sample.no_losing_trades ? "no losses" : "n/a") : r.out_of_sample.profit_factor.toFixed(2)}</td>
                <td className="r mono">{r.out_of_sample.trades}</td><td className="r mono">{pc(r.walk_forward.net_return_pct, 0)}</td><td className="r mono">{Math.round(r.robustness.share_positive * 100)}%</td></tr>
              {open === r.id && <tr><td colSpan={11}><RuleBox id={r.id} /><Detail r={r} run={d} /></td></tr>}</Fragment>))}
          </tbody></table>
        {d.skipped.map((s) => <div key={s.id} className="note">{s.id}: {s.reason}</div>)}
        <div className="small dim">Buy and hold over the whole period: {pc(d.buy_and_hold.metrics.net_return_pct, 0)}, worst drawdown {pc(d.buy_and_hold.metrics.max_drawdown_pct, 0)}. {d.caveats.join(" ")}</div>
      </div>}
    </Panel>);

  function RuleBox({ id }: { id: string }) {
    const s = lib.data?.strategies.find((x) => x.id === id);
    if (!s) return null;
    return <div className="small" style={{ marginBottom: 6 }}><b>Rules.</b> Entry: {s.entry} Exit: {s.exit} Stop: {s.stop} Sizing: {s.sizing} Settings: {Object.entries(s.params).map(([k, v]) => `${k}=${v}`).join(", ")} (in bars).</div>;
  }
}
