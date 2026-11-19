import React from "react";
import { View } from "react-native";
import { ymdLabel } from "../lib/format";
import { safeUrl } from "../lib/links";
import { useEcbRates } from "../state/queries";
import { space } from "../theme";
import { Banner, Divider, GCard, Skeleton, SourceLink, Txt } from "./ui";

const pct = (x: number, digits = 2) => `${x.toFixed(digits)}%`;
const points = (x: number, digits = 2) => `${Math.abs(x).toFixed(digits)} points`;
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
const moved = (c: number) => `${c > 0 ? "up" : "down"} ${points(c)}`;
const sinceYear = (change: number | null | undefined, ago: number | null | undefined) =>
  change == null || ago == null ? "A year ago is not available." : change === 0 ? `The same as a year ago (${pct(ago)}).` : `${cap(moved(change))} on a year ago (${pct(ago)}).`;
const side = (g: number) => (g === 0 ? "level with" : `${points(g, 3)} ${g < 0 ? "under" : "over"}`);
const between = (low: number, high: number) =>
  high < 0 ? `between ${points(high, 3)} and ${points(low, 3)} under` : low > 0 ? `between ${points(low, 3)} and ${points(high, 3)} over` : `from ${points(low, 3)} ${low < 0 ? "under" : "level with"} to ${points(high, 3)} ${high > 0 ? "over" : "level with"}`;

/** The European Central Bank's three key interest rates and the euro short-term rate beside them (ECB Data Portal). Describes what the rates are and were; not a signal or a forecast. */
export function EcbRatesCard() {
  const q = useEcbRates();
  const d = q.data;
  const link = safeUrl(d?.url ?? null);
  return (
    <GCard style={{ padding: space.lg, gap: space.md }} testID="ecbrates-card">
      <View><Txt variant="h2">ECB interest rates</Txt><Txt variant="tiny">The European Central Bank's three official rates for euro-area banks, and the euro overnight market rate beside them</Txt></View>
      {q.isLoading ? <Skeleton h={80} />
        : q.isError || !d ? <Banner tone="warn" title="Couldn't load the ECB rates" testID="ecbrates-error">{q.error instanceof Error ? q.error.message : "Something went wrong."}</Banner>
        : !d.available || !d.rates || !d.market ? <Banner tone={d.demo ? "demo" : "warn"} title={d.demo ? "Demo mode" : "ECB rates unavailable"} testID="ecbrates-unavailable">{d.reason}</Banner>
        : (
          <View style={{ gap: space.sm }} testID="ecbrates-body">
            <Txt variant="label">In force on {ymdLabel(d.date)}{d.freshness === "OVERDUE" ? " · overdue" : ""}</Txt>
            {d.rates.map((r, n) => (
              <View key={r.id} style={{ gap: 2 }}>
                {n > 0 ? <Divider /> : null}
                <Txt variant="label">{r.name}</Txt>
                <Txt variant={n === 0 ? "hero" : "h2"}>{pct(r.rate)}</Txt>
                <Txt variant="small">{cap(r.meaning)}{r.above_deposit_rate != null ? `; ${points(r.above_deposit_rate)} above the deposit rate` : ""}.</Txt>
                <Txt variant="tiny">{r.last_change ? `Last changed on ${ymdLabel(r.last_change.date)}: ${moved(r.last_change.change)}, from ${pct(r.last_change.from)}.` : "No change in the four years of data read."} {sinceYear(r.change_1y, r.year_ago)}</Txt>
              </View>))}
            <Divider />
            <Txt variant="label">Recent changes to the deposit rate</Txt>
            {(d.decisions ?? []).length === 0 ? <Txt variant="small">No change in the four years of data read.</Txt>
              : (d.decisions ?? []).map((c) => <Txt key={c.date} variant="small">{ymdLabel(c.date)}: {moved(c.change)}, from {pct(c.from)} to {pct(c.to)}</Txt>)}
            <Divider />
            <Txt variant="small">Market check: the euro short-term rate (€STR), the average rate financial institutions paid to borrow overnight without collateral, was {pct(d.market.rate, 3)} on {ymdLabel(d.market.date)}{d.market.freshness === "OVERDUE" ? " (overdue)" : ""}, {side(d.market.gap)} the deposit rate ({pct(d.market.deposit_rate)}).</Txt>
            <Txt variant="tiny">On each of its last {d.market.observations} business days ({ymdLabel(d.market.first_date)} to {ymdLabel(d.market.date)}) it was {between(d.market.gap_low, d.market.gap_high)} the deposit rate.</Txt>
            <Txt variant="tiny">{d.note}</Txt>
          </View>)}
      <SourceLink url={link}>Source: European Central Bank</SourceLink>
    </GCard>
  );
}
