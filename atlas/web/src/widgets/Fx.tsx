import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { ErrorBox, Panel } from "../ui";

const pc = (x: number | null | undefined) => (x === null || x === undefined ? "n/a" : `${x > 0 ? "+" : ""}${x.toFixed(2)}%`);
const cls = (x: number | null | undefined) => (x === null || x === undefined ? "dim" : x > 0 ? "up" : x < 0 ? "down" : "");

/** How the US dollar is doing against the major currencies, from the ECB's daily euro reference rates. For information, not tradable quotes. */
export function FxWidget() {
  const q = useQuery({ queryKey: ["fx"], queryFn: api.fx, staleTime: 30 * 60_000, refetchInterval: 60 * 60_000, retry: 0 });
  const d = q.data;
  return (
    <Panel title="US DOLLAR vs MAJOR CURRENCIES · ECB reference rates" right={d && d.available && <span className={`pill ${d.freshness === "OVERDUE" ? "warn" : ""}`}>{d.freshness === "OVERDUE" ? "OVERDUE" : d.date}</span>}>
      {q.isLoading && <div className="note">Loading…</div>}
      {q.isError && <ErrorBox error={q.error} />}
      {d && <div data-testid="fx">
        {!d.available ? <div className="note warn">{d.reason}</div> : <>
          <table className="tbl"><thead><tr><th>Pair</th><th className="r">Rate</th><th className="r">Dollar vs it, 1 day</th><th className="r">Dollar vs it, 30 days</th></tr></thead><tbody>
            {d.pairs!.map((p) => <tr key={p.pair}><td><b>{p.pair}</b></td><td className="r mono">{p.rate}</td><td className={`r mono ${cls(p.dollar_vs_1d_pct)}`}>{pc(p.dollar_vs_1d_pct)}</td><td className={`r mono ${cls(p.dollar_vs_30d_pct)}`}>{pc(p.dollar_vs_30d_pct)}</td></tr>)}
          </tbody></table>
          <div className="small">The dollar is stronger than a month ago against <b>{d.breadth!.stronger_30d} of {d.breadth!.of}</b> of these currencies.</div>
          <div className="small dim">{d.note} Source: <a href={d.url} target="_blank" rel="noreferrer noopener">{d.source}</a>.</div></>}
      </div>}
    </Panel>);
}
