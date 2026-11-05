import React, { useId } from "react";
import { StyleSheet, View, type StyleProp, type ViewStyle } from "react-native";
import Svg, { Defs, LinearGradient, Rect, Stop } from "react-native-svg";

/** A gradient background drawn with SVG, so it looks the same on the web and on a phone. Children sit on top. `from` and `to` are 0-1 corners of the box. */
export function Gradient({ colors, from = [0, 0], to = [1, 1], style, children, testID }: { colors: readonly string[]; from?: [number, number]; to?: [number, number]; style?: StyleProp<ViewStyle>; children?: React.ReactNode; testID?: string }) {
  const id = "g" + useId().replace(/[^a-zA-Z0-9]/g, "");
  return (
    <View style={[{ overflow: "hidden" }, style]} testID={testID}>
      <Svg style={StyleSheet.absoluteFill} width="100%" height="100%" preserveAspectRatio="none" pointerEvents="none">
        <Defs>
          <LinearGradient id={id} x1={from[0]} y1={from[1]} x2={to[0]} y2={to[1]}>
            {colors.map((c, i) => <Stop key={i} offset={colors.length === 1 ? 0 : i / (colors.length - 1)} stopColor={c} />)}
          </LinearGradient>
        </Defs>
        <Rect x="0" y="0" width="100%" height="100%" fill={`url(#${id})`} />
      </Svg>
      {children}
    </View>
  );
}

/** Colour wash at the top of a screen: violet and pink on the left, teal on the right, fading to the background. Purely decorative. */
export function TopGlow({ height = 300 }: { height?: number }) {
  return (
    <View pointerEvents="none" style={{ position: "absolute", top: 0, left: 0, right: 0, height }}>
      <Gradient colors={["rgba(122,92,255,0.60)", "rgba(61,123,255,0.26)", "rgba(5,5,13,0)"]} from={[0, 0]} to={[0.3, 1]} style={StyleSheet.absoluteFill} />
      <Gradient colors={["rgba(22,217,198,0.38)", "rgba(22,217,198,0)"]} from={[1, 0]} to={[0.4, 0.8]} style={StyleSheet.absoluteFill} />
      <Gradient colors={["rgba(255,95,162,0.22)", "rgba(255,95,162,0)"]} from={[0.5, 0]} to={[0.5, 0.6]} style={StyleSheet.absoluteFill} />
    </View>
  );
}
