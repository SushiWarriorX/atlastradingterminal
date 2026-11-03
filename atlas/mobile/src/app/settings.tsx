import { router } from "expo-router";
import React from "react";
import { SettingsView } from "../components/SettingsView";

export default function SettingsScreen() {
  return <SettingsView onClose={() => (router.canGoBack() ? router.back() : router.replace("/"))} />;
}
