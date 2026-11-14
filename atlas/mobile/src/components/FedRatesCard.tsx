import { ymdLabel } from "../lib/format";
import React from "react";
import { Linking, Pressable, View } from "react-native";
import { safeUrl } from "../lib/links";
import { useFedRates } from "../state/queries";
import { color, space } from "../theme";
import { Banner, Divider, GCard, Skeleton, Txt } from "./ui";

const pct = (x: number) => `${x.toFixed(2)}%`;
const pp = (x: number | null | undefined) => (x == null ? "n/a" : `${x > 0 ? "+" : x < 0 ? "−" : ""}${Math.abs(x).toFixed(2)}`);

/** The Fed's policy rate (EFFR), its target range and the overnight reference rates (New York Fed). Describes where overnight money costs; not a signal. */
export function FedRatesCard() {
  const q = useFedRates();
  const d = q.data;
  const link = safeUrl(d?.url ?? null);
  return (
    <GCard style={{ padding: space.lg, gap: space.md }} testID="fedrates-card">
      <View><Txt variant="h2">Fed interest rate</Txt><Txt variant="tiny">Policy rate and overnight rates, from the New York Fed</Txt></View>
      {q.isLoading ? <Skeleton h={80} />
        : q.isError || !d ? <Banner tone="warn" title="Couldn't load the Fed rate" testID="fedrates-error">{q.error instanceof Error ? q.error.message : "Something went wrong."}</Banner>
        : !d.available ? <Banner tone={d.demo ? "demo" : "warn"} title={d.demo ? "Demo mode" : "Fed rate unavailable"} testID="fedrates-unavailable">{d.reason}</Banner>
        : (
          <View style={{ gap: space.sm }} testID="fedrates-body">
            <Txt variant="label">Effective federal funds rate · {ymdLabel(d.date)}{d.freshness === "OVERDUE" ? " · overdue" : ""}</Txt>
            <Txt variant="hero">{pct(d.effr!)}</Txt>
            <Txt variant="small">{pp(d.effr_change_pp)} pts on the day · Fed target range {pct(d.target_low!)} to {pct(d.target_high!)}, the rate is {d.effr_position} it</Txt>
            {d.last_change ? <Txt variant="tiny">Range last changed on {ymdLabel(d.last_change.date)} ({d.last_change.days_ago} days ago): {pct(d.last_change.from_range[0])}–{pct(d.last_change.from_range[1])} to {pct(d.last_change.to_range[0])}–{pct(d.last_change.to_range[1])} ({pp(d.last_change.change_pp)} pts).</Txt>
              : d.history_available ? <Txt variant="tiny">The target range has not changed in the data window.</Txt> : <Txt variant="tiny">{d.history_reason}</Txt>}
            {(d.rates ?? []).filter((r) => r.code !== "EFFR").map((r) => (
              <View key={r.code} style={{ gap: 2 }}>
                <Divider />
                <Txt variant="label">{r.name} · {ymdLabel(r.date)}</Txt>
                <Txt variant="h2">{pct(r.rate)}</Txt>
              </View>))}
            <Txt variant="tiny">{d.note}</Txt>
          </View>)}
      {link ? <Pressable onPress={() => Linking.openURL(link).catch(() => undefined)} accessibilityRole="link"><Txt variant="tiny" c={color.accent}>Source: New York Fed</Txt></Pressable> : null}
    </GCard>
  );
}
