import React from "react";
import { Linking, Pressable, View } from "react-native";
import { ymdLabel } from "../lib/format";
import { safeUrl } from "../lib/links";
import { useJoblessClaims } from "../state/queries";
import { color, space } from "../theme";
import { Banner, Divider, GCard, Skeleton, Txt } from "./ui";

const n0 = (x: number | null | undefined) => (x == null ? "n/a" : Math.round(x).toLocaleString("en-US"));
const moved = (x: number | null | undefined) => (x == null ? "not available" : x === 0 ? "unchanged" : `${x > 0 ? "up" : "down"} ${Math.abs(x).toLocaleString("en-US")}`);
const vsYear = (x: number | null | undefined) => (x == null ? "not available against a year ago" : x === 0 ? "the same as a year ago" : `${x > 0 ? "up" : "down"} ${Math.abs(x).toFixed(1)}% on a year ago`);

/** US weekly jobless claims (initial and continuing, via FRED). Describes what already happened; not a signal or a forecast. */
export function JoblessClaimsCard() {
  const q = useJoblessClaims();
  const d = q.data;
  const link = safeUrl(d?.url ?? null);
  return (
    <GCard style={{ padding: space.lg, gap: space.md }} testID="claims-card">
      <View><Txt variant="h2">Weekly jobless claims</Txt><Txt variant="tiny">People filing for unemployment insurance, from the US Department of Labor</Txt></View>
      {q.isLoading ? <Skeleton h={80} />
        : q.isError || !d ? <Banner tone="warn" title="Couldn't load jobless claims" testID="claims-error">{q.error instanceof Error ? q.error.message : "Something went wrong."}</Banner>
        : !d.available || !d.initial || !d.continuing ? <Banner tone={d.demo ? "demo" : "warn"} title={d.demo ? "Demo mode" : "Jobless claims unavailable"} testID="claims-unavailable">{d.reason}</Banner>
        : (
          <View style={{ gap: space.sm }} testID="claims-body">
            <Txt variant="label">Week ending {ymdLabel(d.date)}{d.freshness === "OVERDUE" ? " · overdue" : ""}</Txt>
            <Txt variant="small">Initial claims {n0(d.initial.value)}: {d.reading}. Four-week average {n0(d.initial.avg4)}.</Txt>
            <Txt variant="tiny">{moved(d.initial.change_1w)} on the week, {vsYear(d.initial.change_1y_pct)}. Past year: low {n0(d.initial.year_low)}, high {n0(d.initial.year_high)}.</Txt>
            <Divider />
            <Txt variant="small">Continuing claims {n0(d.continuing.value)} for the week ending {ymdLabel(d.continuing.date)}: {moved(d.continuing.change_1w)} on the week, {vsYear(d.continuing.change_1y_pct)}.</Txt>
            <Txt variant="tiny">{d.note}</Txt>
          </View>)}
      {link ? <Pressable onPress={() => Linking.openURL(link).catch(() => undefined)} accessibilityRole="link"><Txt variant="tiny" c={color.accent}>Source: US Department of Labor, via FRED</Txt></Pressable> : null}
    </GCard>
  );
}
