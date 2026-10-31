// Local domain records (device-first). Every record is committed before the UI says "Saved on this device".
import { getRecord, listRecords, putRecord, saveMedia } from "./db";
import { sha256Hex, utf8, uuid } from "./hash";

export type SyncState = "Queued" | "Uploading" | "Uploaded unverified" | "Verified" | "Retry wait" | "Blocked";
export type SyncInfo = { state: SyncState; attempts: number; next_at?: string | null; error?: string | null };
export type Permission = "Granted" | "Denied" | "Unknown" | "Policy";

export type LocalVisit = {
  uuid: string;
  site_id: string;
  site_name: string;
  title: string;
  processing_permission: Permission;
  server_revision: number | null;
  status: "Draft" | "Submitted";
  created_at: string;
  pending_permission?: Permission | null;
  manifest?: { uuid: string; state: string; receipt_id: string | null; missing: number } | null;
  repair?: LocalRepair | null; // Phase 15: authorized repair (no proposal/acceptance step)
  repair_sync?: "Saved" | "Verified";
  sync: SyncInfo;
};
export type WorkItem = { uuid: string; kind: "work" | "material" | "labor" | "equipment"; description: string; quantity: string; unit: string; rate_key?: string | null };
export type LocalRepair = {
  operator_id: string | null; operator_name: string | null; po: string | null; railroad: string | null; track: string | null; milepost: string | null;
  work: WorkItem[]; completion_date: string | null; finish: boolean; finished_at_client: string | null;
};
export type LocalEvidence = {
  uuid: string;
  visit_id: string;
  kind: "photo" | "audio" | "note" | "video";
  mime: string;
  filename: string;
  path?: string;
  text?: string;
  sha256: string;
  size: number;
  captured_at: string;
  duration_s?: number;
  sync: SyncInfo;
};
export type LocalObs = {
  uuid: string;
  visit_id: string;
  kind: "measurement" | "location" | "not_inspected" | "finding";
  label?: string;
  value?: string;
  unit?: string;
  text?: string;
  area?: string;
  reason?: string;
  captured_at: string;
  sync: SyncInfo;
};
export type Bundle = { site_id: string; prepared_at: string; data: any };
export type Recovery = { id: string; visit_id: string; what: string; value: string; server_value: string; at: string };

const queued = (): SyncInfo => ({ state: "Queued", attempts: 0 });
const now = () => new Date().toISOString();

// + New site (offline-first): saved locally first with a stable client id, shown at once, sent by the queue.
export type LocalSite = { uuid: string; name: string; address?: string | null; description?: string | null; lat?: number | null; lon?: number | null;
  location_accuracy_m?: number | null; created_at: string; sync: SyncInfo };

export async function createSite(u: string, s: Pick<LocalSite, "name" | "address" | "description" | "lat" | "lon" | "location_accuracy_m">): Promise<LocalSite> {
  const site: LocalSite = { uuid: uuid(), ...s, created_at: now(), sync: queued() };
  await putRecord(u, "site", site.uuid, null, site);
  // local bundle so the site opens and inspections can start offline; fields come from any cached bundle
  const any = (await listRecords<Bundle>(u, "bundle"))[0];
  await saveBundle(u, site.uuid, { site: { uuid: site.uuid, name: site.name, address: site.address, revision: 0, prior_findings: [] }, customer: null,
    tracks: [], fields: any?.data?.fields || [], generated_at: now(), bundle_version: "local", local_only: true });
  const back = await getRecord<LocalSite>(u, site.uuid); // read-back before we say it is saved
  if (!back) throw new Error("Site not saved on this phone. Try again.");
  return back;
}
export const listLocalSites = (u: string) => listRecords<LocalSite>(u, "site");
export const saveLocalSite = (u: string, s: LocalSite) => putRecord(u, "site", s.uuid, null, s);

export async function saveBundle(userId: string, siteId: string, data: any): Promise<Bundle> {
  const b = { site_id: siteId, prepared_at: now(), data };
  await putRecord(userId, "bundle", `bundle-${siteId}`, null, b);
  const back = await getRecord<Bundle>(userId, `bundle-${siteId}`); // confirm commit
  if (!back || back.data.bundle_hash !== data.bundle_hash) throw new Error("Bundle not committed");
  return back;
}
export const getBundle = (u: string, siteId: string) => getRecord<Bundle>(u, `bundle-${siteId}`);
export const listBundles = (u: string) => listRecords<Bundle>(u, "bundle");

export async function createVisit(u: string, siteId: string, siteName: string, title: string): Promise<LocalVisit> {
  const v: LocalVisit = {
    uuid: uuid(), site_id: siteId, site_name: siteName, title, processing_permission: "Policy",
    server_revision: null, status: "Draft", created_at: now(), sync: queued(),
  };
  await putRecord(u, "visit", v.uuid, siteId, v);
  return v;
}
export const listVisits = (u: string) => listRecords<LocalVisit>(u, "visit");
export const getLocalVisit = (u: string, id: string) => getRecord<LocalVisit>(u, id);
export async function saveVisit(u: string, v: LocalVisit) {
  await putRecord(u, "visit", v.uuid, v.site_id, v);
}

export async function addMedia(u: string, visitId: string, kind: "photo" | "audio" | "video", srcUri: string, mime: string, ext: string, duration_s?: number) {
  const id = uuid();
  const saved = await saveMedia(u, id, srcUri, ext);
  const ev: LocalEvidence = {
    uuid: id, visit_id: visitId, kind, mime, filename: `${kind}-${id.slice(0, 8)}.${ext}`, path: saved.path,
    sha256: saved.sha256, size: saved.size, captured_at: now(), duration_s, sync: queued(),
  };
  await putRecord(u, "evidence", id, visitId, ev);
  const back = await getRecord<LocalEvidence>(u, id);
  if (!back || back.sha256 !== saved.sha256) throw new Error("Save not confirmed");
  return back;
}

export async function addNote(u: string, visitId: string, text: string) {
  const bytes = utf8(text);
  const ev: LocalEvidence = {
    uuid: uuid(), visit_id: visitId, kind: "note", mime: "text/plain", filename: "note.txt", text,
    sha256: await sha256Hex(bytes), size: bytes.length, captured_at: now(), sync: queued(),
  };
  await putRecord(u, "evidence", ev.uuid, visitId, ev);
  const back = await getRecord<LocalEvidence>(u, ev.uuid);
  if (!back) throw new Error("Save not confirmed");
  return back;
}

export async function addObservation(u: string, visitId: string, o: Omit<LocalObs, "uuid" | "visit_id" | "captured_at" | "sync">) {
  const rec: LocalObs = { ...o, uuid: uuid(), visit_id: visitId, captured_at: now(), sync: queued() };
  await putRecord(u, "observation", rec.uuid, visitId, rec);
  const back = await getRecord<LocalObs>(u, rec.uuid);
  if (!back) throw new Error("Save not confirmed");
  return back;
}

export const listEvidence = (u: string, visitId?: string) => listRecords<LocalEvidence>(u, "evidence", visitId);
export const listObs = (u: string, visitId?: string) => listRecords<LocalObs>(u, "observation", visitId);
export const getEvidence = (u: string, id: string) => getRecord<LocalEvidence>(u, id);
export async function saveEvidence(u: string, e: LocalEvidence) {
  await putRecord(u, "evidence", e.uuid, e.visit_id, e);
}
export async function saveObs(u: string, o: LocalObs) {
  await putRecord(u, "observation", o.uuid, o.visit_id, o);
}

export async function saveRecovery(u: string, r: Omit<Recovery, "id" | "at">) {
  const rec = { ...r, id: uuid(), at: now() };
  await putRecord(u, "recovery", rec.id, r.visit_id, rec);
  return rec;
}
export const listRecovery = (u: string, visitId: string) => listRecords<Recovery>(u, "recovery", visitId);

export async function unsyncedCount(u: string, visitId?: string) {
  const [ev, ob, vs] = await Promise.all([listEvidence(u, visitId), listObs(u, visitId), listVisits(u)]);
  const pendingVisits = vs.filter((v) => (!visitId || v.uuid === visitId) && (v.sync.state !== "Verified" || v.pending_permission));
  return ev.filter((e) => e.sync.state !== "Verified").length + ob.filter((o) => o.sync.state !== "Verified").length + pendingVisits.length;
}
