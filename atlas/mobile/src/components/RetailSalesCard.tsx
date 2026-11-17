import React from "react";
import { Linking, Pressable, View } from "react-native";
import { ymdLabel } from "../lib/format";
import { safeUrl } from "../lib/links";
import { useRetailSales } from "../state/queries";
import { color, space } from "../theme";
import { Banner, Divider, GCard, Skeleton, Txt } from "./ui";

const billions = (b: number | null | undefined) => (b == null ? "n/a" : `$${b.toLocaleString("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 })} billion`);
const signed = (x: number) => `${x > 0 ? "+" : x < 0 ? "-" : ""}${Math.abs(x).toFixed(1)}%`;
const vs = (x: number | null | undefined, when: string) => (x == null ? `not available against ${when}` : x === 0 ? `the same as ${when}` : `${x > 0 ? "up" : "down"} ${Math.abs(x).toFixed(1)}% on ${when}`);
const share = (x: number) => `${x.toFixed(1)}% of the total`;

/** US retail and food services sales, monthly, seasonally adjusted (Census Bureau, via FRED). Describes what already happened; not a signal or a forecast. */
export function RetailSalesCard() {
  const q = useRetailSales();
  const d = q.data;
  const link = safeUrl(d?.url ?? null);
  return (
    <GCard style={{ padding: space.lg, gap: space.md }} testID="retail-card">
      <View><Txt variant="h2">Retail sales</Txt><Txt variant="tiny">What US shops, online stores, restaurants and bars sold, monthly, from the Census Bureau</Txt></View>
      {q.isLoading ? <Skeleton h={80} />
        : q.isError || !d ? <Banner tone="warn" title="Couldn't load retail sales" testID="retail-error">{q.error instanceof Error ? q.error.message : "Something went wrong."}</Banner>
        : !d.available || d.level_billions == null || !d.retail || !d.food || !d.sums ? <Banner tone={d.demo ? "demo" : "warn"} title={d.demo ? "Demo mode" : "Retail sales unavailable"} testID="retail-unavailable">{d.reason}</Banner>
        : (
          <View style={{ gap: space.sm }} testID="retail-body">
            <Txt variant="label">{ymdLabel(d.month)}, seasonally adjusted, advance estimate{d.freshness === "OVERDUE" ? " · overdue" : ""}</Txt>
            <Txt variant="small">Retail and food services sales were {billions(d.level_billions)} in {ymdLabel(d.month)}, {vs(d.change_1y_pct, "a year ago")}.</Txt>
            <Txt variant="tiny">{vs(d.change_1m_pct, "a month ago")}, {vs(d.change_3m_pct, "three months ago")}. Not adjusted for price changes.{d.growth ? ` Over the past 10 years (${d.growth.months} months), growth over a year ran from ${signed(d.growth.slowest.pct)} (${ymdLabel(d.growth.slowest.month)}) to ${signed(d.growth.fastest.pct)} (${ymdLabel(d.growth.fastest.month)}); ${d.growth.share_slower_pct}% of those months grew slower than now.` : ""}</Txt>
            <Divider />
            <Txt variant="small">Made up of retail trade, {billions(d.retail.level_billions)} ({share(d.retail.share_pct)}; {vs(d.retail.change_1y_pct, "a year ago")}), and food services and drinking places, {billions(d.food.level_billions)} ({share(d.food.share_pct)}; {vs(d.food.change_1y_pct, "a year ago")}).</Txt>
            <Txt variant="tiny">Check: in each of the last {d.sums.months_checked} months, retail trade plus food services adds up to the total {d.sums.max_difference_millions === 0 ? "exactly" : `to within $${d.sums.max_difference_millions} million`}.</Txt>
            <Txt variant="tiny">{d.note}</Txt>
          </View>)}
      {link ? <Pressable onPress={() => Linking.openURL(link).catch(() => undefined)} accessibilityRole="link"><Txt variant="tiny" c={color.accent}>Source: US Census Bureau, via FRED</Txt></Pressable> : null}
    </GCard>
  );
}
