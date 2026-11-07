import React from "react";
import { View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { JournalView } from "../../components/JournalView";
import { color } from "../../theme";

export default function JournalScreen() {
  const insets = useSafeAreaInsets();
  return <View style={{ flex: 1, backgroundColor: color.bg, paddingTop: insets.top }}><JournalView /></View>;
}
