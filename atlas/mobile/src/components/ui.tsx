import { Ionicons } from "@expo/vector-icons";
import React from "react";
import { ActivityIndicator, Pressable, StyleSheet, Text, View, type StyleProp, type TextProps, type TextStyle, type ViewStyle } from "react-native";
import { color, famFor, font, grad, radius, space } from "../theme";
import { Gradient } from "./Gradient";

/** The smallest tap target in points: what Apple's guidelines ask for (WCAG's own minimum is the smaller 24). Web ignores `hitSlop`, so the touchable element itself has to be this big. */
export const TAP = 44;

/** The room a 40-point round logo and its gap take at the left of a list row (see LogoSlot). */
export const LOGO_PAD = 40 + space.md;
/** A round logo drawn over the left padding of a row's button instead of inside it, so its letters ("BTC", "AA") are not part of what the button says or shows to a screen reader. It lets touches through to the button below. */
export function LogoSlot({ children }: { children: React.ReactNode }) {
  return <View style={{ position: "absolute", left: 0, top: 0, bottom: 0, justifyContent: "center", pointerEvents: "none" }}>{children}</View>;
}

type Variant = "hero" | "title" | "h2" | "body" | "small" | "tiny" | "label";
const V: Record<Variant, TextStyle> = {
  hero: { fontSize: font.hero, fontWeight: "700", color: color.text, letterSpacing: -1.2, fontVariant: ["tabular-nums"] },
  title: { fontSize: font.xxl, fontWeight: "700", color: color.text, letterSpacing: -0.8 },
  h2: { fontSize: font.lg, fontWeight: "600", color: color.text, letterSpacing: -0.2 },
  body: { fontSize: font.md, color: color.text, lineHeight: 21 },
  small: { fontSize: font.sm, color: color.dim, lineHeight: 18 },
  tiny: { fontSize: font.xs, color: color.faint, lineHeight: 15 },
  label: { fontSize: font.sm, color: color.dim, fontWeight: "600" },
};
export function Txt({ variant = "body", c, style, ...rest }: TextProps & { variant?: Variant; c?: string }) {
  const flat = StyleSheet.flatten([V[variant], c ? { color: c } : null, style]) as TextStyle;
  return <Text {...rest} style={[flat, { fontFamily: famFor(flat.fontWeight), fontWeight: undefined }]} />;
}

export function Card({ style, children }: { style?: StyleProp<ViewStyle>; children: React.ReactNode }) {
  return <GCard style={[s.card, style]}>{children}</GCard>;
}

/** A card with a faint violet-to-navy gradient and a thin tinted border. `tone` washes it green, amber or red. */
export function GCard({ style, children, tone, colors, testID }: { style?: StyleProp<ViewStyle>; children?: React.ReactNode; tone?: "good" | "warn" | "bad"; colors?: readonly string[]; testID?: string }) {
  return <Gradient colors={colors ?? (tone ? grad[tone] : grad.card)} from={[0, 0]} to={[1, 1]} style={[{ borderRadius: radius.lg, borderWidth: 1, borderColor: color.border }, style]} testID={testID}>{children}</Gradient>;
}

/** A small badge for facts about an asset (its type, where it trades): neutral grey like the badge beside a symbol in TradingView's lists, or tinted when it carries a warning. */
export function Tag({ label, tint }: { label: string; tint?: string }) {
  return <View style={[s.tag, tint ? { borderColor: tint + "55", backgroundColor: tint + "1A" } : { backgroundColor: color.surface2, borderColor: color.surface2 }]}><Text style={{ color: tint ?? color.dim, fontSize: font.xs, fontFamily: famFor(600) }}>{label}</Text></View>;
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

/** A round light-grey button with one icon: the header buttons (back, search, profile) of TradingView's phone app. */
export function RoundButton({ name, onPress, label, tint = color.text, size = TAP, testID, disabled }: { name: React.ComponentProps<typeof Ionicons>["name"]; onPress: () => void; label: string; tint?: string; size?: number; testID?: string; disabled?: boolean }) {
  return (
    <Pressable onPress={onPress} accessibilityRole="button" accessibilityLabel={label} testID={testID} disabled={disabled} hitSlop={6}
      style={({ pressed }) => [{ width: size, height: size, borderRadius: size / 2, backgroundColor: color.surface2, alignItems: "center", justifyContent: "center" }, pressed && { opacity: 0.6 }, disabled && { opacity: 0.35 }]}>
      <Ionicons name={name} size={Math.round(size * 0.5)} color={tint} />
    </Pressable>
  );
}

export function Chip({ label, active, onPress, testID }: { label: string; active?: boolean; onPress: () => void; testID?: string }) {
  return (
    <Pressable onPress={onPress} accessibilityRole="button" accessibilityState={{ selected: !!active }} testID={testID} style={s.chipHit}>
      <View style={[s.chip, { backgroundColor: active ? color.text : color.surface2 }]}><Text style={[s.chipText, active && { color: color.bg }]}>{label}</Text></View>
    </Pressable>
  );
}

/** A real button: a rounded pill with a tinted fill. `solid` makes it the filled main action. */
export function TextButton({ label, onPress, tint = color.accent, testID, disabled, solid, large }: { label: string; onPress: () => void; tint?: string; testID?: string; disabled?: boolean; solid?: boolean; large?: boolean }) {
  const box = { borderRadius: radius.pill, paddingHorizontal: 16, paddingVertical: large ? 13 : 9, minHeight: large ? TAP : undefined, alignItems: "center" as const, justifyContent: "center" as const };      // large: the pill itself is 44 high
  return (
    <Pressable onPress={onPress} accessibilityRole="button" testID={testID} disabled={disabled} hitSlop={6} style={({ pressed }) => [{ minHeight: TAP, justifyContent: "center" }, pressed && { opacity: 0.7 }, disabled && { opacity: 0.4 }]}>
      {solid && tint === color.accent
        ? <Gradient colors={grad.accent} from={[0, 0]} to={[1, 1]} style={box}><Text style={{ color: color.onAccent, fontSize: font.sm + 1, fontFamily: famFor(700) }}>{label}</Text></Gradient>
        : <View style={[box, { backgroundColor: solid ? tint : tint + "2E", borderColor: solid ? "transparent" : tint + "77", borderWidth: 1 }]}><Text style={{ color: solid ? "#FFFFFF" : tint, fontSize: font.sm + 1, fontFamily: famFor(700) }}>{label}</Text></View>}
    </Pressable>
  );
}

/** The small "Show / Hide" button on a collapsible card. */
export function Pill({ label }: { label: string }) {
  return <Gradient colors={grad.accent} from={[0, 0]} to={[1, 1]} style={{ borderRadius: radius.pill, paddingHorizontal: 16, paddingVertical: 8 }}><Text style={{ color: color.onAccent, fontSize: font.sm + 1, fontFamily: famFor(700) }}>{label}</Text></Gradient>;
}

export function PrimaryButton({ label, onPress, busy, testID, disabled }: { label: string; onPress: () => void; busy?: boolean; testID?: string; disabled?: boolean }) {
  return (
    <Pressable onPress={onPress} disabled={busy || disabled} accessibilityRole="button" testID={testID} style={({ pressed }) => [(pressed || busy || disabled) && { opacity: 0.7 }]}>
      <Gradient colors={grad.accent} from={[0, 0]} to={[1, 1]} style={s.primary}>
        {busy ? <ActivityIndicator color={color.onAccent} /> : <Text style={s.primaryText}>{label}</Text>}
      </Gradient>
    </Pressable>
  );
}

/** A coloured note above content: demo data, offline, stale. Colour is the only signal beyond the words, so every banner also says what it means. */
export function Banner({ tone, title, children, action, testID }: { tone: "demo" | "warn" | "info"; title: string; children?: React.ReactNode; action?: React.ReactNode; testID?: string }) {
  const c = tone === "demo" ? color.demo : tone === "warn" ? color.warn : color.accent;
  return (
    <View style={[s.banner, { backgroundColor: c + "1F" }]} testID={testID} accessibilityRole="alert">
      <View style={{ flex: 1 }}>
        <Text style={{ color: c, fontSize: font.sm, fontFamily: famFor(600) }}>{title}</Text>
        {children ? <Text style={{ color: color.dim, fontSize: font.sm, lineHeight: 18, marginTop: 2, fontFamily: famFor(400) }}>{children}</Text> : null}
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
      <Gradient colors={grad.accent} style={s.emptyIcon}><Ionicons name={icon} size={28} color={color.onAccent} /></Gradient>
      <Txt variant="h2" style={{ textAlign: "center" }}>{title}</Txt>
      <Txt variant="small" style={{ textAlign: "center", marginTop: space.xs, maxWidth: 300 }}>{body}</Txt>
      {action ? <View style={{ marginTop: space.lg }}>{action}</View> : null}
    </View>
  );
}

export function ErrorState({ title, body, onRetry, extra, testID }: { title: string; body: string; onRetry?: () => void; extra?: React.ReactNode; testID?: string }) {
  return (
    <View style={s.empty} testID={testID}>
      <View style={[s.emptyIcon, { backgroundColor: color.down + "26" }]}><Ionicons name="cloud-offline-outline" size={30} color={color.down} /></View>
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
  card: { padding: space.xl - 4 },
  tag: { borderWidth: 1, borderColor: color.border, borderRadius: 6, paddingHorizontal: 6, paddingVertical: 1 },
  divider: { height: StyleSheet.hairlineWidth, backgroundColor: color.border, marginLeft: 68 },
  iconBtn: { padding: 4, minWidth: TAP, minHeight: TAP, alignItems: "center", justifyContent: "center" },
  chip: { paddingHorizontal: 14, paddingVertical: 8, borderRadius: radius.pill, backgroundColor: "transparent" },
  chipHit: { minHeight: TAP, minWidth: TAP, justifyContent: "center" },      // the pill stays as drawn; the button around it is at least 44 by 44
  chipText: { color: color.dim, fontSize: font.sm, fontFamily: famFor(600) },
  primary: { borderRadius: radius.pill, paddingVertical: 17, paddingHorizontal: 28, alignItems: "center", justifyContent: "center", minWidth: 160 },
  primaryText: { color: color.onAccent, fontSize: font.lg, fontFamily: famFor(700) },
  banner: { flexDirection: "row", alignItems: "center", gap: space.md, borderRadius: 18, paddingVertical: 12, paddingHorizontal: space.lg },
  center: { alignItems: "center", justifyContent: "center", padding: space.xl },
  empty: { alignItems: "center", justifyContent: "center", paddingHorizontal: space.xl, paddingVertical: 56 },
  emptyIcon: { width: 64, height: 64, borderRadius: 32, alignItems: "center", justifyContent: "center", marginBottom: space.lg },
});
