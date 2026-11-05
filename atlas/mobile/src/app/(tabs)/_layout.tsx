import { Ionicons } from "@expo/vector-icons";
import { Tabs } from "expo-router";
import React from "react";
import { Platform } from "react-native";
import { color } from "../../theme";

/** Five tabs: BTC, Stocks, Macro, Discover, Journal. Search is a screen opened from Stocks; Settings is behind the profile icon. */
export default function TabsLayout() {
  return (
    <Tabs screenOptions={{ headerShown: false, tabBarActiveTintColor: color.accent, tabBarInactiveTintColor: color.faint, tabBarStyle: { backgroundColor: "#0B0B18", borderTopWidth: 1, borderTopColor: color.border, ...Platform.select({ web: { height: 78, paddingBottom: 12, paddingTop: 6 }, default: {} }) }, tabBarLabelStyle: { fontSize: 11, lineHeight: 15, fontWeight: "600" }, tabBarItemStyle: { paddingTop: 2 }, sceneStyle: { backgroundColor: color.bg } }}>
      <Tabs.Screen name="btc" options={{ title: "BTC", tabBarButtonTestID: "tab-btc", tabBarIcon: ({ color: c, focused }) => <Ionicons name={focused ? "logo-bitcoin" : "logo-bitcoin"} size={22} color={c as string} /> }} />
      <Tabs.Screen name="index" options={{ title: "Stocks", tabBarButtonTestID: "tab-stocks", tabBarIcon: ({ color: c, focused }) => <Ionicons name={focused ? "stats-chart" : "stats-chart-outline"} size={22} color={c as string} /> }} />
      <Tabs.Screen name="macro" options={{ title: "Macro", tabBarButtonTestID: "tab-macro", tabBarIcon: ({ color: c, focused }) => <Ionicons name={focused ? "globe" : "globe-outline"} size={22} color={c as string} /> }} />
      <Tabs.Screen name="discover" options={{ title: "Discover", tabBarButtonTestID: "tab-discover", tabBarIcon: ({ color: c, focused }) => <Ionicons name={focused ? "compass" : "compass-outline"} size={22} color={c as string} /> }} />
      <Tabs.Screen name="journal" options={{ title: "Journal", tabBarButtonTestID: "tab-journal", tabBarIcon: ({ color: c, focused }) => <Ionicons name={focused ? "book" : "book-outline"} size={22} color={c as string} /> }} />
    </Tabs>
  );
}
