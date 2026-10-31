// Contextual permission flow: explain -> request -> (one retry if canAskAgain) -> Open Settings. Never dead-ends: typed fallback offered.
import { useRef, useState } from "react";
import { Linking } from "react-native";
import * as ImagePicker from "expo-image-picker";
import { getRecordingPermissionsAsync, requestRecordingPermissionsAsync } from "expo-audio";
import { Banner, Btn, Sheet, T } from "./ui";

type Kind = "camera" | "microphone";
const COPY = {
  camera: { title: "Camera access", why: "Take photos of ties and fastenings. Photos are kept on this phone and backed up automatically." },
  microphone: { title: "Microphone access", why: "Record voice notes about the track. Recordings are kept on this phone and backed up automatically." },
};
const get = (k: Kind) => (k === "camera" ? ImagePicker.getCameraPermissionsAsync() : getRecordingPermissionsAsync());
const req = (k: Kind) => (k === "camera" ? ImagePicker.requestCameraPermissionsAsync() : requestRecordingPermissionsAsync());

export function usePermission(onTypedFallback: () => void, onLibrary?: () => void) {
  const [sheet, setSheet] = useState<{ kind: Kind; mode: "explain" | "retry" | "settings" } | null>(null);
  const resolver = useRef<((ok: boolean) => void) | null>(null);
  const asked = useRef<Record<string, number>>({});

  async function ensure(kind: Kind): Promise<boolean> {
    const st = await get(kind);
    if (st.granted) return true;
    const mode = st.status === "undetermined" ? "explain" : st.canAskAgain && (asked.current[kind] || 0) < 2 ? "retry" : "settings";
    return new Promise((resolve) => {
      resolver.current = resolve;
      setSheet({ kind, mode });
    });
  }

  async function doRequest() {
    if (!sheet) return;
    const kind = sheet.kind;
    asked.current[kind] = (asked.current[kind] || 0) + 1;
    const r = await req(kind);
    if (r.granted) {
      setSheet(null);
      resolver.current?.(true);
      return;
    }
    setSheet({ kind, mode: r.canAskAgain && asked.current[kind] < 2 ? "retry" : "settings" });
  }
  function close() {
    setSheet(null);
    resolver.current?.(false);
  }

  const element = sheet ? (
    <Sheet visible onClose={close} title={COPY[sheet.kind].title} testID="permission-sheet">
      <T size={16}>{COPY[sheet.kind].why}</T>
      {sheet.mode !== "explain" ? (
        <Banner testID="permission-denied-message" tone="warning" icon="alert"
          text={`${sheet.kind === "camera" ? "Camera" : "Microphone"} permission is denied. Nothing was recorded. You can still type a note.`} />
      ) : null}
      {sheet.mode === "settings" ? (
        <Btn testID="permission-open-settings-button" title="Open Settings" icon="cog" onPress={() => Linking.openSettings()} />
      ) : (
        <Btn testID="permission-continue-button" title={sheet.mode === "explain" ? "Continue" : "Try again"} icon="check" onPress={doRequest} />
      )}
      {sheet.kind === "camera" && onLibrary ? (
        <Btn testID="permission-use-library-button" kind="secondary" title="Use photo library" icon="image-plus" onPress={() => { close(); setTimeout(onLibrary, 450); }} />
      ) : null}
      <Btn testID="permission-typed-fallback-button" kind="secondary" title="Type a note instead" icon="keyboard" onPress={() => { close(); onTypedFallback(); }} />
    </Sheet>
  ) : null;
  return { ensure, element };
}
