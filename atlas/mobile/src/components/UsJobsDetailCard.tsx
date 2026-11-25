import React from "react";
import { View } from "react-native";
import { ymdLabel } from "../lib/format";
import { safeUrl } from "../lib/links";
import { checkText, childText, parentText } from "../lib/usJobsDetail";
import { useUsJobsDetail } from "../state/queries";
import { space } from "../theme";
import { Banner, Divider, GCard, Skeleton, SourceLink, Txt } from "./ui";

/** US jobs in detail (U.S. Bureau of Labor Statistics, the Current Employment Statistics survey of employers, via FRED), monthly: how many jobs sit inside seven of the larger industries and in the parts each is made of. Described, not forecast; the sentences come from `lib/usJobsDetail.ts` and every figure from the server. */
export function UsJobsDetailCard() {
  const q = useUsJobsDetail();
  const d = q.data;
  const link = safeUrl(d?.url ?? null);
  return (
    <GCard style={{ padding: space.lg, gap: space.md }} testID="usjobsdetail-card">
      <View><Txt variant="h2">Jobs in detail</Txt><Txt variant="tiny">How many jobs sit inside seven of the larger industries, and in the parts each is made of, monthly, from the Bureau of Labor Statistics</Txt></View>
      {q.isLoading ? <Skeleton h={80} />
        : q.isError || !d ? <Banner tone="warn" title="Couldn't load US jobs in detail" testID="usjobsdetail-error">{q.error instanceof Error ? q.error.message : "Something went wrong."}</Banner>
        : !d.available || !d.month || !d.groups || !d.detail ? <Banner tone={d.demo ? "demo" : "warn"} title={d.demo ? "Demo mode" : "US jobs in detail unavailable"} testID="usjobsdetail-unavailable">{d.reason}</Banner>
        : (
          <View style={{ gap: space.sm }} testID="usjobsdetail-body">
            <Txt variant="label">{ymdLabel(d.month)} · monthly · seasonally adjusted{d.freshness === "OVERDUE" ? " · overdue" : ""}</Txt>
            {d.groups.map((g) => (
              <View key={g.key} style={{ gap: space.sm }} testID={`usjobsdetail-group-${g.key}`}>
                <Divider />
                <Txt variant="label">{g.label}</Txt>
                <Txt variant="small" testID={`usjobsdetail-parent-${g.key}`}>{parentText(g.parent)}</Txt>
                {g.children.map((c) => <Txt key={c.key} variant="small" testID={`usjobsdetail-child-${c.key}`}>{childText(c, g.label)}</Txt>)}
              </View>))}
            <Txt variant="tiny" testID="usjobsdetail-check">{checkText(d.detail)}</Txt>
            <Txt variant="tiny">{d.note}</Txt>
          </View>)}
      <SourceLink url={link}>Source: Bureau of Labor Statistics, via FRED</SourceLink>
    </GCard>
  );
}
