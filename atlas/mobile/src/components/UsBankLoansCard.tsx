import React from "react";
import { View } from "react-native";
import { ymdLabel } from "../lib/format";
import { safeUrl } from "../lib/links";
import { checkText, compareText, estateText, headlineText, kindText, otherText, rangeText, weekText } from "../lib/usBankLoans";
import { useUsBankLoans } from "../state/queries";
import { space } from "../theme";
import { Banner, Divider, GCard, Skeleton, SourceLink, Txt } from "./ui";

/** US bank loans and leases (Board of Governors of the Federal Reserve System, H.8 Assets and Liabilities of Commercial Banks, via FRED), weekly: what US commercial banks have lent out, in all and by kind. Describes what already happened; not a signal or a forecast. */
export function UsBankLoansCard() {
  const q = useUsBankLoans();
  const d = q.data;
  const link = safeUrl(d?.url ?? null);
  return (
    <GCard style={{ padding: space.lg, gap: space.md }} testID="usbankloans-card">
      <View><Txt variant="h2">Bank loans</Txt><Txt variant="tiny">What US commercial banks have lent out, in all and by kind of loan, weekly, from the Federal Reserve</Txt></View>
      {q.isLoading ? <Skeleton h={80} />
        : q.isError || !d ? <Banner tone="warn" title="Couldn't load US bank loans" testID="usbankloans-error">{q.error instanceof Error ? q.error.message : "Something went wrong."}</Banner>
        : !d.available || !d.date || !d.total || !d.kinds || !d.real_estate || !d.other || !d.recent || !d.detail ? <Banner tone={d.demo ? "demo" : "warn"} title={d.demo ? "Demo mode" : "US bank loans unavailable"} testID="usbankloans-unavailable">{d.reason}</Banner>
        : (
          <View style={{ gap: space.sm }} testID="usbankloans-body">
            <Txt variant="label">Wednesday {ymdLabel(d.date)} · weekly · seasonally adjusted{d.freshness === "OVERDUE" ? " · overdue" : ""}</Txt>
            <Txt variant="small" testID="usbankloans-headline">{headlineText(d.total, d.kinds, ymdLabel(d.date))}</Txt>
            <Txt variant="small" testID="usbankloans-compare">{compareText(d.total)}</Txt>
            <Txt variant="tiny" testID="usbankloans-range">{rangeText(d.total.growth_range)}</Txt>
            <Divider />
            <Txt variant="label">By kind of loan</Txt>
            <View style={{ gap: space.sm }} testID="usbankloans-kinds">
              {d.kinds.map((k) => <Txt key={k.key} variant="small" testID={`usbankloans-kind-${k.key}`}>{kindText(k)}</Txt>)}
            </View>
            <Divider />
            <Txt variant="label">Real estate loans in more detail</Txt>
            <View style={{ gap: space.sm }} testID="usbankloans-estate">
              {d.real_estate.map((e) => <Txt key={e.key} variant="small" testID={`usbankloans-estate-${e.key}`}>{estateText(e)}</Txt>)}
            </View>
            <Txt variant="small" testID="usbankloans-other">{otherText(d.other)}</Txt>
            <Divider />
            <Txt variant="label">The last six weeks</Txt>
            <View style={{ gap: space.sm }} testID="usbankloans-recent">
              {d.recent.map((w) => <Txt key={w.date} variant="small" testID={`usbankloans-week-${w.date}`}>{weekText(w, ymdLabel(w.date))}</Txt>)}
            </View>
            <Txt variant="tiny" testID="usbankloans-check">{checkText(d.detail)}</Txt>
            <Txt variant="tiny">{d.note}</Txt>
          </View>)}
      <SourceLink url={link}>Source: Federal Reserve Board (H.8 Assets and Liabilities of Commercial Banks), via FRED</SourceLink>
    </GCard>
  );
}
