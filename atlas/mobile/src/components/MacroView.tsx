import React, { useState } from "react";
import { Linking, Pressable, ScrollView, View } from "react-native";
import { useMacroBrief } from "../state/queries";
import { localDateTime } from "../lib/format";
import { safeUrl } from "../lib/links";
import { signed } from "../lib/journal";
import { color, radius, space } from "../theme";
import { CalendarCard } from "./CalendarCard";
import { TreasuryCard } from "./TreasuryCard";
import { FxCard } from "./FxCard";
import { WorldCard } from "./WorldCard";
import { FedOpsCard } from "./FedOpsCard";
import { TgaCard } from "./TgaCard";
import { AuctionsCard } from "./AuctionsCard";
import { BudgetCard } from "./BudgetCard";
import { ScreenHeader } from "./ScreenHeader";
import { Banner, Chip, Divider, ErrorState, Skeleton, Tag, TextButton, Txt } from "./ui";
import type { MacroIndicator } from "../api/types";

/** The few numbers that drive the rate and inflation story: the Fed's rate, CPI, PCE and PPI (headline and core). Other series stay available from the server. */
const CORE = ["fed", "sofr", "cpi", "core_cpi", "pce", "core_pce", "ppi", "core_ppi"];
const open = (u: string | null | undefined) => { const s = safeUrl(u ?? null); if (s) Linking.openURL(s).catch(() => undefined); };
const value = (i: MacroIndicator) => (typeof i.value === "number" ? `${i.value.toFixed(2)}${i.unit?.startsWith("%") ? "%" : ""}` : String(i.value ?? "n/a"));
const when = (iso: string | null) => (iso ? localDateTime(iso) : "");

function Section({ title, note, children }: { title: string; note?: string; children: React.ReactNode }) {
  return <View style={{ gap: space.sm }}><View><Txt variant="label">{title}</Txt>{note ? <Txt variant="tiny">{note}</Txt> : null}</View>{children}</View>;
}

/** What matters today, key indicators, what is coming, and headlines. Facts, rule-based interpretation and headlines are labelled apart. */
export function MacroView() {
  const q = useMacroBrief();
  const [topic, setTopic] = useState("");
  const [openId, setOpenId] = useState<number | null>(null);
  const d = q.data;
  const heads = (d?.headlines ?? []).filter((h) => !topic || h.topic === topic);
  const core = (d?.indicators ?? []).filter((i) => CORE.includes(i.id));
  return (
    <View style={{ flex: 1, backgroundColor: color.bg }}>
      <ScreenHeader title="Macro" subtitle={d ? `Updated ${when(d.as_of)}` : undefined} />
      {q.isLoading ? <View style={{ padding: space.lg, gap: space.lg }}>{[0, 1, 2, 3].map((i) => <Skeleton key={i} h={44} />)}</View>
        : q.isError || !d ? <ErrorState testID="macro-error" title="Can't load the macro briefing" body={q.error instanceof Error ? q.error.message : "Something went wrong."} onRetry={() => q.refetch()} />
        : (
          <ScrollView contentContainerStyle={{ padding: space.lg, gap: space.xl, paddingBottom: space.xxl * 2 }} testID="macro-brief">
            {d.demo && <Banner tone="demo" title="Demo data" testID="macro-demo">{d.notice ?? "Official indicators and live headlines are not shown in demo mode."}</Banner>}
            {d.calendar_warning ? <Banner tone="warn" title="Calendar needs updating">{d.calendar_warning}</Banner> : null}
            <CalendarCard />
            <Section title="Key indicators" note="Fed rate, CPI, PCE and PPI: official data with its observation date, not live prices. Year-over-year for the price indexes.">
              {d.indicators_note ? <Txt variant="small" c={color.warn} testID="macro-indicators-note">{d.indicators_note}</Txt> : null}
              {core.length === 0 ? (d.indicators_note ? null : <Txt variant="small" c={color.warn}>No official indicators to show.</Txt>) : core.map((i, n) => (
                <View key={i.id}>{n > 0 && <Divider />}
                  {i.available ? (
                    <View style={{ flexDirection: "row", justifyContent: "space-between", paddingVertical: 8, gap: space.md }}>
                      <View style={{ flex: 1 }}><Txt variant="body">{i.label}</Txt><Txt variant="tiny">{i.obs_date}{i.freshness === "OVERDUE" ? " · overdue" : ""}</Txt></View>
                      <View style={{ alignItems: "flex-end" }}><Txt variant="h2">{value(i)}</Txt>{i.change ? <Txt variant="tiny">{signed(i.change.value)} {i.change.unit}</Txt> : null}</View>
                    </View>) : <View style={{ paddingVertical: 8 }}><Txt variant="body">{i.label}</Txt><Txt variant="tiny" c={color.down}>Unavailable: {i.reason}</Txt></View>}
                </View>))}
            </Section>
            <TreasuryCard />
            <FxCard />
            <FedOpsCard />
            <TgaCard />
            <AuctionsCard />
            <BudgetCard />
            <WorldCard />
            <Section title="Upcoming" note="Scheduled dates only. What each release contains is not known in advance.">
              {d.upcoming.length === 0 ? <Txt variant="small">No upcoming events could be loaded.</Txt> : d.upcoming.map((e, i) => (
                <View key={i} style={{ flexDirection: "row", gap: space.md }}><Txt variant="small" style={{ width: 120 }}>{e.at_utc ? when(e.at_utc) : e.date}</Txt><View style={{ flex: 1 }}><Txt variant="body">{e.title}</Txt><Txt variant="tiny">{e.source}</Txt></View></View>))}
            </Section>
            <Section title="Headlines" note="Titles and links as published by the named feed, not summarised or scored.">
              <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 4 }}>
                <Chip label="All" active={!topic} onPress={() => setTopic("")} testID="macro-topic-all" />
                {Object.entries(d.topics).map(([k, v]) => <Chip key={k} label={v} active={topic === k} onPress={() => setTopic(k)} testID={`macro-topic-${k}`} />)}
              </ScrollView>
              {heads.length === 0 ? <Txt variant="small">No matching headlines in the last 72 hours.</Txt> : heads.map((h, i) => (
                <View key={i} style={{ gap: 4, paddingVertical: 6 }} testID={`macro-head-${i}`}>
                  <Pressable onPress={() => open(h.link)} accessibilityRole="link" disabled={!safeUrl(h.link)}><Txt variant="body">{h.title}</Txt></Pressable>
                  <View style={{ flexDirection: "row", alignItems: "center", gap: 6, flexWrap: "wrap" }}><Tag label={h.topic_label} /><Txt variant="tiny">{h.feed} · {when(h.published)}</Txt><TextButton label={openId === i ? "Hide" : "What it can mean"} onPress={() => setOpenId(openId === i ? null : i)} /></View>
                  {openId === i && <View style={{ backgroundColor: color.surface, borderRadius: radius.md, padding: space.md }}><Txt variant="tiny" c={color.warn}>{h.implication_kind}</Txt><Txt variant="small">{h.implication}</Txt></View>}
                </View>))}
            </Section>
            {d.errors.length > 0 && <Banner tone="warn" title="Some sources failed">{d.errors.join("; ")}</Banner>}
            <Section title="Not shown"><Txt variant="small">{d.gaps.join(" ")}</Txt></Section>
          </ScrollView>)}
    </View>
  );
}
