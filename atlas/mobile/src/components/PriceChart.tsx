import React, { useMemo, useRef, useState } from "react";
import { PanResponder, View, type LayoutChangeEvent } from "react-native";
import Svg, { Circle, Line, Path } from "react-native-svg";
import { color } from "../theme";

export interface Scrub { t: number; v: number; i: number }

/** A clean single-line chart, no fill. Touch or drag to read any point; the parent shows that point's price and time in place of the headline price. */
export function PriceChart({ points, tint, height = 210, onScrub }: { points: [number, number][]; tint: string; height?: number; onScrub?: (s: Scrub | null) => void }) {
  const [w, setW] = useState(0);
  const [at, setAt] = useState<number | null>(null);
  const n = points.length;
  const geo = useMemo(() => {
    if (n < 2 || !w) return null;
    const vals = points.map((p) => p[1]);
    const min = Math.min(...vals), max = Math.max(...vals), span = max - min || 1, padY = 14;
    const xs = (i: number) => (i / (n - 1)) * w;
    const ys = (v: number) => padY + (1 - (v - min) / span) * (height - padY * 2);
    const line = points.map((p, i) => `${i === 0 ? "M" : "L"}${xs(i).toFixed(1)} ${ys(p[1]).toFixed(1)}`).join(" ");
    return { xs, ys, line };
  }, [points, w, height, n]);
  const stateRef = useRef({ w: 0, n: 0, points, onScrub });
  stateRef.current = { w, n, points, onScrub };
  const pan = useRef(PanResponder.create({
    onStartShouldSetPanResponder: () => true,
    onMoveShouldSetPanResponder: () => true,
    onPanResponderTerminationRequest: () => true,                      // a vertical swipe hands control back to the page scroll
    onPanResponderGrant: (e) => move(e.nativeEvent.locationX),
    onPanResponderMove: (e) => move(e.nativeEvent.locationX),
    onPanResponderRelease: () => end(),
    onPanResponderTerminate: () => end(),
  })).current;
  function move(x: number) {
    const { w, n, points, onScrub } = stateRef.current;
    if (!w || n < 2) return;
    const i = Math.max(0, Math.min(n - 1, Math.round((x / w) * (n - 1))));
    setAt(i);
    onScrub?.({ t: points[i][0], v: points[i][1], i });
  }
  function end() { setAt(null); stateRef.current.onScrub?.(null); }
  const onLayout = (e: LayoutChangeEvent) => setW(e.nativeEvent.layout.width);
  return (
    <View style={{ height }} onLayout={onLayout} {...pan.panHandlers} testID="price-chart" accessibilityLabel="Price chart. Touch and drag to read prices." accessibilityRole="image">
      {geo && (
        <Svg width={w} height={height}>
          <Path d={geo.line} stroke={tint} strokeWidth={2.5} fill="none" strokeLinejoin="round" strokeLinecap="round" />
          {at !== null && (
            <>
              <Line x1={geo.xs(at)} x2={geo.xs(at)} y1={0} y2={height} stroke={color.dim} strokeWidth={1} strokeDasharray="3,3" />
              <Circle cx={geo.xs(at)} cy={geo.ys(points[at][1])} r={5} fill={tint} stroke={color.bg} strokeWidth={2} />
            </>
          )}
        </Svg>
      )}
    </View>
  );
}
