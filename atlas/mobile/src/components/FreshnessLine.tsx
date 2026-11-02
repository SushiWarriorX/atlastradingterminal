import React from "react";
import { View } from "react-native";
import type { Prov } from "../api/types";
import { describeFreshness, type Fresh } from "../lib/freshness";
import { color, space, toneColor } from "../theme";
import { Txt } from "./ui";

export function FreshDot({ tone, size = 8 }: { tone: Fresh["tone"]; size?: number }) {
  return <View style={{ width: size, height: size, borderRadius: size / 2, backgroundColor: toneColor(tone) }} />;
}

/** "● Delayed ~15 min · updated 12:54 PM · Yahoo Finance". The label comes from the server's status, never from the device guessing. */
export function FreshnessLine({ prov, now, source, testID }: { prov: Prov | null | undefined; now: number; source?: string; testID?: string }) {
  const f = describeFreshness(prov, now);
  return (
    <View style={{ flexDirection: "row", alignItems: "center", gap: space.sm, flexWrap: "wrap" }} testID={testID} accessible accessibilityLabel={`${f.label}. ${f.detail}. ${source ?? ""}`}>
      <FreshDot tone={f.tone} />
      <Txt variant="small" c={f.warn ? color.warn : color.dim} style={{ fontWeight: f.warn ? "700" : "400" }}>{f.label}</Txt>
      {f.detail ? <Txt variant="small">· {f.detail}</Txt> : null}
      {source && f.tone !== "demo" ? <Txt variant="tiny">· {source}</Txt> : null}
    </View>
  );
}
