import React from "react";
import { View } from "react-native";
import type { EuroBankRatesRow } from "../api/types";
import { ymdLabel } from "../lib/format";
import { safeUrl } from "../lib/links";
import { useEuroBankRates } from "../state/queries";
import { space } from "../theme";
import { Banner, Divider, GCard, Skeleton, SourceLink, Txt } from "./ui";

const pct = (x: number) => `${x.toFixed(2)}%`;
const billions = (millions: number) => `€${(millions / 1e3).toLocaleString("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 })} billion`;
const move = (x: number, vs: string) => (x > 0 ? `up ${x.toFixed(2)} points on ${vs}` : x < 0 ? `down ${Math.abs(x).toFixed(2)} points on ${vs}` : `unchanged on ${vs}`);
const gap = (x: number) => `${x > 0 ? "+" : "-"}${+Math.abs(x).toFixed(4)}`;                      // the backend rounds a check's largest gap to four decimals: show them, no more
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

/** Euro-area bank interest rates (what euro-area banks charge on new loans and pay on new deposits, with the ECB's composite cost of borrowing), monthly, from the ECB Data Portal. Describes what already happened; not a signal or a forecast. */
export function EuroBankRatesCard() {
  const q = useEuroBankRates();
  const d = q.data;
  const link = safeUrl(d?.url ?? null);
  const row = (kind: string, r: EuroBankRatesRow, what: string) => (
    <Txt key={r.id} variant="small" testID={`eurobankrates-${kind}-${r.id}`}>
      {cap(r.label)}: {pct(r.rate_pct)} a year, {move(r.change_month_points, "a month earlier")}, {move(r.change_year_points, "a year earlier")}.{r.volume_millions != null ? ` ${what} in the month: ${billions(r.volume_millions)}.` : ""}
    </Txt>
  );
  return (
    <GCard style={{ padding: space.lg, gap: space.md }} testID="eurobankrates-card">
      <View><Txt variant="h2">Euro-area bank interest rates</Txt><Txt variant="tiny">What euro-area banks charge on new loans and pay on new deposits, monthly, from the ECB</Txt></View>
      {q.isLoading ? <Skeleton h={80} />
        : q.isError || !d ? <Banner tone="warn" title="Couldn't load the euro-area bank interest rates" testID="eurobankrates-error">{q.error instanceof Error ? q.error.message : "Something went wrong."}</Banner>
        : !d.available || !d.month || !d.loans || !d.deposits || !d.costs || !d.recent || !d.detail ? <Banner tone={d.demo ? "demo" : "warn"} title={d.demo ? "Demo mode" : "Euro-area bank interest rates unavailable"} testID="eurobankrates-unavailable">{d.reason}</Banner>
        : (
          <View style={{ gap: space.sm }} testID="eurobankrates-body">
            <Txt variant="label">{ymdLabel(d.month)} · monthly · new business · percent a year{d.provisional ? " · provisional" : ""}{d.freshness === "OVERDUE" ? " · overdue" : ""}</Txt>
            <Txt variant="label">What banks charge on new loans</Txt>
            <View style={{ gap: space.sm }} testID="eurobankrates-loans">{d.loans.map((r) => row("loan", r, "New loans"))}</View>
            <Divider />
            <Txt variant="label">The ECB's cost of borrowing</Txt>
            <View style={{ gap: space.sm }} testID="eurobankrates-costs">
              {d.costs.map((r) => (
                <View key={r.id} style={{ gap: space.xs }}>
                  {row("cost", r, "")}
                  {r.window ? <Txt variant="tiny">Over the past 10 years ({r.window.months} months) it ran from {pct(r.window.lowest.pct)} ({ymdLabel(r.window.lowest.month)}) to {pct(r.window.highest.pct)} ({ymdLabel(r.window.highest.month)}); {r.window.share_lower_pct}% of those months were lower than now.</Txt> : null}
                </View>
              ))}
            </View>
            <Divider />
            <Txt variant="label">What banks pay on new deposits</Txt>
            <View style={{ gap: space.sm }} testID="eurobankrates-deposits">{d.deposits.map((r) => row("deposit", r, "New deposits"))}</View>
            <Divider />
            <Txt variant="label">Cost of borrowing by month</Txt>
            <View style={{ gap: space.sm }} testID="eurobankrates-recent">
              {d.recent.map((r) => (
                <Txt key={r.month} variant="small" testID={`eurobankrates-month-${r.month}`}>{ymdLabel(r.month)}: firms {pct(r.firms_cost_pct)}, house purchase {pct(r.house_cost_pct)}</Txt>
              ))}
            </View>
            <Txt variant="tiny">Check: in each of the last {d.detail.months_checked} months every rate and volume lay inside its range, no loan, term-deposit or composite rate moved by more than 2 points in a month and no overnight deposit rate by more than 1 point (plain checks), and each composite lay within one point of the rate on all new loans of the same borrowers. For the six kinds of new business in this card the volume of all of it equalled the volume with a floating rate or up to one year of fixed interest plus the volume fixed for over one year, to 0.016 million euro{d.detail.largest_sum_gap_month ? ` (the largest gap: ${gap(d.detail.largest_sum_gap_millions)} million euro for ${d.detail.largest_sum_gap_series} in ${ymdLabel(d.detail.largest_sum_gap_month)})` : ""}, and in each of the last {d.detail.rate_months_checked} months the rate on all of it equalled the average of the two parts' rates weighted by their volumes, to 0.016 points{d.detail.largest_rate_gap_month ? ` (the largest gap: ${gap(d.detail.largest_rate_gap_points)} points for ${d.detail.largest_rate_gap_series} in ${ymdLabel(d.detail.largest_rate_gap_month)})` : ""}. Those two checks are the ECB's own arithmetic, so they show the series belong together, not that the figures are right. The overnight deposit rates and the composites have no identity of their own to check.</Txt>
            <Txt variant="tiny">{d.note}</Txt>
          </View>)}
      <SourceLink url={link}>Source: European Central Bank (MFI interest rate statistics), via the ECB Data Portal</SourceLink>
    </GCard>
  );
}
