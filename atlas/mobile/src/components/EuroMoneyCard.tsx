import React from "react";
import { View } from "react-native";
import { ymdLabel } from "../lib/format";
import { safeUrl } from "../lib/links";
import { useEuroMoneySupply } from "../state/queries";
import { space } from "../theme";
import { Banner, Divider, GCard, Skeleton, SourceLink, Txt } from "./ui";

const trillions = (millions: number) => `€${(millions / 1e6).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} trillion`;
const signed = (x: number) => `${x > 0 ? "+" : x < 0 ? "-" : ""}${Math.abs(x).toFixed(1)}%`;
const rate = (x: number) => (x === 0 ? "not growing" : `${x > 0 ? "growing" : "shrinking"} ${Math.abs(x).toFixed(1)}% a year`);
const vs = (x: number | null | undefined, when: string) => (x == null ? `not available against ${when}` : x === 0 ? `the same as ${when}` : `${x > 0 ? "up" : "down"} ${Math.abs(x).toFixed(1)}% on ${when}`);
const points = (x: number) => `${x < 0 ? "-" : "+"}${Math.abs(x).toFixed(2)} points`;

/** Euro-area money supply (M1, M2, M3), monthly, from the ECB Data Portal. Describes what already happened; not a signal or a forecast. */
export function EuroMoneyCard() {
  const q = useEuroMoneySupply();
  const d = q.data;
  const link = safeUrl(d?.url ?? null);
  return (
    <GCard style={{ padding: space.lg, gap: space.md }} testID="euromoney-card">
      <View><Txt variant="h2">Euro-area money supply</Txt><Txt variant="tiny">How much money households and firms in the euro area hold, monthly, from the ECB</Txt></View>
      {q.isLoading ? <Skeleton h={80} />
        : q.isError || !d ? <Banner tone="warn" title="Couldn't load the euro-area money supply" testID="euromoney-error">{q.error instanceof Error ? q.error.message : "Something went wrong."}</Banner>
        : !d.available || !d.m3 || !d.m2 || !d.m1 || !d.makeup || !d.detail ? <Banner tone={d.demo ? "demo" : "warn"} title={d.demo ? "Demo mode" : "Euro-area money supply unavailable"} testID="euromoney-unavailable">{d.reason}</Banner>
        : (
          <View style={{ gap: space.sm }} testID="euromoney-body">
            <Txt variant="label">{ymdLabel(d.month)}, seasonally adjusted{d.provisional ? " · provisional" : ""}{d.freshness === "OVERDUE" ? " · overdue" : ""}</Txt>
            <Txt variant="small">At the end of {ymdLabel(d.month)} the euro area's broad money supply (M3) was {trillions(d.m3.level_millions)}, {rate(d.m3.growth_pct)} (the ECB's own annual rate).</Txt>
            <Txt variant="tiny">The amount was {vs(d.m3.change_1m_pct, "a month ago")} and {vs(d.m3.change_3m_pct, "three months ago")}.{d.growth_range ? ` Over the past 10 years (${d.growth_range.months} months), the ECB's growth rate ran from ${signed(d.growth_range.lowest.pct)} (${ymdLabel(d.growth_range.lowest.month)}) to ${signed(d.growth_range.highest.pct)} (${ymdLabel(d.growth_range.highest.month)}); ${d.growth_range.share_lower_pct}% of those months were slower than now.` : ""}</Txt>
            <Divider />
            <Txt variant="small">M2, {trillions(d.m2.level_millions)}, {rate(d.m2.growth_pct)}. M1, {trillions(d.m1.level_millions)}, {rate(d.m1.growth_pct)}.</Txt>
            <Txt variant="small">M3 is made of: {d.makeup.map((m) => `${m.label}, ${m.share_pct.toFixed(1)}%`).join("; ")}.</Txt>
            <Txt variant="tiny">Check: in each of the last {d.detail.months_checked} months, M1, M2 and M3 equal the sums of their parts to the million euro (the ECB builds them that way, so this shows the series belong together, not that they are right), and the published growth of M3 stayed within 4 points of the growth of the amounts{d.detail.largest_gap_month ? ` (the largest gap: ${points(d.detail.largest_gap_points)} in ${ymdLabel(d.detail.largest_gap_month)})` : ""}.</Txt>
            <Txt variant="tiny">{d.note}</Txt>
          </View>)}
      <SourceLink url={link}>Source: European Central Bank, via the ECB Data Portal</SourceLink>
    </GCard>
  );
}
