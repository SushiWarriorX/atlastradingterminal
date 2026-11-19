import React from "react";
import { View } from "react-native";
import { ymdLabel } from "../lib/format";
import { safeUrl } from "../lib/links";
import { useEuroInflation } from "../state/queries";
import { space } from "../theme";
import { Banner, Divider, GCard, Skeleton, SourceLink, Txt } from "./ui";

const signed = (x: number) => `${x > 0 ? "+" : x < 0 ? "-" : ""}${Math.abs(x).toFixed(1)}%`;
const year = (x: number) => (x === 0 ? "unchanged from a year earlier" : `${Math.abs(x).toFixed(1)}% ${x > 0 ? "higher" : "lower"} than a year earlier`);
const moved = (x: number | null | undefined, when: string) => (x == null ? `not available against ${when}` : x === 0 ? `the same as ${when}` : `${x > 0 ? "up" : "down"} ${Math.abs(x).toFixed(1)} points on ${when}`);
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
const points = (x: number) => `${x.toFixed(2)} points`;

/** Euro-area consumer prices (HICP, compiled by Eurostat, published on the ECB Data Portal), monthly. Describes what already happened; not a signal or a forecast. */
export function EuroInflationCard() {
  const q = useEuroInflation();
  const d = q.data;
  const link = safeUrl(d?.url ?? null);
  return (
    <GCard style={{ padding: space.lg, gap: space.md }} testID="euroinflation-card">
      <View><Txt variant="h2">Euro-area consumer prices</Txt><Txt variant="tiny">How fast prices are rising in the euro area, monthly, and what drives it</Txt></View>
      {q.isLoading ? <Skeleton h={80} />
        : q.isError || !d ? <Banner tone="warn" title="Couldn't load the euro-area consumer prices" testID="euroinflation-error">{q.error instanceof Error ? q.error.message : "Something went wrong."}</Banner>
        : !d.available || !d.headline || !d.parts || !d.contributions || !d.detail ? <Banner tone={d.demo ? "demo" : "warn"} title={d.demo ? "Demo mode" : "Euro-area consumer prices unavailable"} testID="euroinflation-unavailable">{d.reason}</Banner>
        : (
          <View style={{ gap: space.sm }} testID="euroinflation-body">
            <Txt variant="label">{ymdLabel(d.month)}{d.estimate ? " · early (flash) estimate" : ""}{d.freshness === "OVERDUE" ? " · overdue" : ""}</Txt>
            <Txt variant="small">In {ymdLabel(d.month)} consumer prices in the euro area were {year(d.headline.rate_pct)}. Without energy, food, alcohol and tobacco (core) the rate was {d.headline.core_rate_pct.toFixed(1)}%.</Txt>
            <Txt variant="tiny">The annual rate was {moved(d.headline.change_1m_points, "a month ago")} and {moved(d.headline.change_3m_points, "three months ago")}.{d.range ? ` Over the past 10 years (${d.range.months} months), it ran from ${signed(d.range.lowest.pct)} (${ymdLabel(d.range.lowest.month)}) to ${signed(d.range.highest.pct)} (${ymdLabel(d.range.highest.month)}); ${d.range.share_lower_pct}% of those months were lower than now.` : ""}</Txt>
            <Divider />
            <Txt variant="label">What the basket is made of</Txt>
            {[...d.parts].sort((a, b) => (d.contributions!.shown ? (b.points ?? 0) - (a.points ?? 0) : b.share_pct - a.share_pct)).map((p) => (
              <Txt key={p.id} variant="small" testID={`euroinflation-part-${p.id}`}>{cap(p.label)}: {p.share_pct.toFixed(1)}% of the basket, {signed(p.rate_pct)} a year{p.points != null ? `, about ${p.points.toFixed(1)} points of the ${d.headline!.rate_pct.toFixed(1)}%` : ""}.</Txt>))}
            <Txt variant="tiny">{d.contributions.shown
              ? `The points are each part's share of the basket times its annual rate: an approximation (together ${d.contributions.sum_points.toFixed(2)} against the published ${d.headline.rate_pct.toFixed(1)}%; the exact contributions Eurostat publishes use the weights of the previous December).`
              : `The points are not shown this month: the shares times the rates add up to ${d.contributions.sum_points.toFixed(2)}, more than 0.3 points from the published ${d.headline.rate_pct.toFixed(1)}% (the approximation breaks down when prices have moved a lot).`}</Txt>
            <Txt variant="tiny">Check: in each of the last {d.detail.months_checked} months the headline lay between the rates of its five parts and core between the goods and the services (neither is Eurostat's own sum), and two checks that are Eurostat's own arithmetic held: the all-items index follows from the parts' indices and weights (largest gap {d.detail.largest_index_gap.toFixed(3)} index points{d.detail.largest_index_gap_month ? `, ${ymdLabel(d.detail.largest_index_gap_month)}` : ""}), and each published rate matches the rate its index gives (largest gap {points(d.detail.largest_rate_gap_points)}). They show the series belong together, not that the figures are right.</Txt>
            <Txt variant="tiny">{d.note}</Txt>
          </View>)}
      <SourceLink url={link}>Source: Eurostat, via the European Central Bank's Data Portal</SourceLink>
    </GCard>
  );
}
