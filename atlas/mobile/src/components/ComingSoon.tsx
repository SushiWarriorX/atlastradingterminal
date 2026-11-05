import React from "react";
import { View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { color } from "../theme";
import { ScreenHeader } from "./ScreenHeader";
import { EmptyState } from "./ui";

/** An honest placeholder for a destination whose data is not wired up yet. No sample figures are shown. */
export function ComingSoon({ title, icon, body, testID }: { title: string; icon: React.ComponentProps<typeof EmptyState>["icon"]; body: string; testID: string }) {
  const insets = useSafeAreaInsets();
  return (
    <View style={{ flex: 1, backgroundColor: color.bg, paddingTop: insets.top }}>
      <ScreenHeader title={title} />
      <EmptyState testID={testID} icon={icon} title="Not built yet" body={body} />
    </View>
  );
}
