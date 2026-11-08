import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { ErrorBox, Panel } from "../ui";

const pp = (x: number | null) => (x == null ? "n/a" : `${x > 0 ? "+" : x < 0 ? "-" : ""}${Math.abs(x).toFixed(3)}`);

/** Average interest rate the US government pays on its debt, by security type (FiscalData). Describes what it pays on what it owes; not a signal. */
export function DebtRatesWidget() {
  const q = useQuery({ queryKey: ["debtrates"], queryFn: api.debtRates, staleTime: 6 * 60 * 60_000, refetchInterval: 12 * 60 * 60_000, retry: 0 });
  const d = q.data;
  const hist = d?.history ?? [];
  const lo = hist.length ? Math.min(...hist.map((h) => h.rate)) : 0;
  const hi = hist.length ? Math.max(...hist.map((h) => h.rate)) : 1;
  return (
    <Panel title="INTEREST THE TREASURY PAYS · average rate on debt outstanding (US Treasury)" right={d && d.available && <span className={`pill ${d.freshness === "OVERDUE" ? "warn" : ""}`}>{d.freshness === "OVERDUE" ? "OVERDUE" : d.date}</span>}>
      {q.isLoading && <div className="note">Loading…</div>}
      {q.isError && <ErrorBox error={q.error} />}
      {d && <div data-testid="debtrates">
        {!d.available ? <div className="note warn">{d.reason}</div> : <>
          <table className="tbl" style={{ width: "100%" }}>
            <thead><tr><th>DEBT TYPE</th><th>AVERAGE RATE %</th><th>VS LAST MONTH (pts)</th><th>VS A YEAR AGO (pts)</th></tr></thead>
            <tbody>{(d.rows ?? []).map((r) => <tr key={r.name}><td>{r.name}</td><td className="mono">{r.rate.toFixed(3)}</td><td className="mono">{pp(r.change_month)}</td><td className="mono">{pp(r.change_year)}</td></tr>)}</tbody>
          </table>
          <div style={{ display: "flex", gap: 2, alignItems: "flex-end", height: 28, margin: "8px 0" }} aria-label="Average rate on all interest-bearing debt, by month">
            {hist.map((h) => <span key={h.date} title={`${h.date}: ${h.rate.toFixed(3)}%`} style={{ flex: 1, height: `${Math.max(((h.rate - lo) / Math.max(hi - lo, 0.001)) * 90, 6)}%`, background: "var(--accent)", opacity: 0.6 }} />)}
          </div>
          <div className="small dim">Bars: all interest-bearing debt by month. {d.note}</div></>}
        <div className="small dim">Source: <a href={d.url} target="_blank" rel="noreferrer noopener">{d.source ?? "US Treasury FiscalData"}</a>.</div>
      </div>}
    </Panel>);
}
