import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { ErrorBox, Panel } from "../ui";

const day = (iso?: string | null) => (iso ? new Date(`${iso}T12:00:00Z`).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" }) : "");
const plain = (x: number) => `$${x.toLocaleString("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 })}B`;
const move = (x: number | null | undefined) => (x == null ? "No change shown (a week is missing in the source)" : x === 0 ? "Unchanged from the week before" : `${x > 0 ? "Up" : "Down"} ${plain(Math.abs(x))} from the week before`);

/** Primary dealers' net position in US Treasuries (New York Fed), weekly. Describes what already happened; not a signal. */
export function DealersWidget() {
  const q = useQuery({ queryKey: ["dealers"], queryFn: api.dealers, staleTime: 6 * 60 * 60_000, refetchInterval: 12 * 60 * 60_000, retry: 0 });
  const d = q.data;
  const hist = d?.history ?? [];
  const lo = hist.length ? Math.min(...hist.map((h) => h.net_billions)) : 0;
  const hi = hist.length ? Math.max(...hist.map((h) => h.net_billions), 0.001) : 1;
  return (
    <Panel title="DEALER TREASURY POSITIONS · what the big Treasury dealers hold (New York Fed)" right={d && d.available && <span className={`pill ${d.freshness === "OVERDUE" ? "warn" : ""}`}>{d.freshness === "OVERDUE" ? `OVERDUE · ${day(d.date)}` : `as of ${day(d.date)}`}</span>}>
      {q.isLoading && <div className="note">Loading…</div>}
      {q.isError && <ErrorBox error={q.error} />}
      {d && <div data-testid="dealers">
        {!d.available ? <div className="note warn">{d.reason}</div> : <>
          <div style={{ display: "flex", gap: 28, flexWrap: "wrap" }}>
            <div>
              <div className="ws-bar" style={{ paddingLeft: 0 }}><span>NET POSITION IN US TREASURIES (as of {day(d.date)})</span></div>
              <div className="small"><b className="mono">{plain(d.net_position_billions!)}</b> · {move(d.week_change_billions)}</div>
              <div className="small dim">Same week a year earlier ({day(d.year_ago_date)}): {d.year_ago_billions != null ? plain(d.year_ago_billions) : "not available"}</div>
            </div>
            {d.range_52w && <div>
              <div className="ws-bar" style={{ paddingLeft: 0 }}><span>LAST {d.range_52w.weeks} WEEKS</span></div>
              <div className="small">Low <b className="mono">{plain(d.range_52w.low_billions)}</b> ({day(d.range_52w.low_date)}) · high <b className="mono">{plain(d.range_52w.high_billions)}</b> ({day(d.range_52w.high_date)})</div>
              <div className="small dim">Higher than {d.range_52w.weeks_lower_than_now} of those {d.range_52w.weeks} weeks</div>
            </div>}
          </div>
          <div style={{ display: "flex", gap: 1, alignItems: "flex-end", height: 36, margin: "8px 0 2px" }} aria-label={`Weekly net position, last ${hist.length} weeks`}>
            {hist.map((h) => <span key={h.date} title={`${day(h.date)}: ${plain(h.net_billions)}`} style={{ flex: 1, height: `${Math.max(((h.net_billions - lo) / Math.max(hi - lo, 0.001)) * 90, 4)}%`, background: "var(--accent)", opacity: 0.6 }} />)}
          </div>
          {hist.length > 0 && <div className="small dim" data-testid="dealers-bars-caption" style={{ marginBottom: 8 }}>Bars: one per week for the last {hist.length} weeks, oldest on the left. The scale starts at the lowest week ({plain(lo)}) and ends at the highest ({plain(hi)}), so differences look bigger than they are.</div>}
          {d.check && <div className="small dim">{d.check.match ? "Checked: the" : "DOES NOT MATCH: the"} week-to-week changes{d.check.match ? " equal" : " differ from"} the source's own change figures for the last {d.check.weeks} weeks.</div>}
          <div className="small dim">{d.note}</div></>}
        <div className="small dim">Source: <a href={d.url} target="_blank" rel="noreferrer noopener">{d.source ?? "Federal Reserve Bank of New York"}</a>.</div>
      </div>}
    </Panel>);
}
