import React from "react";
import { Linking, Pressable, View } from "react-native";
import { safeUrl } from "../lib/links";
import { useBudget } from "../state/queries";
import { color, space } from "../theme";
import { Banner, Divider, GCard, Skeleton, Txt } from "./ui";

const b = (x: number) => `${x < 0 ? "−" : ""}$${Math.abs(x).toLocaleString("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 })}B`;

/** US federal receipts, outlays and deficit from the Monthly Treasury Statement. Describes what already happened; not a signal. */
export function BudgetCard() {
  const q = useBudget();
  const d = q.data;
  const link = safeUrl(d?.url ?? null);
  return (
    <GCard style={{ padding: space.lg, gap: space.md }} testID="budget-card">
      <View><Txt variant="h2">Federal budget</Txt><Txt variant="tiny">What the US government collected and spent, from the US Treasury</Txt></View>
      {q.isLoading ? <Skeleton h={80} />
        : q.isError || !d ? <Banner tone="warn" title="Couldn't load the federal budget" testID="budget-error">{q.error instanceof Error ? q.error.message : "Something went wrong."}</Banner>
        : !d.available ? <Banner tone={d.demo ? "demo" : "warn"} title={d.demo ? "Demo mode" : "Federal budget unavailable"} testID="budget-unavailable">{d.reason}</Banner>
        : (
          <View style={{ gap: space.sm }} testID="budget-body">
            <Txt variant="label">{d.month} {d.date?.slice(0, 4)}{d.freshness === "OVERDUE" ? " · overdue" : ""}</Txt>
            <Txt variant="hero">{d.month_deficit_billions! >= 0 ? "Deficit " : "Surplus "}{b(Math.abs(d.month_deficit_billions!))}</Txt>
            <Txt variant="small">Collected {b(d.month_receipts_billions!)} · spent {b(d.month_outlays_billions!)}</Txt>
            <Divider />
            <Txt variant="label">Fiscal {d.fiscal_year} so far ({d.ytd_months} of 12 months)</Txt>
            <Txt variant="h2">{d.ytd_deficit_billions! >= 0 ? "Deficit " : "Surplus "}{b(Math.abs(d.ytd_deficit_billions!))}</Txt>
            <Txt variant="small">Collected {b(d.ytd_receipts_billions!)} · spent {b(d.ytd_outlays_billions!)}</Txt>
            {d.prior_ytd_deficit_billions != null ? <Txt variant="tiny">Same months a year earlier: {d.prior_ytd_deficit_billions >= 0 ? "deficit" : "surplus"} {b(Math.abs(d.prior_ytd_deficit_billions))}.</Txt> : null}
            <Txt variant="tiny">{d.note}</Txt>
          </View>)}
      {link ? <Pressable onPress={() => Linking.openURL(link).catch(() => undefined)} accessibilityRole="link"><Txt variant="tiny" c={color.accent}>Source: US Treasury FiscalData</Txt></Pressable> : null}
    </GCard>
  );
}
