import React from "react";
import { Linking, Pressable, View } from "react-native";
import { safeUrl } from "../lib/links";
import { useSentiment } from "../state/queries";
import { color, space } from "../theme";
import { Banner, GCard, Skeleton, Tag, Txt } from "./ui";

const tint = (v: number) => (v < 25 ? color.down : v < 45 ? color.warn : v < 55 ? color.dim : color.up);

/** Crypto Fear & Greed index (alternative.me): a daily 0-100 mood gauge with its date and source. Not a forecast and not a trading signal. */
export function SentimentCard() {
  const q = useSentiment();
  const d = q.data;
  const link = safeUrl(d?.url ?? null);
  return (
    <GCard style={{ padding: space.lg, gap: space.sm }} testID="sentiment-card">
      <View><Txt variant="h2">Crypto Fear &amp; Greed</Txt><Txt variant="tiny">A daily mood gauge from alternative.me, 0 (extreme fear) to 100 (extreme greed)</Txt></View>
      {q.isLoading ? <Skeleton h={44} />
        : q.isError || !d ? <Banner tone="warn" title="Couldn't load the index" testID="sentiment-error">{q.error instanceof Error ? q.error.message : "Something went wrong."}</Banner>
        : !d.available ? <Banner tone={d.demo ? "demo" : "warn"} title={d.demo ? "Demo mode" : "Index unavailable"} testID="sentiment-unavailable">{d.reason}</Banner>
        : (
          <View style={{ gap: space.sm }} testID="sentiment-body">
            <View style={{ flexDirection: "row", alignItems: "baseline", gap: space.md }}>
              <Txt variant="hero" c={tint(d.value!)}>{d.value}</Txt>
              <Txt variant="h2">{d.label}</Txt>
              {d.freshness === "OVERDUE" ? <Tag label="Overdue" tint={color.warn} /> : null}
            </View>
            <Txt variant="small">{[["Yesterday", d.yesterday], ["A week ago", d.a_week_ago], ["A month ago", d.a_month_ago]].filter(([, v]) => v !== null && v !== undefined).map(([k, v]) => `${k}: ${v}`).join(" · ")}</Txt>
            <Txt variant="tiny">Reading for {d.date}.</Txt>
          </View>)}
      <Txt variant="tiny">{d?.note ?? "A published mood gauge, not a forecast or a trading signal."}</Txt>
      {link ? <Pressable onPress={() => Linking.openURL(link).catch(() => undefined)} accessibilityRole="link"><Txt variant="tiny" c={color.accent}>Source: alternative.me</Txt></Pressable> : null}
    </GCard>
  );
}
