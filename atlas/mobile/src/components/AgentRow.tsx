import { Ionicons } from "@expo/vector-icons";
import React, { useState } from "react";
import { ActivityIndicator, Linking, Pressable, StyleSheet, View } from "react-native";
import type { AgentName, Finding, Story } from "../api/types";
import { AGENT_TITLE, rowKind, STANCE_LABEL } from "../lib/briefing";
import { countdown, dateOnly, localDateTime, providerName, relativeTime } from "../lib/format";
import { safeUrl } from "../lib/links";
import { color, radius, space, stanceColor } from "../theme";
import { TextButton, Txt } from "./ui";

const ICON: Record<AgentName, React.ComponentProps<typeof Ionicons>["name"]> = { news: "newspaper-outline", technical: "pulse-outline", macro: "globe-outline", fundamentals: "business-outline" };
const KIND_LABEL: Record<Story["kind"], string | null> = { reporting: null, opinion: "Opinion", unconfirmed: "Unconfirmed report" };
const open = (u: string | null) => { const s = safeUrl(u); if (s) Linking.openURL(s).catch(() => undefined); };

interface Props { first?: boolean; agent: AgentName; finding: Finding | undefined; now: number; expanded: boolean; onToggle: () => void; onRefresh: () => void; refreshing: boolean; refreshMessage: string | null }

/** One agent: name, one clear takeaway and when it was last updated. Opening it reveals the evidence: readings, figures with sources, links, and what is missing. */
export function AgentRow({ first, agent, finding, now, expanded, onToggle, onRefresh, refreshing, refreshMessage }: Props) {
  const kind = rowKind(finding);
  const f = finding;
  const stance = f?.stance && f.stance !== "insufficient" ? f.stance : null;
  return (
    <View style={[s.wrap, !first && s.sep]} testID={`agent-${agent}`}>
      <Pressable onPress={onToggle} accessibilityRole="button" accessibilityState={{ expanded }} accessibilityLabel={`${AGENT_TITLE[agent]}. ${f?.takeaway ?? "Loading"}`} style={({ pressed }) => [s.head, pressed && { opacity: 0.75 }]} testID={`agent-toggle-${agent}`}>
        <View style={s.icon}><Ionicons name={ICON[agent]} size={19} color={color.text} /></View>
        <View style={{ flex: 1, minWidth: 0 }}>
          <View style={{ flexDirection: "row", alignItems: "center", gap: space.sm }}>
            <Txt variant="h2">{AGENT_TITLE[agent]}</Txt>
            {stance && <View style={{ backgroundColor: stanceColor(stance) + "26", borderRadius: 8, paddingHorizontal: 8, paddingVertical: 2 }}><Txt variant="tiny" c={stanceColor(stance)} style={{ fontWeight: "700" }} testID={`stance-${agent}`}>{STANCE_LABEL[stance]}</Txt></View>}
            {f?.demo && <Txt variant="tiny" c={color.demo} style={{ fontWeight: "700" }}>DEMO</Txt>}
          </View>
          {kind === "pending" ? (
            <View style={{ flexDirection: "row", alignItems: "center", gap: space.sm, marginTop: 4 }}><ActivityIndicator size="small" color={color.dim} /><Txt variant="small">Working on it…</Txt></View>
          ) : (
            <Txt variant="small" c={kind === "unavailable" ? color.warn : color.dim} numberOfLines={expanded ? undefined : 2} style={{ marginTop: 3 }} testID={`takeaway-${agent}`}>{f?.takeaway}</Txt>
          )}
          {f?.analyzed_at && kind !== "pending" ? <Txt variant="tiny" style={{ marginTop: 3 }}>Updated {relativeTime(f.analyzed_at, now)}{f.data_as_of ? ` · data as of ${localDateTime(f.data_as_of)}` : ""}</Txt> : null}
        </View>
        <Ionicons name={expanded ? "chevron-up" : "chevron-down"} size={18} color={color.faint} />
      </Pressable>
      {expanded && f && kind !== "pending" && <Details f={f} now={now} onRefresh={onRefresh} refreshing={refreshing} refreshMessage={refreshMessage} />}
    </View>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return <View style={{ marginTop: space.lg }}><Txt variant="label" style={{ marginBottom: 6 }}>{title}</Txt>{children}</View>;
}

function Details({ f, now, onRefresh, refreshing, refreshMessage }: { f: Finding; now: number; onRefresh: () => void; refreshing: boolean; refreshMessage: string | null }) {
  const [allFacts, setAllFacts] = useState(false);
  const facts = f.facts.filter((x) => x.key !== "description" || x.display);
  const shown = allFacts ? facts : facts.slice(0, 8);
  return (
    <View style={s.body}>
      {f.status === "unavailable" && (
        <View style={{ gap: space.sm }}>
          <Txt variant="body" c={color.warn}>This analysis is not available right now.</Txt>
          {f.error && f.missing.length === 0 ? <Txt variant="small">Reason: {f.error}</Txt> : null}          {/* otherwise the reason is in the list below */}
        </View>
      )}
      {f.explanation && (
        <View style={s.explain} testID="explanation">
          <Txt variant="label" c={color.text}>In plain words</Txt>
          <Txt variant="body" style={{ marginTop: 4 }}>{f.explanation.text}</Txt>
          <Txt variant="tiny" style={{ marginTop: 4 }}>AI-written ({f.explanation.model}). {f.explanation.note}</Txt>
        </View>
      )}
      {f.interpretations.length > 0 && (
        <Section title="How it reads (interpretation)">
          {f.interpretations.map((i, k) => (
            <View key={k} style={{ marginBottom: space.sm }}>
              <Txt variant="body">{i.text}{i.timeframe ? <Txt variant="tiny">  [{i.timeframe}]</Txt> : null}</Txt>
              {i.caveat ? <Txt variant="tiny" style={{ marginTop: 2 }}>{i.caveat}</Txt> : null}
            </View>
          ))}
          {f.stance_rule ? <Txt variant="tiny">How the stance is decided: {f.stance_rule}</Txt> : null}
        </Section>
      )}
      {f.stories.length > 0 && (
        <Section title="Stories (reporting, with sources)">
          {f.stories.map((st) => <StoryItem key={st.id} st={st} now={now} />)}
        </Section>
      )}
      {f.levels.length > 0 && (
        <Section title="Key levels (calculated from past prices)">
          {f.levels.map((l) => (
            <View key={l.id} style={s.kv}>
              <Txt variant="small" style={{ flex: 1 }}>{l.kind === "support" ? "Support" : "Resistance"} · {l.timeframe}</Txt>
              <Txt variant="body" style={{ fontWeight: "600" }}>{l.display}</Txt>
              <Txt variant="tiny" style={{ width: 54, textAlign: "right" }}>{l.distance_pct === null ? "" : `${l.distance_pct > 0 ? "+" : "−"}${Math.abs(l.distance_pct).toFixed(1)}%`}</Txt>
            </View>
          ))}
          <Txt variant="tiny" style={{ marginTop: 4 }}>{f.levels[0].derivation}</Txt>
        </Section>
      )}
      {f.events.length > 0 && (
        <Section title="Coming up (shown in your timezone)">
          {f.events.map((e) => (
            <Pressable key={e.id} onPress={() => open(e.link)} disabled={!safeUrl(e.link)} style={{ marginBottom: space.sm }} accessibilityRole={safeUrl(e.link) ? "link" : undefined}>
              <Txt variant="body">{e.title}</Txt>
              <Txt variant="small">{e.at_utc ? `${localDateTime(e.at_utc)} · ${countdown(e.at_utc, now)}` : e.date ? dateOnly(e.date) : ""}{e.note ? ` · ${e.note}` : ""}</Txt>
            </Pressable>
          ))}
        </Section>
      )}
      {facts.length > 0 && (
        <Section title="Key figures">
          {shown.map((x) => (
            <View key={x.key} style={s.fact}>
              <View style={{ flex: 1, paddingRight: space.md }}>
                <Txt variant="small">{x.label}</Txt>
                <Txt variant="tiny">{x.kind === "reported" ? "reported" : "calculated"}{x.timeframe ? ` · ${x.timeframe}` : ""}{x.as_of ? ` · as of ${localDateTime(x.as_of)}` : ""} · {x.source}</Txt>
              </View>
              <Txt variant="body" style={{ fontWeight: "600", maxWidth: "52%", textAlign: "right" }} numberOfLines={4}>{x.display}</Txt>
            </View>
          ))}
          {facts.length > 8 && <TextButton label={allFacts ? "Show fewer" : `Show all ${facts.length} figures`} onPress={() => setAllFacts((v) => !v)} />}
        </Section>
      )}
      {f.missing.length > 0 && (
        <Section title="Not available">
          {f.missing.map((m, k) => <Txt key={k} variant="small" style={{ marginBottom: 3 }}>• {m.what}: {m.why}</Txt>)}
        </Section>
      )}
      {f.sources.length > 0 && (
        <Section title="Sources">
          {f.sources.map((src, k) => (
            <Pressable key={k} onPress={() => open(src.url)} disabled={!safeUrl(src.url)} style={{ marginBottom: 6 }} accessibilityRole={safeUrl(src.url) ? "link" : undefined} testID={safeUrl(src.url) ? `source-link-${k}` : undefined}>
              <Txt variant="small" c={safeUrl(src.url) ? color.accent : color.dim}>{providerName(src.name)}{safeUrl(src.url) ? "  ↗" : ""}</Txt>
              <Txt variant="tiny">{[src.status, src.as_of ? `as of ${localDateTime(src.as_of)}` : null, src.note].filter(Boolean).join(" · ")}</Txt>
            </Pressable>
          ))}
        </Section>
      )}
      {f.limitations.length > 0 && (
        <Section title="Limits of this analysis">
          {f.limitations.map((l, k) => <Txt key={k} variant="tiny" style={{ marginBottom: 3 }}>• {l}</Txt>)}
        </Section>
      )}
      <View style={{ marginTop: space.lg, flexDirection: "row", alignItems: "center", gap: space.md }}>
        <TextButton label={refreshing ? "Refreshing…" : "Refresh this analysis"} onPress={onRefresh} disabled={refreshing} testID={`refresh-${f.agent}`} />
        {refreshMessage ? <Txt variant="tiny" c={color.warn} testID={`refresh-msg-${f.agent}`}>{refreshMessage}</Txt> : null}
      </View>
    </View>
  );
}

export function StoryItem({ st, now }: { st: Story; now: number }) {
  const label = KIND_LABEL[st.kind];
  const url = safeUrl(st.link);
  return (
    <View style={{ marginBottom: space.md }} testID={`story-${st.id}`}>
      <Pressable onPress={() => open(st.link)} disabled={!url} accessibilityRole={url ? "link" : undefined}>
        <Txt variant="body" c={url ? color.text : color.dim} style={{ fontWeight: "600" }}>{st.title}{url ? "  ↗" : ""}</Txt>
      </Pressable>
      <Txt variant="tiny">
        {st.source} · published {st.published ? relativeTime(st.published, now) : "at an unknown time"}
        {st.scope === "industry" ? " · industry story" : ""}{st.also.length ? ` · also ${st.also.map((a) => a.source).join(", ")}` : ""}
      </Txt>
      {label && <Txt variant="tiny" c={color.warn} style={{ fontWeight: "700" }}>{label} (judged by wording only)</Txt>}
      {st.why_it_matters ? <Txt variant="small" style={{ marginTop: 3 }}>Why it may matter: {st.why_it_matters}</Txt> : null}
    </View>
  );
}

const s = StyleSheet.create({
  wrap: { overflow: "hidden" },
  sep: { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: color.border },
  head: { flexDirection: "row", alignItems: "flex-start", gap: space.md, padding: space.lg },
  icon: { width: 38, height: 38, borderRadius: 19, backgroundColor: color.surface2, alignItems: "center", justifyContent: "center" },
  body: { paddingHorizontal: space.lg, paddingBottom: space.lg },
  explain: { marginTop: space.lg, padding: space.md, borderRadius: radius.md, backgroundColor: color.surface2 },
  kv: { flexDirection: "row", alignItems: "center", paddingVertical: 4, gap: space.sm },
  fact: { flexDirection: "row", alignItems: "flex-start", paddingVertical: 6, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: color.border },
});
