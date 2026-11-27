import React from "react";
import { View } from "react-native";
import type { JoltsRange, UsJobsRate } from "../api/types";
import { ymdLabel } from "../lib/format";
import { safeUrl } from "../lib/links";
import { useUsJobs } from "../state/queries";
import { space } from "../theme";
import { Banner, Divider, GCard, Skeleton, SourceLink, Txt } from "./ui";

const jobs = (k: number) => `${(k / 1000).toFixed(3)} million`;
const people = (k: number) => `${(k / 1000).toFixed(3)} million`;
const n = (k: number) => Math.abs(k).toLocaleString("en-US", { maximumFractionDigits: 1 });
const swing = (k: number) => (k === 0 ? "unchanged" : `${k > 0 ? "up" : "down"} ${n(k)} thousand`);
const moved = (k: number) => (k === 0 ? "changed by nothing" : `${k > 0 ? "added" : "lost"} ${n(k)} thousand`);
const span = (r: JoltsRange) =>
  `Over the last ${Math.round(r.months / 12)} years (${r.months} months with a figure) the unemployment rate ran from ${r.lowest.value.toFixed(1)}% (${ymdLabel(r.lowest.month)}) to ${r.highest.value.toFixed(1)}% (${ymdLabel(r.highest.month)}); ${r.share_lower_pct}% of those months were lower than now.`;
const before = (r: UsJobsRate) => (r.month_before_pct == null ? "no figure for the month before" : r.month_before_pct === r.pct ? "unchanged from the month before" : `${r.pct > r.month_before_pct ? "up" : "down"} from ${r.month_before_pct.toFixed(1)}% the month before`);
const yearAgo = (r: UsJobsRate, gaps: string[], month: string) => {
  if (r.year_ago_pct != null) return `${r.year_ago_pct.toFixed(1)}% a year earlier`;
  const y = `${+month.slice(0, 4) - 1}-${month.slice(5, 7)}`;
  return gaps.includes(y) ? `a year earlier: the household survey has no figure for ${ymdLabel(y)}` : "no figure for a year earlier";
};

/** The US jobs report (the Bureau of Labor Statistics' Employment Situation, via FRED), monthly. Describes what already happened; not a signal or a forecast. */
export function UsJobsCard() {
  const q = useUsJobs();
  const d = q.data;
  const link = safeUrl(d?.url ?? null);
  return (
    <GCard style={{ padding: space.lg, gap: space.md }} testID="usjobs-card">
      <View><Txt variant="h2">US jobs and unemployment</Txt><Txt variant="tiny">The monthly jobs report from the Bureau of Labor Statistics: jobs at employers and the unemployment rate</Txt></View>
      {q.isLoading ? <Skeleton h={80} />
        : q.isError || !d ? <Banner tone="warn" title="Couldn't load the US jobs report" testID="usjobs-error">{q.error instanceof Error ? q.error.message : "Something went wrong."}</Banner>
        : !d.available || !d.month || !d.payrolls || !d.household || !d.household_gaps || !d.detail ? <Banner tone={d.demo ? "demo" : "warn"} title={d.demo ? "Demo mode" : "US jobs report unavailable"} testID="usjobs-unavailable">{d.reason}</Banner>
        : (
          <View style={{ gap: space.sm }} testID="usjobs-body">
            <Txt variant="label">{ymdLabel(d.month)} · monthly · seasonally adjusted{d.freshness === "OVERDUE" ? " · overdue" : ""}</Txt>
            <Txt variant="small" testID="usjobs-payrolls">Employers had {jobs(d.payrolls.level_thousands)} jobs on their payrolls in {ymdLabel(d.month)}, {swing(d.payrolls.change_thousands)} on the month before and {swing(d.payrolls.change_year_thousands)} on a year earlier. Of the change on the month, private employers {moved(d.payrolls.private.change_thousands)} and government {moved(d.payrolls.government.change_thousands)}.</Txt>
            <Txt variant="label">Jobs added by month</Txt>
            <View style={{ gap: space.sm }} testID="usjobs-recent">
              {d.payrolls.recent.map((r) => <Txt key={r.month} variant="small" testID={`usjobs-month-${r.month}`}>{ymdLabel(r.month)}: {swing(r.change_thousands)}</Txt>)}
            </View>
            <Divider />
            <Txt variant="small" testID="usjobs-unemployment">The unemployment rate was {d.household.unemployment_rate.pct.toFixed(1)}% in {ymdLabel(d.month)}, {before(d.household.unemployment_rate)} ({yearAgo(d.household.unemployment_rate, d.household_gaps, d.month)}). {people(d.household.unemployed_thousands)} people were unemployed, out of a labour force of {people(d.household.labour_force_thousands)}.</Txt>
            <Txt variant="tiny">{span(d.household.range)}</Txt>
            <Txt variant="small" testID="usjobs-participation">{d.household.participation_rate.pct.toFixed(1)}% of the population aged 16 and over was working or looking for work, {before(d.household.participation_rate)}; {d.household.employment_ratio.pct.toFixed(1)}% had a job, {before(d.household.employment_ratio)}.</Txt>
            {d.household_gaps.length ? <Txt variant="tiny" testID="usjobs-gaps">The household survey has no figure for {d.household_gaps.map((m) => ymdLabel(m)).join(", ")}.</Txt> : null}
            <Txt variant="tiny">Check: in each of the {d.detail.months_checked} months from {ymdLabel(d.detail.first_month)} to {ymdLabel(d.detail.last_month)} the three payroll series covered the same months with none missing and every level lay inside its range, and the seven household series covered the same months ({d.detail.household_months_checked} of them with a figure) (plain checks, not the source's sums); three checks that follow from the survey's own definitions held: total payrolls equal private plus government payrolls (largest gap {d.detail.largest_payroll_gap} thousand), the labour force equals the employed plus the unemployed (largest gap {d.detail.largest_labour_force_gap} thousand, which is rounding), and each published rate equals its own numerator over its own denominator (largest gap {d.detail.largest_rate_gap} points, which is rounding). These show the series belong together, not that the figures are right.</Txt>
            <Txt variant="tiny">{d.note}</Txt>
          </View>)}
      <SourceLink url={link}>Source: US Bureau of Labor Statistics (Employment Situation), via FRED</SourceLink>
    </GCard>
  );
}
