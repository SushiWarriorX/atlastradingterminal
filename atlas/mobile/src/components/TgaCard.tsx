import React from "react";
import { Linking, Pressable, View } from "react-native";
import { safeUrl } from "../lib/links";
import { useTga } from "../state/queries";
import { color, space } from "../theme";
import { Banner, GCard, Skeleton, Txt } from "./ui";

const b = (x: number) => `$${x.toFixed(1)}B`;
const chg = (x: number) => `${x > 0 ? "+" : x < 0 ? "−" : ""}$${Math.abs(x).toFixed(1)}B`;

/** The US Treasury's cash balance at the Fed (Daily Treasury Statement). Describes where cash sits; not a signal. */
export function TgaCard() {
  const q = useTga();
  const d = q.data;
  const link = safeUrl(d?.url ?? null);
  return (
    <GCard style={{ padding: space.lg, gap: space.md }} testID="tga-card">
      <View><Txt variant="h2">Treasury cash balance</Txt><Txt variant="tiny">The government's account at the Fed, from the US Treasury</Txt></View>
      {q.isLoading ? <Skeleton h={80} />
        : q.isError || !d ? <Banner tone="warn" title="Couldn't load the Treasury balance" testID="tga-error">{q.error instanceof Error ? q.error.message : "Something went wrong."}</Banner>
        : !d.available ? <Banner tone={d.demo ? "demo" : "warn"} title={d.demo ? "Demo mode" : "Treasury balance unavailable"} testID="tga-unavailable">{d.reason}</Banner>
        : (
          <View style={{ gap: space.sm }} testID="tga-body">
            <Txt variant="hero">{b(d.balance_billions!)}</Txt>
            <Txt variant="small">{chg(d.change_1d_billions!)} on the day{d.change_month_billions != null ? ` · ${chg(d.change_month_billions)} over about a month` : ""} · {d.date}{d.freshness === "OVERDUE" ? " · overdue" : ""}</Txt>
            <Txt variant="tiny">Month average {b(d.month_average_billions!)}. Past year: low {b(d.year_low_billions!)} on {d.year_low_date}, high {b(d.year_high_billions!)} on {d.year_high_date}.</Txt>
            <Txt variant="tiny">{d.note}</Txt>
          </View>)}
      {link ? <Pressable onPress={() => Linking.openURL(link).catch(() => undefined)} accessibilityRole="link"><Txt variant="tiny" c={color.accent}>Source: US Treasury FiscalData</Txt></Pressable> : null}
    </GCard>
  );
}
