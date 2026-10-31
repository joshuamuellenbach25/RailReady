// Photo-scene contract adapter (phase 4b). The backend is moving to /api/photo-scenes/*; the phase 4 routes stay as
// aliases. Everything here only moves and reshapes server data - no geometry, readiness or review logic is invented.
import { API, ApiError, api, getToken } from "./api";
import { absUrl } from "./scene";

const MAX_ASSET_BYTES = 16 * 1024 * 1024;
export const DEPTH_LABEL = "3D view is approximate. Use the photo for details.";

// ---- contract detection (re-polls openapi until the new routes appear) ----
let contract = { v: null, at: 0 };
export async function photoSceneContract() {
  if (contract.v === "v2" || Date.now() - contract.at < 30000) return contract.v || "legacy";
  try {
    const d = await (await fetch(`${API}/openapi.json`, { cache: "no-store" })).json();
    contract = { v: d.paths?.["/api/photo-scenes/{scene_id}"] ? "v2" : "legacy", at: Date.now() };
  } catch {
    contract = { v: contract.v || "legacy", at: Date.now() };
  }
  return contract.v;
}

// ---- normalization ----
const LEGACY_STATUS = { Ready: "ready", Queued: "queued", Processing: "processing", Failed: "failed", Unsupported: "unsupported", "Model unavailable": "failed" };
const num = (...xs) => xs.find((x) => typeof x === "number" && x > 0);

function fromLegacy(s, evidenceId) {
  const cam = s.camera || {};
  const p = s.projection || {};
  const regenerating = s.status === "Regenerating" || (!!s.regenerating && s.status === "Ready");
  const regenFailed = s.error_code === "regeneration_failed";
  const status = regenerating ? "ready" : LEGACY_STATUS[s.status] || String(s.status || "").toLowerCase();
  return {
    contract: "legacy",
    scene_id: s.scene_id,
    evidence_id: evidenceId,
    revision: s.scene_revision,
    is_current: s.is_current,
    regenerating,
    regen_failed: regenFailed,
    scene_hash: s.source_sha256,
    status,
    error: !regenFailed && !regenerating && (s.error || s.error_code) ? { code: s.error_code || (s.status === "Model unavailable" ? "model_unavailable" : s.status === "Unsupported" ? "unsupported_format" : null), message: s.error, retryable: s.status === "Failed" } : null,
    manifest: {
      camera: { position: cam.position, target: cam.target, fov: cam.fov_deg || p.assumed_fov_deg, fov_axis: p.fov_axis || "vertical" },
      width: s.sample_width, height: s.sample_height, oriented_width: s.oriented_width, oriented_height: s.oriented_height,
    },
    assets: {
      splat: s.asset_url ? { kind: "signed_url", url: absUrl(s.asset_url), byte_length: s.asset_bytes, expires_at: s.asset_url_expires_at } : null,
      original: s.original_url ? { kind: "signed_url", url: absUrl(s.original_url) } : null,
    },
    info: s, // provenance strip / footer read the raw record
  };
}

function fromV2(s) {
  const m = s.manifest || {};
  const cam = m.camera || {};
  const src = m.source || {};
  const err = s.error || null;
  return {
    contract: "v2",
    scene_id: s.scene_id,
    evidence_id: s.evidence_id,
    revision: s.revision,
    is_current: s.is_current,
    regenerating: !!s.regenerating,
    last_ready_scene_id: s.last_ready_scene_id,
    scene_hash: s.scene_hash,
    status: err?.code === "unsupported" ? "unsupported" : s.status,
    error: err,
    manifest: {
      ...m,
      camera: {
        position: cam.position, target: cam.target,
        fov: cam.fov_horizontal_deg ?? cam.fov ?? cam.fov_deg ?? m.settings?.fov_horizontal_deg,
        fov_axis: cam.fov_horizontal_deg != null ? "horizontal" : cam.fov_axis || "horizontal",
      },
      coordinate_system: cam.convention,
      width: num(cam.width, m.display?.width, m.width),
      height: num(cam.height, m.display?.height, m.height),
      oriented_width: num(src.oriented_width, m.oriented_width),
      oriented_height: num(src.oriented_height, m.oriented_height),
    },
    assets: s.assets || {},
    info: {
      ...s, scene_revision: s.revision, source_sha256: src.sha256, source_filename: src.filename, mode: "photo_derived_depth",
      model: { ...(m.model || {}), onnx_sha256: m.model?.sha256 },
      exif_transform: { exif_orientation: src.exif_orientation, raw: `${src.raw_width}x${src.raw_height}`, oriented: `${src.oriented_width}x${src.oriented_height}` },
      focal_pixels: cam.focal_px, depth_mode: m.depth?.mode, units: "arbitrary (relative)", gaussians: m.splat?.vertex_count,
    },
  };
}

// ---- scene loading: ensure (POST) -> job polling with backoff -> GET ----
export const TERMINAL = ["ready", "depth_uninformative", "failed", "unsupported"];

/** Returns {scene} or {job_id, status} (v2 202). Never regenerates a ready scene: the server returns it as-is. */
export async function ensureScene(evidenceId, signal) {
  if ((await photoSceneContract()) === "v2") {
    // 200 {status:"ready", scene_id, job_id, revision} or 202 job view; the descriptor is always read with GET.
    const r = await api(`/evidence/${evidenceId}/photo-scene`, { method: "POST", signal });
    if (r?.scene_id && TERMINAL.includes(r.status)) return { scene: { ...fromV2(await api(`/photo-scenes/${r.scene_id}`, { signal })), job_id: r.job_id } };
    if (TERMINAL.includes(r?.status)) return { scene: fromV2({ evidence_id: evidenceId, status: r.status, error: r.error }) };
    // A rebuild is running: show the last ready revision (explicitly labelled as previous) instead of an empty view.
    const list = await api(`/evidence/${evidenceId}/photo-scenes`, { signal }).catch(() => null);
    if (list?.last_ready_scene_id) {
      const prev = fromV2(await api(`/photo-scenes/${list.last_ready_scene_id}`, { signal }));
      if (prev.status === "ready") return { scene: { ...prev, job_id: r?.job_id, regenerating: true } };
    }
    return { job_id: r?.job_id, scene_id: r?.scene_id, status: r?.status || "queued", error: r?.error || null };
  }
  return { scene: fromLegacy(await api(`/evidence/${evidenceId}/scene`, { signal }), evidenceId) };
}

/** Re-read the descriptor (fresh asset URLs). GET only - never triggers generation. */
export async function getScene(scene, signal) {
  if (scene.contract === "v2") return fromV2(await api(`/photo-scenes/${scene.scene_id}`, { signal }));
  return fromLegacy(await api(`/evidence/${scene.evidence_id}/scene`, { signal }), scene.evidence_id);
}

export async function pollJob(job, evidenceId, signal) {
  if (job.job_id) {
    const j = await api(`/photo-scene-jobs/${job.job_id}`, { signal });
    const sid = j.scene_id || job.scene_id;
    if (TERMINAL.includes(j.status) && sid) return { scene: { ...fromV2(await api(`/photo-scenes/${sid}`, { signal })), job_id: job.job_id } };
    if (TERMINAL.includes(j.status)) return { scene: fromV2({ evidence_id: evidenceId, status: j.status, error: j.error }) };
    return { ...job, scene_id: sid, status: j.status, progress: j.progress, error: j.error || null };
  }
  return ensureScene(evidenceId, signal);
}

const BUSY = ["queued", "processing"];
const pendingOf = (s) => ({ status: s.status, revision: s.revision ?? null, failed: !BUSY.includes(s.status), error: s.error || null });

/**
 * GET-only check that the scene on screen is still the current one (never triggers generation).
 * -> {} still current - {next} a newer ready revision - {pending} a newer revision is being built / failed - {missing} shown scene gone.
 */
export async function checkScene(shown, signal) {
  if (shown.contract === "v2") {
    if (shown.job_id) {
      // Cheapest signal first: a rebuild can be queued before the server has created the new revision.
      const j = await api(`/photo-scene-jobs/${shown.job_id}`, { signal });
      if (j.error?.code === "blocked") return { pending: { status: "failed", revision: null, failed: true, error: j.error } };
      if (BUSY.includes(j.status)) return { pending: pendingOf(j) };
    }
    let d;
    try {
      d = await api(`/photo-scenes/${shown.scene_id}`, { signal });
    } catch (e) {
      if (e instanceof ApiError && (e.status === 404 || e.status === 410)) return { missing: true };
      throw e;
    }
    if (d.status !== "ready") return { missing: true };
    if (d.regenerating) return { pending: { status: "processing", revision: d.latest_revision ?? null, failed: false, error: null } };
    if (d.is_current === false && d.latest_scene_id && d.latest_scene_id !== shown.scene_id) {
      const l = fromV2(await api(`/photo-scenes/${d.latest_scene_id}`, { signal }));
      if (l.status === "ready") return { next: { ...l, job_id: shown.job_id } };
      // newest revision did not finish: show the newest *ready* one, still labelled as previous
      if (d.last_ready_scene_id && d.last_ready_scene_id !== shown.scene_id) return { next: { ...fromV2(await api(`/photo-scenes/${d.last_ready_scene_id}`, { signal })), job_id: shown.job_id } };
      return { pending: pendingOf(l) };
    }
    return {};
  }
  const l = fromLegacy(await api(`/evidence/${shown.evidence_id}/scene`, { signal }), shown.evidence_id);
  if (l.status === "ready" && l.revision !== shown.revision) return { next: l };
  if (l.regenerating) return { pending: { status: "processing", revision: null, failed: false, error: null } };
  if (l.regen_failed) return { pending: { status: "failed", revision: null, failed: true, error: { message: l.info?.error, retryable: true } } };
  if (l.status === "ready") return {};
  if (!l.scene_id) return { missing: true };
  return { pending: pendingOf(l) };
}

export async function retryScene(scene) {
  if (scene.contract === "v2") return api(`/evidence/${scene.evidence_id}/photo-scene`, { method: "POST" });
  return api(`/evidence/${scene.evidence_id}/scene/retry`, { method: "POST" });
}

// ---- anchors ----
const anchorFrom = (a, scene) =>
  a && {
    anchor_id: a.anchor_id || a.id || a.finding_id,
    finding_id: a.finding_id || a.item_id,
    version: a.version,
    u: a.u ?? a.image_point?.[0],
    v: a.v ?? a.image_point?.[1],
    xyz: a.xyz || a.position,
    placement: a.placement || a.placement_method,
    placement_method: a.placement_method,
    stale: a.stale,
    stale_reason: a.stale_reason,
    location_basis: a.location_basis,
    uncertainty: a.uncertainty,
    actor: a.actor,
    at: a.at || a.updated_at,
    scene_id: a.scene_id || scene?.scene_id,
    scene_revision: a.scene_revision ?? a.revision ?? scene?.revision,
  };

/** Map finding id -> anchor for this scene revision. v2 reads the scene's anchor list; legacy uses inventory-embedded anchors. */
export async function loadAnchors(scene, items) {
  const out = {};
  if (scene?.contract === "v2") {
    const r = await api(`/photo-scenes/${scene.scene_id}/anchors`);
    const list = Array.isArray(r) ? r : r?.anchors || r?.items || [];
    for (const a of list) out[a.finding_id || a.item_id] = anchorFrom(a, scene);
    for (const u of r?.unplaced || []) out[u.finding_id] = out[u.finding_id] || { unplaced: true, finding_id: u.finding_id, reason: u.reason };
    return out;
  }
  for (const it of items) if (it.anchor) out[it.item_id] = anchorFrom(it.anchor);
  return out;
}

/** v2: expected_version 0 creates the first anchor for an unplaced finding. The server computes xyz from that revision's depth. */
export function moveAnchor(scene, item, [u, v], reason) {
  const a = item.anchor;
  if (scene.contract === "v2") return api(`/photo-scenes/${scene.scene_id}/anchors/${item.item_id}`, { method: "PUT", body: { u, v, expected_version: a?.xyz ? a.version : 0, reason: reason || undefined } });
  return api(`/anchors/${a.anchor_id}`, { method: "PUT", body: { expected_version: a.version, image_point: [u, v], reason: reason || undefined } });
}

// ---- saved view (v2 only): {camera:{position,target,fov_deg}, selected_finding_id}, per user per scene revision ----
export const getView = (scene) => api(`/photo-scenes/${scene.scene_id}/view`);
export const putView = (scene, body) => api(`/photo-scenes/${scene.scene_id}/view`, { method: "PUT", body });

// ---- asset transport ----
const liveBlobs = new Set();
if (typeof window !== "undefined") window.__rrBlobUrls = liveBlobs; // V14 check: should be empty after teardown

export class AssetError extends Error {
  constructor(kind, status, message) {
    super(message);
    this.kind = kind; // "expired" | "denied" | "size" | "network" | "http"
    this.status = status;
  }
}

/**
 * signed_url -> used directly (pre-fetched so expiry is detectable, passed to the viewer as its contents);
 * authenticated_route -> fetched with the Bearer token into a Blob URL (0 < bytes <= 16 MiB). Caller must call dispose().
 */
export async function resolveSceneAsset(desc, signal) {
  if (!desc?.url) throw new AssetError("http", 0, "Scene asset not provided by the server.");
  const auth = desc.kind === "authenticated_route";
  const url = absUrl(desc.url);
  let res;
  try {
    res = await fetch(url, { signal, headers: auth && getToken() ? { Authorization: `Bearer ${getToken()}` } : {} });
  } catch (e) {
    if (e?.name === "AbortError") throw e;
    throw new AssetError("network", 0, "Could not download the scene asset (network).");
  }
  if (res.status === 401 || res.status === 403) {
    const body = await res.text().catch(() => "");
    if (/link_expired/.test(body)) throw new AssetError("expired", res.status, "The scene media link has expired.");
    throw new AssetError("denied", res.status, "Access to the scene media was refused.");
  }
  if (res.status === 410) throw new AssetError("expired", res.status, "The scene media link has expired.");
  if (res.status === 404) throw new AssetError("missing", res.status, "The 3D file was not found.");
  if (!res.ok) throw new AssetError("http", res.status, `Scene asset request failed (${res.status}).`);
  const len = Number(res.headers.get("content-length") || desc.byte_length || 0);
  if (len > MAX_ASSET_BYTES) throw new AssetError("size", res.status, `Scene asset too large (${len} bytes).`);
  if (!auth) return { url, contents: res, bytes: len, dispose: () => {} };
  const blob = await res.blob();
  if (!(blob.size > 0 && blob.size <= MAX_ASSET_BYTES)) throw new AssetError("size", res.status, `Scene asset size out of range (${blob.size} bytes).`);
  if (desc.byte_length && blob.size !== desc.byte_length) throw new AssetError("size", res.status, `Scene asset size mismatch (${blob.size} != ${desc.byte_length}).`);
  const blobUrl = URL.createObjectURL(blob);
  liveBlobs.add(blobUrl);
  return {
    url: blobUrl,
    bytes: blob.size,
    dispose: () => {
      if (liveBlobs.delete(blobUrl)) URL.revokeObjectURL(blobUrl);
    },
  };
}

export const isApiDenied = (e) => e instanceof ApiError && (e.status === 401 || e.status === 403);
