import React from "react";
import { View } from "react-native";
import type { JoltsRange } from "../api/types";
import { ymdLabel } from "../lib/format";
import { safeUrl } from "../lib/links";
import { useJolts } from "../state/queries";
import { space } from "../theme";
import { Banner, Divider, GCard, Skeleton, SourceLink, Txt } from "./ui";

const amount = (k: number) => (k >= 1000 ? `${(k / 1000).toFixed(3)} million` : `${Math.round(k).toLocaleString("en-US")} thousand`);
const vs = (x: number | null | undefined, when: string) => (x == null ? `not available against ${when}` : x === 0 ? `the same as ${when}` : `${x > 0 ? "up" : "down"} ${Math.abs(x).toFixed(1)}% on ${when}`);
const step = (k: number) => (k === 0 ? "unchanged on the month before" : `${k > 0 ? "up" : "down"} ${Math.abs(k).toLocaleString("en-US", { maximumFractionDigits: 1 })} thousand on the month before`);
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
const span = (r: JoltsRange, show: (v: number) => string, now: string) =>
  `Over the last ${Math.round(r.months / 12)} years (${r.months} months) it ran from ${show(r.lowest.value)} (${ymdLabel(r.lowest.month)}) to ${show(r.highest.value)} (${ymdLabel(r.highest.month)}); ${r.share_lower_pct}% of those months were lower than ${now}.`;

/** US job openings and labour turnover (Bureau of Labor Statistics JOLTS, with payroll employment and unemployed persons, via FRED), monthly. Describes what already happened; not a signal or a forecast. */
export function JoltsCard() {
  const q = useJolts();
  const d = q.data;
  const link = safeUrl(d?.url ?? null);
  return (
    <GCard style={{ padding: space.lg, gap: space.md }} testID="jolts-card">
      <View><Txt variant="h2">Job openings and turnover</Txt><Txt variant="tiny">How many jobs US employers have open, and how many people they hire and lose, monthly, from the Bureau of Labor Statistics</Txt></View>
      {q.isLoading ? <Skeleton h={80} />
        : q.isError || !d ? <Banner tone="warn" title="Couldn't load US job openings" testID="jolts-error">{q.error instanceof Error ? q.error.message : "Something went wrong."}</Banner>
        : !d.available || !d.month || !d.openings || !d.per_unemployed || !d.flows || !d.detail ? <Banner tone={d.demo ? "demo" : "warn"} title={d.demo ? "Demo mode" : "US job openings unavailable"} testID="jolts-unavailable">{d.reason}</Banner>
        : (
          <View style={{ gap: space.sm }} testID="jolts-body">
            <Txt variant="label">{ymdLabel(d.month)} · monthly · seasonally adjusted{d.freshness === "OVERDUE" ? " · overdue" : ""}</Txt>
            <Txt variant="small" testID="jolts-openings">Employers had {amount(d.openings.level_thousands)} job openings at the end of {ymdLabel(d.month)}, {step(d.openings.change_1m_thousands)} and {vs(d.openings.change_1y_pct, "a year ago")}. The openings rate, the share of all jobs (filled and open) that were open, was {d.openings.rate_pct.toFixed(1)}% ({d.openings.rate_year_ago_pct.toFixed(1)}% a year ago).</Txt>
            <Txt variant="tiny">{span(d.openings.range, (v) => `${v.toFixed(1)}%`, "now")}</Txt>
            <Divider />
            <Txt variant="small" testID="jolts-ratio">In {ymdLabel(d.per_unemployed.month)} there were {d.per_unemployed.ratio.toFixed(2)} job openings for each unemployed person ({amount(d.per_unemployed.unemployed_thousands)} people were unemployed), {d.per_unemployed.year_ago == null ? "and no figure for a year earlier is available" : `against ${d.per_unemployed.year_ago.toFixed(2)} a year earlier`}.</Txt>
            <Txt variant="tiny">{span(d.per_unemployed.range, (v) => v.toFixed(2), "now")}</Txt>
            <Divider />
            <Txt variant="label">Hires and separations in {ymdLabel(d.month)}</Txt>
            <View style={{ gap: space.sm }} testID="jolts-flows">
              {d.flows.map((f) => (
                <Txt key={f.id} variant="small" testID={`jolts-flow-${f.id}`}>{cap(f.name)}: {amount(f.level_thousands)}, {f.rate_pct.toFixed(1)}% of payroll employment ({f.rate_year_ago_pct.toFixed(1)}% a year ago), {vs(f.change_1y_pct, "a year ago")}.</Txt>
              ))}
            </View>
            <Txt variant="tiny">Check: in each of the {d.detail.months_checked} months from {ymdLabel(d.detail.first_month)} to {ymdLabel(d.detail.last_month)} the twelve JOLTS series covered the same months with none missing, every level lay inside its range and payroll employment was there for each month (plain checks, not the source's sums); two checks that follow from the survey's own definitions held: total separations equal quits plus layoffs plus other separations (largest gap {d.detail.largest_separations_gap} thousand, which is rounding), and each published rate equals its level over payroll employment, job openings over payroll employment plus openings (largest gap {d.detail.largest_rate_gap} points, which is rounding). These show the series belong together, not that the figures are right.</Txt>
            <Txt variant="tiny">{d.note}</Txt>
          </View>)}
      <SourceLink url={link}>Source: US Bureau of Labor Statistics (JOLTS, Current Employment Statistics, Current Population Survey), via FRED</SourceLink>
    </GCard>
  );
}
