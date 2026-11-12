import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { ymdLabel as day } from "../fmt";
import type { FuturesPositioningData } from "../whatif";
import { ErrorBox, Panel } from "../ui";

const n = (x: number) => `${x < 0 ? "\u2212" : ""}${Math.abs(x).toLocaleString("en-US")}`;
const moved = (x: number | null) => (x == null ? "no change shown" : x === 0 ? "unchanged" : `${x > 0 ? "up" : "down"} ${Math.abs(x).toLocaleString("en-US")}`);
const rankText = (r: number | null) => (r == null ? "not enough history" : `at or above ${r}% of the last 52 weeks`);

/** Who holds S&P 500, Nasdaq-100, 2-year and 10-year Treasury and dollar index futures (CFTC Commitments of Traders), weekly. Checked against the report's own totals; describes what already happened, not a signal. */
export function FuturesPositioningWidget() {
  return <PositioningPanel id="futurespos" title="FUTURES POSITIONING · who holds stock, Treasury and dollar futures (CFTC)" fetcher={api.futuresPositioning} />;
}

/** Same layout for gold, crude oil, copper and natural gas (CFTC Disaggregated report). */
export function CommodityPositioningWidget() {
  return <PositioningPanel id="commoditypos" title="COMMODITY POSITIONING · who holds gold, oil, copper and natural gas futures (CFTC)" fetcher={api.commodityPositioning} />;
}

/** Same layout for euro, yen, pound and VIX futures (CFTC Traders in Financial Futures). */
export function CurrencyPositioningWidget() {
  return <PositioningPanel id="currencypos" title="CURRENCY & VOLATILITY POSITIONING · who holds euro, yen, pound and VIX futures (CFTC)" fetcher={api.currencyPositioning} />;
}

/** Same layout for silver, corn, soybean, wheat, coffee and sugar futures (CFTC Disaggregated report). */
export function AgriPositioningWidget() {
  return <PositioningPanel id="agripos" title="SILVER & FARM POSITIONING · who holds silver, corn, soybean, wheat, coffee and sugar futures (CFTC)" fetcher={api.agriPositioning} />;
}

function PositioningPanel({ id, title, fetcher }: { id: string; title: string; fetcher: () => Promise<FuturesPositioningData> }) {
  const q = useQuery({ queryKey: [id], queryFn: fetcher, staleTime: 6 * 60 * 60_000, refetchInterval: 12 * 60 * 60_000, retry: 0 });
  const d = q.data;
  return (
    <Panel title={title} right={d && d.available && <span className={`pill ${d.freshness === "OVERDUE" ? "warn" : ""}`}>{d.freshness === "OVERDUE" ? `OVERDUE \u00b7 ${day(d.date)}` : `as of ${day(d.date)}`}</span>}>
      {q.isLoading && <div className="note">Loading…</div>}
      {q.isError && <ErrorBox error={q.error} />}
      {d && <div data-testid={id}>
        {!d.available ? <div className="note warn">{d.reason}</div> : <>
          {(d.contracts ?? []).map((c) => <div key={c.code} style={{ marginBottom: 10 }}>
            <div className="ws-bar" style={{ paddingLeft: 0 }}><span>{c.name.toUpperCase()}{c.available ? ` \u00b7 as of ${day(c.date)}` : ""}</span></div>
            {!c.available ? <div className="small warn">{c.reason}</div> : <>
              <div className="small dim">{c.what}. Open contracts: <b className="mono">{c.open_interest!.toLocaleString("en-US")}</b> ({moved(c.open_interest_change ?? null)} from the week before).</div>
              <table className="tbl" style={{ tableLayout: "fixed", width: "100%" }}><thead><tr><th style={{ width: "18%" }}>Group</th><th className="r" style={{ width: "13%" }}>Long</th><th className="r" style={{ width: "13%" }}>Short</th><th className="r" style={{ width: "13%" }}>Net</th><th style={{ width: "21%", paddingLeft: 14 }}>Net from the week before</th><th style={{ width: "22%" }}>Where net sits</th></tr></thead>
                <tbody>{(c.groups ?? []).map((g) => <tr key={g.key} title={g.who}><td>{g.name}</td><td className="r mono">{n(g.long)}</td><td className="r mono">{n(g.short)}</td><td className="r mono"><b>{n(g.net)}</b></td><td className="small" style={{ paddingLeft: 14 }}>{moved(g.net_change)}</td><td className="small dim">{rankText(g.net_rank_1y)}</td></tr>)}</tbody></table>
              <div className="small dim">Checked: the groups add up to the report's own totals for the last {c.checks?.weeks_checked} weeks, and the reported change in open contracts equals the difference between weeks.</div></>}
          </div>)}
          <div className="small dim">{d.note}</div></>}
        <div className="small dim">Source: <a href={d.url} target="_blank" rel="noreferrer noopener">{d.source ?? "CFTC Commitments of Traders"}</a>.</div>
      </div>}
    </Panel>);
}
