// Phase 12 send queue (REQ-1208..1213, 1218): runs from the root (home AND inspection screens), on launch, sign-in restore,
// foreground, connectivity regain and a periodic timer with bounded exponential backoff. "Online" = a successful
// backend health check (not Wi-Fi state). Items belong to the signed-in owner: syncAll(uid) only touches that uid's store.
import NetInfo from "@react-native-community/netinfo";
import { useEffect, useRef } from "react";
import { AppState } from "react-native";
import { api } from "./api";
import { useAuth } from "./auth";
import { crumb } from "./crumbs";
import { syncAll } from "./sync";
import { registerBackgroundSend } from "./background";
import * as repo from "./local/repo";
import { storage } from "./utils/storage";

let online: boolean | null = null;
const listeners = new Set<(o: boolean | null) => void>();
export const isOnline = () => online;
export function onOnline(fn: (o: boolean | null) => void) {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}

export async function healthCheck(): Promise<boolean> {
  try {
    await api("/health", { timeoutMs: 5000 });
    online = true;
  } catch {
    online = false;
  }
  listeners.forEach((f) => f(online));
  return online;
}

// Cached site bundles can hold display copy from before the no-metacommentary migration: refetch every cached bundle
// once per user per copy version (after a successful health check), then mark it done on this device.
const COPY_VERSION = "copy-v2";
async function refreshDisplayCopy(uid: string) {
  const key = `display-copy:${uid}`;
  if ((await storage.getItem<string | null>(key, null)) === COPY_VERSION) return;
  try {
    for (const b of await repo.listBundles(uid)) {
      if ((b.data as any)?.local_only) continue;
      const sid = (b.data as any)?.site?.uuid;
      if (sid) await repo.saveBundle(uid, sid, await api(`/sites/${sid}/bundle`, { timeoutMs: 10000 }));
    }
    await storage.setItem(key, COPY_VERSION);
  } catch {
    // try again on the next queue pass
  }
}

export function SendQueue() {
  const { user } = useAuth();
  const uid = user ? user.uuid : null;
  const backoff = useRef(15_000);
  useEffect(() => {
    if (!uid) return;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let stopped = false;
    const run = async (why: string) => {
      if (stopped) return;
      if (!(await healthCheck())) {
        backoff.current = Math.min(backoff.current * 2, 300_000); // bounded backoff while unreachable
        return;
      }
      backoff.current = 15_000;
      await crumb("queue.run", why);
      await refreshDisplayCopy(uid);
      await syncAll(uid).catch(() => {});
    };
    const loop = () => {
      timer = setTimeout(async () => {
        await run("timer");
        if (!stopped) loop();
      }, backoff.current);
    };
    run("launch_or_signin"); // one trigger for launch / sign-in restore (uid became available)
    registerBackgroundSend(); // dev/prod builds: OS-scheduled sends; Expo Go/web: records "unsupported"
    loop();
    const a = AppState.addEventListener("change", (st) => st === "active" && run("foreground"));
    let wasConnected: boolean | null = null;
    const n = NetInfo.addEventListener((s) => {
      const c = !!s.isConnected;
      if (c && wasConnected === false) run("connectivity_regained");
      wasConnected = c;
    });
    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
      a.remove();
      n();
    };
  }, [uid]);
  return null;
}
