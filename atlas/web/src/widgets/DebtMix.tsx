import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { ymdLabel as day } from "../fmt";
import { ErrorBox, Panel } from "../ui";

const money = (b: number) => (Math.abs(b) >= 1000 ? `$${(b / 1000).toFixed(2)}T` : `$${b.toFixed(1)}B`);
const chg = (b: number | null) => (b == null ? "n/a" : `${b > 0 ? "+" : b < 0 ? "-" : ""}${money(Math.abs(b))}`);

/** What the US national debt is made of (Monthly Statement of the Public Debt). A month-end accounting record; not a signal. */
export function DebtMixWidget() {
  const q = useQuery({ queryKey: ["debtmix"], queryFn: api.debtMix, staleTime: 6 * 60 * 60_000, refetchInterval: 12 * 60 * 60_000, retry: 0 });
  const d = q.data;
  return (
    <Panel title="WHAT THE US DEBT IS MADE OF · by type of security (Monthly Statement of the Public Debt)" right={d && d.available && <span className={`pill ${d.freshness === "OVERDUE" ? "warn" : ""}`}>{d.freshness === "OVERDUE" ? "OVERDUE" : day(d.date)}</span>}>
      {q.isLoading && <div className="note">Loading…</div>}
      {q.isError && <ErrorBox error={q.error} />}
      {d && <div data-testid="debtmix">
        {!d.available ? <div className="note warn">{d.reason}</div> : <>
          <div className="small">Total <b className="mono">{money(d.total_billions!)}</b> · held by the public <b className="mono">{money(d.held_by_public_billions!)}</b> · owed to government accounts <b className="mono">{money(d.held_by_government_accounts_billions!)}</b>
            {d.bills_share_of_marketable_pct != null ? ` · bills are ${d.bills_share_of_marketable_pct}% of marketable debt` : ""} · {chg(d.change_since_billions!)} since {day(d.since)} ({d.months_covered} month-ends)</div>
          <table className="tbl" style={{ width: "100%", marginTop: 6 }}>
            <thead><tr><th>TYPE</th><th>AMOUNT</th><th>SHARE OF TOTAL</th><th>VS LAST MONTH</th></tr></thead>
            <tbody>{(d.rows ?? []).map((r) => <tr key={r.name}><td>{r.name}</td><td className="mono">{money(r.billions)}</td><td className="mono">{r.share_of_total_pct.toFixed(1)}%</td><td className="mono">{chg(r.change_month_billions)}</td></tr>)}</tbody>
          </table>
          <div className="small dim">{d.note}</div></>}
        <div className="small dim">Source: <a href={d.url} target="_blank" rel="noreferrer noopener">{d.source ?? "US Treasury FiscalData"}</a>.</div>
      </div>}
    </Panel>);
}
