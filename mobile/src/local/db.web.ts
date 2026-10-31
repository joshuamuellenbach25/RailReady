// Web fallback durable store: IndexedDB for records and media blobs, partitioned by user.
import { sha256Hex } from "./hash";

let dbp: Promise<IDBDatabase> | null = null;
function idb(): Promise<IDBDatabase> {
  if (!dbp)
    dbp = new Promise((resolve, reject) => {
      const req = indexedDB.open("railready", 1);
      req.onupgradeneeded = () => {
        const d = req.result;
        const s = d.createObjectStore("records", { keyPath: ["user_id", "id"] });
        s.createIndex("by_user_type", ["user_id", "type"]);
        d.createObjectStore("blobs", { keyPath: "key" });
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
  return dbp;
}

function done(tx: IDBTransaction) {
  return new Promise<void>((res, rej) => {
    tx.oncomplete = () => res();
    tx.onerror = () => rej(tx.error);
    tx.onabort = () => rej(tx.error);
  });
}
function req<T>(r: IDBRequest<T>) {
  return new Promise<T>((res, rej) => {
    r.onsuccess = () => res(r.result);
    r.onerror = () => rej(r.error);
  });
}

export async function putRecord(userId: string, type: string, id: string, parent: string | null, data: any) {
  const tx = (await idb()).transaction("records", "readwrite");
  tx.objectStore("records").put({ user_id: userId, id, type, parent, data: JSON.stringify(data), updated_at: new Date().toISOString() });
  await done(tx);
}

// All rows commit together or none do (one IndexedDB transaction).
export async function putRecords(userId: string, rows: { type: string; id: string; parent: string | null; data: any }[]) {
  const tx = (await idb()).transaction("records", "readwrite");
  const at = new Date().toISOString();
  for (const r of rows) tx.objectStore("records").put({ user_id: userId, id: r.id, type: r.type, parent: r.parent, data: JSON.stringify(r.data), updated_at: at });
  await done(tx);
}

// IndexedDB serializes read/write transactions on this store across tabs. Keep the
// guard read and dependent inserts in that same transaction, and never replace data.
export async function createRecordsOnce<T>(userId: string, guardId: string, rows: { type: string; id: string; parent: string | null; data: any }[]): Promise<{ data: T; created: boolean }> {
  const guard = rows.find((r) => r.id === guardId);
  if (!guard) throw new Error("Creation guard missing.");
  const tx = (await idb()).transaction("records", "readwrite");
  const committed = done(tx);
  try {
    const store = tx.objectStore("records");
    const prior: any = await req(store.get([userId, guardId]));
    if (prior) {
      const data = JSON.parse(prior.data) as T;
      await committed;
      return { data, created: false };
    }
    const at = new Date().toISOString();
    for (const r of rows) store.add({ user_id: userId, id: r.id, type: r.type, parent: r.parent, data: JSON.stringify(r.data), updated_at: at });
    await committed;
    return { data: guard.data as T, created: true };
  } catch (error) {
    try { tx.abort(); } catch { /* already finished */ }
    await committed.catch(() => {});
    throw error;
  }
}

export async function getRecord<T>(userId: string, id: string): Promise<T | null> {
  const r = await req((await idb()).transaction("records").objectStore("records").get([userId, id]));
  return r ? (JSON.parse((r as any).data) as T) : null;
}

export async function listRecords<T>(userId: string, type: string, parent?: string): Promise<T[]> {
  const rows: any[] = await req((await idb()).transaction("records").objectStore("records").index("by_user_type").getAll([userId, type]));
  return rows
    .filter((r) => !parent || r.parent === parent)
    .sort((a, b) => (a.updated_at < b.updated_at ? -1 : 1))
    .map((r) => JSON.parse(r.data) as T);
}

async function getBlob(userId: string, path: string): Promise<Blob> {
  const r: any = await req((await idb()).transaction("blobs").objectStore("blobs").get(`${userId}/${path}`));
  if (!r) throw new Error("Media missing on this device");
  return r.blob as Blob;
}

export async function saveMedia(userId: string, id: string, srcUri: string, ext: string) {
  const blob = await (await fetch(srcUri)).blob();
  const path = `${id}.${ext}`;
  const tx = (await idb()).transaction("blobs", "readwrite");
  tx.objectStore("blobs").put({ key: `${userId}/${path}`, blob });
  await done(tx);
  const stored = new Uint8Array(await (await getBlob(userId, path)).arrayBuffer());
  return { path, sha256: await sha256Hex(stored), size: stored.length };
}

export async function readMedia(userId: string, path: string): Promise<Uint8Array> {
  return new Uint8Array(await (await getBlob(userId, path)).arrayBuffer());
}

const urls = new Map<string, string>();
export async function mediaUri(userId: string, path: string): Promise<string> {
  const k = `${userId}/${path}`;
  if (!urls.has(k)) urls.set(k, URL.createObjectURL(await getBlob(userId, path)));
  return urls.get(k)!;
}
