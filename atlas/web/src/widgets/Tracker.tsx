import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { ErrorBox, Panel } from "../ui";
import { ymdLabel as ymd } from "../fmt";

const pc = (x: number | null | undefined) => (x === null || x === undefined ? "n/a" : `${x > 0 ? "+" : ""}${Math.abs(x) >= 1000 ? Math.round(x).toLocaleString("en-US") : x.toFixed(1)}%`);
const cls = (x: number | null | undefined) => (x === null || x === undefined ? "dim" : x > 0 ? "up" : x < 0 ? "down" : "");
const EVID: Record<string, string> = { none: "No reliable evidence", weak: "Weak evidence", moderate: "Moderate evidence" };

/** Strategies added by the research loop: a frozen backtest on all BTC history up to the day each was added, and a forward record on the bars that arrived after. Research only. */
export function TrackerWidget() {
  const q = useQuery({ queryKey: ["strategy-tracker"], queryFn: api.strategyTracker, staleTime: 30 * 60_000, refetchInterval: 2 * 60 * 60_000, retry: 0 });
  const d = q.data;
  return (
    <Panel title="STRATEGY TRACKER · new rules, frozen backtest and forward record" right={d && <span className="pill">{d.entries.length} tracked · library {d.library_size}</span>}>
      {q.isLoading && <div className="note">Loading…</div>}
      {q.isError && <ErrorBox error={q.error} />}
      {d && <div data-testid="tracker">
        {d.entries.length === 0 && <div className="note">No strategies have been added to the tracker yet.</div>}
        {d.entries.map((e) => {
          const s = e.snapshot, fw = e.forward;
          return (
            <div key={e.id} data-testid={`tracker-${e.id}`} style={{ borderTop: "1px solid var(--border)", padding: "6px 0" }}>
              <div style={{ display: "flex", gap: 10, alignItems: "baseline", flexWrap: "wrap" }}><b>{e.name}</b><span className="pill">{e.family}</span><span className={`pill ${s.evidence.level === "none" ? "warn" : ""}`}>{EVID[s.evidence.level]}</span><span className="dim small">added {ymd(e.added_at)}</span></div>
              <div className="small dim">{e.idea}</div>
              <table className="tbl" style={{ marginTop: 4 }}><thead><tr><th>Backtest (frozen {ymd(e.added_at)}, data {ymd(s.data_from)} to {ymd(s.data_to)})</th><th className="r">Rule</th><th className="r">Holding BTC</th><th className="r">Rule worst drop</th><th className="r">Holding worst drop</th><th className="r">Trades</th></tr></thead><tbody>
                <tr><td>Whole history</td><td className={`r mono ${cls(s.full.net_return_pct)}`}>{pc(s.full.net_return_pct)}</td><td className="r mono">{pc(s.buy_and_hold.full.net_return_pct)}</td><td className="r mono down">{pc(s.full.max_drawdown_pct)}</td><td className="r mono down">{pc(s.buy_and_hold.full.max_drawdown_pct)}</td><td className="r mono">{s.full.trades}</td></tr>
                <tr><td>Last 30% (not used to design the rule)</td><td className={`r mono ${cls(s.out_of_sample.net_return_pct)}`}>{pc(s.out_of_sample.net_return_pct)}</td><td className="r mono">{pc(s.buy_and_hold.out_of_sample.net_return_pct)}</td><td className="r mono down">{pc(s.out_of_sample.max_drawdown_pct)}</td><td className="r mono down">{pc(s.buy_and_hold.out_of_sample.max_drawdown_pct)}</td><td className="r mono">{s.out_of_sample.trades}</td></tr>
              </tbody></table>
              <div className="small">{s.evidence.reasons.map((r, i) => <div key={i} className="warnc">• {r}</div>)}
                <span className="dim">Nearby settings made money out of sample in {Math.round(s.robustness.share_positive * 100)}% of cases; with doubled costs {pc(s.robustness.doubled_costs_oos_return_pct)}. The luck check counted {s.library_size} rules in the library.</span></div>
              <div className="ws-bar" style={{ paddingLeft: 0 }}><span>FORWARD RECORD · bars after {ymd(e.added_at)}</span></div>
              {fw === null ? <div className="note">Forward tracking needs real prices, so it is not shown in demo mode.</div>
                : fw.error ? <div className="note warn">{fw.error}</div>
                : <div data-testid={`tracker-forward-${e.id}`}>
                  {fw.strategy ? <div className="small">{fw.days} days: rule <b className={`mono ${cls(fw.strategy.return_pct)}`}>{pc(fw.strategy.return_pct)}</b> (worst drop {pc(fw.strategy.max_drawdown_pct)}, {fw.strategy.closed_trades} closed trades) vs holding BTC <b className={`mono ${cls(fw.buy_and_hold?.return_pct)}`}>{pc(fw.buy_and_hold?.return_pct)}</b>. Position now: <b>{fw.position_now}</b>.</div>
                    : <div className="small">Position now: <b>{fw.position_now}</b>.</div>}
                  <div className={`small ${fw.enough ? "dim" : "warnc"}`}>{fw.note}</div></div>}
            </div>);
        })}
        {d.notes.map((n, i) => <div key={i} className="small dim">{n}</div>)}
      </div>}
    </Panel>);
}
