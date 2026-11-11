import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { ErrorBox, Panel } from "../ui";

const bn = (x: number) => `${x < 0 ? "−" : ""}$${Math.abs(x).toLocaleString("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 })}B`;
const move = (x: number | null) => (x == null ? "n/a" : x === 0 ? "unchanged" : `${x > 0 ? "up" : "down"} ${Math.abs(x)}%`);
const monthName = (iso: string) => new Date(`${iso}T12:00:00Z`).toLocaleDateString("en-US", { month: "long", year: "numeric", timeZone: "UTC" });
const monthShort = (iso: string) => new Date(`${iso}T12:00:00Z`).toLocaleDateString("en-US", { month: "short", year: "numeric", timeZone: "UTC" });

/** Where US federal revenue comes from: the seven receipt categories for the latest month and the fiscal year so far versus last year (Monthly Treasury Statement). Describes what already happened; not a signal. */
export function ReceiptsWidget() {
  const q = useQuery({ queryKey: ["receipts"], queryFn: api.receipts, staleTime: 6 * 60 * 60_000, refetchInterval: 12 * 60 * 60_000, retry: 0 });
  const d = q.data;
  return (
    <Panel title="WHERE FEDERAL REVENUE COMES FROM · taxes the US government kept, by source (US Treasury)" right={d && d.available && <span className={`pill ${d.freshness === "OVERDUE" ? "warn" : ""}`}>{d.freshness === "OVERDUE" ? `OVERDUE · ${monthShort(d.date!)}` : monthShort(d.date!)}</span>}>
      {q.isLoading && <div className="note">Loading…</div>}
      {q.isError && <ErrorBox error={q.error} />}
      {d && <div data-testid="receipts">
        {!d.available ? <div className="note warn">{d.reason}</div> : <>
          <div className="small">Fiscal {d.fiscal_year} so far ({d.months_in_year} {d.months_in_year === 1 ? "month" : "months"} from October): the government kept <b className="mono">{bn(d.total!.year_so_far_billions)}</b>, {move(d.total!.change_vs_last_year_pct)} from {bn(d.total!.same_point_last_year_billions)} at the same point last year. {monthName(d.date!)} alone: <b className="mono">{bn(d.total!.month_billions)}</b>.</div>
          <table className="tbl" style={{ tableLayout: "fixed", width: "100%", marginTop: 6 }}><thead><tr><th style={{ width: "30%" }}>Source</th><th className="r" style={{ width: "13%" }}>{monthShort(d.date!)}</th><th className="r" style={{ width: "14%" }}>Year so far</th><th className="r" style={{ width: "12%" }}>Share of year</th><th className="r" style={{ width: "15%" }}>Same point last year</th><th style={{ width: "16%", paddingLeft: 14 }}>Change</th></tr></thead>
            <tbody>{(d.categories ?? []).map((c) => <tr key={c.name} title={c.what}><td>{c.name}</td><td className="r mono">{bn(c.month_billions)}</td><td className="r mono"><b>{bn(c.year_so_far_billions)}</b></td><td className="r mono">{c.share_of_year_pct == null ? "n/a" : `${c.share_of_year_pct}%`}</td><td className="r mono">{bn(c.same_point_last_year_billions)}</td><td className={`small ${c.change_vs_last_year_pct != null && c.change_vs_last_year_pct < 0 ? "down" : ""}`} style={{ paddingLeft: 14 }}>{move(c.change_vs_last_year_pct)}</td></tr>)}
              <tr><td><b>All receipts</b></td><td className="r mono">{bn(d.total!.month_billions)}</td><td className="r mono"><b>{bn(d.total!.year_so_far_billions)}</b></td><td className="r mono">100%</td><td className="r mono">{bn(d.total!.same_point_last_year_billions)}</td><td className="small" style={{ paddingLeft: 14 }}>{move(d.total!.change_vs_last_year_pct)}</td></tr></tbody></table>
          <div className="small dim">Checked: the seven sources add up to the source's own total for the month, the year so far and last year's same point, and on-budget plus off-budget equals it too.</div>
          <div className="small dim">{d.note}</div></>}
        <div className="small dim">Source: <a href={d.url} target="_blank" rel="noreferrer noopener">{d.source ?? "US Treasury FiscalData"}</a>.</div>
      </div>}
    </Panel>);
}
