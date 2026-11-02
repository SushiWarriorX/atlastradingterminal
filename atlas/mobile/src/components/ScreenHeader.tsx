import { router } from "expo-router";
import React from "react";
import { View } from "react-native";
import { space } from "../theme";
import { IconButton, Txt } from "./ui";

/** Large title with the small profile icon that opens Settings. Settings is the only thing behind it: there are exactly two tabs. */
export function ScreenHeader({ title, subtitle, right }: { title: string; subtitle?: string; right?: React.ReactNode }) {
  return (
    <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: space.lg, paddingTop: space.md, paddingBottom: space.sm }}>
      <View style={{ flex: 1 }}>
        <Txt variant="title" testID="screen-title">{title}</Txt>
        {subtitle ? <Txt variant="small" testID="screen-subtitle">{subtitle}</Txt> : null}
      </View>
      <View style={{ flexDirection: "row", alignItems: "center", gap: space.md }}>
        {right}
        <IconButton name="person-circle-outline" size={30} label="Settings" onPress={() => router.push("/settings")} testID="profile-button" />
      </View>
    </View>
  );
}
