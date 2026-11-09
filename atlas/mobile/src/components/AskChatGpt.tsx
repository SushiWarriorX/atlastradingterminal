import React, { useEffect, useRef, useState } from "react";
import { Linking, Platform, Pressable, Share, TextInput, View } from "react-native";
import { useQuery } from "@tanstack/react-query";
import { browserCopyEnv, CHATGPT_URL, COPIED, COPY_FAILED, downloadMarkdown, openChatGpt, POPUP_BLOCKED, startCopy } from "../lib/handoff";
import { useConnection } from "../state/connection";
import { color, radius, space } from "../theme";
import { Banner, GCard, TextButton, Txt } from "./ui";

type Status = { kind: "ok" | "warn" | "info"; text: string } | null;
const web = Platform.OS === "web";
const Check = ({ on, label, onToggle, testID }: { on: boolean; label: string; onToggle: () => void; testID: string }) => (
  <Pressable onPress={onToggle} accessibilityRole="checkbox" accessibilityState={{ checked: on }} testID={testID} style={{ flexDirection: "row", alignItems: "center", gap: space.sm, minHeight: 44 }}>
    <View style={{ width: 22, height: 22, borderRadius: 6, borderWidth: 1.5, borderColor: color.accent, alignItems: "center", justifyContent: "center", backgroundColor: on ? color.accent : "transparent" }}>{on ? <Txt variant="tiny" c={color.bg}>✓</Txt> : null}</View>
    <Txt variant="small" style={{ flex: 1 }}>{label}</Txt>
  </Pressable>);

/** "Ask ChatGPT": a manual research handoff. The brief is built on my server from research the app already holds (no AI call, no key); I copy it and paste it into ChatGPT myself. */
export function AskChatGpt({ symbol, where }: { symbol: string; where: "research" | "valuation" | "scenario" }) {
  const { api } = useConnection();
  const [open, setOpen] = useState(false);
  const [question, setQuestion] = useState("");
  const [debounced, setDebounced] = useState("");
  const [detail, setDetail] = useState<"concise" | "detailed">("concise");
  const [notes, setNotes] = useState(false);
  const [position, setPosition] = useState(false);
  const [shares, setShares] = useState("");
  const [buy, setBuy] = useState("");
  const [status, setStatus] = useState<Status>(null);
  const [blocked, setBlocked] = useState(false);
  const preview = useRef<unknown>(null);
  useEffect(() => { const t = setTimeout(() => setDebounced(question), 400); return () => clearTimeout(t); }, [question]);
  const body = { detail, question: debounced.trim() || undefined, include_notes: notes, include_position: position, shares: position && Number(shares) > 0 ? Number(shares) : undefined, buy_price: position && Number(buy) > 0 ? Number(buy) : undefined };
  const q = useQuery({ queryKey: ["brief", symbol, JSON.stringify(body)], queryFn: () => api!.researchBrief(symbol, body), enabled: open && !!api, retry: 0, staleTime: 0, gcTime: 60_000, placeholderData: (prev) => prev });
  const d = q.data;
  const updating = q.isFetching;
  const text = d?.markdown ?? "";
  const selectAll = () => { const el = preview.current as { focus?: () => void; select?: () => void } | null; el?.focus?.(); el?.select?.(); };
  const copyEnv = () => (web ? browserCopyEnv(preview.current as HTMLTextAreaElement | null) : { clipboardWrite: null, execCopy: null });
  const shareSheet = async (why: string) => { try { await Share.share({ message: text, title: d?.filename }); setStatus({ kind: "info", text: why }); } catch { setStatus({ kind: "warn", text: COPY_FAILED }); } };

  const copyOpen = async () => {
    if (!text) return;
    setBlocked(false);
    if (!web) {                                               // inside a native build there is no clipboard module here: the share sheet is the copy path, and nothing is claimed as copied
      Linking.openURL(CHATGPT_URL).catch(() => setBlocked(true));
      await shareSheet("The share sheet is open: choose Copy, then paste it into ChatGPT.");
      return;
    }
    const copying = startCopy(text, copyEnv());
    const opened = openChatGpt((u, t) => window.open(u, t));
    const copied = await copying;
    if (!opened) setBlocked(true);
    if (!copied) { selectAll(); setStatus({ kind: "warn", text: COPY_FAILED + (opened ? "" : " " + POPUP_BLOCKED) }); return; }
    setStatus(opened ? { kind: "ok", text: COPIED } : { kind: "warn", text: `${COPIED} ${POPUP_BLOCKED}` });
  };
  const copyOnly = async () => {
    if (!text) return;
    if (!web) { await shareSheet("The share sheet is open: choose Copy, then paste it into ChatGPT."); return; }
    const copied = await startCopy(text, copyEnv());
    if (!copied) { selectAll(); setStatus({ kind: "warn", text: COPY_FAILED }); return; }
    setStatus({ kind: "ok", text: COPIED });
  };
  const download = async () => {
    if (!d) return;
    if (web) { downloadMarkdown(d.filename, d.markdown); setStatus({ kind: "info", text: `Download started: ${d.filename}` }); } else await shareSheet(`Choose where to save ${d.filename}.`);
  };

  return (
    <View testID={`ask-${where}`}>
      <TextButton large label="Ask ChatGPT" onPress={() => setOpen(!open)} testID="ask-chatgpt-button" />
      {open ? (
        <GCard style={{ padding: space.md, gap: space.sm, marginTop: space.sm }} testID="ask-panel">
          <Txt variant="label">Ask ChatGPT about {symbol}</Txt>
          <Txt variant="tiny" testID="ask-explanation">{d?.explanation ?? "This handoff makes no AI API calls from this app. ChatGPT usage is subject to your own account's plan and limits."}</Txt>
          <Txt variant="small">What would you like to research? (optional)</Txt>
          <TextInput value={question} onChangeText={setQuestion} multiline maxLength={2000} placeholder="e.g. How durable is the recurring revenue? Leave empty for the default questions." placeholderTextColor={color.dim}
            accessibilityLabel="What would you like to research?" testID="ask-question" style={{ minHeight: 64, borderRadius: radius.md, padding: space.md, color: color.text, backgroundColor: "rgba(255,255,255,0.06)", borderWidth: 1, borderColor: "rgba(255,255,255,0.30)" }} />
          <View style={{ flexDirection: "row", gap: space.sm, flexWrap: "wrap" }}>
            <TextButton large solid={detail === "concise"} label="Concise brief" onPress={() => setDetail("concise")} testID="ask-concise" />
            <TextButton large solid={detail === "detailed"} label="Detailed brief" onPress={() => setDetail("detailed")} testID="ask-detailed" />
          </View>
          <Check on={notes} label="Include my private notes" onToggle={() => setNotes(!notes)} testID="ask-include-notes" />
          <Check on={position} label="Include my holdings (shares and buy price)" onToggle={() => setPosition(!position)} testID="ask-include-position" />
          <Txt variant="tiny">Both are left out unless you switch them on.</Txt>
          {position ? (
            <View style={{ flexDirection: "row", gap: space.sm }}>
              <TextInput value={shares} onChangeText={setShares} keyboardType="decimal-pad" placeholder="Shares" placeholderTextColor={color.dim} accessibilityLabel="Shares" testID="ask-shares" style={{ flex: 1, minHeight: 44, borderRadius: radius.md, padding: space.md, color: color.text, backgroundColor: "rgba(255,255,255,0.06)", borderWidth: 1, borderColor: "rgba(255,255,255,0.30)" }} />
              <TextInput value={buy} onChangeText={setBuy} keyboardType="decimal-pad" placeholder="Buy price $" placeholderTextColor={color.dim} accessibilityLabel="Buy price" testID="ask-buy" style={{ flex: 1, minHeight: 44, borderRadius: radius.md, padding: space.md, color: color.text, backgroundColor: "rgba(255,255,255,0.06)", borderWidth: 1, borderColor: "rgba(255,255,255,0.30)" }} />
            </View>) : null}
          {q.isLoading || updating ? <Txt variant="tiny" testID="ask-updating">{q.isLoading ? "Preparing the context…" : "Updating the preview…"}</Txt> : null}
          {q.isError ? <Banner tone="warn" title="Couldn't prepare the context" testID="ask-error">{q.error instanceof Error ? q.error.message : "Something went wrong."}</Banner> : null}
          {d ? (
            <View style={{ gap: 4 }}>
              <Txt variant="tiny" testID="ask-meta">Preview of the context that will be copied · {d.chars.toLocaleString()} characters · {d.detail} · private notes {d.included.notes ? "INCLUDED" : "not included"} · holdings {d.included.position ? "INCLUDED" : "not included"}{d.redactions ? ` · ${d.redactions} item(s) that looked like emails or keys were removed` : ""}</Txt>
              <TextInput ref={(el) => { preview.current = el; }} value={text} multiline editable={false} selectTextOnFocus accessibilityLabel="Context preview" testID="ask-preview"
                style={{ height: 220, borderRadius: radius.md, padding: space.md, color: color.text, backgroundColor: "rgba(255,255,255,0.06)", borderWidth: 1, borderColor: "rgba(255,255,255,0.30)", fontSize: 11 }} />
            </View>) : null}
          <TextButton large solid label="Copy context & open ChatGPT" onPress={copyOpen} disabled={!text || updating} testID="ask-copy-open" />
          <TextButton large label="Copy context only" onPress={copyOnly} disabled={!text || updating} testID="ask-copy" />
          <TextButton large label="Download context as Markdown" onPress={download} disabled={!d || updating} testID="ask-download" />
          <Pressable onPress={() => { if (web) window.open(CHATGPT_URL, "_blank"); else Linking.openURL(CHATGPT_URL).catch(() => undefined); }} accessibilityRole="link" testID="ask-open-link" style={{ minHeight: 44, justifyContent: "center" }}>
            <Txt variant="small" c={color.accent}>Open ChatGPT</Txt>
          </Pressable>
          {status ? <Txt variant="small" c={status.kind === "warn" ? color.warn : color.text} testID="ask-status" accessibilityRole="alert">{status.text}</Txt> : null}
          {blocked ? <Txt variant="small" c={color.warn} testID="ask-blocked">{POPUP_BLOCKED}</Txt> : null}
        </GCard>) : null}
    </View>);
}
