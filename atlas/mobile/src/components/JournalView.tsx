import { Ionicons } from "@expo/vector-icons";
import React, { useMemo, useState } from "react";
import { FlatList, KeyboardAvoidingView, Modal, Platform, Pressable, ScrollView, StyleSheet, TextInput, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { ApiError } from "../api/client";
import type { JournalEntry, JournalFilters } from "../api/types";
import { blankForm, fromEntry, missingText, resultText, signed, toBody, type JournalForm } from "../lib/journal";
import { useJournal, useJournalDelete, useJournalSave } from "../state/queries";
import { useIsWide } from "../state/layout";
import { color, font, radius, space } from "../theme";
import { noOutline } from "./ConnectForm";
import { ScreenHeader } from "./ScreenHeader";
import { Chip, Divider, EmptyState, ErrorState, IconButton, PrimaryButton, Skeleton, Tag, TextButton, Txt } from "./ui";

const FILTERS: { key: NonNullable<JournalFilters["status"]>; label: string }[] = [{ key: "", label: "All" }, { key: "open", label: "Open" }, { key: "closed", label: "Closed" }, { key: "note", label: "Notes" }];
const today = () => new Date().toISOString().slice(0, 10);
const day = (iso: string) => iso.slice(0, 10);

/** The journal: write a trade down like a note. Only the symbol is needed; P&L appears when size, entry and exit are all there. */
export function JournalView() {
  const wide = useIsWide();
  const [filters, setFilters] = useState<JournalFilters>({ q: "", status: "" });
  const log = useJournal(filters);
  const [editing, setEditing] = useState<JournalEntry | "new" | null>(null);
  const items = log.data?.items ?? [];
  const st = log.data?.stats;
  return (
    <View style={{ flex: 1, backgroundColor: color.bg }}>
      <ScreenHeader title="Journal" subtitle={log.data ? `${log.data.total} ${log.data.total === 1 ? "entry" : "entries"}` : undefined} right={<IconButton name="add-circle" size={32} tint={color.accent} label="Add an entry" onPress={() => setEditing("new")} testID="journal-add" />} />
      <View style={{ paddingHorizontal: space.lg, gap: space.md, paddingBottom: space.sm }}>
        {st && st.n > 0 && (
          <View testID="journal-stats">
            <View style={{ flexDirection: "row", gap: space.xl }}>
              <Stat label="Closed" value={String(st.n)} />
              <Stat label="Net P&L" value={signed(st.net_pnl)} tint={(st.net_pnl ?? 0) >= 0 ? color.up : color.down} />
              <Stat label="Win rate" value={st.win_rate === undefined ? "—" : `${Math.round(st.win_rate * 100)}%`} />
              {wide && <Stat label="Profit factor" value={st.profit_factor == null ? "—" : st.profit_factor.toFixed(2)} />}
            </View>
            {st.note ? <Txt variant="tiny" c={color.warn} style={{ marginTop: 4 }}>{st.note}</Txt> : null}
          </View>)}
        <View style={s.search}>
          <Ionicons name="search" size={16} color={color.faint} />
          <TextInput value={filters.q ?? ""} onChangeText={(q) => setFilters({ ...filters, q })} placeholder="Search notes and symbols" placeholderTextColor={color.faint} style={[s.input, noOutline]} testID="journal-search" accessibilityLabel="Search journal" />
        </View>
        <View style={{ flexDirection: "row", gap: 4 }}>{FILTERS.map((f) => <Chip key={f.key} label={f.label} active={(filters.status ?? "") === f.key} onPress={() => setFilters({ ...filters, status: f.key })} testID={`journal-filter-${f.key || "all"}`} />)}</View>
      </View>
      {log.isLoading ? <View style={{ padding: space.lg, gap: space.lg }}>{[0, 1, 2].map((i) => <Skeleton key={i} h={44} />)}</View>
        : log.isError ? <ErrorState testID="journal-error" title="Can't load your journal" body={log.error instanceof Error ? log.error.message : "Something went wrong."} onRetry={() => log.refetch()} />
        : items.length === 0 ? <EmptyState testID="journal-empty" icon="book-outline" title={log.data?.total ? "Nothing matches" : "No entries yet"} body={log.data?.total ? "Try a different search or filter." : "Write down a trade or an idea. A symbol and a note is enough."} action={log.data?.total ? undefined : <PrimaryButton label="Add an entry" onPress={() => setEditing("new")} testID="journal-empty-add" />} />
        : <FlatList data={items} keyExtractor={(e) => e.id} ItemSeparatorComponent={Divider} contentContainerStyle={{ paddingBottom: space.xxl }} testID="journal-list"
            renderItem={({ item }) => <EntryRow e={item} onPress={() => setEditing(item)} />} />}
      {editing && <EntryForm entry={editing === "new" ? null : editing} onClose={() => setEditing(null)} />}
    </View>
  );
}

function Stat({ label, value, tint }: { label: string; value: string; tint?: string }) {
  return <View><Txt variant="tiny">{label}</Txt><Txt variant="h2" c={tint}>{value}</Txt></View>;
}

function EntryRow({ e, onPress }: { e: JournalEntry; onPress: () => void }) {
  const result = resultText(e);
  const pnl = e.status === "closed" ? (e.net_pnl_num ?? 0) : 0;
  return (
    <Pressable onPress={onPress} accessibilityRole="button" accessibilityLabel={`${e.symbol} ${e.direction}. ${result || "Note"}`} testID={`entry-${e.id}`} style={({ pressed }) => [s.row, pressed && { opacity: 0.7 }]}>
      <View style={{ flex: 1, minWidth: 0 }}>
        <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
          <Txt variant="h2">{e.symbol}</Txt><Tag label={e.direction === "long" ? "Long" : "Short"} />{e.origin === "imported" && <Tag label="Imported" />}
        </View>
        <Txt variant="tiny" style={{ marginTop: 2 }}>{day(e.entry_at)}{e.size ? ` · ${e.size}` : ""}{e.entry_price ? ` @ ${e.entry_price}` : ""}{e.exit_price ? ` → ${e.exit_price}` : ""}</Txt>
        {e.note || e.thesis ? <Txt variant="small" numberOfLines={1} style={{ marginTop: 2 }}>{e.note ?? e.thesis}</Txt> : null}
        {missingText(e) ? <Txt variant="tiny" c={color.warn}>{missingText(e)}</Txt> : null}
      </View>
      {result ? (
        <View style={{ alignItems: "flex-end" }}>
          <Txt variant="h2" c={e.status === "open" ? color.dim : pnl >= 0 ? color.up : color.down}>{result}</Txt>
          {e.return_pct !== null ? <Txt variant="small" c={pnl >= 0 ? color.up : color.down}>{signed(e.return_pct)}%</Txt> : null}
        </View>) : null}
    </Pressable>
  );
}

function EntryForm({ entry, onClose }: { entry: JournalEntry | null; onClose: () => void }) {
  const insets = useSafeAreaInsets();
  const save = useJournalSave();
  const del = useJournalDelete();
  const readOnly = !!entry && !entry.editable;
  const [form, setForm] = useState<JournalForm>(() => (entry ? fromEntry(entry) : blankForm(today())));
  const [more, setMore] = useState(!!entry);
  const [err, setErr] = useState<string | null>(null);
  const full = useMemo(() => entry, [entry]);
  const set = (k: keyof JournalForm) => (v: string) => setForm((f) => ({ ...f, [k]: v }));
  const fail = (e: unknown) => setErr(e instanceof ApiError ? e.message : "Something went wrong. Try again.");
  const submit = () => { setErr(null); save.mutate({ id: entry ? entry.id : null, body: toBody(form, !!entry) }, { onSuccess: onClose, onError: fail }); };
  const remove = () => { if (entry) del.mutate(entry.id, { onSuccess: onClose, onError: fail }); };
  const pickShot = () => {
    if (Platform.OS !== "web" || typeof document === "undefined") return;
    const input = document.createElement("input");
    input.type = "file"; input.accept = "image/png,image/jpeg,image/webp";
    input.onchange = () => { const f = input.files?.[0]; if (!f) return; const r = new FileReader(); r.onload = () => setForm((x) => ({ ...x, screenshot: String(r.result) })); r.readAsDataURL(f); };
    input.click();
  };
  return (
    <Modal visible animationType="slide" transparent={false} onRequestClose={onClose}>
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={{ flex: 1, backgroundColor: color.bg }}>
        <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: space.lg, paddingTop: Math.max(insets.top, space.lg), paddingBottom: space.sm }}>
          <Txt variant="title" style={{ fontSize: 24 }} testID="entry-title">{entry ? (readOnly ? "Imported trade" : "Edit entry") : "New entry"}</Txt>
          <IconButton name="close" size={26} label="Close" onPress={onClose} testID="entry-close" />
        </View>
        <ScrollView contentContainerStyle={{ padding: space.lg, gap: space.lg, paddingBottom: insets.bottom + space.xxl }} keyboardShouldPersistTaps="handled">
          {readOnly && <Txt variant="small">This trade came from an import or from paper trading, so it can't be edited here. Open the ATLAS terminal's detailed journal to add notes to it.</Txt>}
          <Field label="Symbol" value={form.symbol} onChange={(v) => set("symbol")(v.toUpperCase())} placeholder="BTC, AAPL…" testID="f-symbol" autoCapitalize="characters" disabled={readOnly} />
          <View style={{ flexDirection: "row", gap: space.sm }}>
            {(["long", "short"] as const).map((d) => <Chip key={d} label={d === "long" ? "Long" : "Short"} active={form.direction === d} onPress={() => !readOnly && set("direction")(d)} testID={`f-${d}`} />)}
          </View>
          <View style={{ flexDirection: "row", gap: space.md }}>
            <View style={{ flex: 1 }}><Field label="Size" value={form.size} onChange={set("size")} placeholder="optional" keyboard="decimal-pad" testID="f-size" disabled={readOnly} /></View>
            <View style={{ flex: 1 }}><Field label="Entry price" value={form.entry_price} onChange={set("entry_price")} placeholder="optional" keyboard="decimal-pad" testID="f-entry" disabled={readOnly} /></View>
            <View style={{ flex: 1 }}><Field label="Exit price" value={form.exit_price} onChange={set("exit_price")} placeholder="optional" keyboard="decimal-pad" testID="f-exit" disabled={readOnly} /></View>
          </View>
          <Field label="Date" value={form.entry_at} onChange={set("entry_at")} placeholder="YYYY-MM-DD" testID="f-date" disabled={readOnly} />
          <Field label="Note" value={form.note} onChange={set("note")} placeholder="Why you took it, what you saw…" multiline testID="f-note" disabled={readOnly} />
          {!readOnly && <TextButton label={more ? "Fewer details" : "More details"} onPress={() => setMore(!more)} testID="f-more" />}
          {(more || readOnly) && (
            <View style={{ gap: space.lg }}>
              <View style={{ flexDirection: "row", gap: space.md }}>
                <View style={{ flex: 1 }}><Field label="Exit date" value={form.exit_at} onChange={set("exit_at")} placeholder="YYYY-MM-DD" testID="f-exit-date" disabled={readOnly} /></View>
                <View style={{ flex: 1 }}><Field label="Fees" value={form.fees} onChange={set("fees")} placeholder="0" keyboard="decimal-pad" testID="f-fees" disabled={readOnly} /></View>
                <View style={{ flex: 1 }}><Field label="Planned stop" value={form.planned_stop} onChange={set("planned_stop")} placeholder="optional" keyboard="decimal-pad" testID="f-stop" disabled={readOnly} /></View>
              </View>
              <Field label="Thesis" value={form.thesis} onChange={set("thesis")} placeholder="The idea in a sentence or two" multiline testID="f-thesis" disabled={readOnly} />
              <Field label="Risk plan" value={form.risk_plan} onChange={set("risk_plan")} placeholder="Where you are wrong, how much you risk" multiline testID="f-risk" disabled={readOnly} />
              <Field label="Outcome" value={form.outcome} onChange={set("outcome")} placeholder="What happened, what you learned" multiline testID="f-outcome" disabled={readOnly} />
              {Platform.OS === "web" && !readOnly && <TextButton label={form.screenshot ? "Replace screenshot" : "Attach a screenshot"} onPress={pickShot} testID="f-shot" />}
              {form.screenshot ? <View><View style={{ marginBottom: 6 }}>{/* eslint-disable-next-line */}{React.createElement("img" as never, { src: form.screenshot, style: { maxWidth: "100%", maxHeight: 240, borderRadius: 12 }, alt: "Attached screenshot" })}</View>{!readOnly && <TextButton label="Remove screenshot" tint={color.down} onPress={() => setForm({ ...form, screenshot: null })} />}</View> : null}
            </View>)}
          {full && !readOnly && full.status === "closed" && <Txt variant="small">Realised P&L {signed(full.net_pnl_num)}{full.return_pct !== null ? ` (${signed(full.return_pct)}%)` : ""}. Calculated from the size, prices and fees above.</Txt>}
          {err ? <Txt variant="small" c={color.down} testID="entry-error">{err}</Txt> : null}
          {!readOnly && <PrimaryButton label={entry ? "Save changes" : "Add entry"} onPress={submit} busy={save.isPending} disabled={!form.symbol.trim()} testID="entry-save" />}
          {entry && !readOnly && <TextButton label="Delete this entry" tint={color.down} onPress={remove} disabled={del.isPending} testID="entry-delete" />}
        </ScrollView>
      </KeyboardAvoidingView>
    </Modal>
  );
}

function Field({ label, value, onChange, placeholder, multiline, keyboard, testID, disabled, autoCapitalize }: { label: string; value: string; onChange: (v: string) => void; placeholder?: string; multiline?: boolean; keyboard?: "decimal-pad"; testID?: string; disabled?: boolean; autoCapitalize?: "characters" | "none" }) {
  return (
    <View>
      <Txt variant="label" style={{ marginBottom: 6 }}>{label}</Txt>
      <TextInput value={value} onChangeText={onChange} placeholder={placeholder} placeholderTextColor={color.faint} multiline={multiline} keyboardType={keyboard} editable={!disabled} autoCapitalize={autoCapitalize ?? "none"} autoCorrect={false}
        style={[s.field, multiline && { minHeight: 72, textAlignVertical: "top" }, disabled && { opacity: 0.6 }, noOutline]} testID={testID} accessibilityLabel={label} />
    </View>
  );
}

const s = StyleSheet.create({
  row: { flexDirection: "row", alignItems: "center", gap: space.md, paddingHorizontal: space.lg, paddingVertical: 14 },
  search: { flexDirection: "row", alignItems: "center", gap: space.sm, paddingHorizontal: space.md, backgroundColor: color.surface, borderRadius: 16 },
  input: { flex: 1, color: color.text, fontSize: font.md, paddingVertical: 11 },
  field: { backgroundColor: color.surface, borderRadius: 14, color: color.text, paddingHorizontal: space.md, paddingVertical: 12, fontSize: font.md },
});
