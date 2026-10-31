// Outbox sync: visit -> observations -> evidence (register, upload, server verify) -> manifest -> one receipt.
// Retries with exponential backoff; Sync now overrides the wait. Lost acks are safe: every call is idempotent by client UUID.
import { Platform } from "react-native";
import { ApiError, OfflineError, api, getToken, API } from "./api";
import { uploadForm } from "./utils/upload";
import { uploadFile } from "./background";
import { mediaUri } from "./local/db";
import * as repo from "./local/repo";
import type { LocalEvidence, LocalObs, LocalVisit, SyncInfo } from "./local/repo";

const listeners = new Set<() => void>();
export function subscribe(fn: () => void) {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}
const notify = () => listeners.forEach((f) => f());

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
    try { // Phase 15: replay-safe (server is keyed by the inspection; finished repairs accept identical replays)
      await api(`/repairs/${v.uuid}`, { method: "PUT", body: v.repair, sameKeyRetries: 1 });
      v = { ...v, repair_sync: "Verified" };
      await repo.saveVisit(u, v);
      notify();
    } catch {
      /* stays "Saved": retried on the next queue pass */
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
      if (v.status === "Submitted" && v.sync.state === "Verified" && !v.pending_permission) {
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
  } finally {
    running = false;
    notify();
  }
}
export const isSyncing = () => running;
