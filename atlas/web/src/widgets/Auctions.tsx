import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { ErrorBox, Panel } from "../ui";

const pp = (x: number | null) => (x == null ? "n/a" : `${x > 0 ? "+" : x < 0 ? "-" : ""}${Math.abs(x).toFixed(3)}`);

/** US Treasury note and bond auction results by term (FiscalData). Describes finished auctions; not a signal. */
export function AuctionsWidget() {
  const q = useQuery({ queryKey: ["auctions"], queryFn: api.auctions, staleTime: 60 * 60_000, refetchInterval: 2 * 60 * 60_000, retry: 0 });
  const d = q.data;
  return (
    <Panel title="TREASURY AUCTIONS · latest result for each term (US Treasury)" right={d && d.available && <span className={`pill ${d.freshness === "OVERDUE" ? "warn" : ""}`}>{d.freshness === "OVERDUE" ? "OVERDUE" : `latest ${d.date}`}</span>}>
      {q.isLoading && <div className="note">Loading…</div>}
      {q.isError && <ErrorBox error={q.error} />}
      {d && <div data-testid="auctions">
        {!d.available ? <div className="note warn">{d.reason}</div> : <>
          <table className="tbl" style={{ width: "100%" }}>
            <thead><tr><th>TERM</th><th>AUCTION DATE</th><th>HIGH YIELD %</th><th>VS PREVIOUS (pts)</th><th>BID-TO-COVER</th><th>AVG OF PRIOR {d.tenors?.[0]?.compared_with ?? 4}</th><th>OFFERED</th></tr></thead>
            <tbody>{(d.tenors ?? []).map((t) => (
              <tr key={t.tenor}><td>{t.tenor}{t.reopening ? " (reopening)" : ""}</td><td className="mono">{t.auction_date}</td><td className="mono">{t.high_yield.toFixed(3)}</td><td className="mono">{pp(t.yield_change)}</td>
                <td className="mono">{t.bid_to_cover.toFixed(2)}</td><td className="mono">{t.average_bid_to_cover == null ? "n/a" : t.average_bid_to_cover.toFixed(2)}</td><td className="mono">{t.offering_billions == null ? "n/a" : `$${t.offering_billions}B`}</td></tr>))}</tbody>
          </table>
          {(d.pending_results ?? []).length > 0 && <div className="small dim">Results not yet published by the source: {d.pending_results!.map((p) => `${p.tenor} auction of ${p.auction_date}`).join(", ")}.</div>}
          <div className="small dim">{d.note}</div></>}
        <div className="small dim">Source: <a href={d.url} target="_blank" rel="noreferrer noopener">{d.source ?? "US Treasury FiscalData"}</a>.</div>
      </div>}
    </Panel>);
}
