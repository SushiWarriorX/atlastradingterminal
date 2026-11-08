import React from "react";
import { Linking, Pressable, View } from "react-native";
import { safeUrl } from "../lib/links";
import { useDebtRates } from "../state/queries";
import { color, space } from "../theme";
import { Banner, Divider, GCard, Skeleton, Txt } from "./ui";

const pp = (x: number | null, what: string) => (x == null ? `no ${what} to compare` : `${x > 0 ? "+" : x < 0 ? "−" : ""}${Math.abs(x).toFixed(3)} pts vs ${what}`);

/** Average interest rate the US government pays on its debt, by security type. Describes what it pays on what it owes; not a signal. */
export function DebtRatesCard() {
  const q = useDebtRates();
  const d = q.data;
  const link = safeUrl(d?.url ?? null);
  return (
    <GCard style={{ padding: space.lg, gap: space.md }} testID="debtrates-card">
      <View><Txt variant="h2">Interest the Treasury pays</Txt><Txt variant="tiny">Average rate on all debt it owes, from the US Treasury</Txt></View>
      {q.isLoading ? <Skeleton h={80} />
        : q.isError || !d ? <Banner tone="warn" title="Couldn't load Treasury interest rates" testID="debtrates-error">{q.error instanceof Error ? q.error.message : "Something went wrong."}</Banner>
        : !d.available ? <Banner tone={d.demo ? "demo" : "warn"} title={d.demo ? "Demo mode" : "Treasury interest rates unavailable"} testID="debtrates-unavailable">{d.reason}</Banner>
        : (
          <View style={{ gap: space.sm }} testID="debtrates-body">
            {(d.rows ?? []).map((r, i) => (
              <View key={r.name} style={{ gap: 2 }}>
                {i > 0 ? <Divider /> : null}
                <Txt variant="label">{r.name}{i === 0 ? ` · ${d.date}${d.freshness === "OVERDUE" ? " · overdue" : ""}` : ""}</Txt>
                <Txt variant="h2">{r.rate.toFixed(3)}%</Txt>
                <Txt variant="tiny">{pp(r.change_month, "last month")} · {pp(r.change_year, "a year ago")}</Txt>
              </View>))}
            <Txt variant="tiny">{d.note}</Txt>
          </View>)}
      {link ? <Pressable onPress={() => Linking.openURL(link).catch(() => undefined)} accessibilityRole="link"><Txt variant="tiny" c={color.accent}>Source: US Treasury FiscalData</Txt></Pressable> : null}
    </GCard>
  );
}
