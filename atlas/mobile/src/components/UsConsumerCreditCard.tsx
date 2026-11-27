import React from "react";
import { View } from "react-native";
import { ymdLabel } from "../lib/format";
import { safeUrl } from "../lib/links";
import { checkText, compareText, headlineText, kindText, monthText, rangeText } from "../lib/usConsumerCredit";
import { useUsConsumerCredit } from "../state/queries";
import { space } from "../theme";
import { Banner, Divider, GCard, Skeleton, SourceLink, Txt } from "./ui";

/** US consumer credit (Board of Governors of the Federal Reserve System, G.19 Consumer Credit, via FRED), monthly: what American consumers owe on credit cards and other revolving plans and on car, student and other instalment loans. Describes what already happened; not a signal or a forecast. */
export function UsConsumerCreditCard() {
  const q = useUsConsumerCredit();
  const d = q.data;
  const link = safeUrl(d?.url ?? null);
  return (
    <GCard style={{ padding: space.lg, gap: space.md }} testID="usconsumercredit-card">
      <View><Txt variant="h2">Consumer credit</Txt><Txt variant="tiny">What US consumers owe on credit cards, car and student loans and other consumer credit (not mortgages), monthly, from the Federal Reserve</Txt></View>
      {q.isLoading ? <Skeleton h={80} />
        : q.isError || !d ? <Banner tone="warn" title="Couldn't load US consumer credit" testID="usconsumercredit-error">{q.error instanceof Error ? q.error.message : "Something went wrong."}</Banner>
        : !d.available || !d.month || !d.total || !d.kinds || !d.recent || !d.detail ? <Banner tone={d.demo ? "demo" : "warn"} title={d.demo ? "Demo mode" : "US consumer credit unavailable"} testID="usconsumercredit-unavailable">{d.reason}</Banner>
        : (
          <View style={{ gap: space.sm }} testID="usconsumercredit-body">
            <Txt variant="label">{ymdLabel(d.month)} · monthly · seasonally adjusted{d.freshness === "OVERDUE" ? " · overdue" : ""}</Txt>
            <Txt variant="small" testID="usconsumercredit-headline">{headlineText(d.total, ymdLabel(d.month))}</Txt>
            <Txt variant="small" testID="usconsumercredit-compare">{compareText(d.total)}</Txt>
            <Txt variant="tiny" testID="usconsumercredit-range">{rangeText(d.total.growth_range)}</Txt>
            <Divider />
            <Txt variant="label">By kind of credit</Txt>
            <View style={{ gap: space.sm }} testID="usconsumercredit-kinds">
              {d.kinds.map((k) => <Txt key={k.key} variant="small" testID={`usconsumercredit-kind-${k.key}`}>{kindText(k)}</Txt>)}
            </View>
            <Divider />
            <Txt variant="label">The last six months</Txt>
            <View style={{ gap: space.sm }} testID="usconsumercredit-recent">
              {d.recent.map((m) => <Txt key={m.month} variant="small" testID={`usconsumercredit-month-${m.month}`}>{monthText(m, ymdLabel(m.month))}</Txt>)}
            </View>
            <Txt variant="tiny" testID="usconsumercredit-check">{checkText(d.detail)}</Txt>
            <Txt variant="tiny">{d.note}</Txt>
          </View>)}
      <SourceLink url={link}>Source: Federal Reserve Board (G.19 Consumer Credit), via FRED</SourceLink>
    </GCard>
  );
}
