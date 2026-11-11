import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { ErrorBox, Panel } from "../ui";
import { ymdLabel as ymd } from "../fmt";

const n = (x: number) => x.toLocaleString("en-US");
const pc = (x: number) => `${x > 0 ? "+" : ""}${x.toFixed(1)}%`;
const cls = (x: number) => (x > 0 ? "up" : x < 0 ? "down" : "");

/** Bitcoin network health from mempool.space: fees, the mempool queue, the difficulty cycle and hashrate. Each part fails on its own. Not a price signal. */
export function NetworkWidget() {
  const q = useQuery({ queryKey: ["btc-network"], queryFn: api.btcNetwork, staleTime: 5 * 60_000, refetchInterval: 10 * 60_000, retry: 0 });
  const d = q.data;
  const hist = d?.hashrate.history ?? [];
  const lo = hist.length ? Math.min(...hist.map((h) => h.eh)) : 0;
  const hi = hist.length ? Math.max(...hist.map((h) => h.eh)) : 1;
  return (
    <Panel title="BITCOIN NETWORK · fees, mempool, mining" right={d && <span className="pill">{d.demo ? "DEMO" : "mempool.space"}</span>}>
      {q.isLoading && <div className="note">Loading…</div>}
      {q.isError && <ErrorBox error={q.error} />}
      {d && <div data-testid="network" style={{ display: "flex", gap: 24, flexWrap: "wrap" }}>
        <div style={{ flex: 1, minWidth: 250 }}>
          <div className="ws-bar" style={{ paddingLeft: 0 }}><span>FEES AND MEMPOOL</span></div>
          {!d.fees.available ? <div className="note warn">{d.fees.reason}</div> : <>
            <table className="tbl kv"><tbody>
              <tr><td className="dim">Fastest (next block)</td><td className="r mono">{d.fees.sat_per_vbyte!.fastest} sat/vB</td></tr>
              <tr><td className="dim">About an hour</td><td className="r mono">{d.fees.sat_per_vbyte!.hour} sat/vB</td></tr>
              <tr><td className="dim">Economy</td><td className="r mono">{d.fees.sat_per_vbyte!.economy} sat/vB</td></tr>
              <tr><td className="dim">A typical transaction ({d.fees.typical_tx_vbytes} vB), fastest</td><td className="r mono">{n(d.fees.typical_tx_sats_fastest!)} sats</td></tr>
              {d.fees.mempool && <><tr><td className="dim">Waiting to be confirmed</td><td className="r mono">{n(d.fees.mempool.transactions)} transactions</td></tr>
                <tr><td className="dim">Queue size</td><td className="r mono">{d.fees.mempool.megavbytes} MvB (about {d.fees.mempool.blocks_worth} blocks)</td></tr></>}
            </tbody></table></>}
        </div>
        <div style={{ flex: 1, minWidth: 250 }}>
          <div className="ws-bar" style={{ paddingLeft: 0 }}><span>MINING DIFFICULTY</span></div>
          {!d.difficulty.available ? <div className="note warn">{d.difficulty.reason}</div> : <>
            <table className="tbl kv"><tbody>
              {d.difficulty.block_height != null && <tr><td className="dim">Block height</td><td className="r mono">{n(d.difficulty.block_height)}</td></tr>}
              <tr><td className="dim">Through this 2,016-block cycle</td><td className="r mono">{d.difficulty.progress_pct}%</td></tr>
              <tr><td className="dim">Estimated next change (estimate)</td><td className={`r mono ${cls(d.difficulty.estimated_change_pct!)}`}>{pc(d.difficulty.estimated_change_pct!)}</td></tr>
              <tr><td className="dim">Blocks left · estimated date</td><td className="r mono">{n(d.difficulty.remaining_blocks!)} · {d.difficulty.estimated_date ? ymd(d.difficulty.estimated_date) : "n/a"}</td></tr>
              <tr><td className="dim">Last change</td><td className={`r mono ${cls(d.difficulty.previous_change_pct!)}`}>{pc(d.difficulty.previous_change_pct!)}</td></tr>
            </tbody></table>
            <div className="small dim">{d.difficulty.note}</div></>}
        </div>
        <div style={{ flex: 1, minWidth: 250 }}>
          <div className="ws-bar" style={{ paddingLeft: 0 }}><span>HASHRATE</span></div>
          {!d.hashrate.available ? <div className="note warn">{d.hashrate.reason}</div> : <>
            <div style={{ display: "flex", gap: 10, alignItems: "baseline", flexWrap: "wrap" }}><b className="mono" style={{ fontSize: 20 }}>{n(d.hashrate.seven_day_average_eh!)} EH/s</b><span className="dim small">7-day average · {ymd(d.hashrate.date)}</span>
              {d.hashrate.changes!.map((c) => <span key={c.label} className={`small ${cls(c.change_pct)}`}>{c.label}: {pc(c.change_pct)}</span>)}</div>
            <div style={{ display: "flex", gap: 1, alignItems: "flex-end", height: 28, margin: "6px 0" }} aria-label="Last 90 days of hashrate">
              {hist.map((h) => <span key={h.date} title={`${ymd(h.date)}: ${h.eh} EH/s`} style={{ flex: 1, height: `${Math.max(((h.eh - lo) / Math.max(hi - lo, 0.001)) * 90 + 10, 10)}%`, background: "var(--accent)", opacity: 0.6 }} />)}
            </div>
            <div className="small dim">{d.hashrate.note}</div></>}
        </div>
        <div className="small dim" style={{ width: "100%" }}>Not a price signal: fees can be near zero while price moves a lot. Source: <a href={d.url} target="_blank" rel="noreferrer noopener">{d.source}</a>.</div>
      </div>}
    </Panel>);
}
