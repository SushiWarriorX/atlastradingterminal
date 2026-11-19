import React from "react";
import { View } from "react-native";
import { ymdLabel } from "../lib/format";
import { safeUrl } from "../lib/links";
import { useEuroStress } from "../state/queries";
import { space } from "../theme";
import { Banner, Divider, GCard, Skeleton, SourceLink, Txt } from "./ui";

const idx = (x: number) => x.toFixed(4);                                  // the ECB's own four decimals
const now = (change: number) => (change === 0 ? "unchanged" : `${change > 0 ? "up" : "down"} ${Math.abs(change).toFixed(4)}`);
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

/** Euro-area financial stress (the ECB's New Composite Indicator of Systemic Stress, published on the ECB Data Portal), daily. Describes stress that already happened; not a signal or a forecast. */
export function EuroStressCard() {
  const q = useEuroStress();
  const d = q.data;
  const link = safeUrl(d?.url ?? null);
  return (
    <GCard style={{ padding: space.lg, gap: space.md }} testID="eurostress-card">
      <View><Txt variant="h2">Euro-area financial stress</Txt><Txt variant="tiny">The ECB's index of stress in the euro area's financial markets, daily</Txt></View>
      {q.isLoading ? <Skeleton h={80} />
        : q.isError || !d ? <Banner tone="warn" title="Couldn't load the euro-area financial stress" testID="eurostress-error">{q.error instanceof Error ? q.error.message : "Something went wrong."}</Banner>
        : !d.available || d.index == null || !d.segments || d.segments_total == null || d.correlation == null || !d.detail ? <Banner tone={d.demo ? "demo" : "warn"} title={d.demo ? "Demo mode" : "Euro-area financial stress unavailable"} testID="eurostress-unavailable">{d.reason}</Banner>
        : (
          <View style={{ gap: space.sm }} testID="eurostress-body">
            <Txt variant="label">{ymdLabel(d.date)} · daily · euro area, changing composition{d.provisional ? " · provisional" : ""}{d.freshness === "OVERDUE" ? " · overdue" : ""}</Txt>
            <Txt variant="small">On {ymdLabel(d.date)} the ECB's index of systemic stress in the euro area's financial markets stood at {idx(d.index)} (the scale runs from 0 to 1; higher means more stress).</Txt>
            <Txt variant="tiny">
              {d.week_ago ? `A week ago (${ymdLabel(d.week_ago.date)}) it was ${idx(d.week_ago.value)}, now ${now(d.week_ago.change)}` : "Not available against a week ago"}
              {d.month_ago ? `; a month ago (${ymdLabel(d.month_ago.date)}) it was ${idx(d.month_ago.value)}, now ${now(d.month_ago.change)}.` : "; not available against a month ago."}
              {d.window ? ` Over the past ${d.window.years} years (${d.window.days.toLocaleString("en-US")} days), ${d.window.share_lower_pct}% of the days were calmer than now; the middle day was ${idx(d.window.median)}, the calmest ${idx(d.window.lowest.value)} (${ymdLabel(d.window.lowest.date)}) and the most stressed ${idx(d.window.highest.value)} (${ymdLabel(d.window.highest.date)}).` : ""}
            </Txt>
            <Divider />
            <Txt variant="label">What it is made of</Txt>
            {d.segments.map((s) => <Txt key={s.id} variant="small" testID={`eurostress-segment-${s.id}`}>{cap(s.label)}: {idx(s.contribution)}</Txt>)}
            <Txt variant="tiny">Together {idx(d.segments_total)}; the ECB's correlation term between the segments {idx(d.correlation)} (it has been negative on every day since 1999); index {idx(d.index)}. Figures are rounded, so they may not add exactly.</Txt>
            <Txt variant="tiny">Check: in each of the last {d.detail.days_checked.toLocaleString("en-US")} days the index lay between 0 and 1 and moved by at most 0.25 in a day, and in each of the last {d.detail.contribution_days_checked} days each segment contributed between 0 and 1 and the correlation term lay between -1 and 0 (properties, not the ECB's own sum); one check is the ECB's own arithmetic and held: the six contributions add up to the index (largest gap within 0.000001). It shows the series belong together, not that the figures are right.</Txt>
            <Txt variant="tiny">{d.note}</Txt>
          </View>)}
      <SourceLink url={link}>Source: European Central Bank (new Composite Indicator of Systemic Stress), via the ECB Data Portal</SourceLink>
    </GCard>
  );
}
