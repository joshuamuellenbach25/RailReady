// Native: hash a file in 256 KB chunks (bounded memory) instead of loading full-resolution bytes into JS.
import { File } from "expo-file-system";
import { sha256 } from "@noble/hashes/sha2.js";

const CHUNK = 256 * 1024;

export async function hashFile(file: File): Promise<{ sha256: string; size: number }> {
  const h = sha256.create();
  const handle = file.open();
  let size = 0;
  try {
    for (;;) {
      const chunk = await handle.readBytes(CHUNK);
      if (!chunk || chunk.length === 0) break;
      h.update(chunk);
      size += chunk.length;
    }
  } finally {
    handle.close();
  }
  const hex = Array.from(h.digest()).map((b) => b.toString(16).padStart(2, "0")).join("");
  return { sha256: hex, size };
}
