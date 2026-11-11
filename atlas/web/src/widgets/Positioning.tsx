import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { ErrorBox, Panel } from "../ui";
import { ymdLabel as ymd } from "../fmt";

const n = (x: number) => x.toLocaleString("en-US");
const sgn = (x: number | null | undefined) => (x === null || x === undefined ? "n/a" : `${x > 0 ? "+" : ""}${n(x)}`);
const cls = (x: number | null | undefined) => (x === null || x === undefined ? "dim" : x > 0 ? "up" : x < 0 ? "down" : "");

/** Who holds CME Bitcoin futures (CFTC Commitments of Traders): weekly, official and dated. A description of positions, not a signal. */
export function PositioningWidget() {
  const q = useQuery({ queryKey: ["btc-positioning"], queryFn: api.btcPositioning, staleTime: 60 * 60_000, refetchInterval: 6 * 60 * 60_000, retry: 0 });
  const d = q.data;
  return (
    <Panel title="BTC FUTURES POSITIONING · CFTC Commitments of Traders" right={d && d.available && <span className={`pill ${d.freshness === "OVERDUE" ? "warn" : ""}`}>{d.freshness === "OVERDUE" ? "OVERDUE" : `as of ${ymd(d.date)}`}</span>}>
      {q.isLoading && <div className="note">Loading…</div>}
      {q.isError && <ErrorBox error={q.error} />}
      {d && <div data-testid="positioning">
        {!d.available ? <div className="note warn">{d.reason}</div> : <>
          <div className="small">{d.market} · open interest <b className="mono">{n(d.open_interest!)}</b> contracts{d.open_interest_change != null && <span className={cls(d.open_interest_change)}> ({sgn(d.open_interest_change)} on the week)</span>} · {d.traders} reporting traders</div>
          <table className="tbl"><thead><tr><th>Group</th><th className="r">Long</th><th className="r">Short</th><th className="r">Net</th><th className="r">Net vs last week</th><th className="r">% of open interest long / short</th><th className="r">Net rank, 1 year</th></tr></thead><tbody>
            {d.groups!.map((g) => (
              <tr key={g.key} title={g.who}><td>{g.name}</td><td className="r mono">{n(g.long)}</td><td className="r mono">{n(g.short)}</td><td className={`r mono ${cls(g.net)}`}>{sgn(g.net)}</td><td className={`r mono ${cls(g.net_change)}`}>{sgn(g.net_change)}</td>
                <td className="r mono">{g.long_pct_oi}% / {g.short_pct_oi}%</td><td className="r mono">{g.net_rank_1y === null ? "n/a" : `${g.net_rank_1y} of 100`}</td></tr>))}
          </tbody></table>
          <div className="small dim">{d.note}</div>
          <div className="small dim">Source: {d.source}.</div></>}
      </div>}
    </Panel>);
}
