// Outbox sync: visit -> observations -> evidence (register, upload, server verify) -> manifest -> one receipt.
// Retries with exponential backoff; Sync now overrides the wait. Lost acks are safe: every call is idempotent by client UUID.
import { Platform } from "react-native";
import { ApiError, OfflineError, api, getToken, API } from "./api";
import { uploadForm } from "./utils/upload";
import { uploadFile } from "./background";
import { mediaUri, getRecord, createRecordsOnce } from "./local/db";
import * as repo from "./local/repo";
import { storage } from "./utils/storage";
import type { LocalEvidence, LocalObs, LocalVisit, SyncInfo } from "./local/repo";

const listeners = new Set<() => void>();
export function subscribe(fn: () => void) {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}
const notify = () => listeners.forEach((f) => f());
const syncErrors = new Map<string, string>();
export const getSyncError = (u: string): string | null => syncErrors.get(u) || null;

let running = false;

function backoff(s: SyncInfo, e: unknown): SyncInfo {
  const attempts = s.attempts + 1;
  if (e instanceof ApiError && e.status === 401) {
    // Sign-in expired: keep the draft intact and retry after the user signs in again (never Blocked).
    return { state: "Retry wait", attempts, next_at: new Date(Date.now() + 60_000).toISOString(), error: "Sign in again to sync - your captures are kept on this device" };
  }
  if (e instanceof ApiError && e.status >= 400 && e.status < 500 && e.status !== 408 && e.status !== 429) {
    return { state: "Blocked", attempts, error: errMsg(e) };
  }
  const waitMs = Math.min(5 * 60_000, 5_000 * 2 ** Math.min(attempts, 6));
  return { state: "Retry wait", attempts, next_at: new Date(Date.now() + waitMs).toISOString(), error: errMsg(e) };
}
function errMsg(e: unknown) {
  if (e instanceof OfflineError) return "Offline";
  if (e instanceof ApiError) return typeof e.detail === "string" ? e.detail : e.detail?.message || `HTTP ${e.status}`;
  return (e as Error)?.message || "Could not send. Retry";
}
const due = (s: SyncInfo, force: boolean) =>
  s.state !== "Verified" && (force || s.state !== "Blocked") && (force || !s.next_at || s.next_at <= new Date().toISOString());

async function syncVisitRecord(u: string, v: LocalVisit, force: boolean): Promise<LocalVisit> {
  if (v.sync.state !== "Verified" && due(v.sync, force)) {
    try {
      const sv = await api(`/visits`, { body: { uuid: v.uuid, site_id: v.site_id, title: v.title, processing_permission: v.processing_permission, started_at: v.created_at }, sameKeyRetries: 1 });
      v = { ...v, server_revision: sv.revision, status: sv.status, sync: { state: "Verified", attempts: v.sync.attempts + 1 } };
    } catch (e) {
      v = { ...v, sync: backoff(v.sync, e) };
    }
    await repo.saveVisit(u, v);
    notify();
  }
  if (v.sync.state === "Verified" && v.pending_permission) {
    try {
      const sv = await api(`/visits/${v.uuid}`, { method: "PATCH", body: { expected_revision: v.server_revision, processing_permission: v.pending_permission } });
      v = { ...v, processing_permission: sv.processing_permission, server_revision: sv.revision, pending_permission: null };
    } catch (e) {
      if (e instanceof ApiError && e.status === 409 && e.detail?.server) {
        await repo.saveRecovery(u, { visit_id: v.uuid, what: "Processing permission", value: v.pending_permission || "", server_value: e.detail.server.processing_permission });
        v = { ...v, processing_permission: e.detail.server.processing_permission, server_revision: e.detail.server.revision, pending_permission: null };
      }
    }
    await repo.saveVisit(u, v);
    notify();
  }
  if (v.sync.state === "Verified" && v.repair && v.repair_sync !== "Verified") {
    const pendingRepair = v.repair;
    try { // Phase 15: replay-safe (server is keyed by the inspection; finished repairs accept identical replays)
      await api(`/repairs/${v.uuid}`, { method: "PUT", body: pendingRepair, sameKeyRetries: 1 });
      v = { ...v, repair_sync: "Verified", repair_finish_blockers: pendingRepair.finish ? undefined : v.repair_finish_blockers };
      await repo.saveVisit(u, v);
      notify();
    } catch (e) {
      if (e instanceof ApiError && e.status === 409 && e.detail?.code === "finish_blocked") {
        // The server did not record completion. Keep the work and let the foreman correct this draft.
        await repo.saveRecovery(u, { visit_id: v.uuid, what: "Finish repair rejected", value: JSON.stringify(pendingRepair),
          server_value: JSON.stringify(e.detail.blockers || []) });
        const op = e.detail.operator;
        v = { ...v, repair: { ...pendingRepair, finish: false, finished_at_client: null }, repair_sync: "Saved",
          repair_finish_blockers: e.detail.blockers || [e.detail.message],
          ...(op?.uuid ? { repair_requirements: { operator_id: op.uuid, fields: op.required_location_fields || [], name: op.name } } : {}) };
        await repo.saveVisit(u, v);
        notify();
      }
      // Network failures keep the pending completion intact for the next queue pass.
    }
  }
  return v;
}

async function syncObs(u: string, o: LocalObs) {
  try {
    const { sync, visit_id, ...body } = o;
    await api(`/visits/${visit_id}/observations`, { body, sameKeyRetries: 1 }); // uuid-keyed: a resend is the same operation
    o = { ...o, sync: { state: "Verified", attempts: sync.attempts + 1 } };
  } catch (e) {
    o = { ...o, sync: backoff(o.sync, e) };
  }
  await repo.saveObs(u, o);
  notify();
}

async function setEv(u: string, e: LocalEvidence, sync: Partial<SyncInfo> & { state: SyncInfo["state"] }) {
  e.sync = { attempts: e.sync.attempts, ...sync };
  await repo.saveEvidence(u, e);
  notify();
}

async function syncEvidence(u: string, e: LocalEvidence) {
  try {
    await setEv(u, e, { state: "Uploading" });
    const reg = await api(`/visits/${e.visit_id}/evidence`, {
      body: { uuid: e.uuid, kind: e.kind, sha256: e.sha256, size: e.size, mime: e.mime, filename: e.filename, captured_at: e.captured_at, text: e.text },
    });
    let state = reg.upload_state;
    if (e.kind !== "note" && state !== "Verified") {
      if (state !== "Uploaded unverified") {
        const uri = await mediaUri(u, e.path!);
        // C3: bounded upload (deadline scales with size, max 10 min); a stall aborts, releases the sync lock and retries later
        // with the SAME evidence uuid (server upload is idempotent by uuid + sha256), so a retry never duplicates the photo.
        const ctl = new AbortController();
        const timer = setTimeout(() => ctl.abort(), Math.min(600_000, 60_000 + ((e as any).size || 0) / 50));
        let res: { ok: boolean; status: number; body: string };
        try {
          // iOS dev/prod builds: OS background session; Expo Go, web, Android: existing multipart fetch
          res = await uploadFile(`${API}/evidence/${e.uuid}/content`, uri, e.mime, e.filename, ctl.signal, () => uploadForm(`${API}/evidence/${e.uuid}/content`, {
            method: "PUT",
            files: { file: { uri, name: e.filename, mimeType: e.mime } },
            headers: { Authorization: `Bearer ${getToken()}` },
            signal: ctl.signal,
          }));
        } catch {
          throw new OfflineError(ctl.signal.aborted ? "Could not send photo. Retry" : "offline");
        } finally {
          clearTimeout(timer);
        }
        if (!res.ok) throw new ApiError(res.status, (() => { try { return JSON.parse(res.body)?.detail; } catch { return null; } })() || "Upload failed");
        await setEv(u, e, { state: "Uploaded unverified" });
      }
      const ver = await api(`/evidence/${e.uuid}/verify`, { method: "POST", sameKeyRetries: 1 });
      state = ver.upload_state;
    }
    if (state === "Verified") await setEv(u, e, { state: "Verified", attempts: e.sync.attempts + 1 });
    else if (state === "Hash mismatch") await setEv(u, e, { state: "Blocked", attempts: e.sync.attempts + 1, error: "The file changed while sending. It is kept on this phone. Tap Retry." });
    else if (state === "Rejected") await setEv(u, e, { state: "Blocked", attempts: e.sync.attempts + 1, error: (await api(`/evidence/${e.uuid}/content-info`).catch(() => null))?.reject_reason || "The server refused this file. It is kept on this phone." });
    else await setEv(u, e, { state: "Uploaded unverified", attempts: e.sync.attempts + 1 });
  } catch (err) {
    await setEv(u, e, backoff(e.sync, err));
  }
}

async function finalizeManifest(u: string, v: LocalVisit) {
  const ev = await repo.listEvidence(u, v.uuid);
  if (!ev.length) return v;
  const members = ev.map((e) => ({ evidence_id: e.uuid, sha256: e.sha256, size: e.size }));
  try {
    const m = await api(`/visits/${v.uuid}/manifests`, { body: { members, device_id: Platform.OS } });
    v = { ...v, manifest: { uuid: m.uuid, state: m.state, receipt_id: m.receipt_id, missing: m.missing?.length || 0 } };
    await repo.saveVisit(u, v);
    notify();
  } catch {
    /* manifest retried next sync */
  }
  return v;
}

async function syncSites(u: string, force: boolean) {
  for (const s of await repo.listLocalSites(u)) {
    if (s.sync.state === "Verified" || !due(s.sync, force)) continue;
    try {
      // stable client uuid = idempotency key: a retry after a timeout returns the same site, never a second one
      await api("/sites", { body: { uuid: s.uuid, name: s.name, address: s.address, description: s.description, lat: s.lat, lon: s.lon,
        location_accuracy_m: s.location_accuracy_m }, sameKeyRetries: 1 });
      await repo.saveLocalSite(u, { ...s, sync: { state: "Verified", attempts: s.sync.attempts + 1 } });
      await repo.saveBundle(u, s.uuid, await api(`/sites/${s.uuid}/bundle`)).catch(() => null);
    } catch (e) {
      await repo.saveLocalSite(u, { ...s, sync: backoff(s.sync, e) });
    }
    notify();
  }
}

let paused = false;
let startedAt = 0;

// Phase 16: pending map locations. Sent only after their site AND inspection are on the server; the server is idempotent by pin uuid.
// Lists left by the earlier map-screen-only flush (pending-pins:<user>) are moved into the queue once.
async function syncPins(u: string, force: boolean) {
  const legacy = await storage.getItem<string | null>(`pending-pins:${u}`, null);
  syncErrors.delete(u);
  if (legacy) {
    try {
      const list = JSON.parse(legacy);
      if (!Array.isArray(list) || list.some((p) => !p || typeof p !== "object" || Array.isArray(p)
        || ![p.uuid, p.visit_id, p.site_id].every((v) => typeof v === "string" && v.trim())
        || !Number.isFinite(p.lat) || !Number.isFinite(p.lon) || Math.abs(p.lat) > 90 || Math.abs(p.lon) > 180)) {
        throw new Error("Invalid saved location data.");
      }
      // Validate the whole source first. Atomic insert-if-absent preserves any pin
      // that has already synced, including a concurrent migration in another tab.
      for (const p of list) {
        const pin: repo.LocalPin = { id: `pinrec-${p.uuid}`, visit_id: p.visit_id, payload: { fixed_at: null, ...p },
          created_at: new Date().toISOString(), sync: { state: "Queued", attempts: 0 } };
        await createRecordsOnce<repo.LocalPin>(u, pin.id, [{ type: "pin", id: pin.id, parent: pin.visit_id, data: pin }]);
      }
      // Retain the legacy source as a recovery copy. Removing an async-storage key
      // can erase a new value written by an older app/tab while migration awaits.
    } catch {
      syncErrors.set(u, "Some saved locations could not sync. The original location data is kept on this device.");
    }
    notify();
  }
  for (const p of await repo.listPins(u)) {
    if (p.sync.state === "Verified" || !due(p.sync, force)) continue;
    const site = await getRecord<repo.LocalSite>(u, p.payload.site_id);
    const visit = await repo.getLocalVisit(u, p.payload.visit_id);
    if ((site && site.sync.state !== "Verified") || !visit || visit.sync.state !== "Verified") continue; // dependencies first
    try {
      await api("/map/pins", { body: p.payload, sameKeyRetries: 1 });
      await repo.savePin(u, { ...p, sync: { state: "Verified", attempts: p.sync.attempts + 1 } });
    } catch (e) {
      // 409 not_synced = the server has not got the inspection yet: wait and retry, never Blocked
      const s = e instanceof ApiError && e.status === 409 ? { state: "Retry wait" as const, attempts: p.sync.attempts + 1, next_at: new Date(Date.now() + 5_000).toISOString(), error: "Waiting for the inspection to send" } : backoff(p.sync, e);
      await repo.savePin(u, { ...p, sync: s });
    }
    notify();
  }
}

export function pauseSync(p: boolean) {
  paused = p;
}

export async function syncAll(u: string, force = false) {
  // single worker lock with expiry (REQ-1213): a pass stuck > 10 min no longer blocks the queue
  if (paused || (running && Date.now() - startedAt < 600_000)) return;
  running = true;
  startedAt = Date.now();
  notify();
  try {
    await syncSites(u, force); // new sites first, so their inspections can be sent
    for (let v of await repo.listVisits(u)) {
      if (v.status === "Submitted" && v.sync.state === "Verified" && !v.pending_permission && (!v.repair || v.repair_sync === "Verified")) {
        // REQ-1207: a status change never strands captured evidence - still send anything pending
        if (!(await repo.listEvidence(u, v.uuid)).some((e) => e.sync.state !== "Verified")) continue;
      }
      v = await syncVisitRecord(u, v, force);
      if (v.sync.state !== "Verified") continue;
      for (const o of await repo.listObs(u, v.uuid)) if (due(o.sync, force)) await syncObs(u, o).catch(() => {});
      let changed = false;
      for (const e of await repo.listEvidence(u, v.uuid))
        if (due(e.sync, force)) {
          await syncEvidence(u, e).catch(() => {}); // REQ-1215: one stalled/rejected item never stops the others
          changed = true;
        }
      // receipts are kept per inspection but no longer gate analysis (the server queues each verified item)
      if (changed || !v.manifest || v.manifest.state !== "Received complete") await finalizeManifest(u, v).catch(() => {});
    }
    await syncPins(u, force).catch(() => {}); // after sites and inspections
  } finally {
    running = false;
    notify();
  }
}
export const isSyncing = () => running;
