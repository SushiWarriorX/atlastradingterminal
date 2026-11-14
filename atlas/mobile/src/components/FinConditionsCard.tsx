import React from "react";
import { Linking, Pressable, View } from "react-native";
import { ymdLabel } from "../lib/format";
import { safeUrl } from "../lib/links";
import { useFinConditions } from "../state/queries";
import { color, space } from "../theme";
import { Banner, Divider, GCard, Skeleton, Txt } from "./ui";

const n3 = (x: number | null | undefined) => (x == null ? "n/a" : `${x > 0 ? "+" : ""}${x.toFixed(3)}`);
const moved = (x: number | null | undefined) => (x == null ? "not available" : x === 0 ? "unchanged" : `${x > 0 ? "up" : "down"} ${Math.abs(x).toFixed(3)}`);

/** Chicago Fed National Financial Conditions Index (weekly, via FRED). Zero is the average since 1971; positive is tighter, negative looser. Describes what already happened; not a signal or a forecast. */
export function FinConditionsCard() {
  const q = useFinConditions();
  const d = q.data;
  const link = safeUrl(d?.url ?? null);
  return (
    <GCard style={{ padding: space.lg, gap: space.md }} testID="fincond-card">
      <View><Txt variant="h2">Financial conditions</Txt><Txt variant="tiny">How tight or loose money and credit are, from the Chicago Fed</Txt></View>
      {q.isLoading ? <Skeleton h={80} />
        : q.isError || !d ? <Banner tone="warn" title="Couldn't load financial conditions" testID="fincond-error">{q.error instanceof Error ? q.error.message : "Something went wrong."}</Banner>
        : !d.available ? <Banner tone={d.demo ? "demo" : "warn"} title={d.demo ? "Demo mode" : "Financial conditions unavailable"} testID="fincond-unavailable">{d.reason}</Banner>
        : (
          <View style={{ gap: space.sm }} testID="fincond-body">
            <Txt variant="label">Week ending {ymdLabel(d.date)}{d.freshness === "OVERDUE" ? " · overdue" : ""}</Txt>
            <Txt variant="small">Index {n3(d.nfci)}: {d.reading}. Adjusted for the economy {n3(d.adjusted)}.</Txt>
            <Txt variant="tiny">{moved(d.change_1w)} on the week, {moved(d.change_4w)} over four weeks, {moved(d.change_1y)} over a year. Past year: low {n3(d.year_low)}, high {n3(d.year_high)}.</Txt>
            <Divider />
            <Txt variant="small">Pieces as published: risk {n3(d.pieces?.risk)}, credit {n3(d.pieces?.credit)}, leverage {n3(d.pieces?.leverage)}.</Txt>
            <Txt variant="tiny">{d.note}</Txt>
          </View>)}
      {link ? <Pressable onPress={() => Linking.openURL(link).catch(() => undefined)} accessibilityRole="link"><Txt variant="tiny" c={color.accent}>Source: Chicago Fed index, via FRED</Txt></Pressable> : null}
    </GCard>
  );
}
