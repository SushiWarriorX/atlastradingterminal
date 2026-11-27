import React, { useState } from "react";
import { View } from "react-native";
import type { ExperimentEntry } from "../api/types";
import { useExperiments } from "../state/queries";
import { color, space } from "../theme";
import { Banner, Divider, GCard, Skeleton, Tag, TextButton, Txt } from "./ui";

function Entry({ e }: { e: ExperimentEntry }) {
  const [more, setMore] = useState(false);
  const failed = e.verdict === "failed";
  return (
    <View style={{ gap: space.sm }} testID={`experiment-${e.id}`}>
      <View style={{ flexDirection: "row", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
        <Txt variant="body" style={{ fontWeight: "700" }}>{e.name}</Txt>
        <Tag label={failed ? "Did not pass" : "Passed the bar"} tint={failed ? color.down : color.up} />
      </View>
      <Txt variant="tiny">Tested {e.date} · {e.period}</Txt>
      <Txt variant="small">{e.idea}</Txt>
      {e.results.map((r, i) => (
        <View key={i} style={{ flexDirection: "row", justifyContent: "space-between", gap: space.md, paddingVertical: 2 }}>
          <Txt variant="small" style={{ flex: 1 }}>{r.k}</Txt><Txt variant="body">{r.v}</Txt>
        </View>))}
      <Txt variant="small">{e.reading}</Txt>
      {more ? (
        <View style={{ gap: 4 }}>
          <Txt variant="label">The bar, written down before the run</Txt>
          {e.conditions.map((c, i) => <Txt key={i} variant="tiny">{c.met ? "✓" : "✗"} {c.rule}</Txt>)}
          <Txt variant="tiny">Registered: {e.registered}.</Txt>
          <Txt variant="tiny" c={color.warn}>Not verified: {e.not_verified}</Txt>
        </View>) : null}
      <TextButton label={more ? "Hide the bar and caveats" : "Show the bar and caveats"} onPress={() => setMore(!more)} testID={`experiment-more-${e.id}`} />
    </View>
  );
}

/** The pre-registered strategy experiments and how each ended: a frozen record, never recomputed. Research only; nothing here is advice. */
export function ExperimentsCard() {
  const q = useExperiments();
  const d = q.data;
  return (
    <GCard style={{ padding: space.lg, gap: space.md }} testID="experiments-card">
      <View><Txt variant="h2">Experiments record</Txt><Txt variant="tiny">Each idea tested once, with the pass bar written down first</Txt></View>
      {q.isLoading ? <Skeleton h={80} />
        : q.isError || !d ? <Banner tone="warn" title="Couldn't load the experiments record" testID="experiments-error">{q.error instanceof Error ? q.error.message : "Something went wrong."}</Banner>
        : (
          <View style={{ gap: space.md }} testID="experiments-body">
            <Txt variant="label">{d.tested} tested, {d.passed} passed the bar</Txt>
            <Txt variant="tiny">{d.note}</Txt>
            {d.entries.map((e, i) => (<View key={e.id} style={{ gap: space.sm }}>{i > 0 ? <Divider /> : null}<Entry e={e} /></View>))}
          </View>)}
    </GCard>
  );
}
