import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { ErrorBox, Panel } from "../ui";

const b = (x: number) => `${x < 0 ? "-" : ""}$${Math.abs(x).toLocaleString("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 })}B`;
const pct = (x: number | null | undefined) => (x == null ? "" : ` (${x >= 0 ? "+" : ""}${x.toFixed(1)}% vs a year earlier)`);

/** Interest the US government owes on debt held by the public, by month and security type. Describes what already happened; not a signal. */
export function InterestExpenseWidget() {
  const q = useQuery({ queryKey: ["interest"], queryFn: api.interest, staleTime: 6 * 60 * 60_000, refetchInterval: 12 * 60 * 60_000, retry: 0 });
  const d = q.data;
  const hist = d?.history ?? [];
  const hi = hist.length ? Math.max(...hist.map((h) => h.total_billions), 0.001) : 1;
  return (
    <Panel title="INTEREST ON THE DEBT · what the US government owes each month (Treasury)" right={d && d.available && <span className={`pill ${d.freshness === "OVERDUE" ? "warn" : ""}`}>{d.freshness === "OVERDUE" ? "OVERDUE" : d.date?.slice(0, 7)}</span>}>
      {q.isLoading && <div className="note">Loading…</div>}
      {q.isError && <ErrorBox error={q.error} />}
      {d && <div data-testid="interest">
        {!d.available ? <div className="note warn">{d.reason}</div> : <>
          <div style={{ display: "flex", gap: 28, flexWrap: "wrap" }}>
            <div>
              <div className="ws-bar" style={{ paddingLeft: 0 }}><span>{d.date?.slice(0, 7)} (the month)</span></div>
              <div className="small"><b className="mono">{b(d.month_total_billions!)}</b>{pct(d.month_change_pct)}</div>
            </div>
            <div>
              <div className="ws-bar" style={{ paddingLeft: 0 }}><span>FISCAL {d.fiscal_year} SO FAR ({d.ytd_months} of 12 months)</span></div>
              <div className="small"><b className="mono">{b(d.ytd_total_billions!)}</b>{pct(d.ytd_change_pct)}</div>
              {d.ytd_check && <div className="small dim">{d.ytd_check.match ? "Matches" : "DOES NOT match"} the source's own year-to-date total ({b(d.ytd_check.source_billions)}).</div>}
            </div>
          </div>
          <table className="tbl" style={{ marginTop: 8 }}><tbody>
            {(d.breakdown ?? []).map((r) => <tr key={r.key}><td>{r.label}</td><td className="mono" style={{ textAlign: "right" }}>{b(r.billions)}</td><td className="mono dim" style={{ textAlign: "right" }}>{r.share_pct == null ? "" : `${r.share_pct.toFixed(1)}%`}</td></tr>)}
          </tbody></table>
          <div style={{ display: "flex", gap: 2, alignItems: "flex-end", height: 32, margin: "8px 0" }} aria-label="Monthly interest, last months">
            {hist.map((h) => <span key={h.date} title={`${h.date.slice(0, 7)}: ${b(h.total_billions)}`} style={{ flex: 1, height: `${Math.max((h.total_billions / hi) * 95, 4)}%`, background: "var(--accent)", opacity: 0.6 }} />)}
          </div>
          <div className="small dim">{d.note}</div></>}
        <div className="small dim">Source: <a href={d.url} target="_blank" rel="noreferrer noopener">{d.source ?? "US Treasury FiscalData"}</a>.</div>
      </div>}
    </Panel>);
}
