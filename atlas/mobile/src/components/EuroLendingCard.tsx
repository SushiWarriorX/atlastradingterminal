import React from "react";
import { View } from "react-native";
import type { EuroLendingPart } from "../api/types";
import { ymdLabel } from "../lib/format";
import { safeUrl } from "../lib/links";
import { useEuroLending } from "../state/queries";
import { space } from "../theme";
import { Banner, Divider, GCard, Skeleton, SourceLink, Txt } from "./ui";

const trillions = (millions: number) => `€${(millions / 1e6).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} trillion`;
const billions = (millions: number) => `€${(Math.abs(millions) / 1e3).toLocaleString("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 })} billion`;
const grew = (x: number) => (x > 0 ? `grew ${x.toFixed(2)}%` : x < 0 ? `shrank ${Math.abs(x).toFixed(2)}%` : "was unchanged");
const signed = (x: number) => `${x > 0 ? "+" : x < 0 ? "-" : ""}${Math.abs(x).toFixed(2)}%`;
const signed1 = (x: number) => `${x > 0 ? "+" : x < 0 ? "-" : ""}${Math.abs(x).toFixed(1)}%`;          // the ten-year extremes are rounded to one decimal by the backend: show no more digits than there are
const rate = (x: number) => (x === 0 ? "not growing" : `${x > 0 ? "growing" : "shrinking"} ${Math.abs(x).toFixed(2)}% a year`);
const net = (millions: number) => (millions >= 0 ? `net new lending of ${billions(millions)}` : `net repayments of ${billions(millions)}`);
const points = (x: number) => `${x < 0 ? "-" : "+"}${Math.abs(x).toFixed(2)} points`;
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
const yearBefore = (month: string) => `${+month.slice(0, 4) - 1}${month.slice(4)}`;                    // 2026-09 is the month of a year earlier: 2025-09

/** Euro-area bank lending (the ECB's loans of euro-area banks to firms and households, adjusted for loan sales and securitisation), monthly, from the ECB Data Portal. Describes what already happened; not a signal or a forecast. */
export function EuroLendingCard() {
  const q = useEuroLending();
  const d = q.data;
  const link = safeUrl(d?.url ?? null);
  const part = (kind: "firms" | "households", p: EuroLendingPart, of: string) => (
    <Txt key={p.id} variant="small" testID={`eurolending-${kind}-${p.id}`}>{cap(p.label)}: {trillions(p.amount_millions)}, {(p.share_pct ?? 0).toFixed(1)}% of {of}, {rate(p.growth_pct)}.</Txt>
  );
  return (
    <GCard style={{ padding: space.lg, gap: space.md }} testID="eurolending-card">
      <View><Txt variant="h2">Euro-area bank lending</Txt><Txt variant="tiny">Loans of euro-area banks to firms and households, monthly, from the ECB</Txt></View>
      {q.isLoading ? <Skeleton h={80} />
        : q.isError || !d ? <Banner tone="warn" title="Couldn't load the euro-area bank lending" testID="eurolending-error">{q.error instanceof Error ? q.error.message : "Something went wrong."}</Banner>
        : !d.available || !d.month || !d.firms || !d.households || !d.recent || !d.detail ? <Banner tone={d.demo ? "demo" : "warn"} title={d.demo ? "Demo mode" : "Euro-area bank lending unavailable"} testID="eurolending-unavailable">{d.reason}</Banner>
        : (
          <View style={{ gap: space.sm }} testID="eurolending-body">
            <Txt variant="label">{ymdLabel(d.month)} · monthly · seasonally adjusted · adjusted for loan sales and securitisation{d.provisional ? " · provisional" : ""}{d.freshness === "OVERDUE" ? " · overdue" : ""}</Txt>
            <Txt variant="small">Loans of euro-area banks to firms {grew(d.firms.growth_pct)} over the twelve months to {ymdLabel(d.month)}, against {signed(d.firms.growth_year_earlier_pct)} over the twelve months to {ymdLabel(yearBefore(d.month))}; loans to households {grew(d.households.growth_pct)}, against {signed(d.households.growth_year_earlier_pct)}.</Txt>
            {d.firms.window ? <Txt variant="tiny">Loans to firms: over the past 10 years ({d.firms.window.months} months) the annual growth ran from {signed1(d.firms.window.lowest.pct)} ({ymdLabel(d.firms.window.lowest.month)}) to {signed1(d.firms.window.highest.pct)} ({ymdLabel(d.firms.window.highest.month)}); {d.firms.window.share_lower_pct}% of those months were slower than now.</Txt> : null}
            {d.households.window ? <Txt variant="tiny">Loans to households: over the past 10 years ({d.households.window.months} months) the annual growth ran from {signed1(d.households.window.lowest.pct)} ({ymdLabel(d.households.window.lowest.month)}) to {signed1(d.households.window.highest.pct)} ({ymdLabel(d.households.window.highest.month)}); {d.households.window.share_lower_pct}% of those months were slower than now.</Txt> : null}
            <Divider />
            <Txt variant="small">At the end of {ymdLabel(d.month)} euro-area banks had lent {trillions(d.firms.amount_millions)} to firms ({net(d.firms.flow_millions)} in the month) and {trillions(d.households.amount_millions)} to households ({net(d.households.flow_millions)} in the month).</Txt>
            <Divider />
            <Txt variant="label">What households borrow for</Txt>
            <View style={{ gap: space.sm }} testID="eurolending-households">{d.households.parts.map((p) => part("households", p, "household loans"))}</View>
            <Txt variant="label">How long firms' loans run</Txt>
            <View style={{ gap: space.sm }} testID="eurolending-firms">{d.firms.parts.map((p) => part("firms", p, "loans to firms"))}</View>
            <Divider />
            <Txt variant="label">Annual growth by month</Txt>
            <View style={{ gap: space.sm }} testID="eurolending-recent">
              {d.recent.map((r) => (
                <Txt key={r.month} variant="small" testID={`eurolending-month-${r.month}`}>{ymdLabel(r.month)}: firms {signed(r.firms_growth_pct)}, households {signed(r.households_growth_pct)}</Txt>
              ))}
            </View>
            <Txt variant="tiny">Check: in each of the last {d.detail.months_checked} months every amount, every monthly change and every growth rate lay inside its range (plain checks), and the three maturities of the firms' loans and the three purposes of the households' loans added up to the totals, for the amounts and for the flows, to the million euro; in each of the last {d.detail.growth_months_checked} months the published annual growth equalled the growth rebuilt from the monthly flows and amounts to within 0.0625 points{d.detail.largest_growth_gap_month ? ` (the largest gap: ${points(d.detail.largest_growth_gap_points)} for ${d.detail.largest_growth_gap_series} in ${ymdLabel(d.detail.largest_growth_gap_month)})` : ""}. The ECB builds the totals and its growth rates that way, so these two checks show the series belong together, not that the figures are right.</Txt>
            <Txt variant="tiny">{d.note}</Txt>
          </View>)}
      <SourceLink url={link}>Source: European Central Bank (bank balance sheet statistics), via the ECB Data Portal</SourceLink>
    </GCard>
  );
}
