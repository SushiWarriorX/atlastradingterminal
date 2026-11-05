import { router } from "expo-router";
import React from "react";
import { View } from "react-native";
import { useIsWide } from "../state/layout";
import { color, space } from "../theme";
import { IconButton, Txt } from "./ui";

/** Large title with the small profile icon that opens Settings. Settings is the only thing behind it: there are five tabs: BTC, Stocks, Macro, Discover, Journal. */
export function ScreenHeader({ title, subtitle, right, back }: { title: string; subtitle?: string; right?: React.ReactNode; back?: boolean }) {
  const wide = useIsWide();
  return (
    <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: space.lg, paddingTop: wide ? 0 : space.md, paddingBottom: space.sm }}>
      {back ? <IconButton name="chevron-back" size={26} label="Back" onPress={() => (router.canGoBack() ? router.back() : router.replace("/"))} testID="search-back" /> : null}
      <View style={{ flex: 1 }}>
        <Txt variant="title" testID="screen-title">{title}</Txt>
        {subtitle ? <Txt variant="small" testID="screen-subtitle">{subtitle}</Txt> : null}
      </View>
      <View style={{ flexDirection: "row", alignItems: "center", gap: space.md }}>
        {right}
        {wide ? null : <IconButton name="person-circle" size={36} tint={color.faint} label="Settings" onPress={() => router.push("/settings")} testID="profile-button" />}
      </View>
    </View>
  );
}
