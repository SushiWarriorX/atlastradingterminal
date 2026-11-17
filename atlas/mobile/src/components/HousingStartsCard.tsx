import React from "react";
import { Linking, Pressable, View } from "react-native";
import { ymdLabel } from "../lib/format";
import { safeUrl } from "../lib/links";
import { useHousingStarts } from "../state/queries";
import { color, space } from "../theme";
import { Banner, Divider, GCard, Skeleton, Txt } from "./ui";

const thousands = (k: number | null | undefined) => (k == null ? "n/a" : `${Math.round(k).toLocaleString("en-US")} thousand`);
const millions = (k: number | null | undefined) => (k == null ? "n/a" : `${(k / 1000).toLocaleString("en-US", { minimumFractionDigits: 3, maximumFractionDigits: 3 })} million`);
const signed = (x: number) => `${x > 0 ? "+" : x < 0 ? "-" : ""}${Math.abs(x).toFixed(1)}%`;
const vs = (x: number | null | undefined, when: string) => (x == null ? `not available against ${when}` : x === 0 ? `the same as ${when}` : `${x > 0 ? "up" : "down"} ${Math.abs(x).toFixed(1)}% on ${when}`);
const share = (x: number) => `${x.toFixed(1)}% of the total`;

/** US housing starts, monthly, at a seasonally adjusted annual rate (Census Bureau and HUD, via FRED). Describes what already happened; not a signal or a forecast. */
export function HousingStartsCard() {
  const q = useHousingStarts();
  const d = q.data;
  const link = safeUrl(d?.url ?? null);
  return (
    <GCard style={{ padding: space.lg, gap: space.md }} testID="housing-card">
      <View><Txt variant="h2">Housing starts</Txt><Txt variant="tiny">How many new homes US builders began building, monthly, from the Census Bureau and HUD</Txt></View>
      {q.isLoading ? <Skeleton h={80} />
        : q.isError || !d ? <Banner tone="warn" title="Couldn't load housing starts" testID="housing-error">{q.error instanceof Error ? q.error.message : "Something went wrong."}</Banner>
        : !d.available || d.level_thousands == null || !d.single_family || !d.five_plus || !d.parts ? <Banner tone={d.demo ? "demo" : "warn"} title={d.demo ? "Demo mode" : "Housing starts unavailable"} testID="housing-unavailable">{d.reason}</Banner>
        : (
          <View style={{ gap: space.sm }} testID="housing-body">
            <Txt variant="label">{ymdLabel(d.month)}, seasonally adjusted annual rate{d.freshness === "OVERDUE" ? " · overdue" : ""}</Txt>
            <Txt variant="small">Builders began new homes at a pace of {millions(d.level_thousands)} a year in {ymdLabel(d.month)}, {vs(d.change_1y_pct, "a year ago")}.</Txt>
            <Txt variant="tiny">{vs(d.change_1m_pct, "a month ago")}, {vs(d.change_3m_pct, "three months ago")}. This is a yearly pace, not the number of homes started in the month.{d.growth ? ` Over the past 10 years (${d.growth.months} months), the change over a year ran from ${signed(d.growth.slowest.pct)} (${ymdLabel(d.growth.slowest.month)}) to ${signed(d.growth.fastest.pct)} (${ymdLabel(d.growth.fastest.month)}); ${d.growth.share_slower_pct}% of those months were weaker than now.` : ""}</Txt>
            <Divider />
            <Txt variant="small">Single-family homes, {thousands(d.single_family.level_thousands)} ({share(d.single_family.share_pct)}; {vs(d.single_family.change_1y_pct, "a year ago")}). Homes in buildings of five or more units, {thousands(d.five_plus.level_thousands)} ({share(d.five_plus.share_pct)}; {vs(d.five_plus.change_1y_pct, "a year ago")}).</Txt>
            <Txt variant="tiny">Check: in each of the last {d.parts.months_checked} months, single-family plus five-or-more-unit starts are no more than the total; what is left, mostly buildings of two to four units, was between {thousands(d.parts.smallest_remainder_thousands)} and {thousands(d.parts.largest_remainder_thousands)}.</Txt>
            <Txt variant="tiny">{d.note}</Txt>
          </View>)}
      {link ? <Pressable onPress={() => Linking.openURL(link).catch(() => undefined)} accessibilityRole="link"><Txt variant="tiny" c={color.accent}>Source: US Census Bureau and HUD, via FRED</Txt></Pressable> : null}
    </GCard>
  );
}
