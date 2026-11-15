import React from "react";
import { Linking, Pressable, View } from "react-native";
import { ymdLabel } from "../lib/format";
import { safeUrl } from "../lib/links";
import { useMoneySupply } from "../state/queries";
import { color, space } from "../theme";
import { Banner, Divider, GCard, Skeleton, Txt } from "./ui";

const trillions = (b: number | null | undefined) => (b == null ? "n/a" : `$${(b / 1000).toFixed(2)} trillion`);
const billions = (b: number | null | undefined) => (b == null ? "n/a" : `$${b.toLocaleString("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 })} billion`);
const signed = (x: number) => `${x > 0 ? "+" : x < 0 ? "-" : ""}${Math.abs(x).toFixed(1)}%`;
const vs = (x: number | null | undefined, when: string) => (x == null ? `not available against ${when}` : x === 0 ? `the same as ${when}` : `${x > 0 ? "up" : "down"} ${Math.abs(x).toFixed(1)}% on ${when}`);
const gap = (x: number) => (x === 0 ? "the same as" : `${Math.abs(x).toFixed(2)}% ${x < 0 ? "under" : "over"}`);

/** M2 money supply, monthly, seasonally adjusted (Federal Reserve Board, via FRED). Describes what already happened; not a signal or a forecast. */
export function MoneySupplyCard() {
  const q = useMoneySupply();
  const d = q.data;
  const link = safeUrl(d?.url ?? null);
  return (
    <GCard style={{ padding: space.lg, gap: space.md }} testID="m2-card">
      <View><Txt variant="h2">M2 money supply</Txt><Txt variant="tiny">Cash, bank deposits and retail money funds held by the public, monthly, from the Federal Reserve Board</Txt></View>
      {q.isLoading ? <Skeleton h={80} />
        : q.isError || !d ? <Banner tone="warn" title="Couldn't load the money supply" testID="m2-error">{q.error instanceof Error ? q.error.message : "Something went wrong."}</Banner>
        : !d.available || d.level_billions == null || !d.seasonal || !d.weekly ? <Banner tone={d.demo ? "demo" : "warn"} title={d.demo ? "Demo mode" : "Money supply unavailable"} testID="m2-unavailable">{d.reason}</Banner>
        : (
          <View style={{ gap: space.sm }} testID="m2-body">
            <Txt variant="label">{ymdLabel(d.month)}, seasonally adjusted{d.freshness === "OVERDUE" ? " · overdue" : ""}</Txt>
            <Txt variant="small">M2 was {trillions(d.level_billions)} in {ymdLabel(d.month)}, {vs(d.change_1y_pct, "a year ago")}.</Txt>
            <Txt variant="tiny">{vs(d.change_1m_pct, "a month ago")}, {vs(d.change_3m_pct, "three months ago")}.{d.growth ? ` Over the past 10 years (${d.growth.months} months), growth over a year ran from ${signed(d.growth.slowest.pct)} (${ymdLabel(d.growth.slowest.month)}) to ${signed(d.growth.fastest.pct)} (${ymdLabel(d.growth.fastest.month)}); ${d.growth.share_slower_pct}% of those months grew slower than now.` : ""}</Txt>
            <Divider />
            <Txt variant="small">Cross-checks: seasonal adjustment moved {ymdLabel(d.seasonal.month)}'s figure by {d.seasonal.pct == null ? "n/a" : signed(d.seasonal.pct)} ({billions(d.seasonal.adjusted)} adjusted against {billions(d.seasonal.unadjusted)} unadjusted), and its {d.weekly.newest.weeks} weekly figures average {billions(d.weekly.newest.average)}, {gap(d.weekly.newest.diff_pct)} the unadjusted monthly figure.</Txt>
            <Txt variant="tiny">{d.note}</Txt>
          </View>)}
      {link ? <Pressable onPress={() => Linking.openURL(link).catch(() => undefined)} accessibilityRole="link"><Txt variant="tiny" c={color.accent}>Source: Federal Reserve Board, via FRED</Txt></Pressable> : null}
    </GCard>
  );
}
