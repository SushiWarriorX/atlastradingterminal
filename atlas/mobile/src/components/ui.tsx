import { Ionicons } from "@expo/vector-icons";
import React from "react";
import { ActivityIndicator, Pressable, StyleSheet, Text, View, type StyleProp, type TextProps, type TextStyle, type ViewStyle } from "react-native";
import { color, font, radius, space } from "../theme";

type Variant = "hero" | "title" | "h2" | "body" | "small" | "tiny" | "label";
const V: Record<Variant, TextStyle> = {
  hero: { fontSize: font.hero, fontWeight: "700", color: color.text, letterSpacing: -0.5 },
  title: { fontSize: font.xxl, fontWeight: "700", color: color.text, letterSpacing: -0.3 },
  h2: { fontSize: font.lg, fontWeight: "600", color: color.text },
  body: { fontSize: font.md, color: color.text, lineHeight: 21 },
  small: { fontSize: font.sm, color: color.dim, lineHeight: 18 },
  tiny: { fontSize: font.xs, color: color.faint, lineHeight: 15 },
  label: { fontSize: font.xs, color: color.dim, fontWeight: "600", letterSpacing: 0.8, textTransform: "uppercase" },
};
export function Txt({ variant = "body", c, style, ...rest }: TextProps & { variant?: Variant; c?: string }) {
  return <Text {...rest} style={[V[variant], c ? { color: c } : null, style]} />;
}

export function Card({ style, children }: { style?: StyleProp<ViewStyle>; children: React.ReactNode }) {
  return <View style={[s.card, style]}>{children}</View>;
}

export function Divider() {
  return <View style={s.divider} />;
}

export function IconButton({ name, onPress, label, tint = color.text, size = 22, testID, disabled }: { name: React.ComponentProps<typeof Ionicons>["name"]; onPress: () => void; label: string; tint?: string; size?: number; testID?: string; disabled?: boolean }) {
  return (
    <Pressable onPress={onPress} accessibilityRole="button" accessibilityLabel={label} testID={testID} disabled={disabled} hitSlop={10} style={({ pressed }) => [s.iconBtn, pressed && { opacity: 0.6 }, disabled && { opacity: 0.35 }]}>
      <Ionicons name={name} size={size} color={tint} />
    </Pressable>
  );
}

export function Chip({ label, active, onPress, testID }: { label: string; active?: boolean; onPress: () => void; testID?: string }) {
  return (
    <Pressable onPress={onPress} accessibilityRole="button" accessibilityState={{ selected: !!active }} testID={testID} style={[s.chip, active && s.chipOn]}>
      <Text style={[s.chipText, active && { color: color.text }]}>{label}</Text>
    </Pressable>
  );
}

export function TextButton({ label, onPress, tint = color.accent, testID, disabled }: { label: string; onPress: () => void; tint?: string; testID?: string; disabled?: boolean }) {
  return (
    <Pressable onPress={onPress} accessibilityRole="button" testID={testID} disabled={disabled} hitSlop={8} style={({ pressed }) => [pressed && { opacity: 0.6 }, disabled && { opacity: 0.4 }]}>
      <Text style={{ color: tint, fontSize: font.sm, fontWeight: "600" }}>{label}</Text>
    </Pressable>
  );
}

export function PrimaryButton({ label, onPress, busy, testID, disabled }: { label: string; onPress: () => void; busy?: boolean; testID?: string; disabled?: boolean }) {
  return (
    <Pressable onPress={onPress} disabled={busy || disabled} accessibilityRole="button" testID={testID} style={({ pressed }) => [s.primary, (pressed || busy || disabled) && { opacity: 0.7 }]}>
      {busy ? <ActivityIndicator color={color.text} /> : <Text style={s.primaryText}>{label}</Text>}
    </Pressable>
  );
}

/** A coloured note above content: demo data, offline, stale. Colour is the only signal beyond the words, so every banner also says what it means. */
export function Banner({ tone, title, children, action, testID }: { tone: "demo" | "warn" | "info"; title: string; children?: React.ReactNode; action?: React.ReactNode; testID?: string }) {
  const c = tone === "demo" ? color.demo : tone === "warn" ? color.warn : color.accent;
  return (
    <View style={[s.banner, { borderColor: c + "55", backgroundColor: c + "14" }]} testID={testID} accessibilityRole="alert">
      <View style={{ flex: 1 }}>
        <Text style={{ color: c, fontSize: font.sm, fontWeight: "700" }}>{title}</Text>
        {children ? <Text style={{ color: color.dim, fontSize: font.sm, lineHeight: 18, marginTop: 2 }}>{children}</Text> : null}
      </View>
      {action}
    </View>
  );
}

export function Skeleton({ w, h = 14, r = radius.sm, style }: { w?: number | `${number}%`; h?: number; r?: number; style?: StyleProp<ViewStyle> }) {
  return <View style={[{ width: w ?? "100%", height: h, borderRadius: r, backgroundColor: color.surface2 }, style]} />;
}

export function Spinner({ label }: { label?: string }) {
  return (
    <View style={s.center}>
      <ActivityIndicator color={color.accent} />
      {label ? <Txt variant="small" style={{ marginTop: space.sm }}>{label}</Txt> : null}
    </View>
  );
}

export function EmptyState({ icon, title, body, action, testID }: { icon: React.ComponentProps<typeof Ionicons>["name"]; title: string; body: string; action?: React.ReactNode; testID?: string }) {
  return (
    <View style={s.empty} testID={testID}>
      <View style={s.emptyIcon}><Ionicons name={icon} size={30} color={color.accent} /></View>
      <Txt variant="h2" style={{ textAlign: "center" }}>{title}</Txt>
      <Txt variant="small" style={{ textAlign: "center", marginTop: space.xs, maxWidth: 300 }}>{body}</Txt>
      {action ? <View style={{ marginTop: space.lg }}>{action}</View> : null}
    </View>
  );
}

export function ErrorState({ title, body, onRetry, extra, testID }: { title: string; body: string; onRetry?: () => void; extra?: React.ReactNode; testID?: string }) {
  return (
    <View style={s.empty} testID={testID}>
      <View style={[s.emptyIcon, { backgroundColor: color.down + "18" }]}><Ionicons name="cloud-offline-outline" size={30} color={color.down} /></View>
      <Txt variant="h2" style={{ textAlign: "center" }}>{title}</Txt>
      <Txt variant="small" style={{ textAlign: "center", marginTop: space.xs, maxWidth: 320 }}>{body}</Txt>
      <View style={{ marginTop: space.lg, gap: space.md, alignItems: "center" }}>
        {onRetry ? <PrimaryButton label="Try again" onPress={onRetry} testID="retry" /> : null}
        {extra}
      </View>
    </View>
  );
}

const s = StyleSheet.create({
  card: { backgroundColor: color.surface, borderRadius: radius.lg, padding: space.lg, borderWidth: StyleSheet.hairlineWidth, borderColor: color.border },
  divider: { height: StyleSheet.hairlineWidth, backgroundColor: color.border },
  iconBtn: { padding: 4, alignItems: "center", justifyContent: "center" },
  chip: { paddingHorizontal: 12, paddingVertical: 7, borderRadius: radius.pill, backgroundColor: "transparent" },
  chipOn: { backgroundColor: color.surface2 },
  chipText: { color: color.dim, fontSize: font.sm, fontWeight: "600" },
  primary: { backgroundColor: color.accent, borderRadius: radius.md, paddingVertical: 13, paddingHorizontal: 22, alignItems: "center", justifyContent: "center", minWidth: 120 },
  primaryText: { color: "#0B0B10", fontSize: font.md, fontWeight: "700" },
  banner: { flexDirection: "row", alignItems: "center", gap: space.md, borderWidth: 1, borderRadius: radius.md, paddingVertical: 10, paddingHorizontal: space.md },
  center: { alignItems: "center", justifyContent: "center", padding: space.xl },
  empty: { alignItems: "center", justifyContent: "center", paddingHorizontal: space.xl, paddingVertical: 56 },
  emptyIcon: { width: 64, height: 64, borderRadius: 32, backgroundColor: color.accent + "18", alignItems: "center", justifyContent: "center", marginBottom: space.lg },
});
