import { Ionicons } from "@expo/vector-icons";
import { Tabs } from "expo-router/js-tabs";
import React from "react";
import { PillTabBar } from "../../components/PillTabBar";
import { color } from "../../theme";

type IconName = React.ComponentProps<typeof Ionicons>["name"];
const icon = (on: IconName, off: IconName) => ({ color: c, focused }: { color: unknown; focused: boolean }) => <Ionicons name={focused ? on : off} size={22} color={c as string} />;

/** Six tabs: BTC, Journey (the paper-trading lab running the backtested strategies), Stocks, Macro, Discover, Journal. Search is a screen opened from Stocks; Settings is behind the profile button. The bar is TradingView's floating pill. */
export default function TabsLayout() {
  return (
    <Tabs tabBar={(p) => <PillTabBar {...p} />} screenOptions={{ headerShown: false, sceneStyle: { backgroundColor: color.bg } }}>
      <Tabs.Screen name="btc" options={{ title: "BTC", tabBarButtonTestID: "tab-btc", tabBarIcon: icon("logo-bitcoin", "logo-bitcoin") }} />
      <Tabs.Screen name="journey" options={{ title: "Journey", tabBarButtonTestID: "tab-journey", tabBarIcon: icon("trail-sign", "trail-sign-outline") }} />
      <Tabs.Screen name="index" options={{ title: "Stocks", tabBarButtonTestID: "tab-stocks", tabBarIcon: icon("stats-chart", "stats-chart-outline") }} />
      <Tabs.Screen name="macro" options={{ title: "Macro", tabBarButtonTestID: "tab-macro", tabBarIcon: icon("globe", "globe-outline") }} />
      <Tabs.Screen name="discover" options={{ title: "Discover", tabBarButtonTestID: "tab-discover", tabBarIcon: icon("compass", "compass-outline") }} />
      <Tabs.Screen name="journal" options={{ title: "Journal", tabBarButtonTestID: "tab-journal", tabBarIcon: icon("book", "book-outline") }} />
    </Tabs>
  );
}
