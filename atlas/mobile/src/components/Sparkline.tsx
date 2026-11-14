import React from "react";
import { Platform } from "react-native";
import Svg, { Polyline } from "react-native-svg";

// The browser does not know React Native's accessibility props and warns about them; it wants aria-hidden. Phones want the native prop.
const hidden = Platform.OS === "web" ? ({ "aria-hidden": true } as object) : ({ accessibilityElementsHidden: true, importantForAccessibility: "no-hide-descendants" } as object);

export function Sparkline({ values, tint, width = 64, height = 26 }: { values: number[] | null | undefined; tint: string; width?: number; height?: number }) {
  if (!values || values.length < 2) return <Svg width={width} height={height} />;
  const min = Math.min(...values), max = Math.max(...values), span = max - min || 1;
  const pts = values.map((v, i) => `${((i / (values.length - 1)) * (width - 2) + 1).toFixed(1)},${(height - 2 - ((v - min) / span) * (height - 4)).toFixed(1)}`).join(" ");
  return (
    <Svg width={width} height={height} {...hidden}>
      <Polyline points={pts} fill="none" stroke={tint} strokeWidth={1.6} strokeLinejoin="round" strokeLinecap="round" />
    </Svg>
  );
}
