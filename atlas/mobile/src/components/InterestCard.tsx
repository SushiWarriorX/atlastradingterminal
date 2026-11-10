import React from "react";
import { Linking, Pressable, View } from "react-native";
import { safeUrl } from "../lib/links";
import { useInterest } from "../state/queries";
import { color, space } from "../theme";
import { Banner, Divider, GCard, Skeleton, Txt } from "./ui";

const b = (x: number) => `${x < 0 ? "−" : ""}$${Math.abs(x).toLocaleString("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 })}B`;
const monthName = (iso?: string) => (iso ? new Date(`${iso.slice(0, 7)}-15T12:00:00Z`).toLocaleDateString("en-US", { month: "long", year: "numeric", timeZone: "UTC" }) : "");
const change = (x: number | null | undefined) => (x == null ? "" : `${x >= 0 ? "Up" : "Down"} ${Math.abs(x).toFixed(1)}% from a year earlier`);

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
            <Txt variant="label">{monthName(d.date)}{d.freshness === "OVERDUE" ? " · overdue" : ""}</Txt>
            <Txt variant="hero">{b(d.month_total_billions!)}</Txt>
            <Txt variant="small">{change(d.month_change_pct) || "No comparison with a year earlier"}</Txt>
            <Divider />
            <Txt variant="label">Fiscal {d.fiscal_year} so far ({d.ytd_months} of 12 months)</Txt>
            <Txt variant="h2">{b(d.ytd_total_billions!)}</Txt>
            <Txt variant="small">{change(d.ytd_change_pct)}</Txt>
            {d.ytd_check ? <Txt variant="tiny">{d.ytd_check.match ? "Matches" : "DOES NOT match"} the source's own year-to-date total.</Txt> : null}
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
