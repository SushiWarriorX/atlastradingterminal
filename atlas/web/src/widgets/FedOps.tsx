import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { ymdLabel as day } from "../fmt";
import { ErrorBox, Panel } from "../ui";

const b = (x: number) => `$${x.toFixed(x >= 10 ? 1 : 2)}B`;
const chg = (x: number) => `${x > 0 ? "+" : x < 0 ? "-" : ""}$${Math.abs(x).toFixed(2)}B`;

/** Fed liquidity operations from the New York Fed: cash parked at the Fed overnight (reverse repo) and cash the Fed lent (standing repo). Describes money-market plumbing; not a signal. */
export function FedOpsWidget() {
  const q = useQuery({ queryKey: ["fedops"], queryFn: api.fedOps, staleTime: 15 * 60_000, refetchInterval: 30 * 60_000, retry: 0 });
  const d = q.data;
  const hist = d?.history ?? [];
  const hi = hist.length ? Math.max(...hist.map((h) => h.reverse_repo_billions), 0.001) : 1;
  return (
    <Panel title="FED LIQUIDITY OPERATIONS · reverse repo and standing repo (New York Fed)" right={d && d.available && <span className={`pill ${d.freshness === "OVERDUE" ? "warn" : ""}`}>{d.freshness === "OVERDUE" ? "OVERDUE" : day(d.date)}</span>}>
      {q.isLoading && <div className="note">Loading…</div>}
      {q.isError && <ErrorBox error={q.error} />}
      {d && <div data-testid="fedops">
        {!d.available ? <div className="note warn">{d.reason}</div> : <>
          <div style={{ display: "flex", gap: 28, flexWrap: "wrap" }}>
            <div>
              <div className="ws-bar" style={{ paddingLeft: 0 }}><span>CASH PARKED AT THE FED (reverse repo)</span></div>
              <b className="mono" style={{ fontSize: 22 }}>{b(d.reverse_repo!.billions)}</b> <span className="small dim">{chg(d.reverse_repo!.change_billions)} vs the day before</span>
              <div className="small dim">About a month: average {b(d.reverse_repo!.average_billions)}, highest {b(d.reverse_repo!.highest_billions)} on {day(d.reverse_repo!.highest_date)}.</div>
            </div>
            <div>
              <div className="ws-bar" style={{ paddingLeft: 0 }}><span>CASH THE FED LENT (standing repo)</span></div>
              <b className="mono" style={{ fontSize: 22 }}>{b(d.repo!.billions)}</b> <span className="small dim">on {day(d.date)}</span>
              <div className="small dim">About a month: used on {d.repo!.days_used} of {d.repo!.dates_in_window} days, highest {b(d.repo!.highest_billions)}.</div>
            </div>
          </div>
          <div style={{ display: "flex", gap: 1, alignItems: "flex-end", height: 28, margin: "8px 0" }} aria-label="Last 40 days of reverse repo">
            {hist.map((h) => <span key={h.date} title={`${day(h.date)}: reverse repo ${b(h.reverse_repo_billions)}, repo ${b(h.repo_billions)}`} style={{ flex: 1, height: `${Math.max((h.reverse_repo_billions / hi) * 90, 4)}%`, background: "var(--accent)", opacity: 0.6 }} />)}
          </div>
          <div className="small dim">{d.note}</div></>}
        <div className="small dim">Source: <a href={d.url} target="_blank" rel="noreferrer noopener">{d.source ?? "Federal Reserve Bank of New York"}</a>.</div>
      </div>}
    </Panel>);
}
