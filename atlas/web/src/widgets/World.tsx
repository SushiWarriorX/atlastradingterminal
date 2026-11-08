import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { ErrorBox, Panel } from "../ui";

const chg = (x: number | null | undefined) => (x === null || x === undefined ? "n/a" : `${x > 0 ? "+" : ""}${x.toFixed(1)}`);

/** Yearly growth, inflation and unemployment for the US and five other large economies (World Bank). Context only: annual figures arrive months late and are revised. */
export function WorldWidget() {
  const q = useQuery({ queryKey: ["world-bank"], queryFn: api.worldBank, staleTime: 6 * 60 * 60_000, refetchInterval: 12 * 60 * 60_000, retry: 0 });
  const d = q.data;
  return (
    <Panel title="WORLD ECONOMIES · yearly growth, inflation, unemployment (World Bank)" right={d && <span className="pill">{d.demo ? "DEMO" : "annual data"}</span>}>
      {q.isLoading && <div className="note">Loading…</div>}
      {q.isError && <ErrorBox error={q.error} />}
      {d && <div data-testid="world">
        {!d.available && <div className="note warn">{d.reason}</div>}
        <div style={{ display: "flex", gap: 24, flexWrap: "wrap" }}>
          {d.indicators.map((ind) => (
            <div key={ind.key} style={{ flex: 1, minWidth: 260 }}>
              <div className="ws-bar" style={{ paddingLeft: 0 }}><span>{ind.title.toUpperCase()}</span><span className="dim small">{ind.unit}</span></div>
              {!ind.available ? <div className="note warn">{ind.reason}</div> : (
                <table className="tbl"><thead><tr><th>Economy</th><th className="r">Latest</th><th className="r">Year</th><th className="r">vs year before</th></tr></thead><tbody>
                  {ind.rows.map((r) => r.available ? <tr key={r.iso}><td>{r.country}</td><td className="r mono">{r.value!.toFixed(1)}</td><td className="r mono dim">{r.year}</td><td className="r mono">{chg(r.change)}</td></tr>
                    : <tr key={r.iso}><td>{r.country}</td><td colSpan={3} className="dim small">no data</td></tr>)}
                </tbody></table>)}
              <div className="small dim">{ind.what}</div>
            </div>))}
        </div>
        <div className="small dim">{d.note} Source: <a href={d.url} target="_blank" rel="noreferrer noopener">{d.source}</a>.</div>
      </div>}
    </Panel>);
}
