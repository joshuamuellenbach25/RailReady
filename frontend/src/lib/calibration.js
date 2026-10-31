// Calibration (Phase 6) display helpers. All counts, metrics and probabilities come from the server.
import { useEffect } from "react";

export const DOMAIN_LABEL = "Pueblo source-domain calibration. Not field-validated elsewhere.";
export const RAIL_NOTE = "No Bad rail labels. Broken-rail sensitivity is not supported.";
export const BUDGET_MSG = "Image-call budget reached. Admin approval needed.";
export const ACTIVE = ["Queued", "Running", "Downloading", "Verifying", "Storing", "Indexing"];
export const TARGET = ["clip", "spike_and_bolt", "tie"];

export const num = (v) => (v == null ? "-" : Number(v).toLocaleString());
export const pct = (v) => (v == null ? "-" : `${(v * 100).toFixed(1)}%`);
export const dec = (v, d = 3) => (v == null ? "-" : Number(v).toFixed(d));
export const mb = (b) => (b == null ? "-" : `${(b / 1048576).toFixed(1)} MB`);

/** Poll `fn` while `active`; backoff x1.6 up to 15 s while the returned signature is unchanged, reset to 2 s on change. */
export function usePoll(fn, active) {
  useEffect(() => {
    if (!active) return undefined;
    let t;
    let delay = 2000;
    let last = null;
    let stop = false;
    const tick = async () => {
      let sig = last;
      try { sig = await fn(); } catch { /* keep backing off */ }
      if (stop) return;
      delay = sig !== last ? 2000 : Math.min(15000, Math.round(delay * 1.6));
      last = sig;
      t = setTimeout(tick, delay);
    };
    t = setTimeout(tick, delay);
    return () => { stop = true; clearTimeout(t); };
  }, [fn, active]);
}
