// Design tokens for this app. Light theme only.Always modify the colors and theme to Dark, Light or Dark and Light according to the design guidelines.
//
// The keys match the "color" block of /app/design_guidelines.json. Fill the
// values from that file (or from the user's brand colors). Keep every key; do
// not add a second theme or colors file; do not write color literals in
// components.
//
// How the names work: a plain key is a background, and its `on` partner is the
// text or icon color that sits on top of it. Always use them as a pair.
//   <View style={{ backgroundColor: colors.brandPrimary }}>
//     <Text style={{ color: colors.onBrandPrimary }}>Continue</Text>
//   </View>
//
// Styling a screen or component: build the sheet with makeStyles so colors
// and layout live together and follow the active scheme:
//   const useStyles = makeStyles((colors) => ({
//     card: { backgroundColor: colors.surfaceSecondary, padding: 16 },
//     title: { color: colors.onSurfaceSecondary, fontSize: 16 },
//   }));
//   function Screen() {
//     const styles = useStyles();
//     return <View style={styles.card}><Text style={styles.title}>Hi</Text></View>;
//   }
// For color props that are not styles (icon color, placeholderTextColor,
// ActivityIndicator) read useTheme().colors inside the component.
// Never call StyleSheet.create with color values at module level; it cannot
// follow the scheme.
//
// To support dark mode later: add `dark` to `themes` with every key filled.
// Nothing else changes; the device setting takes over automatically.
// Feel free to add as many new colors as you need to support the design guidelines.

import { useMemo } from "react";
import { Appearance, ImageStyle, StyleSheet, TextStyle, useColorScheme, ViewStyle } from "react-native";

export type ColorScheme = "light" | "dark";

const light = {
  surface: "#FFFFFF",
  onSurface: "#202428",
  surfaceSecondary: "#F3F4F4",
  onSurfaceSecondary: "#202428",
  surfaceTertiary: "#E5E7EB",
  onSurfaceTertiary: "#374151",
  surfaceInverse: "#22272B",
  onSurfaceInverse: "#F9FAFB",
  brand: "#B32624",
  onBrand: "#FFFFFF",
  brandPrimary: "#B32624",
  onBrandPrimary: "#FFFFFF",
  brandSecondary: "#FDBA74",
  onBrandSecondary: "#111827",
  brandTertiary: "#F7E4E3",
  onBrandTertiary: "#B32624",
  success: "#15803D",
  onSuccess: "#FFFFFF",
  warning: "#B45309",
  onWarning: "#FFFFFF",
  error: "#B91C1C",
  onError: "#FFFFFF",
  info: "#59636B",
  onInfo: "#FFFFFF",
  border: "#D9DEE2",
  borderStrong: "#9CA3AF",
  divider: "#D9DEE2",
  muted: "#59636B",
};

const dark: typeof light = {
  surface: "#111827",
  onSurface: "#F9FAFB",
  surfaceSecondary: "#1F2937",
  onSurfaceSecondary: "#F9FAFB",
  surfaceTertiary: "#374151",
  onSurfaceTertiary: "#D1D5DB",
  surfaceInverse: "#F9FAFB",
  onSurfaceInverse: "#111827",
  brand: "#F97316",
  onBrand: "#111827",
  brandPrimary: "#F97316",
  onBrandPrimary: "#111827",
  brandSecondary: "#9A3412",
  onBrandSecondary: "#F9FAFB",
  brandTertiary: "#431407",
  onBrandTertiary: "#FDBA74",
  success: "#22C55E",
  onSuccess: "#064E3B",
  warning: "#F59E0B",
  onWarning: "#451A03",
  error: "#EF4444",
  onError: "#450A0A",
  info: "#9CA3AF",
  onInfo: "#111827",
  border: "#374151",
  borderStrong: "#6B7280",
  divider: "#1F2937",
  muted: "#9CA3AF",
};

export type ThemeColors = typeof light;

export const defaultScheme = "light" satisfies ColorScheme;

// Phase 5 (REQ-226): forced light on every mobile screen; `dark` kept only for a future opt-in.
void dark;
export const themes: { light: ThemeColors; dark?: ThemeColors } = { light };

// In-app theme toggle, only after `dark` exists in `themes`. Call
// setColorScheme("dark"), setColorScheme("light"), or setColorScheme(null) to
// follow the device. Every useTheme() consumer re-renders. Persisting the
// choice and re-applying it on launch is the toggle's job.
export function setColorScheme(scheme: ColorScheme | null) {
  // RN 0.86 re-reads the device scheme only for the literal "unspecified";
  // null would pin useColorScheme() to null and the app to light.
  Appearance.setColorScheme?.(scheme ?? "unspecified");
}

// Keep native surfaces (alerts, pickers, navigation chrome) on the schemes this
// app ships: light only forces light; once `dark` exists the device decides.
// Optional call because react-native-web does not implement it.
setColorScheme?.(themes.dark ? null : defaultScheme);

export function useTheme(): { scheme: ColorScheme; colors: ThemeColors } {
  const system = useColorScheme();
  const scheme: ColorScheme = (system === "light" || system === "dark") && themes[system] ? system : defaultScheme;
  return { scheme, colors: themes[scheme] ?? themes.light };
}

// Themed StyleSheet: returns a hook that builds the sheet from the active
// scheme's colors and memoizes it until the scheme changes.
type AnyStyle = ViewStyle | TextStyle | ImageStyle;
export function makeStyles<T extends { [K in keyof T]: AnyStyle }>(
  factory: (colors: ThemeColors) => T,
): () => T {
  return function useStyles(): T {
    const { colors } = useTheme();
    return useMemo(() => StyleSheet.create(factory(colors)), [colors]);
  };
}


