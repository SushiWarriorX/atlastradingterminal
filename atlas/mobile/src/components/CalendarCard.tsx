import React, { useMemo, useState } from "react";
import { Pressable, View } from "react-native";
import type { CalendarEvent } from "../api/types";
import { dayLabel, detailLine, groupByDay, importanceColor, KIND_LABEL } from "../lib/calendar";
import { useCalendar } from "../state/queries";
import { useOpenAsset } from "../state/selection";
import { color, space } from "../theme";
import { Banner, Chip, GCard, Skeleton, Tag, Txt } from "./ui";

const KINDS = ["", "earnings", "economy", "rates", "dividend", "auction"];
const SCOPES: [string, string][] = [["major", "Major"], ["watchlist", "Mine"], ["all", "All"]];

function Row({ e, onOpen }: { e: CalendarEvent; onOpen: (id: string) => void }) {
  const press = e.instrument_id ? () => onOpen(e.instrument_id!) : undefined;
  const when = e.time_label ?? (e.at_utc ? new Date(e.at_utc).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" }) : "");
  return (
    <Pressable onPress={press} disabled={!press} accessibilityRole={press ? "button" : undefined} testID={`cal-event-${e.kind}`} style={{ flexDirection: "row", gap: space.sm, paddingVertical: 8 }}>
      <Txt variant="body" c={importanceColor(e.importance, color)} style={{ width: 14 }}>●</Txt>
      <View style={{ flex: 1, gap: 2 }}>
        <Txt variant="body">{e.symbol ? `${e.symbol}${e.name ? ` · ${e.name}` : ""}` : e.title}{e.watch ? " ★" : ""}</Txt>
        <Txt variant="small">{e.symbol ? (e.kind === "dividend" ? "Ex-dividend" : "Reports") : ""}{e.symbol && when ? " · " : ""}{when}</Txt>
        <Txt variant="tiny">{detailLine(e)}</Txt>
        <View style={{ flexDirection: "row", gap: 6, alignItems: "center" }}><Tag label={KIND_LABEL[e.kind]} /><Txt variant="tiny">{e.official ? "official" : "unofficial"}</Txt></View>
      </View>
    </Pressable>
  );
}

/** Earnings, economic data, Fed decisions, dividends and Treasury auctions in one list grouped by day. Tap a company to open it. */
export function CalendarCard() {
  const [kind, setKind] = useState("");
  const [scope, setScope] = useState("major");
  const [days, setDays] = useState(7);
  const q = useMemo(() => new URLSearchParams({ days: String(days), scope, ...(kind ? { kinds: kind } : {}) }).toString(), [days, scope, kind]);
  const cal = useCalendar(q);
  const open = useOpenAsset();
  const d = cal.data;
  const today = new Date().toISOString().slice(0, 10);
  const groups = useMemo(() => groupByDay(d?.items ?? []), [d]);
  return (
    <GCard style={{ padding: space.lg, gap: space.md }} testID="calendar-card">
      <View><Txt variant="h2">Calendar</Txt><Txt variant="tiny">Earnings, economic data, Fed decisions, dividends, Treasury auctions</Txt></View>
      <View style={{ flexDirection: "row", gap: 4, flexWrap: "wrap" }}>{[7, 14, 21].map((n) => <Chip key={n} label={`${n}d`} active={days === n} onPress={() => setDays(n)} testID={`cal-days-${n}`} />)}{SCOPES.map(([v, l]) => <Chip key={v} label={l} active={scope === v} onPress={() => setScope(v)} testID={`cal-scope-${v}`} />)}</View>
      <View style={{ flexDirection: "row", gap: 4, flexWrap: "wrap" }}>{KINDS.map((k) => <Chip key={k || "all"} label={k ? KIND_LABEL[k] : "All"} active={kind === k} onPress={() => setKind(k)} testID={`cal-kind-${k || "all"}`} />)}</View>
      {cal.isLoading ? <View style={{ gap: space.md }} testID="calendar-loading"><Txt variant="small">Loading the calendar. The first load fetches several sources and can take a few seconds.</Txt>{[0, 1, 2].map((i) => <Skeleton key={i} h={40} />)}</View>
        : cal.isError || !d ? <Banner tone="warn" title="Couldn't load the calendar" testID="calendar-error">{cal.error instanceof Error ? cal.error.message : "Something went wrong."}</Banner>
        : (
          <View testID="calendar-body">
            {d.demo ? <Banner tone="demo" title="Demo data">Company events here are synthetic. The Fed dates are real.</Banner> : null}
            {d.sources.some((s) => !s.ok) ? <Banner tone="warn" title="Some sources could not be loaded">{d.sources.filter((s) => !s.ok).map((s) => `${s.name} (${s.error})`).join("; ")}. The rest is shown.</Banner> : null}
            {d.notes.filter((n) => !n.startsWith("Demo mode")).map((n, i) => <Txt key={i} variant="tiny" c={color.warn}>{n}</Txt>)}
            {groups.length === 0 ? <Txt variant="small">Nothing in this window for these filters.</Txt> : groups.map((g) => (
              <View key={g.day} style={{ marginTop: space.sm }}>
                <Txt variant="label">{dayLabel(g.day, today)} · {g.events.length}</Txt>
                {g.events.map((e, i) => <Row key={`${e.kind}-${e.symbol ?? e.title}-${i}`} e={e} onOpen={open} />)}
              </View>))}
            <Txt variant="tiny" style={{ marginTop: space.md }}>{d.importance_note} ● red = high, amber = medium, grey = low.</Txt>
          </View>)}
    </GCard>
  );
}
