import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { ErrorBox, Panel } from "../ui";

const day = (iso?: string) => (iso ? new Date(`${iso}T12:00:00Z`).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" }) : "");
const termName = (t: string) => t.replace("-Week", " weeks");
const points = (bps: number | null | undefined) => (bps == null ? "no earlier auction to compare" : bps === 0 ? "unchanged" : `${bps > 0 ? "up" : "down"} ${Math.abs(bps / 100).toFixed(2)} points`);

/** US Treasury bill auction results by term. Describes auctions that already happened; not a signal. */
export function BillAuctionsWidget() {
  const q = useQuery({ queryKey: ["bills"], queryFn: api.bills, staleTime: 3 * 60 * 60_000, refetchInterval: 6 * 60 * 60_000, retry: 0 });
  const d = q.data;
  return (
    <Panel title="TREASURY BILL AUCTIONS · what the US pays to borrow for weeks and months (Treasury)" right={d && d.available && <span className={`pill ${d.freshness === "OVERDUE" ? "warn" : ""}`}>{d.freshness === "OVERDUE" ? `OVERDUE · latest ${day(d.date)}` : day(d.date)}</span>}>
      {q.isLoading && <div className="note">Loading…</div>}
      {q.isError && <ErrorBox error={q.error} />}
      {d && <div data-testid="bills">
        {!d.available ? <div className="note warn">{d.reason}</div> : <>
          {d.freshness === "OVERDUE" && <div className="small warn">The source's newest completed bill auction is from {day(d.date)} ({d.age_days} days ago). Newer auctions have not been published there yet.</div>}
          <table className="tbl"><thead><tr><th>Term</th><th>Auction</th><th style={{ textAlign: "right" }}>Rate</th><th>Versus previous</th><th style={{ textAlign: "right" }}>Bid-to-cover (avg)</th><th style={{ textAlign: "right" }}>Accepted</th><th style={{ textAlign: "right" }}>Indirect bidders</th></tr></thead><tbody>
            {(d.terms ?? []).map((t) => <tr key={t.term}>
              <td>{t.term.replace("-Week", "-week")}</td><td className="dim">{day(t.auction_date)}</td>
              <td className="mono" style={{ textAlign: "right" }}>{t.investment_rate.toFixed(3)}%</td><td className="dim">{points(t.rate_change_bps)}</td>
              <td className="mono" style={{ textAlign: "right" }}>{t.bid_to_cover.toFixed(2)}{t.average_bid_to_cover != null ? ` (${t.average_bid_to_cover.toFixed(2)})` : ""}</td>
              <td className="mono" style={{ textAlign: "right" }}>{t.accepted_billions == null ? "" : `$${t.accepted_billions.toFixed(1)}B`}</td>
              <td className="mono" style={{ textAlign: "right" }}>{t.mix ? `${t.mix.indirect_pct.toFixed(1)}%` : ""}</td></tr>)}
          </tbody></table>
          {!!d.pending_results?.length && <div className="small dim">Results not published yet: {d.pending_results.map((p) => `${termName(p.term)} (${day(p.auction_date)})`).join(", ")}.</div>}
          <div className="small dim">{d.note}</div></>}
        <div className="small dim">Source: <a href={d.url} target="_blank" rel="noreferrer noopener">{d.source ?? "US Treasury FiscalData"}</a>.</div>
      </div>}
    </Panel>);
}
