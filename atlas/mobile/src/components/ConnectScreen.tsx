import React from "react";
import { ScrollView, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { color, space } from "../theme";
import { useConnection } from "../state/connection";
import { ConnectForm } from "./ConnectForm";
import { Txt } from "./ui";

/** First run, or the session ended: connect to your own ATLAS server. Nothing in the app works without it, and nothing is shown until it does. */
export function ConnectScreen() {
  const { status } = useConnection();
  const insets = useSafeAreaInsets();
  return (
    <ScrollView style={{ flex: 1, backgroundColor: color.bg }} contentContainerStyle={{ padding: space.xl, paddingTop: insets.top + space.xxl, maxWidth: 520, width: "100%", alignSelf: "center" }} keyboardShouldPersistTaps="handled">
      <Txt variant="title" testID="connect-title">Signal</Txt>
      <Txt variant="body" c={color.dim} style={{ marginTop: space.sm, marginBottom: space.xl }}>
        {status === "needs_login" ? "Your session ended. Log in again to continue." : "Research for Bitcoin, crypto, US stocks and ETFs. Connect to your own ATLAS server to begin."}
      </Txt>
      <ConnectForm submitLabel={status === "needs_login" ? "Log in" : "Connect"} />
      <View style={{ marginTop: space.xl }}>
        <Txt variant="tiny">Research only. Signal cannot place trades or connect to a brokerage account, and nothing in it is financial advice.</Txt>
      </View>
    </ScrollView>
  );
}
