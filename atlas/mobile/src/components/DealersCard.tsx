import React from "react";
import { Linking, Pressable, View } from "react-native";
import { safeUrl } from "../lib/links";
import { useDealers } from "../state/queries";
import { color, space } from "../theme";
import { Banner, Divider, GCard, Skeleton, Txt } from "./ui";

const day = (iso?: string | null) => (iso ? new Date(`${iso}T12:00:00Z`).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" }) : "");
const plain = (x: number) => `$${x.toLocaleString("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 })}B`;
const move = (x: number | null | undefined) => (x == null ? "No change shown (a week is missing in the source)" : x === 0 ? "Unchanged from the week before" : `${x > 0 ? "Up" : "Down"} ${plain(Math.abs(x))} from the week before`);

/** Primary dealers' net position in US Treasuries (New York Fed), weekly. Describes what already happened; not a signal. */
export function DealersCard() {
  const q = useDealers();
  const d = q.data;
  const link = safeUrl(d?.url ?? null);
  return (
    <GCard style={{ padding: space.lg, gap: space.md }} testID="dealers-card">
      <View><Txt variant="h2">Dealer Treasury positions</Txt><Txt variant="tiny">What the big Treasury dealers hold, from the New York Fed</Txt></View>
      {q.isLoading ? <Skeleton h={80} />
        : q.isError || !d ? <Banner tone="warn" title="Couldn't load the dealer positions" testID="dealers-error">{q.error instanceof Error ? q.error.message : "Something went wrong."}</Banner>
        : !d.available ? <Banner tone={d.demo ? "demo" : "warn"} title={d.demo ? "Demo mode" : "Dealer positions unavailable"} testID="dealers-unavailable">{d.reason}</Banner>
        : (
          <View style={{ gap: space.sm }} testID="dealers-body">
            <Txt variant="label">Net position in US Treasuries · as of {day(d.date)}{d.freshness === "OVERDUE" ? " · overdue" : ""}</Txt>
            <Txt variant="hero">{plain(d.net_position_billions!)}</Txt>
            <Txt variant="small">{move(d.week_change_billions)}.</Txt>
            <Txt variant="tiny">Same week a year earlier ({day(d.year_ago_date)}): {d.year_ago_billions != null ? plain(d.year_ago_billions) : "not available"}</Txt>
            {d.range_52w ? (<>
              <Divider />
              <Txt variant="label">Last {d.range_52w.weeks} weeks</Txt>
              <Txt variant="small">Low {plain(d.range_52w.low_billions)} ({day(d.range_52w.low_date)}) · high {plain(d.range_52w.high_billions)} ({day(d.range_52w.high_date)})</Txt>
              <Txt variant="tiny">Higher than {d.range_52w.weeks_lower_than_now} of those {d.range_52w.weeks} weeks.</Txt>
            </>) : null}
            {d.check ? <Txt variant="tiny" c={d.check.match ? undefined : color.down}>{d.check.match ? `Checked: the week-to-week changes equal the source's own change figures for the last ${d.check.weeks} weeks.` : "DOES NOT MATCH: the week-to-week changes differ from the source's own change figures."}</Txt> : null}
            <Txt variant="tiny">{d.note}</Txt>
          </View>)}
      {link ? <Pressable onPress={() => Linking.openURL(link).catch(() => undefined)} accessibilityRole="link"><Txt variant="tiny" c={color.accent}>Source: New York Fed, Primary Dealer Statistics</Txt></Pressable> : null}
    </GCard>
  );
}
