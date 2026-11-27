import React from "react";
import { View } from "react-native";
import { ymdLabel } from "../lib/format";
import { safeUrl } from "../lib/links";
import { useEuroYields } from "../state/queries";
import { space } from "../theme";
import { Banner, Divider, GCard, Skeleton, SourceLink, Txt } from "./ui";

const pct = (x: number) => `${x.toFixed(2)}%`;
const moved = (change: number) => (change === 0 ? "unchanged" : `${change > 0 ? "up" : "down"} ${Math.abs(change).toFixed(2)}`);

/** Euro-area government bond yields (the ECB's yield curve for AAA-rated euro-area government bonds, published on the ECB Data Portal), daily. Describes yields that already happened; not a signal or a forecast. */
export function EuroYieldsCard() {
  const q = useEuroYields();
  const d = q.data;
  const link = safeUrl(d?.url ?? null);
  const rate = (id: string) => d?.rates?.find((r) => r.id === id);
  const ten = rate("SR_10Y"), two = rate("SR_2Y"), three = rate("SR_3M");
  return (
    <GCard style={{ padding: space.lg, gap: space.md }} testID="euroyields-card">
      <View><Txt variant="h2">Euro-area government bond yields</Txt><Txt variant="tiny">The ECB's fitted yield curve for AAA-rated euro-area government bonds, daily</Txt></View>
      {q.isLoading ? <Skeleton h={80} />
        : q.isError || !d ? <Banner tone="warn" title="Couldn't load the euro-area yields" testID="euroyields-error">{q.error instanceof Error ? q.error.message : "Something went wrong."}</Banner>
        : !d.available || !d.rates || !ten || !two || !three || !d.spreads || !d.detail ? <Banner tone={d.demo ? "demo" : "warn"} title={d.demo ? "Demo mode" : "Euro-area yields unavailable"} testID="euroyields-unavailable">{d.reason}</Banner>
        : (
          <View style={{ gap: space.sm }} testID="euroyields-body">
            <Txt variant="label">{ymdLabel(d.date)} · daily · AAA-rated euro-area government bonds{d.provisional ? " · provisional" : ""}{d.freshness === "OVERDUE" ? " · overdue" : ""}</Txt>
            <Txt variant="small">On {ymdLabel(d.date)} the ECB's curve for AAA-rated euro-area government bonds gave {pct(ten.rate_pct)} for 10 years, {pct(two.rate_pct)} for 2 years and {pct(three.rate_pct)} for 3 months (spot rates).</Txt>
            {d.window ? <Txt variant="tiny">Over the past {d.window.years} years ({d.window.days.toLocaleString("en-US")} days) the 10-year rate was lower than now on {d.window.share_lower_pct}% of the days; the middle day was {pct(d.window.median)}, the lowest {pct(d.window.lowest.value)} ({ymdLabel(d.window.lowest.date)}) and the highest {pct(d.window.highest.value)} ({ymdLabel(d.window.highest.date)}).</Txt> : null}
            <Divider />
            <Txt variant="label">Spot rates by maturity</Txt>
            {d.rates.map((r) => (
              <Txt key={r.id} variant="small" testID={`euroyields-rate-${r.id}`}>
                {r.label}: {pct(r.rate_pct)}{r.week_ago || r.month_ago ? ` (${[r.week_ago ? `${moved(r.week_ago.change)} on a week ago` : "", r.month_ago ? `${moved(r.month_ago.change)} on a month ago` : ""].filter(Boolean).join(", ")})` : ""}
              </Txt>
            ))}
            <Txt variant="tiny">The ECB's own spreads of the 10-year rate over the shorter ones, in percentage points: {d.spreads.map((s, i) => (i === 0 ? `${s.label}: ${s.points.toFixed(2)} points` : `${s.label.replace("10 years ", "")}: ${s.points.toFixed(2)}`)).join("; ")}.</Txt>
            <Txt variant="tiny">Check: in each of the last {d.detail.days_checked.toLocaleString("en-US")} days the 10-year rate, and in each of the last {d.detail.rate_days_checked} days every other rate and spread, lay inside its range and moved by no more than the real record allows, and the six model parameters of the newest day lay inside theirs (plain checks, not the ECB's sums); and two checks that are the ECB's own arithmetic held: each spread equals the 10-year rate minus the shorter one on each of the last {d.detail.rate_days_checked} days (largest gap within 0.000001), and on the newest day each rate equals the ECB's fitted curve evaluated with its published parameters (largest gap within 0.000001). They show the series belong together, not that the figures are right.</Txt>
            <Txt variant="tiny">{d.note}</Txt>
          </View>)}
      <SourceLink url={link}>Source: European Central Bank (euro-area yield curve for AAA-rated government bonds), via the ECB Data Portal</SourceLink>
    </GCard>
  );
}
