import React, { useState } from "react";
import { Linking, Pressable, View } from "react-native";
import { safeUrl } from "../lib/links";
import { useNarrative } from "../state/queries";
import { useOpenAsset } from "../state/selection";
import { color, grad, space } from "../theme";
import { Banner, Divider, GCard, Skeleton, Tag, TextButton, Txt } from "./ui";

const pc = (x: number | null | undefined) => (x === null || x === undefined ? "n/a" : `${x > 0 ? "+" : x < 0 ? "−" : ""}${Math.abs(x).toFixed(1)}%`);
const tone = (x: number | null | undefined) => (x === null || x === undefined ? color.dim : x > 0 ? color.up : x < 0 ? color.down : color.text);

/** The market narrative of the day (Quantum, Nuclear, Robotics ...): a theme picked by fixed rules from price strength, breadth, volume and headlines. A story, not a forecast. */
export function NarrativeCard() {
  const q = useNarrative();
  const open = useOpenAsset();
  const [more, setMore] = useState(false);
  const d = q.data;
  return (
    <GCard colors={grad.hot} style={{ padding: space.lg, gap: space.md }} testID="narrative-card">
      <View><Txt variant="label">Narrative of the day</Txt>{d?.asof ? <Txt variant="tiny">{d.asof}</Txt> : null}</View>
      {q.isLoading ? <View style={{ gap: space.sm }} testID="narrative-loading"><Skeleton h={28} /><Skeleton h={60} /></View>
        : q.isError || !d ? <Banner tone="warn" title="Couldn't load today's narrative" testID="narrative-error">{q.error instanceof Error ? q.error.message : "Something went wrong."}</Banner>
        : !d.theme ? <Banner tone="warn" title="No narrative today" testID="narrative-none">{d.notes.join(" ") || "Not enough price data to choose one."}</Banner>
        : (
          <View style={{ gap: space.md }} testID="narrative-body">
            {d.demo ? <Banner tone="demo" title="Demo data" testID="narrative-demo">Prices are synthetic, so this narrative is not real.</Banner> : null}
            <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center", gap: space.md }}>
              <Txt variant="title" style={{ flex: 1 }} testID="narrative-name">{d.name}</Txt>
              <Tag label={`Score ${d.score?.toFixed(0)}`} />
            </View>
            <Txt variant="small">{d.context}</Txt>
            <Txt variant="tiny">{d.context_note}</Txt>

            <Txt variant="label">Why it is in focus</Txt>
            {d.why_now.map((w, i) => <Txt key={i} variant="small">• {w}</Txt>)}

            <Txt variant="label">The basket</Txt>
            <View testID="narrative-basket">
              {d.basket.map((b, i) => (
                <View key={b.symbol}>{i > 0 && <Divider />}
                  <Pressable onPress={() => open(`EQUITY:US:${b.symbol}`)} accessibilityRole="button" style={{ flexDirection: "row", justifyContent: "space-between", paddingVertical: 6, gap: space.md }}>
                    <Txt variant="body">{b.symbol}</Txt>
                    {b.available ? <Txt variant="small">1D <Txt variant="small" c={tone(b.change_1d_pct)}>{pc(b.change_1d_pct)}</Txt> · 1M <Txt variant="small" c={tone(b.return_1m_pct)}>{pc(b.return_1m_pct)}</Txt></Txt> : <Txt variant="tiny">no data</Txt>}
                  </Pressable>
                </View>))}
            </View>

            <Txt variant="label">Risks to weigh</Txt>
            {d.risks.map((r, i) => <Txt key={i} variant="small" c={color.warn}>• {r}</Txt>)}
            <Txt variant="tiny">{d.volatility_note}</Txt>

            {d.headlines.length > 0 ? (<View style={{ gap: 4 }}><Txt variant="label">Headlines (from your news feeds)</Txt>
              {d.headlines.slice(0, 4).map((h, i) => { const u = safeUrl(h.link); return (
                <Pressable key={i} onPress={() => u && Linking.openURL(u).catch(() => undefined)} disabled={!u} accessibilityRole={u ? "link" : undefined}><Txt variant="small">{h.title}<Txt variant="tiny"> · {h.feed}</Txt></Txt></Pressable>); })}</View>) : null}

            {more ? (
              <View style={{ gap: space.sm }} testID="narrative-more">
                <Txt variant="label">Other themes today</Txt>
                {d.all_themes.map((t) => <View key={t.theme} style={{ flexDirection: "row", justifyContent: "space-between" }}><Txt variant="small">{t.name}{t.recently_featured ? " (shown recently)" : ""}</Txt><Txt variant="small">{t.score.toFixed(0)}</Txt></View>)}
                <Txt variant="label">How it is picked</Txt>
                {d.method.steps.map((s, i) => <Txt key={i} variant="tiny">{i + 1}. {s}</Txt>)}
                {Object.entries(d.method.weights).map(([k, w]) => <Txt key={k} variant="tiny">{Math.round(w * 100)}% · {d.method.scales[k]}</Txt>)}
                {d.notes.map((n, i) => <Txt key={i} variant="tiny" c={color.warn}>{n}</Txt>)}
                <Txt variant="tiny">Not included: {d.gaps.join(" ")}</Txt>
              </View>) : null}
            <TextButton label={more ? "Hide details" : "Other themes and how it is picked"} onPress={() => setMore(!more)} testID="narrative-more-toggle" />
            <Txt variant="tiny">{d.disclaimer}</Txt>
          </View>)}
    </GCard>
  );
}
