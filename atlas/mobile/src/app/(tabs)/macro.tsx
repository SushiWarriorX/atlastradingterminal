import React from "react";
import { View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { MacroView } from "../../components/MacroView";
import { color } from "../../theme";

export default function MacroScreen() {
  const insets = useSafeAreaInsets();
  return <View style={{ flex: 1, backgroundColor: color.bg, paddingTop: insets.top }}><MacroView /></View>;
}
