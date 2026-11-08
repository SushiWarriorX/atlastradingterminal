import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { useSelectedId } from "../scope";
import { FILING_GROUPS } from "../secfilings";
import { ErrorBox, Panel } from "../ui";

const sym = (id: string) => id.split(":").pop() ?? id;
const DOT: Record<string, string> = { high: "#ff5a66", medium: "#f5a524", low: "#6c7380" };

/** Latest SEC filings (reports, 8-K events, insider trades, big holders, offerings) for the selected stock or for every stock on the watchlist. */
export function SecFilingsWidget() {
  const id = useSelectedId();
  const [scope, setScope] = useState<"stock" | "watchlist">("stock");
  const [group, setGroup] = useState("all");
  const forms = FILING_GROUPS.find((g) => g[0] === group)?.[2] ?? [];
  const symbols = scope === "stock" ? sym(id) : "";
  const q = useQuery({ queryKey: ["sec-filings", symbols, group], queryFn: () => api.secFilings(symbols, forms, 60, 365), staleTime: 10 * 60_000, retry: 0, placeholderData: (p) => p });
  const d = q.data;
  return (
    <Panel title={`SEC FILINGS ${scope === "stock" ? sym(id) : "· watchlist"}`} right={d && <span className={`pill ${d.demo ? "warn" : ""}`}>{d.demo ? "DEMO" : "SEC EDGAR"}</span>}>
      <div className="toolbar" data-testid="filings-controls">
        <span className="savedchip">{(["stock", "watchlist"] as const).map((s) => <button key={s} className={`mini ${scope === s ? "on" : ""}`} onClick={() => setScope(s)} data-testid={`filings-scope-${s}`}>{s === "stock" ? "This stock" : "My watchlist"}</button>)}</span>
        <span className="savedchip">{FILING_GROUPS.map(([k, label]) => <button key={k} className={`mini ${group === k ? "on" : ""}`} onClick={() => setGroup(k)} data-testid={`filings-group-${k}`}>{label}</button>)}</span>
      </div>
      {q.isLoading && <div className="note">Loading filings from the SEC…</div>}
      {q.isError && <ErrorBox error={q.error} />}
      {d && <div data-testid="sec-filings">
        {d.errors.map((e, i) => <div key={i} className="note warn">{e}</div>)}
        {!d.errors.length && d.items.length === 0 && <div className="note">No filings of this kind in the last year.</div>}
        <table className="tbl"><tbody>
          {d.items.map((f, i) => (
            <tr key={`${f.symbol}-${f.link}-${i}`} data-testid="filing-row">
              <td title={`${f.importance} importance`} style={{ color: DOT[f.importance], width: 14 }}>●</td>
              <td className="mono small">{f.filed}</td>
              <td><b>{f.symbol}</b></td>
              <td className="mono"><span className="pill">{f.form}</span></td>
              <td className="small">{f.meaning}{f.items.length > 0 && <span className="dim"> · {f.items.map((x) => x.meaning).join("; ")}</span>}</td>
              <td className="small">{f.link ? <a href={f.link} target="_blank" rel="noreferrer noopener">open on sec.gov</a> : <span className="dim">no link</span>}</td>
            </tr>))}
        </tbody></table>
        <div className="small dim">{d.note} ● red = high, amber = medium, grey = low. Source: {d.source}</div>
      </div>}
    </Panel>);
}
