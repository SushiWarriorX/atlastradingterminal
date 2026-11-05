import { Ionicons } from "@expo/vector-icons";
import React, { useEffect, useState } from "react";
import { Pressable, View } from "react-native";
import SearchScreen from "../app/search";
import WatchlistScreen from "../app/(tabs)/index";
import { useWatchlist } from "../state/queries";
import { BTC_ID, DESTS, useSelection } from "../state/selection";
import { color, radius, space } from "../theme";
import { MacroView } from "./MacroView";
import { JournalView } from "./JournalView";
import { AssetView } from "./AssetView";
import { NewsPanel } from "./NewsPanel";
import { SettingsView } from "./SettingsView";
import { Ticker } from "./Ticker";
import { IconButton, Txt } from "./ui";

function Panel({ children, width, style }: { children: React.ReactNode; width?: number; style?: object }) {
  return <View style={[{ backgroundColor: "#090909", borderWidth: 1, borderColor: color.border, borderRadius: radius.md, overflow: "hidden", ...(width ? { width } : { flex: 1, minWidth: 0 }) }, style]}>{children}</View>;
}

/** Wide screens: watchlist/search on the left, the research for the selected asset in the middle, its news on the right, a ticker across the top. Five destinations along the top; still no trading. */
export function DesktopShell() {
  const { selectedId, select, pane, setPane, dest, setDest } = useSelection();
  const wl = useWatchlist();
  const [settings, setSettings] = useState(false);
  const first = wl.data?.items[0]?.asset.id ?? null;
  useEffect(() => { if (!selectedId && first) select(first); }, [selectedId, first, select]);
  
  return (
    <View style={{ flex: 1, backgroundColor: color.bg }}>
      <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: space.lg, paddingVertical: 10 }}>
        <Txt variant="h2" style={{ fontSize: 20, fontWeight: "800" }}>Signal</Txt>
        <View style={{ flexDirection: "row", gap: 4 }}>
          {DESTS.map((d) => (
            <Pressable key={d.key} onPress={() => setDest(d.key)} accessibilityRole="button" accessibilityState={{ selected: dest === d.key }} testID={`nav-${d.key}`} style={{ paddingHorizontal: 16, paddingVertical: 8, borderRadius: radius.pill, backgroundColor: dest === d.key ? color.surface2 : "transparent" }}>
              <Txt variant="small" c={dest === d.key ? color.text : color.dim} style={{ fontWeight: "700" }}>{d.label}</Txt>
            </Pressable>
          ))}
        </View>
        <IconButton name="person-circle" size={32} tint={color.faint} label="Settings" onPress={() => setSettings(true)} testID="profile-button" />
      </View>
      <Ticker />
      <View style={{ flex: 1, flexDirection: "row", gap: 8, padding: 8 }}>
        {dest === "stocks" ? <>
        <Panel width={390}>
          <View style={{ flexDirection: "row", gap: 6, padding: space.md }}>
            {(["watchlist", "search"] as const).map((p) => (
              <Pressable key={p} onPress={() => setPane(p)} accessibilityRole="button" accessibilityState={{ selected: pane === p }} testID={`pane-${p}`} style={{ paddingHorizontal: 14, paddingVertical: 7, borderRadius: radius.pill, backgroundColor: pane === p ? color.surface2 : "transparent" }}>
                <Txt variant="small" c={pane === p ? color.text : color.dim} style={{ fontWeight: "600" }}>{p === "watchlist" ? "Watchlist" : "Search"}</Txt>
              </Pressable>
            ))}
          </View>
          {pane === "watchlist" ? <WatchlistScreen /> : <SearchScreen />}
        </Panel>
        <Panel>
          {selectedId ? <AssetView key={selectedId} id={selectedId} embedded /> : (
            <View style={{ flex: 1, alignItems: "center", justifyContent: "center", gap: space.sm }}>
              <Ionicons name="star-outline" size={28} color={color.faint} />
              <Txt variant="small">Save an asset from Search, then pick it here to read it.</Txt>
            </View>
          )}
        </Panel>
        <Panel width={360}><NewsPanel id={selectedId} /></Panel>
        </> : dest === "btc" ? <>
          <Panel><AssetView key={BTC_ID} id={BTC_ID} embedded /></Panel>
          <Panel width={360}><NewsPanel id={BTC_ID} /></Panel>
        </> : dest === "journal" ? (
          <Panel><JournalView /></Panel>
        ) : dest === "macro" ? (
          <Panel><MacroView /></Panel>
        ) : (
          <Panel><View style={{ flex: 1, alignItems: "center", justifyContent: "center", gap: space.sm, padding: space.xl }} testID={`${dest}-soon`}>
            <Ionicons name="compass-outline" size={28} color={color.faint} />
            <Txt variant="h2">Discover is not built yet</Txt>
            <Txt variant="small" style={{ textAlign: "center", maxWidth: 420 }}>A daily shortlist of US stocks worth researching, with reasons, evidence and risks, will appear here.</Txt>
          </View></Panel>
        )}
      </View>
      {settings && (
        <View style={{ position: "absolute", top: 0, right: 0, bottom: 0, width: 440, backgroundColor: color.bg, borderLeftWidth: 1, borderLeftColor: color.border }} testID="settings-drawer">
          <SettingsView onClose={() => setSettings(false)} />
        </View>
      )}
    </View>
  );
}
