import React from "react";
import { View } from "react-native";
import type { JoltsIndustryRow, JoltsRange } from "../api/types";
import { ymdLabel } from "../lib/format";
import { safeUrl } from "../lib/links";
import { useJoltsIndustries } from "../state/queries";
import { space } from "../theme";
import { Banner, Divider, GCard, Skeleton, SourceLink, Txt } from "./ui";

const amount = (k: number) => (k >= 1000 ? `${(k / 1000).toFixed(3)} million` : `${Math.round(k).toLocaleString("en-US")} thousand`);
const vs = (x: number | null | undefined, when: string) => (x == null ? `not available against ${when}` : x === 0 ? `the same as ${when}` : `${x > 0 ? "up" : "down"} ${Math.abs(x).toFixed(1)}% on ${when}`);
const span = (r: JoltsRange) =>
  `Over the last ${Math.round(r.months / 12)} years (${r.months} months) total openings ran from ${amount(r.lowest.value)} (${ymdLabel(r.lowest.month)}) to ${amount(r.highest.value)} (${ymdLabel(r.highest.month)}); ${r.share_lower_pct}% of those months were lower than now.`;
const sentence = (r: JoltsIndustryRow) => `${r.label}${r.derived ? ", by subtraction" : ""}: ${amount(r.openings_thousands)}, ${r.share_pct.toFixed(1)}% of all openings, ${vs(r.change_year_pct, "a year ago")}.`;
const ofWhich = (parts: JoltsIndustryRow[]) => `Of which: ${parts.map((p) => `${p.label} ${amount(p.openings_thousands)} (${vs(p.change_year_pct, "a year ago")}${p.derived ? ", by subtraction" : ""})`).join("; ")}.`;

/** US job openings by industry (Bureau of Labor Statistics JOLTS, via FRED), monthly. Describes what already happened; not a signal or a forecast. */
export function JoltsIndustriesCard() {
  const q = useJoltsIndustries();
  const d = q.data;
  const link = safeUrl(d?.url ?? null);
  return (
    <GCard style={{ padding: space.lg, gap: space.md }} testID="joltsind-card">
      <View><Txt variant="h2">Job openings by industry</Txt><Txt variant="tiny">Where US employers have jobs open, by industry, monthly, from the Bureau of Labor Statistics</Txt></View>
      {q.isLoading ? <Skeleton h={80} />
        : q.isError || !d ? <Banner tone="warn" title="Couldn't load US job openings by industry" testID="joltsind-error">{q.error instanceof Error ? q.error.message : "Something went wrong."}</Banner>
        : !d.available || !d.month || !d.total || !d.industries || !d.detail ? <Banner tone={d.demo ? "demo" : "warn"} title={d.demo ? "Demo mode" : "US job openings by industry unavailable"} testID="joltsind-unavailable">{d.reason}</Banner>
        : (
          <View style={{ gap: space.sm }} testID="joltsind-body">
            <Txt variant="label">{ymdLabel(d.month)} · monthly · seasonally adjusted{d.freshness === "OVERDUE" ? " · overdue" : ""}</Txt>
            <Txt variant="small" testID="joltsind-headline">Employers had {amount(d.total.openings_thousands)} job openings at the end of {ymdLabel(d.month)}, {vs(d.total.change_year_pct, "a year ago")}. {amount(d.total.private_thousands)} ({d.total.private_share_pct.toFixed(1)}%) were in the private sector and {amount(d.total.government_thousands)} ({d.total.government_share_pct.toFixed(1)}%) in government.</Txt>
            <Txt variant="tiny" testID="joltsind-range">{span(d.total.range)}</Txt>
            <Divider />
            <Txt variant="label">Openings by industry, largest first</Txt>
            <View style={{ gap: space.sm }} testID="joltsind-industries">
              {d.industries.map((g) => (
                <View key={g.key} style={{ gap: 2 }}>
                  <Txt variant="small" testID={`joltsind-industry-${g.key}`}>{sentence(g)}</Txt>
                  {g.parts.length > 0 ? <Txt variant="tiny" testID={`joltsind-parts-${g.key}`}>{ofWhich(g.parts)}</Txt> : null}
                </View>
              ))}
            </View>
            <Txt variant="tiny" testID="joltsind-check">Check: in each of the {d.detail.months_checked} months from {ymdLabel(d.detail.first_month)} to {ymdLabel(d.detail.last_month)} the sixteen series covered the same months with none missing and every figure lay inside its range (plain checks, not the source's sums); the survey's own arithmetic held, which shows that the series belong to one release, not that the figures are right: total nonfarm equalled private plus government, manufacturing equalled durable plus nondurable goods and leisure and hospitality equalled arts plus accommodation and food (largest gap {d.detail.largest_sum_gap} thousand, which is rounding; 1.5 is allowed), and retail trade, health care and state and local government were never above the industries that contain them (the closest was {d.detail.closest_part_margin} thousand). What is left of private after the six industries was at least {d.detail.smallest_rest_of_private} thousand.</Txt>
            <Txt variant="tiny">{d.note}</Txt>
          </View>)}
      <SourceLink url={link}>Source: US Bureau of Labor Statistics (Job Openings and Labor Turnover Survey), via FRED</SourceLink>
    </GCard>
  );
}
