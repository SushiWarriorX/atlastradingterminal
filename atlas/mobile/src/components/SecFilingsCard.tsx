import React, { useState } from "react";
import { Linking, Pressable, View } from "react-native";
import { safeUrl } from "../lib/links";
import { useSecFilings } from "../state/queries";
import { color, space } from "../theme";
import { Banner, Chip, Divider, GCard, Skeleton, Tag, Txt } from "./ui";

const GROUPS: [string, string, string[]][] = [
  ["all", "All", []],
  ["reports", "Reports", ["10-K", "10-K/A", "10-Q", "20-F"]],
  ["events", "Events", ["8-K", "8-K/A", "6-K"]],
  ["insiders", "Insiders", ["4", "144"]],
  ["holders", "Big holders", ["SC 13D", "SC 13D/A", "SC 13G"]],
  ["offerings", "Offerings", ["S-1", "S-3", "424B5"]],
];
const dot = (i: string) => (i === "high" ? color.down : i === "medium" ? color.warn : color.faint);

/** Latest SEC filings for this stock: reports, 8-K events, insider trades, big holders and offerings. Form types and links come from the SEC; the meanings are generic. */
export function SecFilingsCard({ symbol }: { symbol: string }) {
  const [group, setGroup] = useState("all");
  const forms = GROUPS.find((g) => g[0] === group)?.[2] ?? [];
  const q = useSecFilings(symbol, forms);
  const d = q.data;
  return (
    <GCard style={{ padding: space.lg, gap: space.md }} testID="filings-card">
      <View><Txt variant="h2">SEC filings</Txt><Txt variant="tiny">Reports, events, insider trades, big holders and offerings, straight from the SEC</Txt></View>
      <View style={{ flexDirection: "row", gap: 4, flexWrap: "wrap" }}>{GROUPS.map(([k, label]) => <Chip key={k} label={label} active={group === k} onPress={() => setGroup(k)} testID={`filings-group-${k}`} />)}</View>
      {q.isLoading ? <View style={{ gap: space.md }} testID="filings-loading">{[0, 1, 2].map((i) => <Skeleton key={i} h={40} />)}</View>
        : q.isError || !d ? <Banner tone="warn" title="Couldn't load the filings" testID="filings-error">{q.error instanceof Error ? q.error.message : "Something went wrong."}</Banner>
        : (
          <View testID="filings-body">
            {d.demo ? <Banner tone="demo" title="Demo mode">{d.errors[0]}</Banner>
              : d.errors.map((e, i) => <Banner key={i} tone="warn" title={d.needs_contact ? "Filings are switched off" : "Some filings could not be loaded"} testID={d.needs_contact ? "filings-needs-contact" : undefined}>{e}</Banner>)}
            {!d.errors.length && d.items.length === 0 ? <Txt variant="small">No filings of this kind in the last year.</Txt> : null}
            {d.items.map((f, i) => {
              const link = safeUrl(f.link);
              return (
                <View key={`${f.link}-${i}`}>{i > 0 && <Divider />}
                  <Pressable onPress={() => link && Linking.openURL(link).catch(() => undefined)} disabled={!link} accessibilityRole={link ? "link" : undefined} testID="filing-row" style={{ flexDirection: "row", gap: space.sm, paddingVertical: 8 }}>
                    <Txt variant="body" c={dot(f.importance)} style={{ width: 14 }}>●</Txt>
                    <View style={{ flex: 1, gap: 2 }}>
                      <View style={{ flexDirection: "row", gap: 6, alignItems: "center" }}><Tag label={f.form} /><Txt variant="small">{f.filed}</Txt></View>
                      <Txt variant="body">{f.meaning}</Txt>
                      {f.items.length > 0 ? <Txt variant="tiny">{f.items.map((x) => x.meaning).join("; ")}</Txt> : null}
                    </View>
                  </Pressable>
                </View>);
            })}
            <Txt variant="tiny" style={{ marginTop: space.sm }}>{d.note} Tap a row to open it on sec.gov. Red = high, amber = medium, grey = low.</Txt>
          </View>)}
    </GCard>
  );
}
