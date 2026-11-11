import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { ymdLabel as day } from "../fmt";
import { ErrorBox, Panel } from "../ui";

const pc = (x: number | null | undefined) => (x == null ? "n/a" : `${x.toFixed(2)}%`);
const moved = (bp: number | null | undefined) => (bp == null ? "not available" : bp === 0 ? "unchanged" : `${bp > 0 ? "up" : "down"} ${(Math.abs(bp) / 100).toFixed(2)} points`);

/** US Treasury real (TIPS) yields and breakeven inflation, 5 to 30 years. Describes what already happened; not a forecast of inflation or prices. */
export function RealYieldsWidget() {
  const q = useQuery({ queryKey: ["realyields"], queryFn: api.realYields, staleTime: 3 * 60 * 60_000, refetchInterval: 6 * 60 * 60_000, retry: 0 });
  const d = q.data;
  const hist = d?.history ?? [];
  const lo = hist.length ? Math.min(...hist.map((h) => h.breakeven_10y_pct)) : 0;
  const hi = hist.length ? Math.max(...hist.map((h) => h.breakeven_10y_pct), 0.001) : 1;
  return (
    <Panel title="REAL YIELDS & BREAKEVEN INFLATION · what bonds pay above inflation (US Treasury)" right={d && d.available && <span className={`pill ${d.freshness === "OVERDUE" ? "warn" : ""}`}>{d.freshness === "OVERDUE" ? `OVERDUE \u00b7 ${day(d.date)}` : `as of ${day(d.date)}`}</span>}>
      {q.isLoading && <div className="note">Loading…</div>}
      {q.isError && <ErrorBox error={q.error} />}
      {d && <div data-testid="realyields">
        {!d.available ? <div className="note warn">{d.reason}</div> : <>
          <table className="tbl" style={{ tableLayout: "fixed", width: "100%" }}><thead><tr><th style={{ width: "12%" }}>Maturity</th><th className="r" style={{ width: "13%" }}>Regular yield</th><th className="r" style={{ width: "13%" }}>Real yield (TIPS)</th><th className="r" style={{ width: "14%" }}>Breakeven inflation</th><th style={{ width: "16%", paddingLeft: 14 }}>Breakeven, a month ago</th><th style={{ width: "16%" }}>Breakeven, a year ago</th><th style={{ width: "16%" }}>Real yield, a year ago</th></tr></thead>
            <tbody>{(d.rows ?? []).map((r) => <tr key={r.tenor}><td>{r.tenor.replace("Y", "-year")}</td><td className="r mono">{pc(r.nominal_pct)}</td><td className="r mono">{pc(r.real_pct)}</td><td className="r mono"><b>{pc(r.breakeven_pct)}</b></td>
              <td className="small" style={{ paddingLeft: 14 }}>{moved(r.breakeven_change_1m_bp)}</td><td className="small">{moved(r.breakeven_change_1y_bp)}</td><td className="small">{moved(r.real_change_1y_bp)}</td></tr>)}</tbody></table>
          <div className="small dim">Compared with {d.month_ago_date ? day(d.month_ago_date) : "a month ago (no day close enough in the data)"} and {d.year_ago_date ? day(d.year_ago_date) : "a year ago (no day close enough in the data)"}.{(d.checks?.maturities_left_out ?? []).length > 0 ? ` Left out because a yield was missing or implausible: ${d.checks!.maturities_left_out.join(", ")}.` : ""}</div>
          {hist.length > 0 && <>
            <div style={{ display: "flex", gap: 1, alignItems: "flex-end", height: 36, margin: "8px 0 2px" }} aria-label={`10-year breakeven inflation, last ${hist.length} days`}>
              {hist.map((h) => <span key={h.date} title={`${day(h.date)}: ${pc(h.breakeven_10y_pct)}`} style={{ flex: 1, height: `${Math.max(((h.breakeven_10y_pct - lo) / Math.max(hi - lo, 0.001)) * 90, 4)}%`, background: "var(--accent)", opacity: 0.6 }} />)}
            </div>
            <div className="small dim" data-testid="realyields-bars-caption" style={{ marginBottom: 8 }}>Bars: 10-year breakeven inflation for each of the last {hist.length} days, oldest on the left. The scale starts at the lowest day ({pc(lo)}) and ends at the highest ({pc(hi)}), so differences look bigger than they are.</div></>}
          <div className="small dim">Checked: both curves are for the same day, and every value is between −3% and 15%.{d.checks?.latest_dates_differ ? " The two curves did not end on the same day; the latest day in both is shown." : ""}</div>
          <div className="small dim">{d.note}</div></>}
        <div className="small dim">Source: <a href={d.url} target="_blank" rel="noreferrer noopener">{d.source ?? "US Treasury"}</a>.</div>
      </div>}
    </Panel>);
}
