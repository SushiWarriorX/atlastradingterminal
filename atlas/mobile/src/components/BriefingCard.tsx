import { Ionicons } from "@expo/vector-icons";
import React, { useState } from "react";
import { View } from "react-native";
import type { ResearchResponse } from "../api/types";
import { AGENT_TITLE, briefingSections, coverageNote, lineText } from "../lib/briefing";
import { color, space } from "../theme";
import { Skeleton, TextButton, Txt } from "./ui";

const COLLAPSED_LINES = 2;

const TINT = { changed: color.text, supports: color.text, risks: color.text, watch: color.text } as const;

/** "What matters now": the combined briefing of the four agents, as four short answers. Disagreements between agents are shown, not smoothed over. */
export function BriefingCard({ research, loading, now }: { research: ResearchResponse | undefined; loading: boolean; now: number }) {
  const [more, setMore] = useState(false);
  if (!research) {
    return (
      <View>
        <Txt variant="title" style={{ fontSize: 24 }}>What matters now</Txt>
        <View style={{ gap: space.sm, marginTop: space.md }}>{loading ? [0, 1, 2, 3].map((i) => <Skeleton key={i} h={14} w={i % 2 ? "78%" : "92%"} />) : <Txt variant="small">The briefing is not available.</Txt>}</View>
      </View>
    );
  }
  const b = research.briefing;
  const note = coverageNote(b);
  const hidden = briefingSections(b).reduce((n, sec) => n + Math.max(0, sec.lines.length - COLLAPSED_LINES), 0);
  return (
    <View>
      <Txt variant="title" style={{ fontSize: 24 }}>What matters now</Txt>
      <Txt variant="body" c={color.dim} style={{ marginTop: space.xs }} testID="briefing-headline">{b.headline.split(" · ").join(", ")}</Txt>
      {b.disagreements.map((d) => (
        <View key={d.agents.join("-")} style={{ flexDirection: "row", gap: space.sm, marginTop: space.md }} testID="briefing-disagreement">
          <Ionicons name="git-compare-outline" size={16} color={color.text} style={{ marginTop: 2 }} />
          <Txt variant="small" c={color.text} style={{ flex: 1 }}>{d.text}</Txt>
        </View>
      ))}
      {note ? <Txt variant="tiny" style={{ marginTop: space.sm }} testID="briefing-coverage">{note}</Txt> : null}
      <View style={{ gap: space.xl, marginTop: space.xl }}>
        {briefingSections(b).map((sec) => (
          <View key={sec.key} testID={`briefing-${sec.key}`}>
            <Txt variant="h2" c={TINT[sec.key]} style={{ marginBottom: 8 }}>{sec.title}</Txt>
            {sec.lines.length === 0 ? (
              <Txt variant="small">Nothing notable.</Txt>
            ) : (
              (more ? sec.lines : sec.lines.slice(0, COLLAPSED_LINES)).map((l, i) => (
                <Txt key={i} variant="body" style={{ marginBottom: 10 }}>{lineText(l, now)} <Txt variant="tiny">{AGENT_TITLE[l.agent]}</Txt></Txt>
              ))
            )}
          </View>
        ))}
      </View>
      {hidden > 0 && <View style={{ marginTop: space.md }}><TextButton label={more ? "Show less" : `Show ${hidden} more`} onPress={() => setMore((v) => !v)} testID="briefing-more" /></View>}
    </View>
  );
}
