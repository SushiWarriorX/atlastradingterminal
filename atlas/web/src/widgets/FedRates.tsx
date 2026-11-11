import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { ymdLabel as day } from "../fmt";
import { ErrorBox, Panel } from "../ui";

const pct = (x: number) => `${x.toFixed(2)}%`;
const pp = (x: number | null | undefined) => (x == null ? "n/a" : `${x > 0 ? "+" : x < 0 ? "-" : ""}${Math.abs(x).toFixed(2)}`);

/** The Fed's policy rate (EFFR), its target range and the overnight reference rates (New York Fed). Describes where overnight money costs; not a signal. */
export function FedRatesWidget() {
  const q = useQuery({ queryKey: ["fedrates"], queryFn: api.fedRates, staleTime: 15 * 60_000, refetchInterval: 30 * 60_000, retry: 0 });
  const d = q.data;
  const hist = d?.history ?? [];
  const lo = hist.length ? Math.min(...hist.map((h) => h.rate)) : 0;
  const hi = hist.length ? Math.max(...hist.map((h) => h.rate)) : 1;
  return (
    <Panel title="FED INTEREST RATE · policy rate, target range and overnight rates (New York Fed)" right={d && d.available && <span className={`pill ${d.freshness === "OVERDUE" ? "warn" : ""}`}>{d.freshness === "OVERDUE" ? "OVERDUE" : day(d.date)}</span>}>
      {q.isLoading && <div className="note">Loading…</div>}
      {q.isError && <ErrorBox error={q.error} />}
      {d && <div data-testid="fedrates">
        {!d.available ? <div className="note warn">{d.reason}</div> : <>
          <div style={{ display: "flex", gap: 28, flexWrap: "wrap" }}>
            <div>
              <div className="ws-bar" style={{ paddingLeft: 0 }}><span>EFFECTIVE FED FUNDS RATE</span></div>
              <b className="mono" style={{ fontSize: 22 }}>{pct(d.effr!)}</b> <span className="small dim">{pp(d.effr_change_pp)} pts on the day</span>
              <div className="small">Fed target range <b className="mono">{pct(d.target_low!)} to {pct(d.target_high!)}</b>; the rate is {d.effr_position} the range ({d.effr_above_bottom_pp!.toFixed(2)} pts above the bottom).</div>
              {d.last_change ? <div className="small dim">Range last changed on {day(d.last_change.date)} ({d.last_change.days_ago} days ago): {pct(d.last_change.from_range[0])}–{pct(d.last_change.from_range[1])} to {pct(d.last_change.to_range[0])}–{pct(d.last_change.to_range[1])} ({pp(d.last_change.change_pp)} pts).</div>
                : d.history_available ? <div className="small dim">The target range has not changed in the data window.</div> : <div className="small dim">{d.history_reason}</div>}
            </div>
            <table className="tbl">
              <thead><tr><th>OVERNIGHT RATE</th><th>RATE</th><th>DATE</th></tr></thead>
              <tbody>{(d.rates ?? []).map((r) => <tr key={r.code}><td>{r.name}</td><td className="mono">{pct(r.rate)}</td><td className="mono">{day(r.date)}</td></tr>)}</tbody>
            </table>
          </div>
          {hist.length > 0 && <div style={{ display: "flex", gap: 1, alignItems: "flex-end", height: 28, margin: "8px 0" }} aria-label="Effective federal funds rate, last 60 business days">
            {hist.map((h) => <span key={h.date} title={`${day(h.date)}: ${pct(h.rate)}`} style={{ flex: 1, height: `${Math.max(((h.rate - lo) / Math.max(hi - lo, 0.001)) * 90, 6)}%`, background: "var(--accent)", opacity: 0.6 }} />)}
          </div>}
          <div className="small dim">{d.note}</div></>}
        <div className="small dim">Source: <a href={d.url} target="_blank" rel="noreferrer noopener">{d.source ?? "Federal Reserve Bank of New York"}</a>.</div>
      </div>}
    </Panel>);
}
