// Photo review client (Phase 7 contract, legacy fallback). Moves server data only; admission, identity and concern
// statuses come from the server. People see plain labels; scores and model data stay in `raw` for admin Details.
import { api, apiWrite, isAbort, newId } from "./api";

export const LEGACY_LABEL = {
  "possible missing/displaced fastener": "Possible missing or loose fastener",
  "visible tie-surface deterioration": "Possible damaged tie",
  "other visible condition": "Something else worth a look",
};
export const LEGACY_CATS = Object.keys(LEGACY_LABEL);
const CONCERN_LABEL = { visible_tie_surface_damage: "Possible damaged tie", missing_or_displaced_fastener: "Possible missing or loose fastener" };

const finite = (n) => typeof n === "number" && Number.isFinite(n);
/** Valid normalized [x, y, w, h] inside the image. Anything else is an image-level result (no box). */
export function validRegion(r) {
  if (!Array.isArray(r) || r.length !== 4 || !r.every(finite)) return false;
  const [x, y, w, h] = r;
  return x >= 0 && y >= 0 && w > 0 && h > 0 && x + w <= 1.001 && y + h <= 1.001;
}

// Rail surface (rail_surface_v1, schema rs-v1). Joint is a normal rail component, never damage.
export const RAIL_LABEL = {
  crack: "Possible crack", flaking: "Possible flaking", groove: "Possible groove", joint: "Rail joint",
  shelling: "Possible shelling", spalling: "Possible spalling", squat: "Possible squat (dent)",
};
export const RAIL_CATS = Object.keys(RAIL_LABEL);
export const isRail = (c) => c?.pipeline === "rail_surface_v1" || c?.schema === "rail_surface" || c?.schema_id === "rail-surface";
const isVideo = (c) => c?.pipeline === "video_v1" || !!c?.video_evidence_id || c?.timestamp_s != null;

function concernOf(c) {
  const e = Object.entries(c.concerns || {}).find(([, v]) => ["suggested", "needs_review"].includes(v?.status || v));
  return e ? CONCERN_LABEL[e[0]] || e[1]?.label : null;
}

function labelOf(c, source) {
  if (isRail(c)) {
    if (c.condition_kind === "component" || c.category === "joint") return "Rail joint";
    if (c.category === "not_assessable") return "Rail surface not clear enough to check";
    return RAIL_LABEL[c.category] || c.category || "Rail surface item";
  }
  if (source === "p7") return concernOf(c) || c.component_display || LEGACY_LABEL[c.category] || "Something worth a look";
  return LEGACY_LABEL[c.category] || c.category || "Something worth a look";
}

/** kind: "rail" (rail classes) | "p7" (taxonomy component, Phase 7 review route) | "legacy" (tie/fastener classes). */
function norm(c, source, admission) {
  const kind = isRail(c) ? "rail" : source === "p7" && !isVideo(c) ? "p7" : "legacy";
  const boxed = c.scope !== "image" && (kind !== "p7" || c.box_state === "valid") && validRegion(c.region);
  return { uuid: c.uuid, revision: c.revision, source, kind, admission, label: labelOf(c, source), boxed, region: boxed ? c.region : null,
    reason: c.visible_reason, alternatives: kind === "legacy" ? c.alternatives || [] : [], review_state: c.review_state, decisions: c.decisions || [],
    pending: c.review_state === "Pending", video: isVideo(c), raw: c };
}

/**
 * One read of everything the server has for this item (photo or video): the state fields from /analysis, rendered
 * as sent, and every finding (tie/fastener, rail surface, video), uncertain ones included. No client-side filter.
 */
export async function loadReview(evidenceId, signal) {
  const [an, vc] = await Promise.all([
    api(`/evidence/${evidenceId}/analysis`, { signal }),
    api(`/evidence/${evidenceId}/visual-candidates?include_review=true`, { signal }).catch((e) => { if (isAbort(e)) throw e; return null; }),
  ]);
  const byId = new Map();
  const add = (c, source, admission) => { if (c?.uuid && !byId.has(c.uuid)) byId.set(c.uuid, norm(c, source, admission)); };
  (vc?.admitted || []).forEach((c) => add(c, "p7", "admitted"));
  (vc?.review || []).forEach((c) => add(c, "p7", "review"));
  (an?.candidates || []).forEach((c) => add(c, "legacy", "admitted"));
  const items = [...byId.values()];
  if (items.some((i) => i.video)) items.sort((x, y) => (x.raw.timestamp_s ?? 0) - (y.raw.timestamp_s ?? 0));
  return {
    state: an?.result_state ?? null, label: an?.result_label || null, reason: an?.result_reason || null, empty: an?.result_empty_copy || null,
    runs: an?.runs || [], evidence: an?.evidence || null, items, taxonomyId: vc?.taxonomy?.id,
  };
}

/** Start (or replay) the photo check. The key is kept per photo so a retry after a timeout never starts a second run. */
export async function analyzePhoto(evidenceId, again = false) {
  const k = `rr_analyze_${evidenceId}${again ? "_again" : ""}`;
  if (again) sessionStorage.removeItem(k); // a deliberate "try again" is a new request; its own retries reuse this key
  const key = sessionStorage.getItem(k) || newId();
  sessionStorage.setItem(k, key);
  return apiWrite(`/evidence/${evidenceId}/analyze-photo`, { body: { idempotency_key: key, reanalyze: again }, idempotencyKey: key });
}

/** Decision with optimistic revision. A retry at the same expected_revision is a replay on the server (no duplicate). */
export function reviewCandidate(item, action, extra = {}) {
  const id = encodeURIComponent(item.uuid);
  if (item.kind === "p7")
    return apiWrite(`/visual-candidates/${id}/review`, {
      body: { action, expected_revision: item.revision, ...(extra.code ? { corrected_component_code: extra.code } : {}), ...(extra.note ? { note: extra.note } : {}) },
      idempotencyKey: `${item.uuid}:${item.revision}:${action}`,
    });
  return apiWrite(`/candidates/${id}/decision`, {
    body: { action, expected_revision: item.revision, ...(action === "correct" ? { corrected_category: extra.category } : {}), ...(extra.note ? { note: extra.note } : {}) },
    idempotencyKey: `${item.uuid}:${item.revision}:${action}`,
  });
}

let taxo = null;
export async function components(taxonomyId) {
  if (!taxo) taxo = api(`/taxonomies/${taxonomyId || "rail-components-v1"}`).then((d) => d.leaves || []).catch(() => { taxo = null; return []; });
  return taxo;
}
