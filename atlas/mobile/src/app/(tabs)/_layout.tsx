import { Ionicons } from "@expo/vector-icons";
import { Tabs } from "expo-router";
import React from "react";
import { Platform } from "react-native";
import { color } from "../../theme";

/** Exactly two tabs. Settings is behind the profile icon; there is no tab or screen per agent. */
export default function TabsLayout() {
  return (
    <Tabs screenOptions={{ headerShown: false, tabBarActiveTintColor: color.text, tabBarInactiveTintColor: color.faint, tabBarStyle: { backgroundColor: color.bg, borderTopWidth: 0, ...Platform.select({ web: { height: 78, paddingBottom: 12, paddingTop: 6 }, default: {} }) }, tabBarLabelStyle: { fontSize: 11, lineHeight: 15, fontWeight: "600" }, tabBarItemStyle: { paddingTop: 2 }, sceneStyle: { backgroundColor: color.bg } }}>
      <Tabs.Screen name="index" options={{ title: "Watchlist", tabBarButtonTestID: "tab-watchlist", tabBarIcon: ({ color: c, focused }) => <Ionicons name={focused ? "star" : "star-outline"} size={22} color={c as string} /> }} />
      <Tabs.Screen name="search" options={{ title: "Search", tabBarButtonTestID: "tab-search", tabBarIcon: ({ color: c, focused }) => <Ionicons name={focused ? "search" : "search-outline"} size={22} color={c as string} /> }} />
    </Tabs>
  );
}
