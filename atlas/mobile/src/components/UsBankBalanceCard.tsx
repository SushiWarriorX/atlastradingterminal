import React from "react";
import { View } from "react-native";
import { ymdLabel } from "../lib/format";
import { safeUrl } from "../lib/links";
import { checkText, compareText, headlineText, itemText, liabilitiesText, owedText, rangeText, residualText, securitiesText, weekText } from "../lib/usBankBalance";
import { useUsBankBalance } from "../state/queries";
import { space } from "../theme";
import { Banner, Divider, GCard, Skeleton, SourceLink, Txt } from "./ui";

/** US bank balance sheet (Board of Governors of the Federal Reserve System, H.8 Assets and Liabilities of Commercial Banks, via FRED), weekly: what US commercial banks hold and owe. Describes what already happened; not a signal or a forecast. */
export function UsBankBalanceCard() {
  const q = useUsBankBalance();
  const d = q.data;
  const link = safeUrl(d?.url ?? null);
  return (
    <GCard style={{ padding: space.lg, gap: space.md }} testID="usbankbalance-card">
      <View><Txt variant="h2">Bank balance sheet</Txt><Txt variant="tiny">What US commercial banks hold and what they owe, weekly, from the Federal Reserve</Txt></View>
      {q.isLoading ? <Skeleton h={80} />
        : q.isError || !d ? <Banner tone="warn" title="Couldn't load the US bank balance sheet" testID="usbankbalance-error">{q.error instanceof Error ? q.error.message : "Something went wrong."}</Banner>
        : !d.available || !d.date || !d.total || !d.assets || !d.securities || !d.liabilities || !d.residual || !d.recent || !d.detail ? <Banner tone={d.demo ? "demo" : "warn"} title={d.demo ? "Demo mode" : "US bank balance sheet unavailable"} testID="usbankbalance-unavailable">{d.reason}</Banner>
        : (
          <View style={{ gap: space.sm }} testID="usbankbalance-body">
            <Txt variant="label">Wednesday {ymdLabel(d.date)} · weekly · seasonally adjusted{d.freshness === "OVERDUE" ? " · overdue" : ""}</Txt>
            <Txt variant="small" testID="usbankbalance-headline">{headlineText(d.total, d.assets, ymdLabel(d.date))}</Txt>
            <Txt variant="small" testID="usbankbalance-owed">{owedText(d.liabilities, d.residual)}</Txt>
            <Txt variant="small" testID="usbankbalance-compare">{compareText(d.total)}</Txt>
            <Txt variant="tiny" testID="usbankbalance-range">{rangeText(d.total.growth_range)}</Txt>
            <Divider />
            <Txt variant="label">What the banks hold</Txt>
            <View style={{ gap: space.sm }} testID="usbankbalance-assets">
              {d.assets.map((a) => <Txt key={a.key} variant="small" testID={`usbankbalance-asset-${a.key}`}>{itemText(a, "total assets")}</Txt>)}
            </View>
            <Txt variant="small" testID="usbankbalance-securities">{securitiesText(d.securities)}</Txt>
            <Divider />
            <Txt variant="label">What the banks owe</Txt>
            <View style={{ gap: space.sm }} testID="usbankbalance-liabilities">
              <Txt variant="small" testID="usbankbalance-liability-total">{liabilitiesText(d.liabilities)}</Txt>
              {d.liabilities.items.map((a) => <Txt key={a.key} variant="small" testID={`usbankbalance-liability-${a.key}`}>{itemText(a, "total liabilities")}</Txt>)}
              <Txt variant="small" testID="usbankbalance-residual">{residualText(d.residual)}</Txt>
            </View>
            <Divider />
            <Txt variant="label">The last six weeks</Txt>
            <View style={{ gap: space.sm }} testID="usbankbalance-recent">
              {d.recent.map((w) => <Txt key={w.date} variant="small" testID={`usbankbalance-week-${w.date}`}>{weekText(w, ymdLabel(w.date))}</Txt>)}
            </View>
            <Txt variant="tiny" testID="usbankbalance-check">{checkText(d.detail)}</Txt>
            <Txt variant="tiny">{d.note}</Txt>
          </View>)}
      <SourceLink url={link}>Source: Federal Reserve Board (H.8 Assets and Liabilities of Commercial Banks), via FRED</SourceLink>
    </GCard>
  );
}
