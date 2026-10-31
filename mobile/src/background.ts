// Background sending (Phase 12 item 4). Inspected for SDK 58:
// - expo-file-system UploadTask with sessionType "background" (iOS): the native transfer can continue while the app is
//   suspended. The JS task is NOT restored after termination, so the durable queue re-sends the same evidence uuid
//   (idempotent server side) on the next run. Android ignores sessionType (foreground transfer).
// - expo-background-task: OS-scheduled runs (iOS BGTaskScheduler, Android WorkManager), at least ~15 min apart, at the
//   OS's discretion. Only in dev/production builds; Expo Go and web: unsupported (reported, nothing registered).
// "Sent" is only ever shown after the server's verify returns Verified (sync.ts), never on transfer completion.
import Constants, { ExecutionEnvironment } from "expo-constants";
import { Platform } from "react-native";
import { getToken, setToken } from "./api";
import { crumb } from "./crumbs";
import { storage } from "./utils/storage";

export const BG_TASK = "railready-send-queue";
export const isExpoGo = Constants.executionEnvironment === ExecutionEnvironment.StoreClient;
export const bgSupported = Platform.OS !== "web" && !isExpoGo;

export function backgroundStatus(): { upload: string; task: string } {
  if (Platform.OS === "web") return { upload: "unsupported (web)", task: "unsupported (web)" };
  if (isExpoGo) return { upload: "unsupported (Expo Go)", task: "unsupported (Expo Go)" };
  return { upload: Platform.OS === "ios" ? "iOS background session" : "foreground only (Android ignores sessionType)", task: "OS-scheduled" };
}

/** Upload one file. iOS dev/prod builds use a background URLSession; everything else uses the existing multipart fetch. */
export async function uploadFile(url: string, uri: string, mime: string, name: string, signal: AbortSignal,
  fallback: () => Promise<Response>): Promise<{ ok: boolean; status: number; body: string }> {
  if (Platform.OS === "ios" && bgSupported) {
    const FS = await import("expo-file-system");
    const task = new FS.UploadTask(new FS.File(uri), url, {
      httpMethod: "PUT", uploadType: FS.UploadType.MULTIPART, fieldName: "file", mimeType: mime,
      headers: { Authorization: `Bearer ${getToken()}` }, sessionType: "background", signal,
    });
    const r = await task.uploadAsync();
    return { ok: r.status >= 200 && r.status < 300, status: r.status, body: r.body };
  }
  const res = await fallback();
  return { ok: res.ok, status: res.status, body: await res.text().catch(() => "") };
}

/** Register the OS-scheduled queue run (dev/prod builds only). Safe to call on every launch. */
export async function registerBackgroundSend() {
  if (!bgSupported || !TM || !BT) return crumb("bg.register", backgroundStatus().task);
  try {
    if ((await BT.getStatusAsync()) === BT.BackgroundTaskStatus.Available && !(await TM.isTaskRegisteredAsync(BG_TASK))) {
      await BT.registerTaskAsync(BG_TASK, { minimumInterval: 15 });
    }
    await crumb("bg.register", "registered");
  } catch (e: any) {
    await crumb("bg.register_failed", e?.message);
  }
}

// The task must be defined at module scope so a headless (app not open) OS launch finds it. Imported from app/_layout.tsx.
// eslint-disable-next-line @typescript-eslint/no-require-imports
const TM: any = bgSupported ? (() => { try { return require("expo-task-manager"); } catch { return null; } })() : null;
// eslint-disable-next-line @typescript-eslint/no-require-imports
const BT: any = bgSupported ? (() => { try { return require("expo-background-task"); } catch { return null; } })() : null;
if (TM && BT && !TM.isTaskDefined(BG_TASK)) {
  TM.defineTask(BG_TASK, async () => {
    try {
      // owner-bound: only the account signed in on this phone; no token -> nothing is sent
      const t = await storage.secureGet("auth_token", null);
      const cached = await storage.getItem<string | null>("auth_user", null);
      const uid = cached ? JSON.parse(cached)?.user?.uuid : null;
      if (!t || !uid) return BT.BackgroundTaskResult.Success;
      setToken(String(t));
      // eslint-disable-next-line @typescript-eslint/no-require-imports
      await require("./sync").syncAll(uid);
      await crumb("bg.run", "done");
      return BT.BackgroundTaskResult.Success;
    } catch (e: any) {
      await crumb("bg.run_failed", e?.message);
      return BT.BackgroundTaskResult.Failed;
    }
  });
}
