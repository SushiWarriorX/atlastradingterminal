import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { ErrorBox, Panel } from "../ui";

const bp = (x: number | null | undefined) => (x === null || x === undefined ? "n/a" : `${x > 0 ? "+" : ""}${x} bp`);
const cls = (x: number | null | undefined) => (x === null || x === undefined ? "dim" : x > 0 ? "up" : x < 0 ? "down" : "");

/** The full US Treasury yield curve (1 month to 30 years) with the usual inversion checks, plus total public debt. Official data, dated. */
export function TreasuryWidget() {
  const q = useQuery({ queryKey: ["treasury"], queryFn: api.treasury, staleTime: 30 * 60_000, refetchInterval: 60 * 60_000, retry: 0 });
  const d = q.data;
  const c = d?.curve, debt = d?.debt;
  return (
    <Panel title="US TREASURY · yield curve and debt" right={c?.available && <span className={`pill ${c.freshness === "OVERDUE" ? "warn" : ""}`}>{c.freshness === "OVERDUE" ? "OVERDUE" : c.date}</span>}>
      {q.isLoading && <div className="note">Loading…</div>}
      {q.isError && <ErrorBox error={q.error} />}
      {d && <div data-testid="treasury">
        {!c!.available ? <div className="note warn">{c!.reason}</div> : <>
          <table className="tbl"><thead><tr><th>Maturity</th>{c!.points!.map((p) => <th key={p.tenor} className="r">{p.tenor}</th>)}</tr></thead><tbody>
            <tr><td>Yield %</td>{c!.points!.map((p) => <td key={p.tenor} className="r mono">{p.rate === null ? "n/a" : p.rate.toFixed(2)}</td>)}</tr>
            <tr><td className="dim">vs previous day</td>{c!.points!.map((p) => <td key={p.tenor} className={`r mono ${cls(p.change_1d_bp)}`}>{bp(p.change_1d_bp)}</td>)}</tr>
            <tr><td className="dim">vs about a month ago</td>{c!.points!.map((p) => <td key={p.tenor} className={`r mono ${cls(p.change_1m_bp)}`}>{bp(p.change_1m_bp)}</td>)}</tr>
          </tbody></table>
          <div className="small" data-testid="treasury-spreads">2s10s (10Y minus 2Y): <b className={`mono ${cls(c!.spreads!["2s10s_bp"])}`}>{bp(c!.spreads!["2s10s_bp"])}</b>{c!.spreads!["2s10s_inverted"] ? " · inverted" : ""} · 3m10y (10Y minus 3M): <b className={`mono ${cls(c!.spreads!["3m10y_bp"])}`}>{bp(c!.spreads!["3m10y_bp"])}</b>{c!.spreads!["3m10y_inverted"] ? " · inverted" : ""}</div>
          <div className="small dim">{c!.note} Source: {c!.source}.</div></>}
        <div className="ws-bar" style={{ paddingLeft: 0 }}><span>TOTAL PUBLIC DEBT</span></div>
        {!debt!.available ? <div className="note warn">{debt!.reason}</div> : <>
          <div className="small"><b className="mono" style={{ fontSize: 18 }}>${debt!.total_trillions!.toFixed(2)}T</b> <span className="dim">on {debt!.date}{debt!.freshness === "OVERDUE" ? " · overdue" : ""}</span>
            {debt!.change_vs_previous_day_billions != null && <> · {debt!.change_vs_previous_day_billions >= 0 ? "+" : ""}${debt!.change_vs_previous_day_billions.toFixed(1)}B vs the previous day</>}
            {debt!.change_vs_a_year_ago_pct != null && <> · {debt!.change_vs_a_year_ago_pct >= 0 ? "+" : ""}{debt!.change_vs_a_year_ago_pct.toFixed(1)}% vs a year ago</>}</div>
          <div className="small dim">Held by the public ${debt!.held_by_public_trillions!.toFixed(2)}T · intragovernmental ${debt!.intragovernmental_trillions!.toFixed(2)}T. {debt!.note} Source: {debt!.source}.</div></>}
      </div>}
    </Panel>);
}
