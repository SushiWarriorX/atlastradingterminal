import { Ionicons } from "@expo/vector-icons";
import React, { useState } from "react";
import { View } from "react-native";
import type { ResearchResponse } from "../api/types";
import { AGENT_TITLE, briefingSections, coverageNote, lineText } from "../lib/briefing";
import { color, space } from "../theme";
import { Card, Skeleton, TextButton, Txt } from "./ui";

const COLLAPSED_LINES = 2;

const ICON = { changed: "swap-vertical", supports: "trending-up", risks: "alert-circle-outline", watch: "eye-outline" } as const;
const TINT = { changed: color.accent, supports: color.up, risks: color.warn, watch: color.dim } as const;

/** "What matters now": the combined briefing of the four agents, as four short answers. Disagreements between agents are shown, not smoothed over. */
export function BriefingCard({ research, loading, now }: { research: ResearchResponse | undefined; loading: boolean; now: number }) {
  const [more, setMore] = useState(false);
  if (!research) {
    return (
      <Card>
        <Txt variant="label">What matters now</Txt>
        <View style={{ gap: space.sm, marginTop: space.md }}>{loading ? [0, 1, 2, 3].map((i) => <Skeleton key={i} h={14} w={i % 2 ? "78%" : "92%"} />) : <Txt variant="small">The briefing is not available.</Txt>}</View>
      </Card>
    );
  }
  const b = research.briefing;
  const note = coverageNote(b);
  const hidden = briefingSections(b).reduce((n, sec) => n + Math.max(0, sec.lines.length - COLLAPSED_LINES), 0);
  return (
    <Card>
      <Txt variant="label">What matters now</Txt>
      <Txt variant="h2" style={{ marginTop: space.sm }} testID="briefing-headline">{b.headline}</Txt>
      {b.disagreements.map((d) => (
        <View key={d.agents.join("-")} style={{ flexDirection: "row", gap: space.sm, marginTop: space.md }} testID="briefing-disagreement">
          <Ionicons name="git-compare-outline" size={16} color={color.accent} style={{ marginTop: 2 }} />
          <Txt variant="small" style={{ flex: 1 }}>{d.text}</Txt>
        </View>
      ))}
      {note ? <Txt variant="tiny" style={{ marginTop: space.sm }} testID="briefing-coverage">{note}</Txt> : null}
      <View style={{ gap: space.lg, marginTop: space.lg }}>
        {briefingSections(b).map((sec) => (
          <View key={sec.key} testID={`briefing-${sec.key}`}>
            <View style={{ flexDirection: "row", alignItems: "center", gap: space.sm, marginBottom: 6 }}>
              <Ionicons name={ICON[sec.key]} size={16} color={TINT[sec.key]} />
              <Txt variant="label" c={TINT[sec.key]}>{sec.title}</Txt>
            </View>
            {sec.lines.length === 0 ? (
              <Txt variant="small">Nothing notable.</Txt>
            ) : (
              (more ? sec.lines : sec.lines.slice(0, COLLAPSED_LINES)).map((l, i) => (
                <View key={i} style={{ flexDirection: "row", gap: space.sm, marginBottom: 6 }}>
                  <Txt variant="small" style={{ width: 8 }}>•</Txt>
                  <Txt variant="body" style={{ flex: 1 }}>{lineText(l, now)} <Txt variant="tiny">{AGENT_TITLE[l.agent]}</Txt></Txt>
                </View>
              ))
            )}
          </View>
        ))}
      </View>
      {hidden > 0 && <View style={{ marginTop: space.md }}><TextButton label={more ? "Show less" : `Show ${hidden} more`} onPress={() => setMore((v) => !v)} testID="briefing-more" /></View>}
    </Card>
  );
}
