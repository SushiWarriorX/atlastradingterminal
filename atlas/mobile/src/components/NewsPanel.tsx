import React from "react";
import { ScrollView, View } from "react-native";
import { relativeTime } from "../lib/format";
import { useNow, useResearch } from "../state/queries";
import { color, space } from "../theme";
import { StoryItem } from "./AgentRow";
import { Skeleton, Txt } from "./ui";

/** The News agent's findings for the asset being read, kept beside the research on wide screens. Same data as the News row: headlines, sources, when they were published. */
export function NewsPanel({ id }: { id: string | null }) {
  const now = useNow(30_000);
  const research = useResearch(id ?? "");
  const f = research.data?.findings.news;
  const stories = f?.stories ?? [];
  return (
    <View style={{ flex: 1 }} testID="news-panel">
      <View style={{ paddingHorizontal: space.lg, paddingTop: space.lg, paddingBottom: space.sm }}>
        <Txt variant="h2">News</Txt>
        {research.data?.asset ? <Txt variant="tiny">About {research.data.asset.name}{f?.analyzed_at ? `, checked ${relativeTime(f.analyzed_at, now)}` : ""}</Txt> : null}
      </View>
      <ScrollView contentContainerStyle={{ paddingHorizontal: space.lg, paddingBottom: space.xl }}>
        {!id ? <Txt variant="small">Pick an asset to see its news.</Txt>
          : !f ? <View style={{ gap: space.md }}>{[0, 1, 2, 3].map((i) => <Skeleton key={i} h={44} />)}</View>
          : <>
              <Txt variant="small" c={f.status === "unavailable" ? color.warn : color.dim} style={{ marginBottom: space.md }}>{f.takeaway}</Txt>
              {stories.map((st) => <StoryItem key={st.id} st={st} now={now} />)}
              {f.missing.map((m, k) => <Txt key={k} variant="tiny" style={{ marginTop: 4 }}>{m.what}: {m.why}</Txt>)}
              {f.limitations.length ? <Txt variant="tiny" style={{ marginTop: space.md }}>{f.limitations[0]}</Txt> : null}
            </>}
      </ScrollView>
    </View>
  );
}
