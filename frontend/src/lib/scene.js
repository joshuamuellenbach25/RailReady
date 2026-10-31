// Scene workspace API (phase 4 contract). Display only - no geometry is invented here.
import { BACKEND, api, withAuth } from "./api";

export const sceneApi = {
  list: (visitId) => api(`/visits/${visitId}/scenes`),
  scene: (evidenceId) => api(`/evidence/${evidenceId}/scene`),
  retry: (evidenceId) => api(`/evidence/${evidenceId}/scene/retry`, { method: "POST" }),
  inventory: (visitId, evidenceId, includeReview = false, signal) => api(`/visits/${visitId}/inventory?evidence_id=${encodeURIComponent(evidenceId)}${includeReview ? "&include_review=true" : ""}`, { signal }),
  moveAnchor: (anchorId, body) => api(`/anchors/${anchorId}`, { method: "PUT", body }),
};

// Signed URLs may come back absolute or as /api/... paths. Auth-only paths (crop) get ?auth= like other media.
export const absUrl = (u) => (!u ? null : /^https?:|^data:|^blob:/.test(u) ? u : `${BACKEND}${u.startsWith("/") ? "" : "/"}${u}`);
export const cropUrl = (itemId) => withAuth(`/inventory-items/${itemId}/crop`);

export function contentFilename(scene) {
  if (scene.asset_filename) return scene.asset_filename;
  try {
    const last = new URL(absUrl(scene.asset_url)).pathname.split("/").pop();
    if (/\.(ply|sog|splat|ksplat|spz|gsaf|json)$/i.test(last)) return last;
  } catch {
    /* fall through */
  }
  return "scene.ply";
}

let glOk = null;
export function webglAvailable() {
  if (glOk !== null) return glOk;
  try {
    const c = document.createElement("canvas");
    const gl = c.getContext("webgl2") || c.getContext("webgl");
    glOk = !!gl;
    gl?.getExtension("WEBGL_lose_context")?.loseContext(); // do not keep a probe context alive
  } catch {
    glOk = false;
  }
  return glOk;
}

// An anchor is only drawn on the exact scene + revision it was authored on (never transferred between photos).
export const isPlaced = (it, scene) =>
  !!(it.located && it.anchor?.xyz && scene?.scene_id && it.anchor.scene_id === scene.scene_id && it.anchor.scene_revision === scene.scene_revision);

export function unplacedReason(it, scene) {
  if (isPlaced(it, scene)) return null;
  if (it.anchor && scene && (it.anchor.scene_id !== scene.scene_id || it.anchor.scene_revision !== scene.scene_revision)) return `Anchor belongs to scene revision ${it.anchor.scene_revision}, not the current one`;
  return it.unplaced_reason || (Array.isArray(it.region) ? "No anchor placed yet" : "No image region. It could not be located in the photo.");
}

export const SCENE_STATUS_TEXT = {
  Queued: "Scene queued for depth estimation",
  Processing: "Estimating depth from this photo...",
  Failed: "Scene generation failed",
  Unsupported: "This photo format is not supported. Open the original or upload a JPEG or PNG.",
  "Model unavailable": "Depth model unavailable",
};

export const isPlanar = (scene) => !!scene && scene.mode && scene.mode !== "photo_derived_depth";
