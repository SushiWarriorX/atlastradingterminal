import React from "react";
import { Linking, Pressable, View } from "react-native";
import { safeUrl } from "../lib/links";
import { useDebtMix } from "../state/queries";
import { color, space } from "../theme";
import { Banner, Divider, GCard, Skeleton, Txt } from "./ui";

const money = (b: number) => (Math.abs(b) >= 1000 ? `$${(b / 1000).toFixed(2)}T` : `$${b.toFixed(1)}B`);
const chg = (b: number | null) => (b == null ? "no earlier month to compare" : `${b > 0 ? "+" : b < 0 ? "−" : ""}${money(Math.abs(b))} vs last month`);

/** What the US national debt is made of (Monthly Statement of the Public Debt). A month-end accounting record; not a signal. */
export function DebtMixCard() {
  const q = useDebtMix();
  const d = q.data;
  const link = safeUrl(d?.url ?? null);
  return (
    <GCard style={{ padding: space.lg, gap: space.md }} testID="debtmix-card">
      <View><Txt variant="h2">What the US debt is made of</Txt><Txt variant="tiny">Total debt by type of security, from the US Treasury</Txt></View>
      {q.isLoading ? <Skeleton h={80} />
        : q.isError || !d ? <Banner tone="warn" title="Couldn't load the debt breakdown" testID="debtmix-error">{q.error instanceof Error ? q.error.message : "Something went wrong."}</Banner>
        : !d.available ? <Banner tone={d.demo ? "demo" : "warn"} title={d.demo ? "Demo mode" : "Debt breakdown unavailable"} testID="debtmix-unavailable">{d.reason}</Banner>
        : (
          <View style={{ gap: space.sm }} testID="debtmix-body">
            <Txt variant="label">Total public debt · {d.date}{d.freshness === "OVERDUE" ? " · overdue" : ""}</Txt>
            <Txt variant="hero">{money(d.total_billions!)}</Txt>
            <Txt variant="small">{money(d.held_by_public_billions!)} held by the public · {money(d.held_by_government_accounts_billions!)} owed to government accounts</Txt>
            {d.bills_share_of_marketable_pct != null ? <Txt variant="tiny">Short-term bills are {d.bills_share_of_marketable_pct}% of marketable debt. Change since {d.since}: {money(Math.abs(d.change_since_billions!))} {d.change_since_billions! >= 0 ? "more" : "less"} ({d.months_covered} month-ends).</Txt> : null}
            {(d.rows ?? []).filter((r) => !r.name.startsWith("Total")).map((r) => (
              <View key={r.name} style={{ gap: 2 }}>
                <Divider />
                <Txt variant="label">{r.name}</Txt>
                <Txt variant="h2">{money(r.billions)} · {r.share_of_total_pct.toFixed(1)}%</Txt>
                <Txt variant="tiny">{chg(r.change_month_billions)}</Txt>
              </View>))}
            <Txt variant="tiny">{d.note}</Txt>
          </View>)}
      {link ? <Pressable onPress={() => Linking.openURL(link).catch(() => undefined)} accessibilityRole="link"><Txt variant="tiny" c={color.accent}>Source: US Treasury FiscalData</Txt></Pressable> : null}
    </GCard>
  );
}
