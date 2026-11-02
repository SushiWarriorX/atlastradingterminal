import { router } from "expo-router";
import React, { useMemo, useState } from "react";
import { FlatList, RefreshControl, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { ScreenHeader } from "../../components/ScreenHeader";
import { WatchRowItem } from "../../components/WatchRowItem";
import { Banner, Divider, EmptyState, ErrorState, PrimaryButton, Skeleton, TextButton, Txt } from "../../components/ui";
import { localClock, relativeTime } from "../../lib/format";
import { describeFreshness, summarizeTones } from "../../lib/freshness";
import { idsOf, moveId, settledRows } from "../../lib/watchlist";
import { useMeta, useNow, useRemoveFromWatchlist, useReorderWatchlist, useWatchlist } from "../../state/queries";
import { color, space } from "../../theme";

export default function WatchlistScreen() {
  const insets = useSafeAreaInsets();
  const now = useNow(15_000);
  const meta = useMeta();
  const wl = useWatchlist();
  const remove = useRemoveFromWatchlist();
  const reorder = useReorderWatchlist();
  const [editing, setEditing] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const items = wl.data?.items ?? [];
  const ids = useMemo(() => idsOf(wl.data), [wl.data]);
  const tones = useMemo(() => settledRows(items).map((r) => describeFreshness(r.quote?.prov, now).tone), [items, now]);
  const problems = summarizeTones(tones);
  const offline = !!wl.data && wl.isError;                // only after a request has actually failed: a saved copy shown while the first request is in flight is not an outage
  const demo = !!(wl.data?.demo || meta.data?.demo);
  const failMsg = (e: unknown) => setNotice(`That change was not saved: ${e instanceof Error ? e.message : "unknown error"}`);
  const updated = wl.updatedAt ?? wl.cachedAt;

  const header = (
    <View style={{ gap: space.sm, paddingHorizontal: space.lg, paddingBottom: space.sm }}>
      {demo && <Banner tone="demo" title="Demo data" testID="demo-banner">Prices and research here are synthetic, for trying the app. They are not real market data.</Banner>}
      {offline && <Banner tone="warn" title="Can't reach the server" testID="offline-banner" action={<TextButton label="Retry" onPress={() => { void wl.refetch(); }} testID="offline-retry" />}>Showing your last list{updated ? ` from ${relativeTime(new Date(updated).toISOString(), now)}` : ""}. Prices may be out of date.</Banner>}
      {!offline && problems ? <Banner tone="warn" title={problems} testID="stale-banner">Some prices are not current. Check the dot next to each price.</Banner> : null}
      {notice && <Banner tone="warn" title="Couldn't save" testID="notice-banner" action={<TextButton label="Dismiss" onPress={() => setNotice(null)} />}>{notice}</Banner>}
    </View>
  );

  let body: React.ReactNode;
  if (!wl.cacheLoaded || (wl.isLoading && !wl.data)) {
    body = <View style={{ paddingHorizontal: space.lg, gap: space.lg, paddingTop: space.md }} testID="watchlist-loading">{[0, 1, 2, 3, 4].map((i) => <View key={i} style={{ flexDirection: "row", gap: space.md, alignItems: "center" }}><Skeleton w={44} h={44} r={22} /><View style={{ flex: 1, gap: 8 }}><Skeleton w="55%" h={15} /><Skeleton w="35%" h={11} /></View><Skeleton w={70} h={28} /></View>)}</View>;
  } else if (wl.isError && !wl.data) {
    body = <ErrorState testID="watchlist-error" title="Can't reach your Signal server" body={wl.error instanceof Error ? wl.error.message : "Something went wrong."} onRetry={() => wl.refetch()} extra={<TextButton label="Check connection settings" onPress={() => router.push("/settings")} />} />;
  } else if (items.length === 0) {
    body = <EmptyState testID="watchlist-empty" icon="star-outline" title="Your watchlist is empty" body="Search for Bitcoin, other crypto, US stocks or ETFs and tap + to save them here." action={<PrimaryButton label="Search assets" onPress={() => router.navigate("/search")} testID="empty-search" />} />;
  }

  return (
    <View style={{ flex: 1, backgroundColor: color.bg, paddingTop: insets.top }}>
      <ScreenHeader title="Watchlist" subtitle={updated ? `${items.length} asset${items.length === 1 ? "" : "s"} · updated ${localClock(new Date(updated).toISOString())}` : undefined}
        right={items.length > 0 ? <TextButton label={editing ? "Done" : "Edit"} onPress={() => setEditing((e) => !e)} testID="edit-toggle" /> : undefined} />
      <FlatList
        data={body ? [] : items}
        keyExtractor={(r) => r.asset.id}
        ListHeaderComponent={header}
        ListEmptyComponent={body ? (body as React.ReactElement) : undefined}
        ItemSeparatorComponent={Divider}
        refreshControl={<RefreshControl refreshing={wl.isRefetching && !wl.isLoading} onRefresh={() => { void wl.refetch(); }} tintColor={color.accent} />}
        contentContainerStyle={{ paddingBottom: space.xxl }}
        renderItem={({ item, index }) => (
          <WatchRowItem row={item} now={now} editing={editing} canUp={index > 0} canDown={index < items.length - 1}
            onOpen={() => router.push({ pathname: "/asset/[id]", params: { id: item.asset.id } })}
            onRemove={() => remove.mutate(item.asset.id, { onError: failMsg })}
            onMove={(dir) => reorder.mutate(moveId(ids, item.asset.id, dir), { onError: failMsg })} />
        )}
        testID="watchlist"
      />
      {items.length > 0 && !editing && <Txt variant="tiny" style={{ textAlign: "center", paddingBottom: space.sm }}>Research only · not financial advice</Txt>}
    </View>
  );
}
