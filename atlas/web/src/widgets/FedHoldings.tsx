import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { ErrorBox, Panel } from "../ui";

const money = (b: number) => (Math.abs(b) >= 1000 ? `$${(b / 1000).toFixed(2)}T` : `$${b.toFixed(1)}B`);
const chg = (b: number | null) => (b == null ? "n/a" : `${b > 0 ? "+" : b < 0 ? "-" : ""}${money(Math.abs(b))}`);

/** What the Federal Reserve holds (SOMA, weekly, New York Fed). Describes the Fed's own portfolio; not a signal. */
export function FedHoldingsWidget() {
  const q = useQuery({ queryKey: ["fedholdings"], queryFn: api.fedHoldings, staleTime: 6 * 60 * 60_000, refetchInterval: 12 * 60 * 60_000, retry: 0 });
  const d = q.data;
  const hist = d?.history ?? [];
  const lo = hist.length ? Math.min(...hist.map((h) => h.total_billions)) : 0;
  const hi = hist.length ? Math.max(...hist.map((h) => h.total_billions)) : 1;
  return (
    <Panel title="WHAT THE FED HOLDS · Treasuries and mortgage bonds on its books (New York Fed, weekly)" right={d && d.available && <span className={`pill ${d.freshness === "OVERDUE" ? "warn" : ""}`}>{d.freshness === "OVERDUE" ? "OVERDUE" : d.date}</span>}>
      {q.isLoading && <div className="note">Loading…</div>}
      {q.isError && <ErrorBox error={q.error} />}
      {d && <div data-testid="fedholdings">
        {!d.available ? <div className="note warn">{d.reason}</div> : <>
          <div style={{ display: "flex", gap: 28, flexWrap: "wrap" }}>
            <div>
              <div className="ws-bar" style={{ paddingLeft: 0 }}><span>TOTAL HOLDINGS</span></div>
              <b className="mono" style={{ fontSize: 22 }}>{money(d.total_billions!)}</b>
              <div className="small dim">Peak {money(d.peak_billions!)} on {d.peak_date}; now {chg(d.from_peak_billions!)} ({d.from_peak_pct}%) from the peak.</div>
              <div className="small">{(d.changes ?? []).map((c) => `${c.period}: ${chg(c.change_billions)}`).join(" · ")}</div>
            </div>
            <table className="tbl">
              <thead><tr><th>WHAT IT HOLDS</th><th>AMOUNT</th><th>SHARE</th></tr></thead>
              <tbody>{(d.mix ?? []).map((m) => <tr key={m.name}><td>{m.name}</td><td className="mono">{money(m.billions)}</td><td className="mono">{m.share_pct.toFixed(1)}%</td></tr>)}</tbody>
            </table>
          </div>
          <div style={{ display: "flex", gap: 1, alignItems: "flex-end", height: 32, margin: "8px 0" }} aria-label="Weekly total holdings, last two years">
            {hist.map((h) => <span key={h.date} title={`${h.date}: ${money(h.total_billions)}`} style={{ flex: 1, height: `${Math.max(((h.total_billions - lo) / Math.max(hi - lo, 0.001)) * 90, 5)}%`, background: "var(--accent)", opacity: 0.6 }} />)}
          </div>
          <div className="small dim">Bars: the last two years, weekly. {d.note}</div></>}
        <div className="small dim">Source: <a href={d.url} target="_blank" rel="noreferrer noopener">{d.source ?? "Federal Reserve Bank of New York"}</a>.</div>
      </div>}
    </Panel>);
}
