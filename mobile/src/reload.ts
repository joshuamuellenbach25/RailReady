// Safe app reload (gear/Account -> Reload app). Stops background work, waits for pending local writes,
// writes settings.reload.* breadcrumbs BEFORE each native call, then reloads with a runtime-supported method.
// Fallback when native reload is unavailable/throws: re-mount the root tree and re-hydrate auth from storage.
import { reloadAppAsync } from "expo";
import { crumb, flushCrumbs } from "./crumbs";
import { isSyncing, pauseSync } from "./sync";

const remounters = new Set<() => void>();
export function onRemount(fn: () => void) {
  remounters.add(fn);
  return () => {
    remounters.delete(fn);
  };
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export async function safeReload() {
  await crumb("settings.reload.tap");
  pauseSync(true); // no new sync passes start
  const until = Date.now() + 8000;
  while (isSyncing() && Date.now() < until) await sleep(200); // let the in-flight pass finish its local writes
  await crumb("settings.reload.idle", isSyncing() ? "sync still running after 8s" : "idle");
  await Promise.race([flushCrumbs(), sleep(3000)]);
  try {
    await crumb("settings.reload.native");
    await reloadAppAsync("user reload");
  } catch (e: any) {
    await crumb("settings.reload.fallback", e?.message);
    pauseSync(false);
    remounters.forEach((f) => f());
  }
}
