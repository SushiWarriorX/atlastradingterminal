import React, { useState } from "react";
import { Platform, StyleSheet, TextInput, View } from "react-native";
import { ApiError } from "../api/client";
import { color, font, radius, space, fonts } from "../theme";
import { useConnection } from "../state/connection";
import { PrimaryButton, Txt } from "./ui";

/** Server address + optional password. Used for first-run setup, for logging in again, and in Settings. */
export function ConnectForm({ initialUrl, submitLabel = "Connect", onDone }: { initialUrl?: string; submitLabel?: string; onDone?: () => void }) {
  const { connect, baseUrl, defaultUrl, authRequired } = useConnection();
  const [url, setUrl] = useState(initialUrl ?? baseUrl ?? defaultUrl ?? "");
  const [pw, setPw] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  async function submit() {
    setBusy(true); setErr(null);
    try { await connect(url, pw || undefined); setPw(""); onDone?.(); }
    catch (e) { setErr(e instanceof ApiError ? e.message : "Something went wrong. Check the address and try again."); }
    finally { setBusy(false); }
  }
  return (
    <View style={{ gap: space.md }}>
      <View>
        <Txt variant="label" style={{ marginBottom: 6 }}>Server address</Txt>
        <TextInput value={url} onChangeText={setUrl} placeholder="https://signal.example.com" placeholderTextColor={color.faint} autoCapitalize="none" autoCorrect={false} keyboardType="url" style={[s.input, noOutline]} testID="server-url" accessibilityLabel="Server address" />
        <Txt variant="tiny" style={{ marginTop: 4 }}>Your own ATLAS server. On the same Wi-Fi this looks like http://192.168.1.20:8000.</Txt>
      </View>
      <View>
        <Txt variant="label" style={{ marginBottom: 6 }}>Password{authRequired ? "" : " (only if your server has one)"}</Txt>
        <TextInput value={pw} onChangeText={setPw} placeholder="Leave blank if there is no login" placeholderTextColor={color.faint} secureTextEntry autoCapitalize="none" autoCorrect={false} style={[s.input, noOutline]} testID="server-password" accessibilityLabel="Password" onSubmitEditing={submit} />
      </View>
      {err ? <Txt variant="small" c={color.down} testID="connect-error">{err}</Txt> : null}
      <PrimaryButton label={submitLabel} onPress={submit} busy={busy} testID="connect-submit" />
    </View>
  );
}

export const noOutline = Platform.OS === "web" ? ({ outlineStyle: "none" } as object) : {};

const s = StyleSheet.create({
  input: { backgroundColor: color.surface, borderRadius: 16, color: color.text, fontFamily: fonts.regular, paddingHorizontal: space.md, paddingVertical: 14, fontSize: font.md },
});
