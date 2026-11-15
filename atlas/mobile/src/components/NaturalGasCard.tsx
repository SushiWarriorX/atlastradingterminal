import React from "react";
import { Linking, Pressable, View } from "react-native";
import { ymdLabel } from "../lib/format";
import { safeUrl } from "../lib/links";
import { useNaturalGas } from "../state/queries";
import { color, space } from "../theme";
import { Banner, Divider, GCard, Skeleton, Txt } from "./ui";

const usd = (x: number | null | undefined) => (x == null ? "n/a" : `$${x.toFixed(2)}`);
const dayMove = (x: number | null | undefined) => (x == null ? "not available since the previous trading day" : x === 0 ? "unchanged since the previous trading day" : `${x > 0 ? "up" : "down"} ${usd(Math.abs(x))} since the previous trading day`);
const vs = (x: number | null | undefined, when: string) => (x == null ? `not available against ${when}` : x === 0 ? `the same as ${when}` : `${x > 0 ? "up" : "down"} ${Math.abs(x).toFixed(1)}% on ${when}`);

/** Henry Hub natural gas spot price, daily (US Energy Information Administration, via FRED). Describes what already happened; not a signal or a forecast. */
export function NaturalGasCard() {
  const q = useNaturalGas();
  const d = q.data;
  const link = safeUrl(d?.url ?? null);
  return (
    <GCard style={{ padding: space.lg, gap: space.md }} testID="natgas-card">
      <View><Txt variant="h2">Natural gas prices</Txt><Txt variant="tiny">Henry Hub spot price, daily, from the US Energy Information Administration</Txt></View>
      {q.isLoading ? <Skeleton h={80} />
        : q.isError || !d ? <Banner tone="warn" title="Couldn't load natural gas prices" testID="natgas-error">{q.error instanceof Error ? q.error.message : "Something went wrong."}</Banner>
        : !d.available || d.price == null || !d.monthly ? <Banner tone={d.demo ? "demo" : "warn"} title={d.demo ? "Demo mode" : "Natural gas prices unavailable"} testID="natgas-unavailable">{d.reason}</Banner>
        : (
          <View style={{ gap: space.sm }} testID="natgas-body">
            <Txt variant="label">Latest daily price, in dollars per million BTU</Txt>
            <Txt variant="small">Natural gas {usd(d.price)} per million BTU on {ymdLabel(d.date)}: {d.reading}.{d.freshness === "OVERDUE" ? " (overdue)" : ""}</Txt>
            <Txt variant="tiny">{dayMove(d.change_1d)}, {vs(d.change_1m_pct, "a month ago")}, {vs(d.change_1y_pct, "a year ago")}. Past year: low {usd(d.year_low)}, high {usd(d.year_high)}; {d.rank_in_year ?? "n/a"}% of its {d.days_in_year ?? "n/a"} days were at or below this price.</Txt>
            <Divider />
            <Txt variant="small">Cross-check: the daily prices for {ymdLabel(d.monthly.month)} average {usd(d.monthly.average_of_daily)}; the EIA publishes {usd(d.monthly.published)} for the month.</Txt>
            <Txt variant="tiny">{d.note}</Txt>
          </View>)}
      {link ? <Pressable onPress={() => Linking.openURL(link).catch(() => undefined)} accessibilityRole="link"><Txt variant="tiny" c={color.accent}>Source: US Energy Information Administration, via FRED</Txt></Pressable> : null}
    </GCard>
  );
}
