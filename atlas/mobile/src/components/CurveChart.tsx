import React, { useId, useState } from "react";
import { Platform, View, type LayoutChangeEvent } from "react-native";
import Svg, { Circle, Defs, Line, LinearGradient, Path, Rect, Stop, Text as SvgText } from "react-native-svg";
import type { PaperLab } from "../api/types";
import { fonts, color } from "../theme";

const hidden = Platform.OS === "web" ? ({ "aria-hidden": true } as object) : ({ accessibilityElementsHidden: true, importantForAccessibility: "no-hide-descendants" } as object);
const CAPTION = { TRAIN: "chosen on this", VALIDATION: "checked on this", TEST: "not a clean test" } as const;

/** One backtest as a picture: the equity of a rule replayed on past prices (a ratio of its $10,000 start), over three bands that say how each stretch of history was used: the settings were chosen on 2020-2022, checked on 2023-2024, and 2025 onward is not a clean test. A dashed line marks the start. */
export function CurveChart({ curve, periods, tint, height = 150, label }: { curve: number[]; periods: NonNullable<PaperLab["backtest"]>["periods"]; tint: string; height?: number; label: string }) {
  const id = "c" + useId().replace(/[^a-zA-Z0-9]/g, "");
  const [w, setW] = useState(0);
  const n = curve.length;
  const onLayout = (e: LayoutChangeEvent) => setW(e.nativeEvent.layout.width);
  let body: React.ReactNode = null;
  if (w > 0 && n >= 2) {
    const lo = Math.min(...curve, 1), hi = Math.max(...curve, 1), span = hi - lo || 1, top = 20, bottom = 8;
    const x = (i: number) => (i / (n - 1)) * w;
    const y = (v: number) => top + (1 - (v - lo) / span) * (height - top - bottom);
    const pts = curve.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`);
    const line = `M${pts.join(" L")}`;
    const bands = periods.map((p) => ({ ...p, x0: x(p.from), x1: p.to >= n - 1 ? w : x(p.to + 1) }));
    body = (
      <Svg width={w} height={height} {...hidden}>
        <Defs><LinearGradient id={id} x1="0" y1="0" x2="0" y2="1"><Stop offset="0" stopColor={tint} stopOpacity={0.22} /><Stop offset="1" stopColor={tint} stopOpacity={0} /></LinearGradient></Defs>
        {bands.map((b) => <Rect key={b.name} x={b.x0} y={0} width={Math.max(0, b.x1 - b.x0)} height={height} fill={b.name === "TRAIN" ? color.surface : b.name === "TEST" ? "#FFF6E6" : color.bg} />)}
        {bands.map((b) => (b.x1 - b.x0 > 64 ? <SvgText key={b.name} x={b.x0 + 6} y={13} fontSize={10} fontFamily={fonts.semibold} fill={color.faint}>{CAPTION[b.name]}</SvgText> : null))}
        <Line x1={0} x2={w} y1={y(1)} y2={y(1)} stroke={color.faint} strokeWidth={1} strokeDasharray="3,4" />
        <Path d={`${line} L${w},${height} L0,${height} Z`} fill={`url(#${id})`} />
        <Path d={line} stroke={tint} strokeWidth={2} fill="none" strokeLinejoin="round" strokeLinecap="round" />
        <Circle cx={x(n - 1) - 3} cy={y(curve[n - 1])} r={3.5} fill={tint} stroke={color.bg} strokeWidth={1.5} />
      </Svg>
    );
  }
  return <View style={{ height, borderRadius: 12, overflow: "hidden", borderWidth: 1, borderColor: color.border }} onLayout={onLayout} accessibilityRole="image" accessibilityLabel={label} testID="curve-chart">{body}</View>;
}
