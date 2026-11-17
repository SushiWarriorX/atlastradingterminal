import React from "react";
import { View } from "react-native";
import { ymdLabel } from "../lib/format";
import { safeUrl } from "../lib/links";
import { useEuroUnemployment } from "../state/queries";
import { space } from "../theme";
import { Banner, Divider, GCard, Skeleton, SourceLink, Txt } from "./ui";

const pct = (x: number) => `${x.toFixed(1)}%`;
const millions = (thousands: number) => `${(thousands / 1000).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} million`;
const moved = (x: number | null | undefined, when: string) => (x == null ? `not available against ${when}` : x === 0 ? `the same as ${when}` : `${x > 0 ? "up" : "down"} ${Math.abs(x).toFixed(1)} points on ${when}`);
const people = (x: number | null | undefined) => (x == null ? "" : x === 0 ? " The number of unemployed is the same as a year ago." : ` There are ${Math.round(Math.abs(x)).toLocaleString("en-US")} thousand ${x > 0 ? "more" : "fewer"} unemployed people than a year ago.`);
const thousands = (x: number) => `${x.toFixed(1)} thousand`;

/** Euro-area unemployment (the European Labour Force Survey, compiled by Eurostat, published on the ECB Data Portal), monthly. Describes what already happened; not a signal or a forecast. */
export function EuroUnemploymentCard() {
  const q = useEuroUnemployment();
  const d = q.data;
  const link = safeUrl(d?.url ?? null);
  return (
    <GCard style={{ padding: space.lg, gap: space.md }} testID="eurounemployment-card">
      <View><Txt variant="h2">Euro-area unemployment</Txt><Txt variant="tiny">How many people in the euro area are out of work, monthly, and who they are</Txt></View>
      {q.isLoading ? <Skeleton h={80} />
        : q.isError || !d ? <Banner tone="warn" title="Couldn't load the euro-area unemployment" testID="eurounemployment-error">{q.error instanceof Error ? q.error.message : "Something went wrong."}</Banner>
        : !d.available || !d.headline || !d.persons || !d.groups || !d.detail ? <Banner tone={d.demo ? "demo" : "warn"} title={d.demo ? "Demo mode" : "Euro-area unemployment unavailable"} testID="eurounemployment-unavailable">{d.reason}</Banner>
        : (
          <View style={{ gap: space.sm }} testID="eurounemployment-body">
            <Txt variant="label">{ymdLabel(d.month)}, seasonally adjusted{d.provisional ? " · provisional" : ""}{d.freshness === "OVERDUE" ? " · overdue" : ""}</Txt>
            <Txt variant="small">In {ymdLabel(d.month)}, {d.headline.rate_pct.toFixed(1)}% of the euro area's labour force was unemployed: {millions(d.persons.total_thousands)} people (the euro area of 20 countries).</Txt>
            <Txt variant="tiny">The rate was {moved(d.headline.change_1m_points, "a month ago")}, {moved(d.headline.change_3m_points, "three months ago")} and {moved(d.headline.change_12m_points, "a year ago")}.{people(d.persons.change_12m_thousands)}{d.range ? ` Over the past 10 years (${d.range.months} months), the rate ran from ${pct(d.range.lowest.pct)} (${ymdLabel(d.range.lowest.month)}) to ${pct(d.range.highest.pct)} (${ymdLabel(d.range.highest.month)}); ${d.range.share_lower_pct}% of those months were lower than now.` : ""}</Txt>
            <Divider />
            <Txt variant="label">Who they are</Txt>
            {d.groups.map((g) => <Txt key={g.id} variant="small" testID={`eurounemployment-group-${g.id}`}>Unemployment among {g.label}: {g.rate_pct.toFixed(1)}%.</Txt>)}
            <Txt variant="tiny">Of the {millions(d.persons.total_thousands)} unemployed, {d.persons.women_share_pct}% are women and {d.persons.youth_share_pct}% are under 25 (calculated here from the published numbers).</Txt>
            <Txt variant="tiny">Check: in each of the last {d.detail.months_checked} months the rate for everybody lay between the rates of women and men and between those of the under 25 and the 25 to 74 (neither is Eurostat's own sum), and three checks that are Eurostat's own arithmetic held: the unemployed of the parts add up to the total (largest gap {thousands(d.detail.largest_sum_gap_thousands)}), and the labour force implied by the parts agrees with the one for everybody (largest gap {d.detail.largest_labour_force_gap_pct.toFixed(2)}%{d.detail.largest_labour_force_gap_month ? `, ${ymdLabel(d.detail.largest_labour_force_gap_month)}` : ""}). They show the series belong together, not that the figures are right.</Txt>
            <Txt variant="tiny">{d.note}</Txt>
          </View>)}
      <SourceLink url={link}>Source: Eurostat (European Labour Force Survey), via the European Central Bank's Data Portal</SourceLink>
    </GCard>
  );
}
