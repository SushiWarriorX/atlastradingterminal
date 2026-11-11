import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { ErrorBox, Panel } from "../ui";

const bn = (x: number) => `${x < 0 ? "−" : ""}$${Math.abs(x).toLocaleString("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 })}B`;
const monthName = (iso: string) => new Date(`${iso}T12:00:00Z`).toLocaleDateString("en-US", { month: "long", year: "numeric", timeZone: "UTC" });
const monthShort = (iso: string) => new Date(`${iso}T12:00:00Z`).toLocaleDateString("en-US", { month: "short", year: "numeric", timeZone: "UTC" });

/** US customs duties (tariff revenue): collected, refunded and net, by month and fiscal year so far (Monthly Treasury Statement). Describes what already happened; not a signal. */
export function CustomsWidget() {
  const q = useQuery({ queryKey: ["customs"], queryFn: api.customs, staleTime: 6 * 60 * 60_000, refetchInterval: 12 * 60 * 60_000, retry: 0 });
  const d = q.data;
  return (
    <Panel title="CUSTOMS DUTIES · tariff revenue the Treasury collected, refunded and kept (US Treasury)" right={d && d.available && <span className={`pill ${d.freshness === "OVERDUE" ? "warn" : ""}`}>{d.freshness === "OVERDUE" ? `OVERDUE · ${monthShort(d.date!)}` : monthShort(d.date!)}</span>}>
      {q.isLoading && <div className="note">Loading…</div>}
      {q.isError && <ErrorBox error={q.error} />}
      {d && <div data-testid="customs">
        {!d.available ? <div className="note warn">{d.reason}</div> : <>
          <div style={{ display: "flex", gap: 28, flexWrap: "wrap" }}>
            <div>
              <div className="ws-bar" style={{ paddingLeft: 0 }}><span>{monthName(d.date!).toUpperCase()}</span></div>
              <div className="small">Collected <b className="mono">{bn(d.latest!.gross_billions)}</b> · paid back in refunds <b className="mono">{bn(d.latest!.refunds_billions)}</b>{d.latest!.refunds_share_of_gross_pct != null ? ` (${d.latest!.refunds_share_of_gross_pct}% of what was collected)` : ""} · kept <b className="mono">{bn(d.latest!.net_billions)}</b></div>
            </div>
            <div>
              <div className="ws-bar" style={{ paddingLeft: 0 }}><span>FISCAL {d.fiscal_year} SO FAR ({d.year_so_far!.months} {d.year_so_far!.months === 1 ? "MONTH" : "MONTHS"} FROM OCTOBER)</span></div>
              <div className="small">Kept <b className="mono">{bn(d.year_so_far!.net_billions)}</b> (collected {bn(d.year_so_far!.gross_billions)}, refunded {bn(d.year_so_far!.refunds_billions)})</div>
              <div className="small dim">Same point last year: {bn(d.year_so_far!.same_point_last_year_net_billions)}{d.year_so_far!.change_vs_last_year_pct != null ? ` · ${d.year_so_far!.change_vs_last_year_pct > 0 ? "up" : "down"} ${Math.abs(d.year_so_far!.change_vs_last_year_pct)}%` : ""}</div>
            </div>
          </div>
          <div className="ws-bar" style={{ paddingLeft: 0, marginTop: 8 }}><span>LAST {(d.months ?? []).length} MONTHS</span></div>
          <table className="tbl" style={{ tableLayout: "fixed", width: "100%" }}><thead><tr><th style={{ width: "25%" }}>Month</th><th className="r" style={{ width: "25%" }}>Collected</th><th className="r" style={{ width: "25%" }}>Refunded</th><th className="r" style={{ width: "25%" }}>Kept (net)</th></tr></thead>
            <tbody>{[...(d.months ?? [])].reverse().map((m) => <tr key={m.date}><td>{monthName(m.date)}</td><td className="r mono">{bn(m.gross_billions)}</td><td className="r mono">{bn(m.refunds_billions)}</td><td className={`r mono ${m.net_billions < 0 ? "down" : ""}`}><b>{bn(m.net_billions)}</b></td></tr>)}</tbody></table>
          <div className="small dim">Checked: each month's collected minus refunded equals what was kept, and the year-so-far total equals the sum of that year's months ({d.checks?.fytd_sum_checks} checks, no mismatches).</div>
          <div className="small dim">{d.note}</div></>}
        <div className="small dim">Source: <a href={d.url} target="_blank" rel="noreferrer noopener">{d.source ?? "US Treasury FiscalData"}</a>.</div>
      </div>}
    </Panel>);
}
