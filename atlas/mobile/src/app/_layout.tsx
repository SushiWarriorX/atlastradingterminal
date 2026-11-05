import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Figtree_400Regular, Figtree_500Medium, Figtree_600SemiBold, Figtree_700Bold, useFonts } from "@expo-google-fonts/figtree";
import { Stack } from "expo-router";
import { StatusBar } from "expo-status-bar";
import React from "react";
import { Platform, View } from "react-native";
import { SafeAreaProvider } from "react-native-safe-area-context";
import { ConnectScreen } from "../components/ConnectScreen";
import { Spinner } from "../components/ui";
import { DesktopShell } from "../components/DesktopShell";
import { ConnectionProvider, useConnection } from "../state/connection";
import { useIsWide } from "../state/layout";
import { SelectionProvider } from "../state/selection";
import { color } from "../theme";

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: 1, staleTime: 5_000, refetchOnReconnect: true } } });

if (Platform.OS === "web" && typeof document !== "undefined") {
  document.body.style.backgroundColor = color.bg;               // no white flash while the app loads
  document.documentElement.style.colorScheme = "dark";
}

function Gate() {
  const { status } = useConnection();
  const wide = useIsWide();
  if (status === "loading") return <Spinner label="Starting…" />;
  if (status === "needs_server" || status === "needs_login") return <ConnectScreen />;
  if (wide) return <DesktopShell />;
  return (
    <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: color.bg } }}>
      <Stack.Screen name="(tabs)" />
      <Stack.Screen name="asset/[id]" />
      <Stack.Screen name="search" />
      <Stack.Screen name="settings" options={{ presentation: "modal" }} />
    </Stack>
  );
}

export default function RootLayout() {
  const [loaded, fontError] = useFonts({ Figtree_400Regular, Figtree_500Medium, Figtree_600SemiBold, Figtree_700Bold });
  if (!loaded && !fontError) return <View style={{ flex: 1, backgroundColor: color.bg }} />;      // a blink of black while the font loads; if it fails the system font is used
  return (
    <SafeAreaProvider>
      <QueryClientProvider client={queryClient}>
        <ConnectionProvider>
          <StatusBar style="light" />
          <SelectionProvider><Gate /></SelectionProvider>
        </ConnectionProvider>
      </QueryClientProvider>
    </SafeAreaProvider>
  );
}
