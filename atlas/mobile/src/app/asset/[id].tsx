import { useLocalSearchParams } from "expo-router";
import React from "react";
import { AssetView } from "../../components/AssetView";

const decode = (v: string | undefined) => { try { return v ? decodeURIComponent(v) : ""; } catch { return v ?? ""; } };

export default function AssetScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  return <AssetView id={decode(id)} />;
}
