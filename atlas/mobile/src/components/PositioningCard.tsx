import React from "react";
import { View } from "react-native";
import { usePositioning } from "../state/queries";
import { color, space } from "../theme";
import { Banner, Divider, GCard, Skeleton, Txt } from "./ui";

const n = (x: number) => x.toLocaleString("en-US");
const sgn = (x: number | null | undefined) => (x === null || x === undefined ? "n/a" : `${x > 0 ? "+" : x < 0 ? "−" : ""}${n(Math.abs(x))}`);
const tone = (x: number | null | undefined) => (x === null || x === undefined ? color.dim : x > 0 ? color.up : x < 0 ? color.down : color.text);

/** Who holds CME Bitcoin futures (CFTC Commitments of Traders): weekly, official, dated. Describes positions; not a signal. */
export function PositioningCard() {
  const q = usePositioning();
  const d = q.data;
  return (
    <GCard style={{ padding: space.lg, gap: space.md }} testID="positioning-card">
      <View><Txt variant="h2">Bitcoin futures positioning</Txt><Txt variant="tiny">Who holds CME Bitcoin futures, from the CFTC's weekly report</Txt></View>
      {q.isLoading ? <Skeleton h={90} />
        : q.isError || !d ? <Banner tone="warn" title="Couldn't load positioning" testID="positioning-error">{q.error instanceof Error ? q.error.message : "Something went wrong."}</Banner>
        : !d.available ? <Banner tone={d.demo ? "demo" : "warn"} title={d.demo ? "Demo mode" : "Positioning unavailable"} testID="positioning-unavailable">{d.reason}</Banner>
        : (
          <View style={{ gap: space.sm }} testID="positioning-body">
            <Txt variant="small">As of {d.date}{d.freshness === "OVERDUE" ? " · overdue" : ""} · {n(d.open_interest!)} contracts open{d.open_interest_change != null ? ` (${sgn(d.open_interest_change)} on the week)` : ""}</Txt>
            {d.groups!.map((g, i) => (
              <View key={g.key}>{i > 0 && <Divider />}
                <View style={{ paddingVertical: 4, gap: 2 }}>
                  <View style={{ flexDirection: "row", justifyContent: "space-between" }}><Txt variant="body">{g.name}</Txt><Txt variant="body" c={tone(g.net)}>Net {sgn(g.net)}</Txt></View>
                  <Txt variant="tiny">Long {n(g.long)} ({g.long_pct_oi}% of open interest) · short {n(g.short)} ({g.short_pct_oi}%) · {sgn(g.net_change)} net vs last week{g.net_rank_1y !== null ? ` · rank ${g.net_rank_1y} of 100 over a year` : ""}</Txt>
                  <Txt variant="tiny">{g.who}</Txt>
                </View>
              </View>))}
            <Txt variant="tiny">{d.note}</Txt>
          </View>)}
    </GCard>
  );
}
