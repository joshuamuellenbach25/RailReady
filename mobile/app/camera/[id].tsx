// Phase 13 in-app camera (supported native builds only). Live preview + on-screen shutter always usable; volume buttons
// take one photo per press while this screen is focused. Photos go through the SAME local save -> queue -> upload ->
// per-item analysis path as the picker shutter (repo.addMedia + syncAll). "Saved on phone" only after durable readback.
import { CameraView, useCameraPermissions } from "expo-camera";
import { useFocusEffect, useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";
import { Linking, Pressable, StyleSheet, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useAuth } from "@/src/auth";
import { crumb, flushCrumbs } from "@/src/crumbs";
import * as repo from "@/src/local/repo";
import { syncAll } from "@/src/sync";
import { useTheme } from "@/src/theme";
import { Btn, T } from "@/src/ui";
import { storage } from "@/src/utils/storage";
import { attachVolumeCapture, makePressGate } from "@/src/volumeCapture";

export const promptKey = (uid: string) => `volume-prompt-seen:${uid}`;

export default function CameraScreen() {
  const { id, help } = useLocalSearchParams<{ id: string; help?: string }>();
  const { user } = useAuth();
  const uid = user ? user.uuid : "";
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { colors } = useTheme();
  const [perm, requestPerm] = useCameraPermissions();
  const cam = useRef<CameraView>(null);
  const gate = useRef(makePressGate(600)).current;
  const [supported, setSupported] = useState(false);
  const [prompt, setPrompt] = useState(false);
  const [toast, setToast] = useState<{ ok: boolean; text: string } | null>(null);
  const [count, setCount] = useState(0);

  const shoot = useCallback(async (via: "shutter" | "volume") => {
    if (!gate.tryStart()) return crumb("camera.press_ignored", via); // repeat / held / double press
    setPrompt(false); // REQ-1305/1306: first press closes the prompt AND takes the photo
    try {
      await crumb("camera.capture", via);
      const pic = await cam.current?.takePictureAsync({ quality: 0.9, exif: true });
      if (!pic?.uri) throw new Error("The camera did not return a photo");
      await repo.addMedia(uid, id, "photo", pic.uri, "image/jpeg", "jpg"); // throws unless durable readback matches
      setCount((n) => n + 1);
      setToast({ ok: true, text: "Saved on phone" });
      syncAll(uid).catch(() => {});
    } catch (e: any) {
      await crumb("camera.save_failed", e?.message);
      setToast({ ok: false, text: `Photo not saved: ${e?.message ?? "storage failed"}. Take it again.` });
    } finally {
      gate.done();
      flushCrumbs();
      setTimeout(() => setToast(null), 2500);
    }
  }, [gate, id, uid]);

  // attach only while focused; detach on blur/unmount so volume behaves normally elsewhere (REQ-1314)
  useFocusEffect(useCallback(() => {
    let detach: null | (() => void) = null;
    let live = true;
    attachVolumeCapture(() => shoot("volume")).then(async (d) => {
      if (!live) return d?.();
      detach = d;
      setSupported(!!d);
      if (d) {
        const seen = await storage.getItem<string | null>(promptKey(uid), null);
        if (!seen || help) {
          setPrompt(true);
          storage.setItem(promptKey(uid), "1"); // once per user per device (REQ-1308)
        }
      }
      crumb("camera.volume_attach", d ? "attached" : "unsupported");
    });
    return () => {
      live = false;
      detach?.();
    };
  }, [shoot, uid, help]));

  useEffect(() => {
    if (perm && !perm.granted && perm.canAskAgain) requestPerm();
  }, [perm, requestPerm]);

  if (!perm) return <View style={[st.root, { backgroundColor: "#000" }]} />;
  if (!perm.granted)
    return (
      <View testID="camera-permission" style={[st.root, { backgroundColor: colors.surface, padding: 24, paddingTop: insets.top + 24, gap: 12 }]}>
        <T>RailReady needs the camera to photograph track conditions.</T>
        {perm.canAskAgain ? <Btn testID="camera-allow-button" title="Allow camera" onPress={requestPerm} />
          : <Btn testID="camera-open-settings-button" title="Open Settings" onPress={() => Linking.openSettings()} />}
        <Btn testID="camera-back-button" kind="ghost" title="Back" onPress={() => router.back()} />
      </View>
    );
  return (
    <View testID="camera-screen" style={[st.root, { backgroundColor: "#000" }]}>
      <CameraView ref={cam} style={StyleSheet.absoluteFill} facing="back" />
      <View style={[st.top, { paddingTop: insets.top + 8 }]}>
        <Pressable testID="camera-done-button" onPress={() => router.back()} style={st.pill} hitSlop={8}>
          <Text style={st.pillText}>Done{count ? ` (${count})` : ""}</Text>
        </Pressable>
      </View>
      {prompt && supported ? (
        <View testID="volume-prompt" style={[st.prompt, { top: insets.top + 64 }]} pointerEvents="box-none">
          <Text style={st.promptTitle}>Take photos with your volume buttons</Text>
          <Text style={st.promptText}>Keep your thumb on either volume button and press it to take a photo. The shutter still works.</Text>
          <Pressable testID="volume-prompt-got-it" onPress={() => setPrompt(false)} style={st.gotIt}>
            <Text style={st.gotItText}>Got it</Text>
          </Pressable>
        </View>
      ) : null}
      {toast ? (
        <View testID={toast.ok ? "camera-saved-toast" : "camera-error-toast"} style={[st.toast, { backgroundColor: toast.ok ? "#14532D" : "#7F1D1D" }]}>
          <Text style={st.toastText}>{toast.text}</Text>
        </View>
      ) : null}
      <View style={[st.bottom, { paddingBottom: insets.bottom + 24 }]}>
        <Pressable testID="camera-shutter-button" accessibilityLabel="Take photo" onPress={() => shoot("shutter")} style={st.shutter}>
          <View style={st.shutterInner} />
        </Pressable>
      </View>
    </View>
  );
}

// Camera chrome stays the same in light and dark themes (white on live video), so literals are intentional here.
const st = StyleSheet.create({
  root: { flex: 1 },
  top: { position: "absolute", left: 0, right: 0, flexDirection: "row", justifyContent: "flex-end", paddingHorizontal: 16 },
  pill: { minHeight: 44, paddingHorizontal: 16, borderRadius: 22, backgroundColor: "rgba(0,0,0,0.55)", justifyContent: "center" },
  pillText: { color: "#fff", fontSize: 17, fontWeight: "600" },
  prompt: { position: "absolute", left: 16, right: 16, padding: 16, borderRadius: 16, backgroundColor: "rgba(17,24,39,0.92)", gap: 8 },
  promptTitle: { color: "#fff", fontSize: 20, fontWeight: "700" },
  promptText: { color: "#E5E7EB", fontSize: 17, lineHeight: 24 },
  gotIt: { alignSelf: "flex-start", minHeight: 56, minWidth: 120, paddingHorizontal: 20, borderRadius: 28, backgroundColor: "#fff", justifyContent: "center", alignItems: "center" },
  gotItText: { color: "#111", fontSize: 18, fontWeight: "700" },
  toast: { position: "absolute", left: 16, right: 16, bottom: 140, padding: 14, borderRadius: 12 },
  toastText: { color: "#fff", fontSize: 17, fontWeight: "600" },
  bottom: { position: "absolute", left: 0, right: 0, bottom: 0, alignItems: "center" },
  shutterInner: { width: 58, height: 58, borderRadius: 29, backgroundColor: "#fff", borderWidth: 2, borderColor: "#111" },
  shutter: { width: 78, height: 78, borderRadius: 39, backgroundColor: "#fff", borderWidth: 5, borderColor: "rgba(255,255,255,0.5)", justifyContent: "center", alignItems: "center" },
});
