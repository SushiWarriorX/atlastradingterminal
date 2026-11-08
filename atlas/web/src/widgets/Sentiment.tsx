import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { ErrorBox, Panel } from "../ui";

const TINT = (v: number) => (v < 25 ? "down" : v < 45 ? "warnc" : v < 55 ? "dim" : "up");

/** Crypto Fear & Greed index from alternative.me: a daily 0-100 mood gauge with its date and source. Not a forecast and not a trading signal. */
export function SentimentWidget() {
  const q = useQuery({ queryKey: ["btc-sentiment"], queryFn: api.btcSentiment, staleTime: 15 * 60_000, refetchInterval: 30 * 60_000, retry: 0 });
  const d = q.data;
  return (
    <Panel title="CRYPTO FEAR & GREED" right={d && d.available && <span className={`pill ${d.freshness === "OVERDUE" ? "warn" : ""}`}>{d.freshness === "OVERDUE" ? "OVERDUE" : d.date}</span>}>
      {q.isLoading && <div className="note">Loading…</div>}
      {q.isError && <ErrorBox error={q.error} />}
      {d && <div data-testid="sentiment">
        {!d.available ? <div className="note warn">{d.reason}</div> : <>
          <div style={{ display: "flex", gap: 14, alignItems: "baseline" }}>
            <span className={`mono ${TINT(d.value!)}`} style={{ fontSize: 30, fontWeight: 700 }}>{d.value}</span>
            <b>{d.label}</b>
            <span className="dim small">out of 100</span>
          </div>
          <div className="small dim">{[["yesterday", d.yesterday], ["a week ago", d.a_week_ago], ["a month ago", d.a_month_ago]].filter(([, v]) => v !== null && v !== undefined).map(([k, v]) => `${k}: ${v}`).join(" · ")}</div>
          <div className="small" style={{ display: "flex", gap: 1, alignItems: "flex-end", height: 26, margin: "6px 0" }} aria-label="Last 31 days">
            {d.history!.map((h) => <span key={h.date} title={`${h.date}: ${h.value}`} style={{ flex: 1, height: `${Math.max(h.value, 3)}%`, background: "var(--accent)", opacity: 0.35 + h.value / 160 }} />)}
          </div></>}
        <div className="small dim">{d.note} Source: <a href={d.url} target="_blank" rel="noreferrer noopener">{d.source}</a>.</div>
      </div>}
    </Panel>);
}
