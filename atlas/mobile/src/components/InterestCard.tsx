import React from "react";
import { Linking, Pressable, View } from "react-native";
import { safeUrl } from "../lib/links";
import { useInterest } from "../state/queries";
import { color, space } from "../theme";
import { Banner, Divider, GCard, Skeleton, Txt } from "./ui";

const b = (x: number) => `${x < 0 ? "−" : ""}$${Math.abs(x).toLocaleString("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 })}B`;
const pct = (x: number | null | undefined) => (x == null ? "" : ` (${x >= 0 ? "+" : "−"}${Math.abs(x).toFixed(1)}% vs a year earlier)`);

/** Interest the US government owes on debt held by the public, by month and security type. Describes what already happened; not a signal. */
export function InterestCard() {
  const q = useInterest();
  const d = q.data;
  const link = safeUrl(d?.url ?? null);
  return (
    <GCard style={{ padding: space.lg, gap: space.md }} testID="interest-card">
      <View><Txt variant="h2">Interest on the debt</Txt><Txt variant="tiny">What the US government owes in interest each month, from the US Treasury</Txt></View>
      {q.isLoading ? <Skeleton h={80} />
        : q.isError || !d ? <Banner tone="warn" title="Couldn't load the interest figures" testID="interest-error">{q.error instanceof Error ? q.error.message : "Something went wrong."}</Banner>
        : !d.available ? <Banner tone={d.demo ? "demo" : "warn"} title={d.demo ? "Demo mode" : "Interest figures unavailable"} testID="interest-unavailable">{d.reason}</Banner>
        : (
          <View style={{ gap: space.sm }} testID="interest-body">
            <Txt variant="label">{d.date?.slice(0, 7)}{d.freshness === "OVERDUE" ? " · overdue" : ""}</Txt>
            <Txt variant="hero">{b(d.month_total_billions!)}</Txt>
            <Txt variant="tiny">{pct(d.month_change_pct).trim() || "No comparison with a year earlier"}</Txt>
            <Divider />
            <Txt variant="label">Fiscal {d.fiscal_year} so far ({d.ytd_months} of 12 months)</Txt>
            <Txt variant="h2">{b(d.ytd_total_billions!)}</Txt>
            <Txt variant="tiny">{pct(d.ytd_change_pct).trim()}{d.ytd_check ? `${pct(d.ytd_change_pct) ? " · " : ""}${d.ytd_check.match ? "matches" : "DOES NOT match"} the source's own total` : ""}</Txt>
            <Divider />
            {(d.breakdown ?? []).map((r) => (
              <View key={r.key} style={{ flexDirection: "row", justifyContent: "space-between", gap: space.md }}>
                <Txt variant="small" style={{ flex: 1 }}>{r.label}</Txt>
                <Txt variant="small">{b(r.billions)}{r.share_pct == null ? "" : ` · ${r.share_pct.toFixed(1)}%`}</Txt>
              </View>))}
            <Txt variant="tiny">{d.note}</Txt>
          </View>)}
      {link ? <Pressable onPress={() => Linking.openURL(link).catch(() => undefined)} accessibilityRole="link"><Txt variant="tiny" c={color.accent}>Source: US Treasury FiscalData</Txt></Pressable> : null}
    </GCard>
  );
}
