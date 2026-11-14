import { ymdLabel } from "../lib/format";
import React from "react";
import { Linking, Pressable, View } from "react-native";
import { safeUrl } from "../lib/links";
import { useFedOps } from "../state/queries";
import { color, space } from "../theme";
import { Banner, Divider, GCard, Skeleton, Txt } from "./ui";

const b = (x: number) => `$${x.toFixed(x >= 10 ? 1 : 2)}B`;
const chg = (x: number) => `${x > 0 ? "+" : x < 0 ? "−" : ""}$${Math.abs(x).toFixed(2)}B`;

/** Fed liquidity operations from the New York Fed: cash parked at the Fed overnight (reverse repo) and cash the Fed lent (standing repo). Describes money-market plumbing; not a signal. */
export function FedOpsCard() {
  const q = useFedOps();
  const d = q.data;
  const link = safeUrl(d?.url ?? null);
  return (
    <GCard style={{ padding: space.lg, gap: space.md }} testID="fedops-card">
      <View><Txt variant="h2">Fed liquidity operations</Txt><Txt variant="tiny">Cash parked at the Fed and cash the Fed lent, from the New York Fed</Txt></View>
      {q.isLoading ? <Skeleton h={80} />
        : q.isError || !d ? <Banner tone="warn" title="Couldn't load Fed operations" testID="fedops-error">{q.error instanceof Error ? q.error.message : "Something went wrong."}</Banner>
        : !d.available ? <Banner tone={d.demo ? "demo" : "warn"} title={d.demo ? "Demo mode" : "Fed operations unavailable"} testID="fedops-unavailable">{d.reason}</Banner>
        : (
          <View style={{ gap: space.sm }} testID="fedops-body">
            <Txt variant="label">Cash parked at the Fed (reverse repo)</Txt>
            <Txt variant="hero">{b(d.reverse_repo!.billions)}</Txt>
            <Txt variant="small">{chg(d.reverse_repo!.change_billions)} vs the day before · {ymdLabel(d.date)}{d.freshness === "OVERDUE" ? " · overdue" : ""}</Txt>
            <Txt variant="tiny">About a month: average {b(d.reverse_repo!.average_billions)}, highest {b(d.reverse_repo!.highest_billions)} on {ymdLabel(d.reverse_repo!.highest_date)}.</Txt>
            <Divider />
            <Txt variant="label">Cash the Fed lent (standing repo)</Txt>
            <Txt variant="h2">{b(d.repo!.billions)}</Txt>
            <Txt variant="tiny">About a month: used on {d.repo!.days_used} of {d.repo!.dates_in_window} days, highest {b(d.repo!.highest_billions)}.</Txt>
            <Txt variant="tiny">{d.note}</Txt>
          </View>)}
      {link ? <Pressable onPress={() => Linking.openURL(link).catch(() => undefined)} accessibilityRole="link"><Txt variant="tiny" c={color.accent}>Source: New York Fed</Txt></Pressable> : null}
    </GCard>
  );
}
