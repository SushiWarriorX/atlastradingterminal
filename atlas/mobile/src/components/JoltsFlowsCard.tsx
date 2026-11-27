import React from "react";
import { View } from "react-native";
import { ymdLabel } from "../lib/format";
import { checkText, compareText, headlineText, industryText, monthText, rangeText, sectorText } from "../lib/joltsFlows";
import { safeUrl } from "../lib/links";
import { useJoltsFlows } from "../state/queries";
import { space } from "../theme";
import { Banner, Divider, GCard, Skeleton, SourceLink, Txt } from "./ui";

/** US hires, quits and layoffs by industry (Bureau of Labor Statistics JOLTS, via FRED), monthly: how many people employers took on and how many left. Describes what already happened; not a signal or a forecast. */
export function JoltsFlowsCard() {
  const q = useJoltsFlows();
  const d = q.data;
  const link = safeUrl(d?.url ?? null);
  return (
    <GCard style={{ padding: space.lg, gap: space.md }} testID="joltsflows-card">
      <View><Txt variant="h2">Hires, quits and layoffs by industry</Txt><Txt variant="tiny">How many people US employers took on and how many left their jobs, by industry, monthly, from the Bureau of Labor Statistics</Txt></View>
      {q.isLoading ? <Skeleton h={80} />
        : q.isError || !d ? <Banner tone="warn" title="Couldn't load US hires and quits" testID="joltsflows-error">{q.error instanceof Error ? q.error.message : "Something went wrong."}</Banner>
        : !d.available || !d.month || !d.total || !d.sectors || !d.industries || !d.recent || !d.detail ? <Banner tone={d.demo ? "demo" : "warn"} title={d.demo ? "Demo mode" : "US hires and quits unavailable"} testID="joltsflows-unavailable">{d.reason}</Banner>
        : (
          <View style={{ gap: space.sm }} testID="joltsflows-body">
            <Txt variant="label">{ymdLabel(d.month)} · monthly · seasonally adjusted{d.freshness === "OVERDUE" ? " · overdue" : ""}</Txt>
            <Txt variant="small" testID="joltsflows-headline">{headlineText(d.total, ymdLabel(d.month))}</Txt>
            <Txt variant="small" testID="joltsflows-compare">{compareText(d.total)}</Txt>
            <View style={{ gap: 2 }} testID="joltsflows-ranges">
              <Txt variant="tiny" testID="joltsflows-range-hires">{rangeText("hires", d.total.hires_range)}</Txt>
              <Txt variant="tiny" testID="joltsflows-range-quits">{rangeText("quits", d.total.quits_range)}</Txt>
              <Txt variant="tiny" testID="joltsflows-range-layoffs">{rangeText("layoffs and discharges", d.total.layoffs_range)}</Txt>
            </View>
            <Divider />
            <Txt variant="label">The private sector and government</Txt>
            <View style={{ gap: space.sm }} testID="joltsflows-sectors">
              {d.sectors.map((s) => <Txt key={s.key} variant="small" testID={`joltsflows-sector-${s.key}`}>{sectorText(s)}</Txt>)}
            </View>
            <Divider />
            <Txt variant="label">Six private industries, most hires first</Txt>
            <View style={{ gap: space.sm }} testID="joltsflows-industries">
              {d.industries.map((r) => <Txt key={r.key} variant="small" testID={`joltsflows-industry-${r.key}`}>{industryText(r)}</Txt>)}
            </View>
            <Divider />
            <Txt variant="label">The last six months, all of nonfarm</Txt>
            <View style={{ gap: space.sm }} testID="joltsflows-recent">
              {d.recent.map((m) => <Txt key={m.month} variant="small" testID={`joltsflows-month-${m.month}`}>{monthText(m, ymdLabel(m.month))}</Txt>)}
            </View>
            <Txt variant="tiny" testID="joltsflows-check">{checkText(d.detail)}</Txt>
            <Txt variant="tiny">{d.note}</Txt>
          </View>)}
      <SourceLink url={link}>Source: US Bureau of Labor Statistics (Job Openings and Labor Turnover Survey), via FRED</SourceLink>
    </GCard>
  );
}
