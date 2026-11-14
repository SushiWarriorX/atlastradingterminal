import React from "react";
import { Linking, Pressable, View } from "react-native";
import type { OilSeries } from "../api/types";
import { ymdLabel } from "../lib/format";
import { safeUrl } from "../lib/links";
import { useOilPrices } from "../state/queries";
import { color, space } from "../theme";
import { Banner, Divider, GCard, Skeleton, Txt } from "./ui";

const usd = (x: number | null | undefined) => (x == null ? "n/a" : `$${x.toFixed(2)}`);
const dayMove = (x: number | null | undefined) => (x == null ? "not available on the day" : x === 0 ? "unchanged on the day" : `${x > 0 ? "up" : "down"} ${usd(Math.abs(x))} on the day`);
const vs = (x: number | null | undefined, when: string) => (x == null ? `not available against ${when}` : x === 0 ? `the same as ${when}` : `${x > 0 ? "up" : "down"} ${Math.abs(x).toFixed(1)}% on ${when}`);

function Line({ name, s }: { name: string; s: OilSeries }) {
  return (
    <View style={{ gap: space.sm }}>
      <Txt variant="small">{name} {usd(s.value)} a barrel on {ymdLabel(s.date)}: {s.reading}.{s.freshness === "OVERDUE" ? " (overdue)" : ""}</Txt>
      <Txt variant="tiny">{dayMove(s.change_1d)}, {vs(s.change_1m_pct, "a month ago")}, {vs(s.change_1y_pct, "a year ago")}. Past year: low {usd(s.year_low)}, high {usd(s.year_high)}.</Txt>
    </View>
  );
}

/** WTI and Brent crude spot prices (US Energy Information Administration, via FRED). Describes what already happened; not a signal or a forecast. */
export function OilPricesCard() {
  const q = useOilPrices();
  const d = q.data;
  const link = safeUrl(d?.url ?? null);
  const gap = d?.spread?.value ?? 0;
  return (
    <GCard style={{ padding: space.lg, gap: space.md }} testID="oil-card">
      <View><Txt variant="h2">Oil prices</Txt><Txt variant="tiny">WTI and Brent crude, spot, from the US Energy Information Administration</Txt></View>
      {q.isLoading ? <Skeleton h={80} />
        : q.isError || !d ? <Banner tone="warn" title="Couldn't load oil prices" testID="oil-error">{q.error instanceof Error ? q.error.message : "Something went wrong."}</Banner>
        : !d.available || !d.wti || !d.brent || !d.spread ? <Banner tone={d.demo ? "demo" : "warn"} title={d.demo ? "Demo mode" : "Oil prices unavailable"} testID="oil-unavailable">{d.reason}</Banner>
        : (
          <View style={{ gap: space.sm }} testID="oil-body">
            <Txt variant="label">Latest daily prices, in dollars a barrel</Txt>
            <Line name="WTI crude (US)" s={d.wti} />
            <Divider />
            <Line name="Brent crude (Europe)" s={d.brent} />
            <Divider />
            <Txt variant="small">{gap === 0 ? "Brent and WTI cost the same" : `Brent is ${usd(Math.abs(gap))} ${gap > 0 ? "above" : "below"} WTI`} on {ymdLabel(d.spread.date)}.</Txt>
            <Txt variant="tiny">{d.note}</Txt>
          </View>)}
      {link ? <Pressable onPress={() => Linking.openURL(link).catch(() => undefined)} accessibilityRole="link"><Txt variant="tiny" c={color.accent}>Source: US Energy Information Administration, via FRED</Txt></Pressable> : null}
    </GCard>
  );
}
