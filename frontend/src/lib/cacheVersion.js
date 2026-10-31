// Client cache version. Bump CACHE_VERSION whenever cached display data (user, workspace names, labels) must be
// dropped. Imported first in index.js so it runs before anything reads localStorage.
// Kept: rr_token (sign-in, no labels) and rr_demo (session id for Reset demo). Idempotency keys (rr_analyze_*) are kept
// so an in-flight photo check is never started twice.
export const CACHE_VERSION = "2026-10-25-copy-cleanup";
const VERSION_KEY = "rr_cache_version";
const KEEP = new Set(["rr_token", "rr_demo", VERSION_KEY]);

function purge() {
  try {
    if (localStorage.getItem(VERSION_KEY) === CACHE_VERSION) return;
    Object.keys(localStorage).filter((k) => k.startsWith("rr_") && !KEEP.has(k)).forEach((k) => localStorage.removeItem(k));
    Object.keys(sessionStorage).filter((k) => k.startsWith("rr_scene_")).forEach((k) => sessionStorage.removeItem(k));
    localStorage.setItem(VERSION_KEY, CACHE_VERSION);
  } catch {
    // storage blocked (private mode): nothing cached to clear
  }
  // This app registers no service worker. Remove any left from an earlier build, with their caches.
  navigator.serviceWorker?.getRegistrations?.().then((rs) => rs.forEach((r) => r.unregister())).catch(() => {});
  window.caches?.keys?.().then((ks) => ks.forEach((k) => window.caches.delete(k))).catch(() => {});
}

purge();
