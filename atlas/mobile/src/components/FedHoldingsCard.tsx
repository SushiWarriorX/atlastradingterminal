import { ymdLabel } from "../lib/format";
import React from "react";
import { Linking, Pressable, View } from "react-native";
import { safeUrl } from "../lib/links";
import { useFedHoldings } from "../state/queries";
import { color, space } from "../theme";
import { Banner, Divider, GCard, Skeleton, Txt } from "./ui";

const money = (b: number) => (Math.abs(b) >= 1000 ? `$${(b / 1000).toFixed(2)}T` : `$${b.toFixed(1)}B`);
const chg = (b: number | null) => (b == null ? "n/a" : `${b > 0 ? "+" : b < 0 ? "−" : ""}${money(Math.abs(b))}`);

/** What the Federal Reserve holds (SOMA, weekly, New York Fed). Describes the Fed's own portfolio; not a signal. */
export function FedHoldingsCard() {
  const q = useFedHoldings();
  const d = q.data;
  const link = safeUrl(d?.url ?? null);
  return (
    <GCard style={{ padding: space.lg, gap: space.md }} testID="fedholdings-card">
      <View><Txt variant="h2">What the Fed holds</Txt><Txt variant="tiny">Treasuries and mortgage bonds on its books, from the New York Fed</Txt></View>
      {q.isLoading ? <Skeleton h={80} />
        : q.isError || !d ? <Banner tone="warn" title="Couldn't load the Fed's holdings" testID="fedholdings-error">{q.error instanceof Error ? q.error.message : "Something went wrong."}</Banner>
        : !d.available ? <Banner tone={d.demo ? "demo" : "warn"} title={d.demo ? "Demo mode" : "Fed holdings unavailable"} testID="fedholdings-unavailable">{d.reason}</Banner>
        : (
          <View style={{ gap: space.sm }} testID="fedholdings-body">
            <Txt variant="label">Total holdings · {ymdLabel(d.date)}{d.freshness === "OVERDUE" ? " · overdue" : ""}</Txt>
            <Txt variant="hero">{money(d.total_billions!)}</Txt>
            <Txt variant="small">{chg(d.from_peak_billions!)} ({d.from_peak_pct}%) from the peak of {money(d.peak_billions!)} on {ymdLabel(d.peak_date)}</Txt>
            <Txt variant="tiny">{(d.changes ?? []).map((c) => `${c.period}: ${chg(c.change_billions)}`).join(" · ")}</Txt>
            {(d.mix ?? []).map((m) => (
              <View key={m.name} style={{ gap: 2 }}>
                <Divider />
                <Txt variant="label">{m.name}</Txt>
                <Txt variant="h2">{money(m.billions)} · {m.share_pct.toFixed(1)}%</Txt>
              </View>))}
            <Txt variant="tiny">{d.note}</Txt>
          </View>)}
      {link ? <Pressable onPress={() => Linking.openURL(link).catch(() => undefined)} accessibilityRole="link"><Txt variant="tiny" c={color.accent}>Source: New York Fed</Txt></Pressable> : null}
    </GCard>
  );
}
