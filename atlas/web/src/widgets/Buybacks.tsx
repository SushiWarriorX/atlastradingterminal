import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { ErrorBox, Panel } from "../ui";

const day = (iso?: string) => (iso ? new Date(`${iso}T12:00:00Z`).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" }) : "");
const bn = (x: number | null | undefined) => (x == null ? "no result reported" : `$${x.toLocaleString("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 2 })}B`);
const share = (x: number | null | undefined) => (x == null ? "" : ` (${x.toFixed(1)}% of what was offered)`);

/** US Treasury buyback operations: what dealers offered and what the Treasury bought. Describes what already happened; not a signal. */
export function BuybacksWidget() {
  const q = useQuery({ queryKey: ["buybacks"], queryFn: api.buybacks, staleTime: 6 * 60 * 60_000, refetchInterval: 12 * 60 * 60_000, retry: 0 });
  const d = q.data;
  const w = (name: string, x?: { operations: number; no_result: number; accepted_billions: number; offered_billions: number; bought_share_pct: number | null }) => x && (
    <div>
      <div className="ws-bar" style={{ paddingLeft: 0 }}><span>{name}</span></div>
      <div className="small">Bought <b className="mono">{bn(x.accepted_billions)}</b> in {x.operations} operations{share(x.bought_share_pct)}</div>
      {x.no_result > 0 && <div className="small warn">{x.no_result} operation(s) have no result in the source and are not counted.</div>}
    </div>);
  return (
    <Panel title="TREASURY BUYBACKS · what the US Treasury bought back (Treasury)" right={d && d.available && <span className={`pill ${d.freshness === "OVERDUE" ? "warn" : ""}`}>{d.freshness === "OVERDUE" ? "OVERDUE" : day(d.date)}</span>}>
      {q.isLoading && <div className="note">Loading…</div>}
      {q.isError && <ErrorBox error={q.error} />}
      {d && <div data-testid="buybacks">
        {!d.available ? <div className="note warn">{d.reason}</div> : <>
          <div className="small">Latest operation, <b>{day(d.latest!.date)}</b> ({d.latest!.type.toLowerCase()}, {d.latest!.security.toLowerCase()}, {d.latest!.maturity}): dealers offered <b className="mono">{bn(d.latest!.offered_billions)}</b>, the Treasury bought <b className="mono">{bn(d.latest!.accepted_billions)}</b>{share(d.latest!.bought_share_pct)}.</div>
          <div style={{ display: "flex", gap: 28, flexWrap: "wrap", marginTop: 8 }}>{w("LAST 90 DAYS", d.last_90_days)}{w("LAST 12 MONTHS", d.last_365_days)}</div>
          <table className="tbl" style={{ marginTop: 8 }}><tbody>
            {[...(d.by_type ?? []), ...(d.by_security ?? [])].map((r) => <tr key={r.key}><td>{r.label} (last 12 months)</td><td className="mono" style={{ textAlign: "right" }}>{bn(r.accepted_billions)}</td><td className="mono dim" style={{ textAlign: "right" }}>{r.operations} operations</td></tr>)}
          </tbody></table>
          <div className="ws-bar" style={{ paddingLeft: 0, marginTop: 8 }}><span>RECENT OPERATIONS</span></div>
          <table className="tbl"><tbody>
            {(d.recent ?? []).slice(0, 6).map((r) => <tr key={`${r.date}${r.maturity}${r.security}`}><td>{day(r.date)}</td><td>{r.maturity}</td><td className="dim">{r.type}</td><td className="mono" style={{ textAlign: "right" }}>{bn(r.accepted_billions)} of {bn(r.offered_billions)}</td></tr>)}
          </tbody></table>
          {!!d.anomalies && <div className="small warn">{d.anomalies} operation(s) show more bought than offered or announced; the source may contain an error.</div>}
          <div className="small dim">{d.note}</div></>}
        <div className="small dim">Source: <a href={d.url} target="_blank" rel="noreferrer noopener">{d.source ?? "US Treasury FiscalData"}</a>.</div>
      </div>}
    </Panel>);
}
