// Capture breadcrumbs (no media, no credentials): persisted locally BEFORE each native step so the last step
// reached survives a hard native crash; flushed to /api/diagnostics/breadcrumbs on next launch or right away when online.
import Constants from "expo-constants";
import { Platform } from "react-native";
import { API, getToken } from "./api";
import { uuid } from "./local/hash";
import { storage } from "./utils/storage";

const KEY = "rr_crumbs_v1";
const SESSION = uuid();
type Crumb = { step: string; at: string; detail?: string; session: string };

async function readAll(): Promise<Crumb[]> {
  try {
    return JSON.parse((await storage.getItem<string>(KEY, "[]")) || "[]");
  } catch {
    return [];
  }
}

export async function crumb(step: string, detail?: string) {
  const list = (await readAll()).slice(-150);
  list.push({ step, at: new Date().toISOString(), detail: detail?.slice(0, 200), session: SESSION });
  await storage.setItem(KEY, JSON.stringify(list));
}

export async function flushCrumbs() {
  const list = await readAll();
  if (!list.length) return;
  try {
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    const t = getToken();
    if (t) headers.Authorization = `Bearer ${t}`;
    const res = await fetch(`${API}/diagnostics/breadcrumbs`, {
      method: "POST", headers,
      body: JSON.stringify({
        platform: Platform.OS, os_version: String(Platform.Version), app_version: Constants.expoConfig?.version ?? null,
        sdk: Constants.expoConfig?.sdkVersion ?? null, expo_go: Constants.executionEnvironment === "storeClient", crumbs: list,
      }),
    });
    if (res.ok) await storage.setItem(KEY, "[]");
  } catch {
    // offline - keep for next launch
  }
}
