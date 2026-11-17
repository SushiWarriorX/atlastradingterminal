import React from "react";
import { Linking, Pressable, View } from "react-native";
import { ymdLabel } from "../lib/format";
import { safeUrl } from "../lib/links";
import { useIndustrialProduction } from "../state/queries";
import { color, space } from "../theme";
import { Banner, Divider, GCard, Skeleton, Txt } from "./ui";
import type { IndustrialGroup } from "../api/types";

const signed = (x: number) => `${x > 0 ? "+" : x < 0 ? "-" : ""}${Math.abs(x).toFixed(1)}%`;
const signed2 = (x: number) => `${x < 0 ? "-" : "+"}${Math.abs(x).toFixed(2)}%`;
const vs = (x: number | null | undefined, when: string) => (x == null ? `not available against ${when}` : x === 0 ? `the same as ${when}` : `${x > 0 ? "up" : "down"} ${Math.abs(x).toFixed(1)}% on ${when}`);
const points = (x: number | null | undefined, when: string) => (x == null ? "" : x === 0 ? `, the same as ${when}` : `, ${x > 0 ? "up" : "down"} ${Math.abs(x).toFixed(1)} points on ${when}`);
const group = (name: string, g: IndustrialGroup) => `${name}, ${g.level.toFixed(2)} (${vs(g.change_1y_pct, "a year ago")})`;

/** US industrial production, monthly, seasonally adjusted index with 2017 = 100, and capacity utilization (Federal Reserve Board, release G.17, via FRED). Describes what already happened; not a signal or a forecast. */
export function IndustrialProductionCard() {
  const q = useIndustrialProduction();
  const d = q.data;
  const link = safeUrl(d?.url ?? null);
  return (
    <GCard style={{ padding: space.lg, gap: space.md }} testID="industrial-card">
      <View><Txt variant="h2">Industrial production</Txt><Txt variant="tiny">How much US factories, mines and power and gas utilities produced, monthly, from the Federal Reserve</Txt></View>
      {q.isLoading ? <Skeleton h={80} />
        : q.isError || !d ? <Banner tone="warn" title="Couldn't load industrial production" testID="industrial-error">{q.error instanceof Error ? q.error.message : "Something went wrong."}</Banner>
        : !d.available || d.level == null || !d.manufacturing || !d.mining || !d.utilities || !d.capacity || !d.detail ? <Banner tone={d.demo ? "demo" : "warn"} title={d.demo ? "Demo mode" : "Industrial production unavailable"} testID="industrial-unavailable">{d.reason}</Banner>
        : (
          <View style={{ gap: space.sm }} testID="industrial-body">
            <Txt variant="label">{ymdLabel(d.month)}, seasonally adjusted index, 2017 = 100{d.freshness === "OVERDUE" ? " · overdue" : ""}</Txt>
            <Txt variant="small">Output of US factories, mines and power and gas utilities was {d.level.toFixed(2)} on an index where 2017 is 100 in {ymdLabel(d.month)}, {vs(d.change_1y_pct, "a year ago")}.</Txt>
            <Txt variant="tiny">{vs(d.change_1m_pct, "a month ago")}, {vs(d.change_3m_pct, "three months ago")}. This is the volume produced, not its value in dollars.{d.growth ? ` Over the past 10 years (${d.growth.months} months), the change over a year ran from ${signed(d.growth.slowest.pct)} (${ymdLabel(d.growth.slowest.month)}) to ${signed(d.growth.fastest.pct)} (${ymdLabel(d.growth.fastest.month)}); ${d.growth.share_slower_pct}% of those months were weaker than now.` : ""}</Txt>
            <Divider />
            <Txt variant="small">Capacity in use: {d.capacity.utilization_pct.toFixed(1)}% of what the plants could sustainably produce in {ymdLabel(d.month)}{points(d.capacity.change_1y_points, "a year ago")}.</Txt>
            <Txt variant="small">{group("Manufacturing", d.manufacturing)}. {group("Mining", d.mining)}. {group("Electric and gas utilities", d.utilities)}.</Txt>
            <Txt variant="tiny">Check: in each of the last {d.detail.changes_checked} months, the total's change lay between those of manufacturing, mining and utilities, and the capacity implied by output and utilization moved by between {signed2(d.detail.capacity_change_pct.smallest)} and {signed2(d.detail.capacity_change_pct.largest)} a month.</Txt>
            <Txt variant="tiny">{d.note}</Txt>
          </View>)}
      {link ? <Pressable onPress={() => Linking.openURL(link).catch(() => undefined)} accessibilityRole="link"><Txt variant="tiny" c={color.accent}>Source: Federal Reserve Board, via FRED</Txt></Pressable> : null}
    </GCard>
  );
}
