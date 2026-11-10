import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { ErrorBox, Panel } from "../ui";

const day = (iso?: string | null) => (iso ? new Date(`${iso}T12:00:00Z`).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" }) : "");
const monthYear = (iso?: string) => (iso ? new Date(`${iso}T12:00:00Z`).toLocaleDateString("en-US", { month: "long", year: "numeric", timeZone: "UTC" }) : "");
const bn = (x: number) => `${x < 0 ? "-" : x > 0 ? "+" : ""}$${Math.abs(x).toLocaleString("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 })}B`;
const plain = (x: number) => `$${x.toLocaleString("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 })}B`;
const vsYear = (x: number | null | undefined) => (x == null ? "No year-ago figure for this point" : `Same point a year earlier: ${bn(x)}`);

/** US Treasury marketable borrowing from the Daily Treasury Statement. Describes what already happened; not a signal. */
export function BorrowingWidget() {
  const q = useQuery({ queryKey: ["borrowing"], queryFn: api.borrowing, staleTime: 3 * 60 * 60_000, refetchInterval: 6 * 60 * 60_000, retry: 0 });
  const d = q.data;
  return (
    <Panel title="TREASURY BORROWING · new debt sold and old debt paid back (Treasury)" right={d && d.available && <span className={`pill ${d.freshness === "OVERDUE" ? "warn" : ""}`}>{d.freshness === "OVERDUE" ? `OVERDUE · ${day(d.date)}` : day(d.date)}</span>}>
      {q.isLoading && <div className="note">Loading…</div>}
      {q.isError && <ErrorBox error={q.error} />}
      {d && <div data-testid="borrowing">
        {!d.available ? <div className="note warn">{d.reason}</div> : <>
          <div style={{ display: "flex", gap: 28, flexWrap: "wrap" }}>
            <div>
              <div className="ws-bar" style={{ paddingLeft: 0 }}><span>{monthYear(d.date).toUpperCase()} SO FAR (through {day(d.date)})</span></div>
              <div className="small">Net new borrowing <b className="mono">{bn(d.month_to_date!.net_billions)}</b> · {vsYear(d.month_to_date!.year_ago_net_billions)}</div>
              <div className="small dim">Sold {plain(d.month_to_date!.issues_billions)} · paid back {plain(d.month_to_date!.redemptions_billions)}</div>
            </div>
            <div>
              <div className="ws-bar" style={{ paddingLeft: 0 }}><span>FISCAL {d.fiscal_year} SO FAR (since Oct 1)</span></div>
              <div className="small">Net new borrowing <b className="mono">{bn(d.fiscal_year_to_date!.net_billions)}</b> · {vsYear(d.fiscal_year_to_date!.year_ago_net_billions)}</div>
              <div className="small dim">Sold {plain(d.fiscal_year_to_date!.issues_billions)} · paid back {plain(d.fiscal_year_to_date!.redemptions_billions)}</div>
            </div>
          </div>
          <table className="tbl" style={{ marginTop: 8 }}><thead><tr><th>This month so far</th><th style={{ textAlign: "right" }}>Sold</th><th style={{ textAlign: "right" }}>Paid back</th><th style={{ textAlign: "right" }}>Net (month)</th><th style={{ textAlign: "right" }}>Net (fiscal year)</th></tr></thead><tbody>
            {(d.by_security ?? []).map((r) => <tr key={r.key}><td>{r.label}</td><td className="mono" style={{ textAlign: "right" }}>{plain(r.mtd_issues_billions)}</td><td className="mono" style={{ textAlign: "right" }}>{plain(r.mtd_redemptions_billions)}</td><td className="mono" style={{ textAlign: "right" }}>{bn(r.mtd_net_billions)}</td><td className="mono" style={{ textAlign: "right" }}>{bn(r.fytd_net_billions)}</td></tr>)}
          </tbody></table>
          {d.mtd_check && <div className="small dim">{d.mtd_check.match ? "Checked: the" : "DOES NOT MATCH: the"} {d.mtd_check.days} daily amounts add up to {d.mtd_check.match ? "" : "something different from "}the source's own month-to-date totals ({plain(d.mtd_check.source_issues_billions)} sold, {plain(d.mtd_check.source_redemptions_billions)} paid back).</div>}
          <div className="small dim">{d.note}</div></>}
        <div className="small dim">Source: <a href={d.url} target="_blank" rel="noreferrer noopener">{d.source ?? "US Treasury FiscalData"}</a>.</div>
      </div>}
    </Panel>);
}
