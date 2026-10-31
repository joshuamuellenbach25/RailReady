// Camera smoke test: each native step is a separate button with a persisted breadcrumb before/after,
// so the last step reached on a real phone is visible in /api/diagnostics/breadcrumbs even after a hard crash.
import { useState } from "react";
import { Platform } from "react-native";
import * as ImagePicker from "expo-image-picker";
import Constants from "expo-constants";
import { crumb, flushCrumbs } from "@/src/crumbs";
import { Banner, Btn, Card, H, Screen, T } from "@/src/ui";

export default function CameraSmoke() {
  const [log, setLog] = useState<string[]>([]);
  const add = (s: string) => setLog((l) => [...l, `${new Date().toLocaleTimeString()} ${s}`]);

  async function step(name: string, fn: () => Promise<any>) {
    await crumb(`smoke.${name}.before`);
    try {
      const r = await fn();
      const d = JSON.stringify(r)?.slice(0, 160);
      await crumb(`smoke.${name}.after`, d);
      add(`${name}: ${d}`);
    } catch (e: any) {
      await crumb(`smoke.${name}.error`, e?.message);
      add(`${name} ERROR: ${e?.message}`);
    }
    flushCrumbs();
  }
  const summary = (r: any) => (r && "assets" in r ? { canceled: r.canceled, n: r.assets?.length ?? 0, w: r.assets?.[0]?.width, h: r.assets?.[0]?.height, mime: r.assets?.[0]?.mimeType } : r);

  return (
    <Screen testID="camera-smoke-screen" title="Camera check" subtitle={`${Platform.OS} ${Platform.Version} - SDK ${Constants.expoConfig?.sdkVersion ?? "?"}`}>
      <Banner tone="info" icon="information" text="Tap the steps in order. If the app closes, reopen it - the last step reached is sent automatically. No photos are uploaded." />
      <Card>
        <H>Steps</H>
        <Btn testID="smoke-get-permission" kind="secondary" title="1. Check camera permission" onPress={() => step("get_permission", () => ImagePicker.getCameraPermissionsAsync())} />
        <Btn testID="smoke-request-permission" kind="secondary" title="2. Ask for camera permission" onPress={() => step("request_permission", () => ImagePicker.requestCameraPermissionsAsync())} />
        <Btn testID="smoke-open-camera" title="3. Open camera (no options)" onPress={() => step("launch_camera_default", async () => summary(await ImagePicker.launchCameraAsync()))} />
        <Btn testID="smoke-open-camera-images" kind="secondary" title="4. Open camera (photos, quality 0.8)" onPress={() => step("launch_camera_images", async () => summary(await ImagePicker.launchCameraAsync({ mediaTypes: ["images"], quality: 0.8, exif: false, base64: false })))} />
        <Btn testID="smoke-open-library" kind="secondary" title="5. Open photo library" onPress={() => step("launch_library", async () => summary(await ImagePicker.launchImageLibraryAsync({ mediaTypes: ["images"], quality: 0.8 })))} />
        <Btn testID="smoke-send" kind="secondary" title="Send check results" onPress={() => flushCrumbs().then(() => add("sent"))} />
      </Card>
      <Card testID="smoke-log">
        {log.length ? log.map((l, i) => <T key={i} size={13}>{l}</T>) : <T muted>No steps run yet.</T>}
      </Card>
    </Screen>
  );
}
