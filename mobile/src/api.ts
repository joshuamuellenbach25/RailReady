// Thin API client. All business rules live on the server; this only moves data.
import { Platform } from "react-native";
import { fetch as expoFetch } from "expo/fetch";

export const API = `${process.env.EXPO_PUBLIC_BACKEND_URL}/api`;

let token: string | null = null;
export function setToken(t: string | null) {
  token = t;
}
export function getToken() {
  return token;
}

export class ApiError extends Error {
  status: number;
  detail: any;
  constructor(status: number, detail: any) {
    super(typeof detail === "string" ? detail : detail?.message || `Request failed (${status})`);
    this.status = status;
    this.detail = detail;
  }
}
export class OfflineError extends Error {}
// U3: a bounded wait ran out. For writes the outcome is UNKNOWN - callers retry with the SAME idempotency key or re-read.
export class TimeoutError extends OfflineError {}
export class CancelledError extends Error {}

export function isCancelled(e: unknown) {
  return e instanceof CancelledError;
}

export function errText(e: unknown): string {
  if (e instanceof TimeoutError) return "This is taking too long. Your work is kept on this phone - please try again.";
  if (e instanceof OfflineError) return "No connection right now. Your work is kept on this phone.";
  if (e instanceof ApiError) {
    const d = e.detail;
    if (Array.isArray(d)) return d.map((x) => x?.msg || String(x)).join(" ");
    return e.message;
  }
  return (e as Error)?.message || "That did not work. Check your connection and try again.";
}

type ApiOpts = {
  method?: string;
  body?: any;
  form?: FormData;
  signal?: AbortSignal; // cancel when the screen is left / the photo is switched
  timeoutMs?: number; // bounded wait (default 15s reads, 30s writes, 120s file bodies)
  sameKeyRetries?: number; // writes carrying an idempotency key/uuid: resend the SAME body after a timeout
};

export async function api<T = any>(path: string, opts: ApiOpts = {}): Promise<T> {
  const write = !!(opts.form || opts.body !== undefined || (opts.method && opts.method !== "GET"));
  const timeoutMs = opts.timeoutMs ?? (opts.form ? 120000 : write ? 30000 : 15000);
  for (let attempt = 0; ; attempt++) {
    try {
      return await once<T>(path, opts, timeoutMs);
    } catch (e) {
      // never a second operation: only bodies that carry their own idempotency key are resent, byte-identical
      if (e instanceof TimeoutError && write && attempt < (opts.sameKeyRetries ?? 0)) continue;
      throw e;
    }
  }
}

async function once<T>(path: string, opts: ApiOpts, timeoutMs: number): Promise<T> {
  const headers: Record<string, string> = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  let body: any;
  if (opts.form) body = opts.form;
  else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }
  if (opts.signal?.aborted) throw new CancelledError("cancelled");
  const ctl = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    ctl.abort();
  }, timeoutMs);
  const onAbort = () => ctl.abort();
  opts.signal?.addEventListener("abort", onAbort);
  let res: Response;
  try {
    try {
      const init = { method: opts.method || (body ? "POST" : "GET"), headers, body, signal: ctl.signal };
      res = (Platform.OS === "web" ? await fetch(API + path, init) : await expoFetch(API + path, init as any)) as Response;
    } catch {
      if (timedOut) throw new TimeoutError("timeout");
      if (opts.signal?.aborted) throw new CancelledError("cancelled");
      throw new OfflineError("offline");
    }
    const text = await res.text();
    let data: any = null;
    try {
      data = text ? JSON.parse(text) : null;
    } catch {
      data = text;
    }
    if (!res.ok) throw new ApiError(res.status, data?.detail ?? data);
    return data as T;
  } catch (e) {
    if (e instanceof ApiError || e instanceof OfflineError || e instanceof CancelledError) throw e;
    if (timedOut) throw new TimeoutError("timeout");
    if (opts.signal?.aborted) throw new CancelledError("cancelled");
    throw e;
  } finally {
    clearTimeout(timer);
    opts.signal?.removeEventListener("abort", onAbort);
  }
}

// Authenticated media URL for <Image>/<audio> (img tags cannot send headers).
export function mediaUrl(evidenceId: string) {
  return `${API}/evidence/${evidenceId}/content?auth=${encodeURIComponent(token || "")}`;
}

// Phase 17: work-order form / invoice / packet PDF (Preview = inline, Download = attachment).
export function paperworkUrl(repairVisitId: string, doc: "work_order" | "invoice" | "packet", download: boolean) {
  return `${API}/repairs/${repairVisitId}/paperwork/${doc}.pdf?download=${download}&auth=${encodeURIComponent(token || "")}`;
}
