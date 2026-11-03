import { router } from "expo-router";
import React from "react";
import { View } from "react-native";
import { useIsWide } from "../state/layout";
import { color, space } from "../theme";
import { IconButton, Txt } from "./ui";

/** Large title with the small profile icon that opens Settings. Settings is the only thing behind it: there are exactly two tabs. */
export function ScreenHeader({ title, subtitle, right }: { title: string; subtitle?: string; right?: React.ReactNode }) {
  const wide = useIsWide();
  return (
    <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: space.lg, paddingTop: wide ? 0 : space.md, paddingBottom: space.sm }}>
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
