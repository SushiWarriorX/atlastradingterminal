import Constants from "expo-constants";
import React, { useState } from "react";
import { ScrollView, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { ConnectForm } from "./ConnectForm";
import { Card, IconButton, PrimaryButton, TextButton, Txt } from "./ui";
import { storage } from "../state/storage";
import { useConnection } from "../state/connection";
import { useMeta } from "../state/queries";
import { color, space } from "../theme";

export function SettingsView({ onClose }: { onClose: () => void }) {
  const insets = useSafeAreaInsets();
  const { baseUrl, authRequired, logout } = useConnection();
  const meta = useMeta();
  const [cleared, setCleared] = useState(false);
  const m = meta.data;
  return (
    <View style={{ flex: 1, backgroundColor: color.bg, paddingTop: Math.max(insets.top, space.lg) }}>
      <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: space.lg, paddingBottom: space.sm }}>
        <Txt variant="title" testID="settings-title">Settings</Txt>
        <IconButton name="close" size={26} label="Close settings" onPress={onClose} testID="settings-close" />
      </View>
      <ScrollView contentContainerStyle={{ padding: space.lg, gap: space.lg, paddingBottom: insets.bottom + space.xxl }}>
        <Card>
          <Txt variant="label">Connection</Txt>
          <Txt variant="body" style={{ marginTop: space.sm }} testID="settings-server">{baseUrl ?? "Not connected"}</Txt>
          <Txt variant="small">{m ? "Connected" : meta.isError ? "Can't reach the server right now" : "Checking…"}{authRequired ? " · password protected" : ""}</Txt>
          <View style={{ marginTop: space.lg }}><ConnectForm submitLabel="Save and reconnect" /></View>
          {authRequired && <View style={{ marginTop: space.lg }}><TextButton label="Log out" tint={color.down} onPress={() => logout()} testID="logout" /></View>}
        </Card>

        <Card>
          <Txt variant="label">About the data</Txt>
          {m ? (
            <View style={{ gap: space.sm, marginTop: space.sm }}>
              <Txt variant="body" c={m.demo ? color.demo : color.text}>{m.demo ? "Demo mode: all prices and research are synthetic." : "Live mode: data comes from the providers named next to each figure."}</Txt>
              <Txt variant="small">Crypto: {m.coverage.crypto}</Txt>
              <Txt variant="small">Stocks and ETFs: {m.coverage.stocks_etfs}</Txt>
              {m.directory.error ? <Txt variant="small" c={color.warn}>{m.directory.error}. Search is limited to the built-in list until it loads.</Txt> : null}
              <Txt variant="small">Written explanations: {m.ai.enabled ? `on (${m.ai.model}). ${m.ai.note}` : "off. Summaries are rule-based."}</Txt>
            </View>
          ) : <Txt variant="small" style={{ marginTop: space.sm }}>{meta.isError ? "Connect to a server to see its data coverage." : "Loading…"}</Txt>}
        </Card>

        <Card>
          <Txt variant="label">On this device</Txt>
          <Txt variant="small" style={{ marginTop: space.sm, marginBottom: space.md }}>Your watchlist lives on your server. This device keeps a copy to show when you are offline, plus your recent searches.</Txt>
          <PrimaryButton label={cleared ? "Cleared" : "Clear saved copy and recent searches"} onPress={async () => { await storage.clearWatchlistCache(); await storage.setRecents([], baseUrl); setCleared(true); }} testID="clear-local" />
        </Card>

        <Card>
          <Txt variant="label">About Signal</Txt>
          <Txt variant="small" style={{ marginTop: space.sm }}>Signal Mobile {Constants.expoConfig?.version ?? ""}. Research only: it cannot place trades, connect to a brokerage, or hold your money. Nothing in the app is financial advice.</Txt>
          {m?.notes.map((n, i) => <Txt key={i} variant="tiny" style={{ marginTop: 4 }}>{n}</Txt>)}
        </Card>
      </ScrollView>
    </View>
  );
}
