import React from "react";
import { View } from "react-native";
import { safeUrl } from "../lib/links";
import { billions, dayText, dealerCheck } from "../lib/dealers";
import { useDealers } from "../state/queries";
import { color, space } from "../theme";
import { Banner, Divider, GCard, Skeleton, SourceLink, Txt } from "./ui";

const move = (x: number | null | undefined) => (x == null ? "No change shown (a week is missing in the source)" : x === 0 ? "Unchanged from the week before" : `${x > 0 ? "Up" : "Down"} ${billions(Math.abs(x))} from the week before`);

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
            <Txt variant="label">Net position in US Treasuries · as of {dayText(d.date)}{d.freshness === "OVERDUE" ? " · overdue" : ""}</Txt>
            <Txt variant="hero">{billions(d.net_position_billions!)}</Txt>
            <Txt variant="small">{move(d.week_change_billions)}.</Txt>
            <Txt variant="tiny">Same week a year earlier ({dayText(d.year_ago_date)}): {d.year_ago_billions != null ? billions(d.year_ago_billions) : "not available"}</Txt>
            {d.range_52w ? (<>
              <Divider />
              <Txt variant="label">Last {d.range_52w.weeks} weeks</Txt>
              <Txt variant="small">Low {billions(d.range_52w.low_billions)} ({dayText(d.range_52w.low_date)}) · high {billions(d.range_52w.high_billions)} ({dayText(d.range_52w.high_date)})</Txt>
              <Txt variant="tiny">Higher than {d.range_52w.weeks_lower_than_now} of those {d.range_52w.weeks} weeks.</Txt>
            </>) : null}
            {d.check ? <Txt variant="tiny" c={dealerCheck(d.check).red ? color.down : undefined} testID="dealers-check">{dealerCheck(d.check).text}</Txt> : null}
            <Txt variant="tiny">{d.note}</Txt>
          </View>)}
      <SourceLink url={link}>Source: New York Fed, Primary Dealer Statistics</SourceLink>
    </GCard>
  );
}
