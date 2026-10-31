// Native durable store: expo-sqlite rows + media bytes in the document directory, partitioned by user.
import * as SQLite from "expo-sqlite";
import { Directory, File, Paths } from "expo-file-system";
import { hashFile } from "./hashfile";

let dbp: Promise<SQLite.SQLiteDatabase> | null = null;
function db() {
  if (!dbp)
    dbp = (async () => {
      const d = await SQLite.openDatabaseAsync("railready.db");
      await d.execAsync(
        "PRAGMA journal_mode=WAL; CREATE TABLE IF NOT EXISTS records (user_id TEXT NOT NULL, id TEXT NOT NULL, type TEXT NOT NULL, parent TEXT, data TEXT NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY(user_id,id));",
      );
      return d;
    })();
  return dbp;
}

export async function putRecord(userId: string, type: string, id: string, parent: string | null, data: any) {
  const d = await db();
  await d.runAsync("INSERT OR REPLACE INTO records VALUES (?,?,?,?,?,?)", userId, id, type, parent, JSON.stringify(data), new Date().toISOString());
}

// All rows commit together or none do (used where a partial write would strand a record, e.g. pin + its inspection).
export async function putRecords(userId: string, rows: { type: string; id: string; parent: string | null; data: any }[]) {
  const d = await db();
  const at = new Date().toISOString();
  await d.withExclusiveTransactionAsync(async (tx) => {
    for (const r of rows) await tx.runAsync("INSERT OR REPLACE INTO records VALUES (?,?,?,?,?,?)", userId, r.id, r.type, r.parent, JSON.stringify(r.data), at);
  });
}

// The guard and all dependent rows share one transaction. Replays return the committed
// guard without replacing records that the worker may already have edited or synced.
let createTail: Promise<void> = Promise.resolve();
export async function createRecordsOnce<T>(userId: string, guardId: string, rows: { type: string; id: string; parent: string | null; data: any }[]): Promise<{ data: T; created: boolean }> {
  const guard = rows.find((r) => r.id === guardId);
  if (!guard) throw new Error("Creation guard missing.");
  const run = async () => {
    const d = await db();
    let result: { data: T; created: boolean } | undefined;
    await d.withExclusiveTransactionAsync(async (tx) => {
      const prior = await tx.getFirstAsync<{ data: string }>("SELECT data FROM records WHERE user_id=? AND id=?", userId, guardId);
      if (prior) {
        result = { data: JSON.parse(prior.data) as T, created: false };
        return;
      }
      const at = new Date().toISOString();
      for (const r of rows) await tx.runAsync("INSERT INTO records VALUES (?,?,?,?,?,?)", userId, r.id, r.type, r.parent, JSON.stringify(r.data), at);
      result = { data: guard.data as T, created: true };
    });
    if (!result) throw new Error("Creation was not committed.");
    return result;
  };
  // Avoid competing write connections in one Expo runtime. The database transaction
  // also protects the guard against another connection/runtime.
  const pending = createTail.then(run, run);
  createTail = pending.then(() => {}, () => {});
  return pending;
}

export async function getRecord<T>(userId: string, id: string): Promise<T | null> {
  const row = await (await db()).getFirstAsync<{ data: string }>("SELECT data FROM records WHERE user_id=? AND id=?", userId, id);
  return row ? (JSON.parse(row.data) as T) : null;
}

export async function listRecords<T>(userId: string, type: string, parent?: string): Promise<T[]> {
  const d = await db();
  const rows = parent
    ? await d.getAllAsync<{ data: string }>("SELECT data FROM records WHERE user_id=? AND type=? AND parent=? ORDER BY updated_at", userId, type, parent)
    : await d.getAllAsync<{ data: string }>("SELECT data FROM records WHERE user_id=? AND type=? ORDER BY updated_at", userId, type);
  return rows.map((r) => JSON.parse(r.data) as T);
}

function mediaDir(userId: string) {
  const dir = new Directory(Paths.document, "media", userId);
  if (!dir.exists) dir.create({ intermediates: true });
  return dir;
}

// Copies bytes into the user's partition, re-reads them and hashes the stored copy.
export async function saveMedia(userId: string, id: string, srcUri: string, ext: string) {
  const dest = new File(mediaDir(userId), `${id}.${ext}`);
  if (dest.exists) dest.delete();
  new File(srcUri).copy(dest); // durable copy into app documents before anything else
  const { sha256, size } = await hashFile(new File(mediaDir(userId), `${id}.${ext}`)); // chunked, never full bytes in JS
  return { path: `${id}.${ext}`, sha256, size };
}

export async function readMedia(userId: string, path: string): Promise<Uint8Array> {
  return new Uint8Array(await new File(mediaDir(userId), path).arrayBuffer());
}

export async function mediaUri(userId: string, path: string): Promise<string> {
  return new File(mediaDir(userId), path).uri;
}
