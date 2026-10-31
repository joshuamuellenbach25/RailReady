// Phase 13: volume-button capture, gated by RUNTIME detection (REQ-1315/1316).
// iOS: expo-hardware-buttons (AVCaptureEventInteraction, iOS 17.2+). Android: local module "RailReadyVolumeKeys"
// (Activity key interception, only while attached). Expo Go / web / PWA: modules absent -> unsupported -> no prompt, no Help entry.
import { requireOptionalNativeModule } from "expo";
import { Platform } from "react-native";

type Sub = { remove(): void };
type IosMod = { getCapabilitiesAsync(): Promise<{ hasVolumeButtons: boolean }>; attachCameraButton(): void; detachCameraButton(): void;
  addListener(e: "onVolumeButton", f: (p: { direction: "up" | "down" }) => void): Sub };
type AndroidMod = { attach(): void; detach(): void; addListener(e: "onVolumeKey", f: (p: { direction: "up" | "down"; repeat: number }) => void): Sub };

const ios = Platform.OS === "ios" ? requireOptionalNativeModule<IosMod>("HardwareButtons") : null;
const android = Platform.OS === "android" ? requireOptionalNativeModule<AndroidMod>("RailReadyVolumeKeys") : null;

export const volumeModulePresent = () => !!(ios || android);

/** Runtime support check for gating the Help entry: module present AND the device reports volume buttons. */
export async function volumeSupported(): Promise<boolean> {
  try {
    if (ios) return !!(await ios.getCapabilitiesAsync())?.hasVolumeButtons;
    return !!android;
  } catch {
    return false;
  }
}

/** Attach while the camera screen is focused. Resolves to a detach function, or null when unsupported / attach failed. */
export async function attachVolumeCapture(onPress: () => void): Promise<null | (() => void)> {
  try {
    if (ios) {
      const caps = await ios.getCapabilitiesAsync();
      if (!caps?.hasVolumeButtons) return null;
      const sub = ios.addListener("onVolumeButton", () => onPress());
      ios.attachCameraButton();
      return () => {
        sub.remove();
        ios.detachCameraButton();
      };
    }
    if (android) {
      const sub = android.addListener("onVolumeKey", (p) => p.repeat === 0 && onPress()); // key repeat (held button) ignored
      android.attach();
      return () => {
        sub.remove();
        android.detach();
      };
    }
  } catch {
    return null; // attach failed: treated as unsupported (no prompt)
  }
  return null;
}

/** One photo per press: in-flight lock + >= 600 ms debounce (REQ-1313). Pure, so it is unit-testable. */
export function makePressGate(debounceMs = 600, now: () => number = Date.now) {
  let last = -Infinity;
  let busy = false;
  return {
    tryStart() {
      const t = now();
      if (busy || t - last < debounceMs) return false;
      busy = true;
      last = t;
      return true;
    },
    done() {
      busy = false;
    },
  };
}
