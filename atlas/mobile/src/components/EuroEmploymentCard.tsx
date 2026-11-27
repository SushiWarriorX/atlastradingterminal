import React from "react";
import { View } from "react-native";
import { safeUrl } from "../lib/links";
import { useEuroEmployment } from "../state/queries";
import { space } from "../theme";
import { Banner, Divider, GCard, Skeleton, SourceLink, Txt } from "./ui";

const quarter = (q: string) => `${q.slice(5)} ${q.slice(0, 4)}`;                       // 2026-Q3 is shown as Q3 2026
const move = (x: number) => (x > 0 ? `up ${x.toFixed(2)}%` : x < 0 ? `down ${Math.abs(x).toFixed(2)}%` : "unchanged");
const signed = (x: number) => (x > 0 ? `+${x.toFixed(2)}` : x < 0 ? `-${Math.abs(x).toFixed(2)}` : "0.00");
const thousands = (x: number) => (x > 0 ? `+${x.toLocaleString("en-US")}` : x < 0 ? `-${Math.abs(x).toLocaleString("en-US")}` : "0");
const million = (x: number) => `${x.toFixed(1)} million`;
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
const gap = (x: number) => (x < 0.000001 ? "under 0.000001" : x.toPrecision(2));        // the sums hold to floating-point noise; the backend rounds a gap to 9 or 12 decimals, so a zero means "smaller than that"

/** Euro-area employment and productivity (Eurostat's quarterly national accounts for the euro area, seasonally adjusted, published on the ECB Data Portal), quarterly. Describes what already happened; not a signal or a forecast. */
export function EuroEmploymentCard() {
  const q = useEuroEmployment();
  const d = q.data;
  const link = safeUrl(d?.url ?? null);
  return (
    <GCard style={{ padding: space.lg, gap: space.md }} testID="euroemployment-card">
      <View><Txt variant="h2">Euro-area employment and productivity</Txt><Txt variant="tiny">People in work and hours worked in the euro area (21 countries), and output per worker, quarterly, from the ECB</Txt></View>
      {q.isLoading ? <Skeleton h={80} />
        : q.isError || !d ? <Banner tone="warn" title="Couldn't load the euro-area employment" testID="euroemployment-error">{q.error instanceof Error ? q.error.message : "Something went wrong."}</Banner>
        : !d.available || !d.quarter || !d.jobs || !d.recent || !d.breakdown || !d.productivity || !d.detail ? <Banner tone={d.demo ? "demo" : "warn"} title={d.demo ? "Demo mode" : "Euro-area employment unavailable"} testID="euroemployment-unavailable">{d.reason}</Banner>
        : (
          <View style={{ gap: space.sm }} testID="euroemployment-body">
            <Txt variant="label">{quarter(d.quarter)} · quarterly · seasonally adjusted · people in work{d.provisional ? " · provisional" : ""}{d.freshness === "OVERDUE" ? " · overdue" : ""}</Txt>
            <Txt variant="small">{million(d.jobs.persons)} people were in work in {quarter(d.jobs.quarter)}, {move(d.jobs.quarter_on_quarter)} from the previous quarter ({quarter(d.jobs.previous_quarter)}) and {move(d.jobs.year_on_year)} from the same quarter a year earlier ({quarter(d.jobs.year_earlier)}).</Txt>
            <Divider />
            <Txt variant="label">People in work by quarter</Txt>
            <View style={{ gap: space.sm }} testID="euroemployment-recent">
              {d.recent.map((r) => (
                <Txt key={r.quarter} variant="small" testID={`euroemployment-quarter-${r.quarter}`}>{quarter(r.quarter)}: {million(r.persons)}, {signed(r.quarter_on_quarter)}% on the previous quarter, {signed(r.year_on_year)}% on a year earlier</Txt>
              ))}
            </View>
            <Divider />
            <Txt variant="label">Hours and who works</Txt>
            <View style={{ gap: space.sm }} testID="euroemployment-hours">
              <Txt variant="small">In {quarter(d.breakdown.quarter)} (the newest quarter with a breakdown) people worked {d.breakdown.hours.toFixed(1)} billion hours, {d.breakdown.hours_per_person.toFixed(1)} hours each in the quarter; hours worked were {move(d.breakdown.hours_change_year)} from a year earlier.</Txt>
              <Txt variant="small">Employees were {d.breakdown.employees.share.toFixed(1)}% of the people in work ({million(d.breakdown.employees.persons)}) and {d.breakdown.employees.hours_share.toFixed(1)}% of the hours; the self-employed were {d.breakdown.self_employed.share.toFixed(1)}% ({million(d.breakdown.self_employed.persons)}) and {d.breakdown.self_employed.hours_share.toFixed(1)}% of the hours.</Txt>
            </View>
            <Divider />
            <Txt variant="label">Jobs by activity, {quarter(d.breakdown.quarter)}</Txt>
            <View style={{ gap: space.sm }} testID="euroemployment-sectors">
              {d.breakdown.sectors.map((s) => (
                <Txt key={s.id} variant="small" testID={`euroemployment-sector-${s.id}`}>{cap(s.name)}: {million(s.persons)} people ({s.share.toFixed(1)}% of all jobs), {move(s.change_year)} ({thousands(s.change_year_thousands)} thousand) on a year earlier.</Txt>
              ))}
            </View>
            <Divider />
            <Txt variant="label">Output per worker</Txt>
            <View style={{ gap: space.sm }} testID="euroemployment-productivity">
              <Txt variant="small">Real GDP per person in work was {move(d.productivity.per_person.quarter_on_quarter)} on the previous quarter and {move(d.productivity.per_person.year_on_year)} on a year earlier ({quarter(d.productivity.per_person.quarter)}).</Txt>
              <Txt variant="small">Real GDP per hour worked was {move(d.productivity.per_hour.quarter_on_quarter)} on the previous quarter and {move(d.productivity.per_hour.year_on_year)} on a year earlier ({quarter(d.productivity.per_hour.quarter)}).</Txt>
            </View>
            <Txt variant="tiny">Check: in each of the last {d.detail.quarters_checked} quarters ({d.detail.persons_quarters_checked} for persons, where total employment is a quarter ahead of its breakdown) every figure lay inside its range and total employment moved by no more than 10% in a quarter (plain checks, not the source's sums); two checks that are Eurostat's own arithmetic held: the ten activities add up to total employment, and employees plus the self-employed add up to total employment, for persons (largest gap {gap(d.detail.largest_persons_gap)} thousand persons) and for hours (largest gap {gap(d.detail.largest_hours_gap)} thousand hours), which is rounding noise; and the ECB's productivity growth equals real GDP growth over employment growth (largest gap {gap(d.detail.largest_productivity_gap)} points), which the ECB calculates from them, so it proves the units and the quarters of three series, nothing more. These show the series belong together, not that the figures are right.</Txt>
            <Txt variant="tiny">{d.note}</Txt>
          </View>)}
      <SourceLink url={link}>Source: European Central Bank (euro-area employment and productivity, from Eurostat's quarterly national accounts), via the ECB Data Portal</SourceLink>
    </GCard>
  );
}
