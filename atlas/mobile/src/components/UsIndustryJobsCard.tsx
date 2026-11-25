import React from "react";
import { View } from "react-native";
import { ymdLabel } from "../lib/format";
import { safeUrl } from "../lib/links";
import { checkText, compareText, headlineText, itemText, monthText } from "../lib/usIndustryJobs";
import { useUsIndustryJobs } from "../state/queries";
import { space } from "../theme";
import { Banner, Divider, GCard, Skeleton, SourceLink, Txt } from "./ui";

/** US jobs by industry (U.S. Bureau of Labor Statistics, the Current Employment Statistics survey of employers, via FRED), monthly: how many jobs employers had on their payrolls in each industry. Described, not forecast; the sentences come from `lib/usIndustryJobs.ts` and every figure from the server. */
export function UsIndustryJobsCard() {
  const q = useUsIndustryJobs();
  const d = q.data;
  const link = safeUrl(d?.url ?? null);
  return (
    <GCard style={{ padding: space.lg, gap: space.md }} testID="usindustryjobs-card">
      <View><Txt variant="h2">Jobs by industry</Txt><Txt variant="tiny">How many jobs US employers had on their payrolls in each industry, monthly, from the Bureau of Labor Statistics</Txt></View>
      {q.isLoading ? <Skeleton h={80} />
        : q.isError || !d ? <Banner tone="warn" title="Couldn't load US jobs by industry" testID="usindustryjobs-error">{q.error instanceof Error ? q.error.message : "Something went wrong."}</Banner>
        : !d.available || !d.month || !d.total || !d.groups || !d.industries || !d.manufacturing || !d.recent || !d.detail ? <Banner tone={d.demo ? "demo" : "warn"} title={d.demo ? "Demo mode" : "US jobs by industry unavailable"} testID="usindustryjobs-unavailable">{d.reason}</Banner>
        : (
          <View style={{ gap: space.sm }} testID="usindustryjobs-body">
            <Txt variant="label">{ymdLabel(d.month)} · monthly · seasonally adjusted{d.freshness === "OVERDUE" ? " · overdue" : ""}</Txt>
            <Txt variant="small" testID="usindustryjobs-headline">{headlineText(d.total, d.groups, ymdLabel(d.month))}</Txt>
            <Txt variant="small" testID="usindustryjobs-compare">{compareText(d.total)}</Txt>
            <Divider />
            <Txt variant="label">The three big groups</Txt>
            <View style={{ gap: space.sm }} testID="usindustryjobs-groups">
              {d.groups.map((i) => <Txt key={i.key} variant="small" testID={`usindustryjobs-group-${i.key}`}>{itemText(i)}</Txt>)}
            </View>
            <Divider />
            <Txt variant="label">Private industries</Txt>
            <View style={{ gap: space.sm }} testID="usindustryjobs-industries">
              {d.industries.filter((i) => i.key !== "government").map((i) => <Txt key={i.key} variant="small" testID={`usindustryjobs-industry-${i.key}`}>{itemText(i)}</Txt>)}
            </View>
            <Divider />
            <Txt variant="label">Inside manufacturing</Txt>
            <View style={{ gap: space.sm }} testID="usindustryjobs-manufacturing">
              {d.manufacturing.map((i) => <Txt key={i.key} variant="small" testID={`usindustryjobs-manufacturing-${i.key}`}>{itemText(i, "manufacturing")}</Txt>)}
            </View>
            <Divider />
            <Txt variant="label">The last six months</Txt>
            <View style={{ gap: space.sm }} testID="usindustryjobs-recent">
              {d.recent.map((m) => <Txt key={m.month} variant="small" testID={`usindustryjobs-month-${m.month}`}>{monthText(m, ymdLabel(m.month))}</Txt>)}
            </View>
            <Txt variant="tiny" testID="usindustryjobs-check">{checkText(d.detail)}</Txt>
            <Txt variant="tiny">{d.note}</Txt>
          </View>)}
      <SourceLink url={link}>Source: Bureau of Labor Statistics, via FRED</SourceLink>
    </GCard>
  );
}
