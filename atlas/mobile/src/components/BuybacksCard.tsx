import React from "react";
import { Linking, Pressable, View } from "react-native";
import { safeUrl } from "../lib/links";
import { useBuybacks } from "../state/queries";
import { color, space } from "../theme";
import { Banner, Divider, GCard, Skeleton, Txt } from "./ui";

const day = (iso?: string) => (iso ? new Date(`${iso}T12:00:00Z`).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" }) : "");
const bn = (x: number | null | undefined) => (x == null ? "no result reported" : `$${x.toLocaleString("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 2 })}B`);
const share = (x: number | null | undefined) => (x == null ? "" : ` (${x.toFixed(1)}% of what was offered)`);

/** US Treasury buyback operations: what dealers offered and what the Treasury bought. Describes what already happened; not a signal. */
export function BuybacksCard() {
  const q = useBuybacks();
  const d = q.data;
  const link = safeUrl(d?.url ?? null);
  const win = (name: string, x?: { operations: number; no_result: number; accepted_billions: number; bought_share_pct: number | null }) => x ? (
    <View style={{ gap: 2 }}>
      <Txt variant="label">{name}</Txt>
      <Txt variant="h2">{bn(x.accepted_billions)}</Txt>
      <Txt variant="small">{x.operations} operations{share(x.bought_share_pct)}</Txt>
      {x.no_result > 0 ? <Txt variant="tiny" c={color.down}>{x.no_result} operation(s) have no result in the source and are not counted.</Txt> : null}
    </View>) : null;
  return (
    <GCard style={{ padding: space.lg, gap: space.md }} testID="buybacks-card">
      <View><Txt variant="h2">Treasury buybacks</Txt><Txt variant="tiny">Older securities the US Treasury bought back for cash, from the US Treasury</Txt></View>
      {q.isLoading ? <Skeleton h={80} />
        : q.isError || !d ? <Banner tone="warn" title="Couldn't load the buybacks" testID="buybacks-error">{q.error instanceof Error ? q.error.message : "Something went wrong."}</Banner>
        : !d.available ? <Banner tone={d.demo ? "demo" : "warn"} title={d.demo ? "Demo mode" : "Buybacks unavailable"} testID="buybacks-unavailable">{d.reason}</Banner>
        : (
          <View style={{ gap: space.sm }} testID="buybacks-body">
            <Txt variant="label">Latest operation · {day(d.date)}{d.freshness === "OVERDUE" ? " · overdue" : ""}</Txt>
            <Txt variant="hero">{bn(d.latest!.accepted_billions)}</Txt>
            <Txt variant="small">The Treasury bought this much out of {bn(d.latest!.offered_billions)} that dealers offered{d.latest!.bought_share_pct == null ? "" : ` (${d.latest!.bought_share_pct.toFixed(1)}%)`}. {d.latest!.type}, {d.latest!.security.toLowerCase()}, {d.latest!.maturity}.</Txt>
            <Divider />
            {win("Last 90 days", d.last_90_days)}
            {win("Last 12 months", d.last_365_days)}
            <Divider />
            {[...(d.by_type ?? []), ...(d.by_security ?? [])].map((r) => (
              <View key={r.key} style={{ flexDirection: "row", justifyContent: "space-between", gap: space.md }}>
                <Txt variant="small" style={{ flex: 1 }}>{r.label}</Txt>
                <Txt variant="small">{bn(r.accepted_billions)} · {r.operations} ops</Txt>
              </View>))}
            <Txt variant="tiny">Types and sizes above cover the last 12 months.</Txt>
            {!!d.anomalies && <Txt variant="tiny" c={color.down}>{d.anomalies} operation(s) show more bought than offered or announced; the source may contain an error.</Txt>}
            <Txt variant="tiny">{d.note}</Txt>
          </View>)}
      {link ? <Pressable onPress={() => Linking.openURL(link).catch(() => undefined)} accessibilityRole="link"><Txt variant="tiny" c={color.accent}>Source: US Treasury FiscalData</Txt></Pressable> : null}
    </GCard>
  );
}
