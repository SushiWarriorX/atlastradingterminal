import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { ErrorBox, Panel } from "../ui";

const bn = (x: number) => `${x < 0 ? "−" : ""}$${Math.abs(x).toLocaleString("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 })}B`;
const move = (x: number | null) => (x == null ? "n/a" : x === 0 ? "unchanged" : `${x > 0 ? "up" : "down"} ${Math.abs(x)}%`);
const monthName = (iso: string) => new Date(`${iso}T12:00:00Z`).toLocaleDateString("en-US", { month: "long", year: "numeric", timeZone: "UTC" });
const monthShort = (iso: string) => new Date(`${iso}T12:00:00Z`).toLocaleDateString("en-US", { month: "short", year: "numeric", timeZone: "UTC" });

/** Where US federal money goes: net outlays by purpose, receipts and the deficit for the latest month and the fiscal year so far versus last year (Monthly Treasury Statement). Describes what already happened; not a signal. */
export function OutlaysWidget() {
  const q = useQuery({ queryKey: ["outlays"], queryFn: api.outlays, staleTime: 6 * 60 * 60_000, refetchInterval: 12 * 60 * 60_000, retry: 0 });
  const d = q.data;
  return (
    <Panel title="WHERE FEDERAL MONEY GOES · what the US government spent, by purpose (US Treasury)" right={d && d.available && <span className={`pill ${d.freshness === "OVERDUE" ? "warn" : ""}`}>{d.freshness === "OVERDUE" ? `OVERDUE · ${monthShort(d.date!)}` : monthShort(d.date!)}</span>}>
      {q.isLoading && <div className="note">Loading…</div>}
      {q.isError && <ErrorBox error={q.error} />}
      {d && <div data-testid="outlays">
        {!d.available ? <div className="note warn">{d.reason}</div> : <>
          <div className="small">Fiscal {d.fiscal_year} so far ({d.months_in_year} {d.months_in_year === 1 ? "month" : "months"} from October): the government spent <b className="mono">{bn(d.outlays!.year_so_far_billions)}</b> ({move(d.outlays!.change_vs_last_year_pct)}) and took in <b className="mono">{bn(d.receipts!.year_so_far_billions)}</b> ({move(d.receipts!.change_vs_last_year_pct)}), so spending ran ahead of income by <b className="mono">{bn(d.deficit!.year_so_far_billions)}</b> ({move(d.deficit!.change_vs_last_year_pct)} from {bn(d.deficit!.same_point_last_year_billions)} at the same point last year). {monthName(d.date!)} alone: spent {bn(d.outlays!.month_billions)}, took in {bn(d.receipts!.month_billions)}.</div>
          <table className="tbl" style={{ tableLayout: "fixed", width: "100%", marginTop: 6 }}><thead><tr><th style={{ width: "30%" }}>Purpose</th><th className="r" style={{ width: "13%" }}>{monthShort(d.date!)}</th><th className="r" style={{ width: "14%" }}>Year so far</th><th className="r" style={{ width: "12%" }}>Share of spending</th><th className="r" style={{ width: "15%" }}>Same point last year</th><th style={{ width: "16%", paddingLeft: 14 }}>Change</th></tr></thead>
            <tbody>{(d.functions ?? []).map((f) => <tr key={f.name} title={f.what}><td>{f.name}</td><td className="r mono">{bn(f.month_billions)}</td><td className="r mono"><b>{bn(f.year_so_far_billions)}</b></td><td className="r mono">{f.share_of_outlays_pct == null ? "n/a" : `${f.share_of_outlays_pct}%`}</td><td className="r mono">{bn(f.same_point_last_year_billions)}</td><td className="small" style={{ paddingLeft: 14 }}>{move(f.change_vs_last_year_pct)}</td></tr>)}
              <tr><td><b>All spending (net outlays)</b></td><td className="r mono">{bn(d.outlays!.month_billions)}</td><td className="r mono"><b>{bn(d.outlays!.year_so_far_billions)}</b></td><td className="r mono">100%</td><td className="r mono">{bn(d.outlays!.same_point_last_year_billions)}</td><td className="small" style={{ paddingLeft: 14 }}>{move(d.outlays!.change_vs_last_year_pct)}</td></tr>
              <tr><td><b>All receipts (income)</b></td><td className="r mono">{bn(d.receipts!.month_billions)}</td><td className="r mono"><b>{bn(d.receipts!.year_so_far_billions)}</b></td><td className="r mono" /><td className="r mono">{bn(d.receipts!.same_point_last_year_billions)}</td><td className="small" style={{ paddingLeft: 14 }}>{move(d.receipts!.change_vs_last_year_pct)}</td></tr>
              <tr><td><b>Gap (spending minus receipts)</b></td><td className="r mono">{bn(d.deficit!.month_billions)}</td><td className="r mono"><b>{bn(d.deficit!.year_so_far_billions)}</b></td><td className="r mono" /><td className="r mono">{bn(d.deficit!.same_point_last_year_billions)}</td><td className="small" style={{ paddingLeft: 14 }}>{move(d.deficit!.change_vs_last_year_pct)}</td></tr></tbody></table>
          <div className="small dim">Checked: the purposes add up to the source's own total spending, and the receipts lines to its total receipts, for the month, the year so far and last year's same point.</div>
          <div className="small dim">{d.note}</div></>}
        <div className="small dim">Source: <a href={d.url} target="_blank" rel="noreferrer noopener">{d.source ?? "US Treasury FiscalData"}</a>.</div>
      </div>}
    </Panel>);
}
