import * as Crypto from "expo-crypto";

export async function sha256Hex(bytes: Uint8Array): Promise<string> {
  const buf = await Crypto.digest(Crypto.CryptoDigestAlgorithm.SHA256, bytes as any);
  return Array.from(new Uint8Array(buf))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

export function utf8(s: string): Uint8Array {
  return new TextEncoder().encode(s);
}

export const uuid = () => Crypto.randomUUID();
