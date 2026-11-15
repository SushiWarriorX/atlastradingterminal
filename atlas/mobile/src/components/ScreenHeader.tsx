import { router } from "expo-router";
import React from "react";
import { View } from "react-native";
import { useIsWide } from "../state/layout";
import { font, space } from "../theme";
import { RoundButton, Txt } from "./ui";

/** TradingView's phone header: a round button on each side and a centred title. On the left a back button, or on a tab screen the round profile button that opens Settings (Settings is the only thing behind it); on the right whatever the screen needs. */
export function ScreenHeader({ title, subtitle, right, back }: { title: string; subtitle?: string; right?: React.ReactNode; back?: boolean }) {
  const wide = useIsWide();
  return (
    <View style={{ flexDirection: "row", alignItems: "center", paddingHorizontal: space.lg, paddingTop: wide ? 0 : space.sm, paddingBottom: space.sm, gap: space.sm }}>
      <View style={{ width: 88, flexDirection: "row", alignItems: "center" }}>
        {back ? <RoundButton name="chevron-back" label="Back" onPress={() => (router.canGoBack() ? router.back() : router.replace("/"))} testID="search-back" />
          : wide ? null : <RoundButton name="person" label="Settings" onPress={() => router.push("/settings")} testID="profile-button" />}
      </View>
      <View style={{ flex: 1, alignItems: "center" }}>
        <Txt variant="h2" style={{ fontSize: font.lg, fontWeight: "700" }} numberOfLines={1} testID="screen-title">{title}</Txt>
        {subtitle ? <Txt variant="tiny" numberOfLines={1} testID="screen-subtitle">{subtitle}</Txt> : null}
      </View>
      <View style={{ width: 88, flexDirection: "row", alignItems: "center", justifyContent: "flex-end", gap: space.sm }}>{right}</View>
    </View>
  );
}
