import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { ErrorBox, Panel } from "../ui";

const b = (x: number) => `${x < 0 ? "-" : ""}$${Math.abs(x).toLocaleString("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 })}B`;

/** US federal receipts, outlays and deficit from the Monthly Treasury Statement. Describes what already happened; not a signal. */
export function BudgetWidget() {
  const q = useQuery({ queryKey: ["budget"], queryFn: api.budget, staleTime: 6 * 60 * 60_000, refetchInterval: 12 * 60 * 60_000, retry: 0 });
  const d = q.data;
  const hist = d?.history ?? [];
  const hi = hist.length ? Math.max(...hist.map((h) => Math.max(h.receipts_billions, h.outlays_billions)), 0.001) : 1;
  return (
    <Panel title="FEDERAL BUDGET · receipts, spending and deficit (Monthly Treasury Statement)" right={d && d.available && <span className={`pill ${d.freshness === "OVERDUE" ? "warn" : ""}`}>{d.freshness === "OVERDUE" ? "OVERDUE" : `${d.month} ${d.date?.slice(0, 4)}`}</span>}>
      {q.isLoading && <div className="note">Loading…</div>}
      {q.isError && <ErrorBox error={q.error} />}
      {d && <div data-testid="budget">
        {!d.available ? <div className="note warn">{d.reason}</div> : <>
          <div style={{ display: "flex", gap: 28, flexWrap: "wrap" }}>
            <div>
              <div className="ws-bar" style={{ paddingLeft: 0 }}><span>{d.month!.toUpperCase()} (the month)</span></div>
              <div className="small">Collected <b className="mono">{b(d.month_receipts_billions!)}</b> · spent <b className="mono">{b(d.month_outlays_billions!)}</b></div>
              <div className="small">{d.month_deficit_billions! >= 0 ? "Deficit" : "Surplus"} <b className="mono">{b(Math.abs(d.month_deficit_billions!))}</b></div>
            </div>
            <div>
              <div className="ws-bar" style={{ paddingLeft: 0 }}><span>FISCAL {d.fiscal_year} SO FAR ({d.ytd_months} of 12 months)</span></div>
              <div className="small">Collected <b className="mono">{b(d.ytd_receipts_billions!)}</b> · spent <b className="mono">{b(d.ytd_outlays_billions!)}</b></div>
              <div className="small">{d.ytd_deficit_billions! >= 0 ? "Deficit" : "Surplus"} <b className="mono">{b(Math.abs(d.ytd_deficit_billions!))}</b>{d.prior_ytd_deficit_billions != null ? ` · same months a year earlier: ${d.prior_ytd_deficit_billions >= 0 ? "deficit" : "surplus"} ${b(Math.abs(d.prior_ytd_deficit_billions))}` : ""}</div>
            </div>
          </div>
          <div style={{ display: "flex", gap: 2, alignItems: "flex-end", height: 32, margin: "8px 0" }} aria-label="Monthly receipts and outlays, last 24 months">
            {hist.map((h) => <span key={`${h.fiscal_year}${h.month}`} title={`${h.month} FY${h.fiscal_year}: collected ${b(h.receipts_billions)}, spent ${b(h.outlays_billions)}`} style={{ flex: 1, height: `${Math.max((h.outlays_billions / hi) * 95, 4)}%`, background: "var(--accent)", opacity: 0.6 }} />)}
          </div>
          <div className="small dim">Bars show monthly spending. {d.note}</div></>}
        <div className="small dim">Source: <a href={d.url} target="_blank" rel="noreferrer noopener">{d.source ?? "US Treasury FiscalData"}</a>.</div>
      </div>}
    </Panel>);
}
