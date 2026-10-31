import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, FundRow } from "../api";
import { ago } from "../fmt";
import { useStore } from "../store";
import { Badge, ErrorBox, Panel } from "../ui";

function show(r: FundRow): string {
  const v = r.value;
  if (v === null) return "—";
  if (r.unit === "$" || r.unit === "") return Math.abs(v) >= 1e9 ? `${r.unit === "$" ? "$" : ""}${(v / 1e9).toFixed(2)}B` : Math.abs(v) >= 1e6 ? `${r.unit === "$" ? "$" : ""}${(v / 1e6).toFixed(1)}M` : v.toLocaleString("en-US", { maximumFractionDigits: 2 });
  if (r.unit === "%") return `${v.toFixed(1)}%`;
  if (r.unit === "x") return `${v.toFixed(2)}x`;
  return `${v.toFixed(2)} ${r.unit}`;
}

export function FundamentalsWidget() {
  const qc = useQueryClient();
  const id = useStore((s) => s.selected);
  const q = useQuery({ queryKey: ["fundamentals", id], queryFn: () => api.fundamentals(id), retry: 0, staleTime: 60_000 });
  const d = q.data;
  return (
    <Panel title={`FUNDAMENTALS ${d?.symbol ?? ""}`} right={d && <span className="dim"><Badge status={d.prov.status} /> {d.prov.provider} · {d.prov.origin === "cache" ? "cached " : ""}{ago(d.prov.fetched_at)}</span>} className="fa">
      {q.isError && <ErrorBox error={q.error} />}
      {q.isLoading && <div className="note">Loading company data…</div>}
      {d && (
        <>
          <div className="toolbar">
            <b>{d.name ?? d.symbol}</b><span className="dim small">{[d.sector, d.industry].filter(Boolean).join(" · ")}</span>
            {d.next_earnings_date && <span className="small" title="From the provider's calendar: may be an estimate">next earnings {d.next_earnings_date}</span>}
            <button className="mini spacer" onClick={() => { api.fundamentals(id, true).then((x) => qc.setQueryData(["fundamentals", id], x)).catch(() => undefined); }}>refresh</button>
          </div>
          {d.flags.map((f) => <div key={f} className="note warn">⚠ {f}</div>)}
          {d.prov.status === "DEMO" && <div className="note warn">⚠ Synthetic demo data: these are not real company figures.</div>}
          {d.prov.quality.filter((x) => !x.startsWith("synthetic")).map((x) => <div key={x} className="note">{x}</div>)}
          <div className="fa-grid">
            {d.groups.map((g) => (
              <div key={g.name} className="fa-group">
                <b className="small">{g.name}</b>
                <table className="tbl"><tbody>
                  {g.rows.map((r) => (
                    <tr key={r.key} title={`${r.basis}${r.note ? ` · ${r.note}` : ""}`}>
                      <td>{r.label}</td>
                      <td className="r mono">{r.value === null ? <span className="dim" title={r.note ?? "the provider did not supply the inputs"}>{r.note && r.note !== "input missing" ? "n/m" : "—"}</span> : show(r)}</td>
                    </tr>))}
                </tbody></table>
              </div>))}
          </div>
          <div className="note">
            Ratios are computed here from raw figures (hover a row for its basis). "n/m" = not meaningful (e.g. negative earnings); "—" = the provider did not supply the inputs{d.missing.length ? ` (${d.missing.length} fields)` : ""}.
            {d.financials_as_of && ` Latest reported quarter ended ${d.financials_as_of}.`} Company data is unofficial and lags filings.
          </div>
        </>)}
    </Panel>
  );
}
