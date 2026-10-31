// Shared industrial UI primitives. Status always = icon + text (never color alone). Min 56pt touch targets.
import { MaterialDesignIcons } from "@react-native-vector-icons/material-design-icons";
import { router } from "expo-router";
import { PropsWithChildren, ReactNode, useState } from "react";
import { ActivityIndicator, InputAccessoryView, Keyboard, KeyboardTypeOptions, Modal, Platform, Pressable, RefreshControl, ScrollView, Text, TextInput, View, ViewStyle } from "react-native";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { makeStyles, ThemeColors, useTheme } from "./theme";

export const Icon = MaterialDesignIcons;
type Tone = "neutral" | "success" | "warning" | "error" | "info" | "brand";

const STATUS: Record<string, { icon: string; tone: Tone }> = {
  "Saved on this device": { icon: "content-save-check", tone: "info" },
  Queued: { icon: "clock-outline", tone: "neutral" },
  Uploading: { icon: "upload", tone: "info" },
  "Uploaded unverified": { icon: "cloud-question", tone: "warning" },
  Verified: { icon: "cloud-check", tone: "success" },
  "Retry wait": { icon: "timer-sand", tone: "warning" },
  Blocked: { icon: "alert-octagon", tone: "error" },
  Running: { icon: "cog-sync", tone: "info" },
  Done: { icon: "check-circle", tone: "success" },
  Failed: { icon: "close-octagon", tone: "error" },
  "Not started": { icon: "circle-outline", tone: "neutral" },
  Provided: { icon: "check-bold", tone: "success" },
  "Missing required": { icon: "alert-circle", tone: "error" },
  "Needs review": { icon: "eye-check", tone: "warning" },
  // C4/REQ-1236 photo + video states: each has its own icon + tone
  "Checking photo": { icon: "progress-clock", tone: "info" },
  "Checking video": { icon: "progress-clock", tone: "info" },
  "Check complete": { icon: "check-circle-outline", tone: "success" },
  "Could not finish the check": { icon: "alert-octagon-outline", tone: "error" },
  "Waiting for connection": { icon: "wifi-off", tone: "neutral" },
  "Saved on phone": { icon: "cellphone-check", tone: "info" },
  "Sending photo": { icon: "upload-outline", tone: "info" },
  "Sending video": { icon: "upload-outline", tone: "info" },
  "Unknown with reason": { icon: "help-circle", tone: "neutral" },
  "Not applicable": { icon: "minus-circle", tone: "neutral" },
  "Needs estimator input": { icon: "account-tie", tone: "info" },
  Draft: { icon: "pencil", tone: "neutral" },
  Submitted: { icon: "lock", tone: "success" },
  "Received complete": { icon: "receipt", tone: "success" },
  "Receiving partial": { icon: "receipt-text-remove", tone: "warning" },
  "Offline ready": { icon: "cloud-check-outline", tone: "success" },
  "Available offline": { icon: "cloud-check-outline", tone: "success" },
  "Saved on device": { icon: "content-save-check-outline", tone: "info" },
  Synced: { icon: "cloud-check-outline", tone: "success" },
  "Not prepared": { icon: "cloud-download-outline", tone: "neutral" },
  Pending: { icon: "clock-outline", tone: "warning" },
  Confirmed: { icon: "check-decagram", tone: "success" },
  Corrected: { icon: "pencil-circle", tone: "success" },
  Dismissed: { icon: "close-circle-outline", tone: "neutral" },
  "Closer photo requested": { icon: "camera-retake", tone: "warning" },
  Granted: { icon: "check", tone: "success" },
  Denied: { icon: "cancel", tone: "error" },
  Unknown: { icon: "help", tone: "warning" },
};

export function toneColors(c: ThemeColors, tone: Tone) {
  switch (tone) {
    case "success": return { bg: c.success, fg: c.onSuccess };
    case "warning": return { bg: c.warning, fg: c.onWarning };
    case "error": return { bg: c.error, fg: c.onError };
    case "info": return { bg: c.info, fg: c.onInfo };
    case "brand": return { bg: c.brandPrimary, fg: c.onBrandPrimary };
    default: return { bg: c.surfaceTertiary, fg: c.onSurfaceTertiary };
  }
}

// Phase 8 (REQ-258): internal states are shown to people in plain words only.
const PLAIN: Record<string, string> = {
  "Saved on this device": "Saved", "Saved on device": "Saved", Queued: "Waiting", "Uploaded unverified": "Uploading",
  Verified: "Backed up", Synced: "Backed up", "Retry wait": "Will try again", Blocked: "Needs attention", Running: "Working on it", Done: "Ready",
  Failed: "Needs another try", "Not started": "Waiting", "Received complete": "All received", "Receiving partial": "Some items still coming",
  "Unknown with reason": "Not known", "Needs estimator input": "Asked the estimator", Pending: "Waiting for you", "Closer photo requested": "Closer photo asked for",
  Granted: "Allowed", Denied: "Not allowed", Unknown: "Not set", "Missing required": "Still needed", Provided: "Answered",
};

export function Badge({ label, prefix, testID, icon, tone }: { label: string; prefix?: string; testID?: string; icon?: string; tone?: Tone }) {
  const { colors } = useTheme();
  const s = STATUS[label] || { icon: icon || "information-outline", tone: tone || "neutral" };
  const t = toneColors(colors, tone || s.tone);
  // REQ-226: status = text + line icon (no filled pills); tone colours only the icon.
  return (
    <View testID={testID} accessibilityLabel={`${prefix ? prefix + ": " : ""}${PLAIN[label] ?? label}`}
      style={{ flexDirection: "row", alignItems: "center", alignSelf: "flex-start", gap: 6, paddingVertical: 2 }}>
      <Icon name={(icon || s.icon) as any} size={16} color={tone === "neutral" || s.tone === "neutral" ? colors.muted : t.bg} />
      <Text style={{ color: colors.onSurface, fontSize: 13, fontWeight: "500" }}>{prefix ? `${prefix}: ` : ""}{PLAIN[label] ?? label}</Text>
    </View>
  );
}

export function Btn({ title, onPress, icon, kind = "primary", disabled, loading, testID, style, small }: {
  title: string; onPress?: () => void; icon?: string; kind?: "primary" | "secondary" | "danger" | "ghost" | "header"; disabled?: boolean; loading?: boolean; testID?: string; style?: ViewStyle; small?: boolean;
}) {
  const { colors } = useTheme();
  const map = {
    header: { bg: "transparent", fg: colors.onSurfaceInverse, bd: colors.onSurfaceInverse },
    primary: { bg: colors.brandPrimary, fg: colors.onBrandPrimary, bd: colors.brandPrimary },
    secondary: { bg: colors.surface, fg: colors.onSurface, bd: colors.border },
    danger: { bg: colors.surface, fg: colors.error, bd: colors.error },
    ghost: { bg: "transparent", fg: colors.onSurface, bd: colors.border },
  }[kind];
  return (
    <Pressable testID={testID} accessibilityRole="button" accessibilityState={{ disabled: !!disabled }} disabled={disabled || loading} onPress={onPress}
      style={({ pressed }) => [{
        minHeight: small ? 44 : 52, borderRadius: 8, borderWidth: 1, borderColor: map.bd, backgroundColor: map.bg,
        flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, paddingHorizontal: 16,
        opacity: disabled ? 0.45 : pressed ? 0.8 : 1, transform: [{ scale: pressed ? 0.98 : 1 }],
      }, style]}>
      {loading ? <ActivityIndicator color={map.fg} /> : icon ? <Icon name={icon as any} size={20} color={map.fg} /> : null}
      <Text style={{ color: map.fg, fontSize: small ? 14 : 16, fontWeight: "600", flexShrink: 1 }}>{title}</Text>
    </Pressable>
  );
}

export function Screen({ title, subtitle, back = true, right, children, scroll = true, testID, footer, refreshing, onRefresh, fab }: PropsWithChildren<{
  title: string; subtitle?: string; back?: boolean; right?: ReactNode; scroll?: boolean; testID?: string; footer?: ReactNode; refreshing?: boolean; onRefresh?: () => void; fab?: ReactNode;
}>) {
  const insets = useSafeAreaInsets();
  const s = useStyles();
  const { colors } = useTheme();
  return (
    <View style={s.root} testID={testID}>
      <View style={[s.header, { paddingTop: insets.top + 8 }]}>
        {back ? (
          <Pressable testID="header-back-button" accessibilityLabel="Back" onPress={() => (router.canGoBack() ? router.back() : router.replace("/"))} style={s.backBtn}>
            <Icon name="arrow-left" size={26} color={colors.onSurfaceInverse} />
          </Pressable>
        ) : null}
        <View style={{ flex: 1 }}>
          <Text style={s.title} numberOfLines={2}>{title}</Text>
          {subtitle ? <Text style={s.subtitle} numberOfLines={1}>{subtitle}</Text> : null}
        </View>
        {right}
      </View>
      {scroll ? (
        <KeyboardAwareScrollView bottomOffset={24} contentContainerStyle={[s.content, { paddingBottom: (footer ? 16 : insets.bottom + 24) }]} keyboardShouldPersistTaps="handled" keyboardDismissMode={Platform.OS === "ios" ? "interactive" : "on-drag"}
          refreshControl={onRefresh ? <RefreshControl testID="screen-pull-to-refresh" refreshing={!!refreshing} onRefresh={onRefresh} /> : undefined}>
          {children}
        </KeyboardAwareScrollView>
      ) : (
        <View style={{ flex: 1 }}>{children}</View>
      )}
      {footer ? <View style={[s.footer, { paddingBottom: insets.bottom + 12 }]}>{footer}</View> : null}
      {fab ? <View style={{ position: "absolute", right: 20, bottom: insets.bottom + 20 }}>{fab}</View> : null}
    </View>
  );
}

// Floating "+" action (Phase 8: start a new inspection from anywhere on My work).
export function Fab({ onPress, label, testID }: { onPress: () => void; label: string; testID?: string }) {
  const { colors } = useTheme();
  return (
    <Pressable testID={testID} accessibilityRole="button" accessibilityLabel={label} onPress={onPress}
      style={({ pressed }) => ({ width: 60, height: 60, borderRadius: 30, backgroundColor: colors.brandPrimary, alignItems: "center", justifyContent: "center",
        transform: [{ scale: pressed ? 0.94 : 1 }], shadowColor: "#000", shadowOpacity: 0.2, shadowRadius: 8, shadowOffset: { width: 0, height: 4 }, elevation: 6 })}>
      <Icon name="plus" size={30} color={colors.onBrandPrimary} />
    </Pressable>
  );
}

export function Card({ children, testID, style, onPress }: PropsWithChildren<{ testID?: string; style?: ViewStyle; onPress?: () => void }>) {
  const s = useStyles();
  if (onPress)
    return (
      <Pressable testID={testID} onPress={onPress} style={({ pressed }) => [s.card, style, pressed && { opacity: 0.85 }]}>{children}</Pressable>
    );
  return <View testID={testID} style={[s.card, style]}>{children}</View>;
}

export function H({ children }: PropsWithChildren) {
  const s = useStyles();
  return <Text style={s.h} accessibilityRole="header">{children}</Text>;
}
export function T({ children, muted, bold, size, testID, style, numberOfLines }: PropsWithChildren<{ muted?: boolean; bold?: boolean; size?: number; testID?: string; style?: any; numberOfLines?: number }>) {
  const { colors } = useTheme();
  return <Text testID={testID} numberOfLines={numberOfLines} style={[{ color: muted ? colors.muted : colors.onSurface, fontWeight: bold ? "700" : "400", fontSize: size || 15, lineHeight: (size || 15) * 1.4 }, style]}>{children}</Text>;
}

export function Input({ label, value, onChangeText, multiline, keyboardType, testID, placeholder, onSubmitEditing }: {
  label: string; value: string; onChangeText: (s: string) => void; multiline?: boolean; keyboardType?: KeyboardTypeOptions; testID?: string; placeholder?: string;
  onSubmitEditing?: () => void;
}) {
  const s = useStyles();
  const { colors } = useTheme();
  const [focused, setFocused] = useState(false);
  const accId = testID ? `${testID}-done` : undefined;
  // Keyboard: single-line Return = Done (closes the keyboard). Multi-line keeps newlines and gets a visible Done control
  // (label row on every platform + an iOS accessory bar). Text is never lost: it is controlled state, saved by drafts.
  return (
    <View style={{ gap: 4 }}>
      <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
        <Text style={s.label}>{label}</Text>
        {multiline && focused ? (
          <Pressable testID={accId ? `${accId}-button` : undefined} accessibilityRole="button" onPress={() => Keyboard.dismiss()} hitSlop={12} style={{ minHeight: 32, justifyContent: "center", paddingHorizontal: 8 }}>
            <Text style={{ color: colors.brand, fontWeight: "600" }}>Done</Text>
          </Pressable>
        ) : null}
      </View>
      <TextInput testID={testID} accessibilityLabel={label} value={value} onChangeText={onChangeText} multiline={multiline} keyboardType={keyboardType}
        placeholder={placeholder} placeholderTextColor={colors.muted}
        returnKeyType={multiline ? "default" : "done"} submitBehavior={multiline ? "newline" : "blurAndSubmit"} onSubmitEditing={onSubmitEditing}
        onFocus={() => setFocused(true)} onBlur={() => setFocused(false)}
        inputAccessoryViewID={Platform.OS === "ios" && multiline ? accId : undefined}
        style={[s.input, multiline && { minHeight: 110, textAlignVertical: "top", paddingTop: 12 }]} />
      {Platform.OS === "ios" && multiline && accId ? (
        <InputAccessoryView nativeID={accId}>
          <View style={{ flexDirection: "row", justifyContent: "flex-end", backgroundColor: colors.surface, borderTopWidth: 1, borderColor: colors.border, padding: 8 }}>
            <Pressable accessibilityRole="button" onPress={() => Keyboard.dismiss()} style={{ minHeight: 36, paddingHorizontal: 12, justifyContent: "center" }}>
              <Text style={{ color: colors.brand, fontWeight: "600", fontSize: 16 }}>Done</Text>
            </Pressable>
          </View>
        </InputAccessoryView>
      ) : null}
    </View>
  );
}

export function Banner({ text, tone = "info", icon, testID, children }: PropsWithChildren<{ text: string; tone?: Tone; icon?: string; testID?: string }>) {
  const { colors } = useTheme();
  const t = toneColors(colors, tone);
  return (
    <View testID={testID} style={{ backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 8, padding: 12, gap: 8 }}>
      <View style={{ flexDirection: "row", gap: 8, alignItems: "flex-start" }}>
        <Icon name={(icon || "information-outline") as any} size={20} color={tone === "neutral" ? colors.muted : t.bg} />
        <Text style={{ color: colors.onSurface, fontWeight: "500", flex: 1, fontSize: 14 }}>{text}</Text>
      </View>
      {children}
    </View>
  );
}

export function Sheet({ visible, onClose, title, children, testID }: PropsWithChildren<{ visible: boolean; onClose: () => void; title: string; testID?: string }>) {
  const s = useStyles();
  const insets = useSafeAreaInsets();
  const { colors } = useTheme();
  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <View style={s.backdrop}>
        <View testID={testID} style={[s.sheet, { paddingBottom: insets.bottom + 16 }]}>
          <View style={{ flexDirection: "row", alignItems: "center", marginBottom: 12 }}>
            <Text style={[s.h, { flex: 1 }]}>{title}</Text>
            <Pressable testID="sheet-close-button" accessibilityLabel="Close" onPress={onClose} style={{ padding: 10 }}>
              <Icon name="close" size={26} color={colors.onSurface} />
            </Pressable>
          </View>
          <KeyboardAwareScrollView bottomOffset={24} keyboardShouldPersistTaps="handled" keyboardDismissMode={Platform.OS === "ios" ? "interactive" : "on-drag"} contentContainerStyle={{ gap: 12 }}>{children}</KeyboardAwareScrollView>
        </View>
      </View>
    </Modal>
  );
}

export function Row({ children, style }: PropsWithChildren<{ style?: ViewStyle }>) {
  return <View style={[{ flexDirection: "row", flexWrap: "wrap", gap: 8, alignItems: "center" }, style]}>{children}</View>;
}

// Segmented control (Capture / Review / Details): one row, equal segments, selection = colour/border only.
export function Segments<K extends string>({ value, onChange, items, testID }: { value: K; onChange: (k: K) => void; items: [K, string][]; testID?: string }) {
  const { colors } = useTheme();
  return (
    <View testID={testID} style={{ flexDirection: "row", backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 8, padding: 3 }}>
      {items.map(([k, label]) => {
        const on = k === value;
        return (
          <Pressable key={k} testID={`${testID}-${k}`} accessibilityRole="tab" accessibilityState={{ selected: on }} onPress={() => onChange(k)}
            style={{ flex: 1, minHeight: 40, alignItems: "center", justifyContent: "center", borderRadius: 6, backgroundColor: on ? colors.surfaceInverse : "transparent" }}>
            <Text style={{ color: on ? colors.onSurfaceInverse : colors.onSurface, fontSize: 14, fontWeight: "500" }}>{label}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

// Quiet empty/error state: line icon + one sentence + optional action.
export function Empty({ icon, text, action, testID }: { icon: string; text: string; action?: ReactNode; testID?: string }) {
  const { colors } = useTheme();
  return (
    <View testID={testID} style={{ alignItems: "center", gap: 8, paddingVertical: 24 }}>
      <Icon name={icon as any} size={28} color={colors.muted} />
      <Text style={{ color: colors.muted, fontSize: 14, textAlign: "center" }}>{text}</Text>
      {action}
    </View>
  );
}

export function Loading({ text = "Loading..." }: { text?: string }) {
  const { colors } = useTheme();
  return (
    <View style={{ padding: 32, alignItems: "center", gap: 8 }}>
      <ActivityIndicator color={colors.brandPrimary} size="large" />
      <T muted>{text}</T>
    </View>
  );
}

export const fmt = (iso?: string | null) => (iso ? new Date(iso).toLocaleString() : "-");

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surfaceSecondary },
  header: { backgroundColor: c.surfaceInverse, flexDirection: "row", alignItems: "center", gap: 8, paddingHorizontal: 12, paddingBottom: 12 },
  backBtn: { width: 48, height: 48, alignItems: "center", justifyContent: "center" },
  title: { color: c.onSurfaceInverse, fontSize: 22, fontWeight: "600" },
  subtitle: { color: c.onSurfaceInverse, fontSize: 13, opacity: 0.85 },
  content: { padding: 16, gap: 16 },
  footer: { borderTopWidth: 1, borderTopColor: c.border, backgroundColor: c.surface, paddingHorizontal: 16, paddingTop: 12, gap: 8 },
  card: { backgroundColor: c.surface, borderWidth: 1, borderColor: c.border, borderRadius: 8, padding: 12, gap: 8 },
  h: { color: c.onSurface, fontSize: 18, fontWeight: "600" },
  label: { color: c.onSurface, fontSize: 14, fontWeight: "500" },
  input: { minHeight: 48, borderWidth: 1, borderColor: c.border, borderRadius: 8, paddingHorizontal: 12, fontSize: 16, color: c.onSurface, backgroundColor: c.surface },
  backdrop: { flex: 1, backgroundColor: "rgba(0,0,0,0.55)", justifyContent: "flex-end" },
  sheet: { backgroundColor: c.surface, borderTopLeftRadius: 12, borderTopRightRadius: 12, padding: 16, maxHeight: "88%" },
}));

export { ScrollView };
