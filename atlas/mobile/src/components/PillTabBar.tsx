import type { BottomTabBarProps } from "expo-router/js-tabs";
import React from "react";
import { Pressable, Text, View } from "react-native";
import { color, famFor, font } from "../theme";
import { MiniQuoteBar } from "./MiniQuoteBar";

/** TradingView's bottom bar: a rounded white pill with a hairline border and a soft shadow, each tab an icon over its label, the current tab on a light-grey pill. Above it, on every tab but Bitcoin's own, the small Bitcoin quote. */
export function PillTabBar({ state, descriptors, emitter, navigateToTab, insets }: BottomTabBarProps) {
  const current = state.routes[state.index];
  const btc = state.routes.find((r) => r.name === "btc");
  return (
    <View style={{ backgroundColor: color.bg, paddingHorizontal: 12, paddingTop: 6, paddingBottom: Math.max(insets.bottom, 10), gap: 8 }}>
      {btc && current.name !== "btc" ? <MiniQuoteBar onOpen={() => navigateToTab(btc.key)} /> : null}
      <View style={{ flexDirection: "row", backgroundColor: color.bg, borderRadius: 32, borderWidth: 1, borderColor: color.border, padding: 4, boxShadow: "0 2px 14px rgba(16,24,40,0.10)" }}>
        {state.routes.map((route) => {
          const { options } = descriptors[route.key];
          const focused = current.key === route.key;
          const title = options.title ?? route.name;
          const tint = focused ? color.text : color.dim;
          const press = () => {
            const event = emitter.emit({ type: "tabPress", target: route.key, canPreventDefault: true });
            if (!focused && !event.defaultPrevented) navigateToTab(route.key);
          };
          return (
            <Pressable key={route.key} onPress={press} accessibilityRole="tab" accessibilityState={{ selected: focused }} accessibilityLabel={title} testID={options.tabBarButtonTestID}
              style={({ pressed }) => [{ flex: 1, alignItems: "center", paddingTop: 7, paddingBottom: 6, borderRadius: 26, backgroundColor: focused ? color.surface2 : "transparent" }, pressed && { opacity: 0.6 }]}>
              {options.tabBarIcon?.({ focused, color: tint, size: 22 })}
              <Text numberOfLines={1} style={{ fontSize: font.xs, lineHeight: 14, marginTop: 2, color: tint, fontFamily: famFor(focused ? 700 : 600) }}>{title}</Text>
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}
