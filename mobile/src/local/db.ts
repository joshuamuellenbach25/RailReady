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
