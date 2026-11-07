import React from "react";
import { View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { DiscoverView } from "../../components/DiscoverView";
import { color } from "../../theme";

export default function DiscoverScreen() {
  const insets = useSafeAreaInsets();
  return <View style={{ flex: 1, backgroundColor: color.bg, paddingTop: insets.top }}><DiscoverView /></View>;
}
