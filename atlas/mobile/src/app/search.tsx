import { Ionicons } from "@expo/vector-icons";
import React, { useMemo, useState } from "react";
import { FlatList, Pressable, StyleSheet, TextInput, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import type { Asset } from "../api/types";
import { ScreenHeader } from "../components/ScreenHeader";
import { SearchRowItem } from "../components/SearchRowItem";
import { noOutline } from "../components/ConnectForm";
import { Banner, Divider, EmptyState, ErrorState, Skeleton, TextButton, Txt } from "../components/ui";
import { idsOf } from "../lib/watchlist";
import { useAddToWatchlist, useDebounced, useRecents, useRemoveFromWatchlist, useSearch, useWatchlist } from "../state/queries";
import { useIsWide } from "../state/layout";
import { useOpenAsset } from "../state/selection";
import { color, font, radius, space } from "../theme";

export default function SearchScreen() {
  const wide = useIsWide();
  const insets = useSafeAreaInsets();
  const [q, setQ] = useState("");
  const debounced = useDebounced(q, 300);
  const search = useSearch(debounced);
  const wl = useWatchlist();
  const add = useAddToWatchlist();
  const remove = useRemoveFromWatchlist();
  const recents = useRecents();
  const [notice, setNotice] = useState<string | null>(null);
  const saved = useMemo(() => new Set(idsOf(wl.data)), [wl.data]);
  const typing = q.trim().length > 0;
  const waiting = typing && (q.trim() !== debounced.trim() || search.isFetching);

  const openAsset = useOpenAsset();
  function open(a: Asset) {
    recents.add(a);
    openAsset(a.id);
  }
  function toggle(a: Asset) {
    setNotice(null);
    recents.add(a);
    const onError = (e: Error) => setNotice(e.message);
    if (saved.has(a.id)) remove.mutate(a.id, { onError }); else add.mutate(a, { onError });
  }
  const row = (a: Asset) => <SearchRowItem asset={a} saved={saved.has(a.id)} onOpen={() => open(a)} onToggle={() => toggle(a)} />;

  let content: React.ReactNode;
  if (!typing) {
    content = recents.list.length ? (
      <View>
        <View style={s.sectionHead}><Txt variant="label">Recent</Txt><TextButton label="Clear" onPress={recents.clear} testID="clear-recents" /></View>
        {recents.list.map((a, i) => <View key={a.id}>{i > 0 && <Divider />}{row(a)}</View>)}
      </View>
    ) : <EmptyState testID="search-hint" icon="search-outline" title="Find an asset" body="Search by name or ticker: Bitcoin, Ethereum, AAPL, SPY. Results show the type and venue so similar tickers are never confused." />;
  } else if (search.isError) {
    content = <ErrorState title="Search failed" body={search.error instanceof Error ? search.error.message : "Something went wrong."} onRetry={() => search.refetch()} testID="search-error" />;
  } else if (waiting && !search.data) {
    content = <View style={{ paddingHorizontal: space.lg, gap: space.lg, paddingTop: space.lg }} testID="search-loading">{[0, 1, 2].map((i) => <View key={i} style={{ flexDirection: "row", gap: space.md, alignItems: "center" }}><Skeleton w={44} h={44} r={22} /><View style={{ flex: 1, gap: 8 }}><Skeleton w="50%" h={15} /><Skeleton w="30%" h={11} /></View></View>)}</View>;
  } else if (search.data) {
    const d = search.data;
    content = (
      <View>
        {d.results.map((a, i) => <View key={a.id}>{i > 0 && <Divider />}{row(a)}</View>)}
        {d.unsupported && <EmptyState testID="search-unsupported" icon="help-circle-outline" title="Not supported" body={d.unsupported.message} />}
        {d.notes.map((n, i) => <Txt key={i} variant="tiny" style={{ paddingHorizontal: space.lg, paddingTop: space.md }} testID="search-note">{n}</Txt>)}
      </View>
    );
  }

  return (
    <View style={{ flex: 1, backgroundColor: color.bg, paddingTop: insets.top }}>
      <ScreenHeader title="Search" back={!wide} />
      <View style={s.inputWrap}>
        <Ionicons name="search" size={18} color={color.faint} />
        <TextInput value={q} onChangeText={setQ} placeholder="Bitcoin, AAPL, SPY…" placeholderTextColor={color.faint} autoCapitalize="none" autoCorrect={false} returnKeyType="search" style={[s.input, noOutline]} testID="search-input" accessibilityLabel="Search assets" />
        {typing && <Pressable onPress={() => setQ("")} accessibilityRole="button" accessibilityLabel="Clear search" hitSlop={10} testID="search-clear"><Ionicons name="close-circle" size={18} color={color.faint} /></Pressable>}
      </View>
      {notice && <View style={{ paddingHorizontal: space.lg, paddingBottom: space.sm }}><Banner tone="warn" title="Couldn't save" action={<TextButton label="Dismiss" onPress={() => setNotice(null)} />}>{notice}</Banner></View>}
      <FlatList data={[0]} keyExtractor={() => "c"} renderItem={() => <>{content}</>} keyboardShouldPersistTaps="handled" contentContainerStyle={{ paddingBottom: space.xxl }} />
    </View>
  );
}

const s = StyleSheet.create({
  inputWrap: { flexDirection: "row", alignItems: "center", gap: space.sm, marginHorizontal: space.lg, marginBottom: space.md, paddingHorizontal: space.md, backgroundColor: color.surface, borderRadius: 16 },
  input: { flex: 1, color: color.text, fontSize: font.md, paddingVertical: 12 },
  sectionHead: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", paddingHorizontal: space.lg, paddingVertical: space.sm },
});
