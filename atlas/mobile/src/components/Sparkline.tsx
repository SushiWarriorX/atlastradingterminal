import React, { useId } from "react";
import { Platform } from "react-native";
import Svg, { Circle, Defs, LinearGradient, Path, Polyline, Stop } from "react-native-svg";

// The browser does not know React Native's accessibility props and warns about them; it wants aria-hidden. Phones want the native prop.
const hidden = Platform.OS === "web" ? ({ "aria-hidden": true } as object) : ({ accessibilityElementsHidden: true, importantForAccessibility: "no-hide-descendants" } as object);

/** A small line of recent values. With `area` the space under the line fades from the line's colour to nothing, and `dot` marks the last value, as on TradingView's coin cards. */
export function Sparkline({ values, tint, width = 64, height = 26, area, dot }: { values: number[] | null | undefined; tint: string; width?: number; height?: number; area?: boolean; dot?: boolean }) {
  const id = "s" + useId().replace(/[^a-zA-Z0-9]/g, "");
  if (!values || values.length < 2) return <Svg width={width} height={height} />;
  const min = Math.min(...values), max = Math.max(...values), span = max - min || 1, pad = dot ? 4 : 2;
  const xy = values.map((v, i): [number, number] => [(i / (values.length - 1)) * (width - 2 * pad) + pad, height - pad - ((v - min) / span) * (height - 2 * pad - (area ? 2 : 0))]);
  const pts = xy.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  const last = xy[xy.length - 1];
  return (
    <Svg width={width} height={height} {...hidden}>
      {area ? (
        <>
          <Defs><LinearGradient id={id} x1="0" y1="0" x2="0" y2="1"><Stop offset="0" stopColor={tint} stopOpacity={0.28} /><Stop offset="1" stopColor={tint} stopOpacity={0} /></LinearGradient></Defs>
          <Path d={`M${xy[0][0].toFixed(1)},${height} L${pts.replace(/ /g, " L")} L${last[0].toFixed(1)},${height} Z`} fill={`url(#${id})`} />
        </>
      ) : null}
      <Polyline points={pts} fill="none" stroke={tint} strokeWidth={1.8} strokeLinejoin="round" strokeLinecap="round" />
      {dot ? <Circle cx={last[0]} cy={last[1]} r={3} fill={tint} stroke="#FFFFFF" strokeWidth={1.5} /> : null}
    </Svg>
  );
}
