import React from "react";
import { Linking, Pressable, View } from "react-native";
import { safeUrl } from "../lib/links";
import { useWorldBank } from "../state/queries";
import { color, space } from "../theme";
import { Banner, Divider, GCard, Skeleton, Txt } from "./ui";

const chg = (x: number | null | undefined) => (x === null || x === undefined ? "n/a" : `${x > 0 ? "+" : x < 0 ? "−" : ""}${Math.abs(x).toFixed(1)}`);

/** Yearly growth, inflation and unemployment for the US and five other large economies (World Bank). Context only: annual figures arrive months late and are revised. */
export function WorldCard() {
  const q = useWorldBank();
  const d = q.data;
  const link = safeUrl(d?.url ?? null);
  return (
    <GCard style={{ padding: space.lg, gap: space.md }} testID="world-card">
      <View><Txt variant="h2">World economies</Txt><Txt variant="tiny">Yearly growth, inflation and unemployment from the World Bank</Txt></View>
      {q.isLoading ? <Skeleton h={80} />
        : q.isError || !d ? <Banner tone="warn" title="Couldn't load World Bank data" testID="world-error">{q.error instanceof Error ? q.error.message : "Something went wrong."}</Banner>
        : !d.available ? <Banner tone={d.demo ? "demo" : "warn"} title={d.demo ? "Demo mode" : "World Bank data unavailable"} testID="world-unavailable">{d.reason}</Banner>
        : (
          <View style={{ gap: space.lg }} testID="world-body">
            {d.indicators.map((ind) => (
              <View key={ind.key} style={{ gap: 2 }}>
                <Txt variant="label">{ind.title} · {ind.unit}</Txt>
                {!ind.available ? <Txt variant="small" c={color.warn}>{ind.reason}</Txt> : ind.rows.map((r, i) => (
                  <View key={r.iso}>{i > 0 && <Divider />}
                    <View style={{ flexDirection: "row", justifyContent: "space-between", paddingVertical: 4 }}>
                      <Txt variant="body">{r.country}</Txt>
                      {r.available ? <Txt variant="body">{r.value!.toFixed(1)} <Txt variant="tiny">({r.year}) · {chg(r.change)} vs year before</Txt></Txt> : <Txt variant="tiny">no data</Txt>}
                    </View>
                  </View>))}
                <Txt variant="tiny">{ind.what}</Txt>
              </View>))}
            <Txt variant="tiny">{d.note}</Txt>
            {link ? <Pressable onPress={() => Linking.openURL(link).catch(() => undefined)} accessibilityRole="link"><Txt variant="tiny" c={color.accent}>Source: World Bank</Txt></Pressable> : null}
          </View>)}
    </GCard>
  );
}
