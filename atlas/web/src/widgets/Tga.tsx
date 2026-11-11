import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { ymdLabel as day } from "../fmt";
import { ErrorBox, Panel } from "../ui";

const b = (x: number) => `$${x.toLocaleString("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 })}B`;
const chg = (x: number) => `${x > 0 ? "+" : x < 0 ? "-" : ""}$${Math.abs(x).toFixed(1)}B`;

/** US Treasury General Account: the government's cash balance at the Fed (Daily Treasury Statement). Describes where cash sits; not a signal. */
export function TgaWidget() {
  const q = useQuery({ queryKey: ["tga"], queryFn: api.tga, staleTime: 30 * 60_000, refetchInterval: 60 * 60_000, retry: 0 });
  const d = q.data;
  const hist = d?.history ?? [];
  const lo = hist.length ? Math.min(...hist.map((h) => h.balance_billions)) : 0;
  const hi = hist.length ? Math.max(...hist.map((h) => h.balance_billions)) : 1;
  return (
    <Panel title="TREASURY CASH BALANCE (TGA) · the government's account at the Fed" right={d && d.available && <span className={`pill ${d.freshness === "OVERDUE" ? "warn" : ""}`}>{d.freshness === "OVERDUE" ? "OVERDUE" : day(d.date)}</span>}>
      {q.isLoading && <div className="note">Loading…</div>}
      {q.isError && <ErrorBox error={q.error} />}
      {d && <div data-testid="tga">
        {!d.available ? <div className="note warn">{d.reason}</div> : <>
          <b className="mono" style={{ fontSize: 22 }}>{b(d.balance_billions!)}</b> <span className="small dim">{chg(d.change_1d_billions!)} on the day{d.change_month_billions != null ? `, ${chg(d.change_month_billions)} over about a month` : ""}</span>
          <div className="small dim">Month average {b(d.month_average_billions!)}. Past year: low {b(d.year_low_billions!)} on {day(d.year_low_date)}, high {b(d.year_high_billions!)} on {day(d.year_high_date)}.</div>
          <div style={{ display: "flex", gap: 1, alignItems: "flex-end", height: 28, margin: "8px 0" }} aria-label="Last 60 business days of the Treasury cash balance">
            {hist.map((h) => <span key={h.date} title={`${day(h.date)}: ${b(h.balance_billions)}`} style={{ flex: 1, height: `${Math.max(((h.balance_billions - lo) / Math.max(hi - lo, 0.001)) * 90, 4)}%`, background: "var(--accent)", opacity: 0.6 }} />)}
          </div>
          <div className="small dim">{d.note}</div></>}
        <div className="small dim">Source: <a href={d.url} target="_blank" rel="noreferrer noopener">{d.source ?? "US Treasury FiscalData"}</a>.</div>
      </div>}
    </Panel>);
}
