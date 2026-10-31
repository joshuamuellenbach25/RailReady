// Thin API client mirroring /app/mobile/src/api.ts. All business rules live on the server; this only moves data.
export const BACKEND = process.env.REACT_APP_BACKEND_URL;
export const API = `${BACKEND}/api`;

let token = localStorage.getItem("rr_token");
export function setToken(t) {
  token = t;
  if (t) localStorage.setItem("rr_token", t);
  else localStorage.removeItem("rr_token");
}
export const getToken = () => token;

export class ApiError extends Error {
  constructor(status, detail) {
    super(
      typeof detail === "string"
        ? detail
        : detail?.message || (detail?.blockers ? `A few things need finishing before this can be sent (${detail.blockers.length}).` : ""),
    );
    this.status = status;
    this.detail = detail;
  }
}
export class OfflineError extends Error {}
export class TimeoutError extends Error {}
export const isAbort = (e) => e?.name === "AbortError";

// Plain, actionable error sentences (phase 8): never codes, ids or internal words.
const TECH = /server|backend|version|hash|uuid|manifest|receipt|model|provider|sync|upload|payload|schema|token|request failed|\b[a-z]+_[a-z_]+\b|\(\d{3}\)/i;
const BY_STATUS = {
  400: "Something in this form needs another look. Check it and try again.",
  401: "You are signed out. Sign in again to continue.",
  403: "You don't have access to this. Ask your office admin if you need it.",
  404: "We couldn't find that. It may have been moved or removed.",
  409: "Someone else changed this a moment ago. Refresh the page and try again.",
  413: "That file is too large. Try a smaller photo.",
  422: "Something in this form needs another look. Check it and try again.",
};
const plain = (msg, status) => (msg && !TECH.test(msg) ? msg : BY_STATUS[status] || "RailReady did not answer. Anything you typed is still here. Try again in a moment.");
export function errText(e) {
  if (e instanceof OfflineError) return "You're offline. Your input is still here. Check your connection and try again.";
  if (e instanceof TimeoutError) return "RailReady did not answer in time. Your input is still here. Try again.";
  if (e instanceof ApiError) {
    const d = e.detail;
    if (Array.isArray(d)) return d.map((x) => { const f = x?.loc?.slice(1).join(".").replace(/^fields\.(\d+)\.?/, (_, n) => `Question ${Number(n) + 1} `); return `${f && !TECH.test(f) ? `${f}: ` : ""}${plain(x?.msg, 422)}`; }).join(" ");
    if (d?.field) return plain(`${d.field.replace(/_/g, " ")}: ${d.message}`, e.status);
    return plain(e.message, e.status);
  }
  return plain(e?.message, 0);
}

/**
 * opts: method, body | form, signal (caller abort: photo switch / unmount), timeout ms (default 20 s reads, 30 s writes),
 * idempotencyKey (sent as Idempotency-Key). Abort -> AbortError (callers ignore it); timeout -> TimeoutError.
 */
export async function api(path, opts = {}) {
  const headers = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  if (opts.idempotencyKey) headers["Idempotency-Key"] = opts.idempotencyKey;
  let body;
  if (opts.form) body = opts.form;
  else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }
  const ctrl = new AbortController();
  const outer = opts.signal;
  const onAbort = () => ctrl.abort();
  if (outer?.aborted) ctrl.abort();
  else outer?.addEventListener("abort", onAbort, { once: true });
  let timedOut = false;
  const timer = setTimeout(() => { timedOut = true; ctrl.abort(); }, opts.timeout ?? (opts.form ? 120000 : body ? 30000 : 20000));
  let res;
  let text;
  try {
    res = await fetch(API + path, { method: opts.method || (body ? "POST" : "GET"), headers, body, signal: ctrl.signal });
    text = await res.text();
  } catch (e) {
    if (timedOut) throw new TimeoutError("timeout");
    if (outer?.aborted) throw e;
    throw new OfflineError("offline");
  } finally {
    clearTimeout(timer);
    outer?.removeEventListener("abort", onAbort);
  }
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  if (!res.ok) {
    // Proxies (502/503/504) return HTML error pages - never show raw markup to the user.
    if (typeof data === "string" && /^\s*</.test(data)) throw new ApiError(res.status, { message: "RailReady is busy right now. Nothing was saved. Try again in a moment.", retryable: true });
    throw new ApiError(res.status, data?.detail ?? data);
  }
  return data;
}

/**
 * Write that must never run twice: on a client timeout or dropped connection it is re-sent once with the SAME
 * idempotency key (the server replays the first result). Without a key, `reconcile()` re-reads instead of re-sending.
 */
export async function apiWrite(path, opts, reconcile) {
  try {
    return await api(path, opts);
  } catch (e) {
    if (!(e instanceof TimeoutError || e instanceof OfflineError)) throw e;
    if (opts.idempotencyKey || opts.body?.idempotency_key || opts.body?.request_key) return api(path, { ...opts, timeout: 45000 });
    if (reconcile) {
      const r = await reconcile();
      if (r !== undefined) return r;
    }
    throw e;
  }
}

// <img>/<audio>/print windows cannot send headers; the server accepts ?auth= (same as mobile).
export const withAuth = (path) => `${API}${path}${path.includes("?") ? "&" : "?"}auth=${encodeURIComponent(token || "")}`;
export const mediaUrl = (evidenceId) => withAuth(`/evidence/${evidenceId}/content`);
export const openPrint = (path) => window.open(withAuth(path), "_blank", "noopener");

// Route discovery: the backend is being extended concurrently (demo sessions, jobs, contracts).
// We read OpenAPI once so the UI can say clearly when a route is not deployed yet.
let routesP = null;
const norm = (p) => p.replace(/\{[^}]+\}/g, "{}");
export function apiRoutes() {
  if (!routesP)
    routesP = fetch(`${API}/openapi.json`)
      .then((r) => r.json())
      .then((d) => new Set(Object.keys(d.paths || {}).map(norm)))
      .catch(() => null);
  return routesP;
}
export async function hasRoute(path) {
  const s = await apiRoutes();
  return s ? s.has(norm(`/api${path}`)) : true;
}

export const newId = () =>
  window.crypto?.randomUUID ? window.crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`;

export async function sha256Hex(buf) {
  const h = await window.crypto.subtle.digest("SHA-256", buf);
  return Array.from(new Uint8Array(h)).map((b) => b.toString(16).padStart(2, "0")).join("");
}

/**
 * Endpoints added for the web phase. Shapes are read tolerantly.
 * @typedef {{token:string,user?:object,workspace?:object,session_id?:string}} DemoSession
 */
export const endpoints = {
  createDemo: () => api("/demo/sessions", { method: "POST" }),
  resetDemo: (id) => api(`/demo/sessions/${id}/reset`, { method: "POST" }),
  jobs: () => api("/office/jobs"),
  contracts: () => api("/contracts"),
  contract: (id) => api(`/contracts/${id}`),
};
