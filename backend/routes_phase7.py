"""Phase 7 APIs (requirement §L). Aliases/extends existing records. See docs/spec/phase7/requirement.md."""
import hashlib
import json
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

import photo_analysis_rules as R
import photo_pipeline as P
import policy
import routes_ai
from core import assert_editable, audit, current_user, db, get_scoped, iso, require_role, revision_conflict

router = APIRouter(prefix="/api", tags=["phase7"])
RUN_HIDE = {"_id": 0}


class AnalyzeIn(BaseModel):
    idempotency_key: Optional[str] = Field(None, max_length=120)
    reanalyze: bool = False


def _run_view(r: dict, user: dict) -> dict:
    out = {k: v for k, v in r.items() if k != "_id"}
    if user["role"] not in ("admin", "estimator"):
        out.pop("raw_responses", None)
    return out


@router.post("/evidence/{evidence_id}/analyze-photo")
async def analyze_photo(evidence_id: str, body: AnalyzeIn = AnalyzeIn(), idempotency_key: Optional[str] = Header(None), user=Depends(current_user)):
    ev, v = await get_scoped("evidence", user, evidence_id)
    if ev.get("kind") != "photo":
        raise HTTPException(422, {"code": "not_a_photo", "message": "Only photos can be analyzed"})
    if ev.get("upload_state") != "Verified":
        raise HTTPException(409, {"code": "not_verified", "message": "Photo is not verified yet", "retryable": True})
    pol = await policy.evaluate(v, evidence_id)
    if not pol["allowed"]:
        raise HTTPException(409, {"code": "processing_not_permitted", "message": pol["message"], "retryable": False})
    key = body.idempotency_key or idempotency_key
    payload = hashlib.sha256(json.dumps({"evidence_id": evidence_id, "reanalyze": body.reanalyze}, sort_keys=True).encode()).hexdigest()
    if key:
        prior = await db.idempotency_keys.find_one({"workspace_id": user["workspace_id"], "scope": "analyze-photo", "key": key})
        if prior:
            if prior["payload_hash"] != payload:
                raise HTTPException(409, {"code": "idempotency_key_reused", "message": "This idempotency key was used with a different request"})
            run = await db.image_analysis_runs.find_one({"uuid": prior["run_id"]}, RUN_HIDE)
            return {"run": _run_view(run, user), "replayed": True, "provider_calls": 0}
    run, created = await P.start(ev, user, body.reanalyze)
    if key:
        await db.idempotency_keys.update_one({"workspace_id": user["workspace_id"], "scope": "analyze-photo", "key": key},
                                             {"$setOnInsert": {"payload_hash": payload, "run_id": run["uuid"], "at": iso()}}, upsert=True)
    if created:
        await audit(user, v["workspace_id"], "photo_analysis_started", "evidence", evidence_id, {"run_id": run["uuid"], "reanalyze": body.reanalyze})
    return JSONResponse(status_code=202 if created else 200,
                        content={"run": _run_view(run, user), "replayed": not created, "provider_calls": None if created else 0})


@router.get("/photo-analysis-runs/{run_id}")
async def get_run(run_id: str, user=Depends(current_user)):
    r, _ = await get_scoped("image_analysis_runs", user, run_id)
    r.pop("_id", None)
    return _run_view(r, user)


def _cand_view(c: dict) -> dict:
    c = {k: v for k, v in c.items() if k != "_id"}
    c["admission"] = "admitted" if c.get("admitted") or c.get("human_identity") else "review"
    return c


@router.get("/evidence/{evidence_id}/visual-candidates")
async def list_candidates(evidence_id: str, include_review: bool = True, user=Depends(current_user)):
    """C2/C4: tie/fastener (two_stage_v1) AND rail-surface (rail_surface_v1) candidates. Uncertain ('review') items are
    included by default; include_review=false returns admitted only."""
    ev, _ = await get_scoped("evidence", user, evidence_id)
    import rail_surface as RS
    cands = [_cand_view(c) for c in await db.visual_candidates.find({"evidence_id": evidence_id, "pipeline": {"$in": [P.PIPELINE, RS.PIPELINE, "video_v1"]}}).sort("created_at", 1).to_list(500)]
    run = await db.image_analysis_runs.find_one({"evidence_id": evidence_id, "pipeline": P.PIPELINE}, {"_id": 0, "raw_responses": 0}, sort=[("created_at", -1)])
    rs_run = await db.image_analysis_runs.find_one({"evidence_id": evidence_id, "pipeline": RS.PIPELINE}, {"_id": 0, "raw_responses": 0}, sort=[("created_at", -1)])
    admitted = [c for c in cands if c["admission"] == "admitted"]
    return {"evidence_id": evidence_id, "taxonomy": {"id": R.TAXONOMY_ID, "version": R.TAXONOMY_VERSION, "label": R.TAXONOMY_LABEL},
            "rail_surface_schema": {"id": RS.SCHEMA_ID, "version": RS.SCHEMA_VERSION}, "latest_run": run, "latest_rail_surface_run": rs_run,
            "admitted": admitted, "review": [c for c in cands if c["admission"] == "review"] if include_review else None,
            "counts": {"admitted": len(admitted), "review": len(cands) - len(admitted)}}


class ReviewIn(BaseModel):
    action: Literal["confirm", "correct", "dismiss", "request_closer_photo", "mark_evidence_verified"]
    expected_revision: int
    corrected_component_code: Optional[str] = None
    note: Optional[str] = Field(None, max_length=500)


@router.post("/visual-candidates/{cand_id}/review")
async def review(cand_id: str, body: ReviewIn, user=Depends(current_user)):
    c, v = await get_scoped("visual_candidates", user, cand_id)
    if body.action == "mark_evidence_verified":
        assert_editable(v, user)
        if body.expected_revision != c["revision"]:
            revision_conflict(c, "candidate")
        res = await db.visual_candidates.find_one_and_update({"uuid": cand_id, "revision": c["revision"]}, {
            "$set": {"evidence_verified": {"by": user["uuid"], "role": user["role"], "at": iso()}, "updated_at": iso(), "updated_by": user["uuid"]},
            "$push": {"decisions": {"action": "mark_evidence_verified", "actor_id": user["uuid"], "actor_role": user["role"], "at": iso(), "candidate_revision": c["revision"]}},
            "$inc": {"revision": 1}}, return_document=True)
        await audit(user, v["workspace_id"], "candidate_evidence_verified", "candidate", cand_id, {})
        return _cand_view(res)
    leaf = None
    if body.action == "correct" and c.get("pipeline") == P.PIPELINE:
        leaf = R.LEAF_BY_CODE.get(body.corrected_component_code or "")
        if not leaf and not body.note:
            raise HTTPException(422, "Correction needs a component code or note")
    note = body.note or (f"Identity corrected to {P.taxonomy_display(leaf)}" if leaf else None)
    # same decision path as the legacy endpoint (observation/finding id reaches estimate → proposal → work order)
    await routes_ai.decide(cand_id, routes_ai.DecisionIn(action=body.action, expected_revision=body.expected_revision, note=note), user)
    if c.get("pipeline") == P.PIPELINE and body.action in ("confirm", "correct"):
        human = {"code": leaf["code"], "name": leaf["name"], "display": P.taxonomy_display(leaf)} if leaf else \
            {"code": (c.get("identity") or {}).get("component_code"), "name": c.get("category"), "display": c.get("component_display")}
        upd = {"human_identity": {**human, "by": user["uuid"], "at": iso()}, "admitted": True}
        if leaf:
            upd["category"] = leaf["name"]  # model output (identity) is kept unchanged; no fabricated 1.0
        await db.visual_candidates.update_one({"uuid": cand_id}, {"$set": upd})
    return _cand_view(await db.visual_candidates.find_one({"uuid": cand_id}))


@router.get("/taxonomies/{taxonomy_id}")
async def taxonomy(taxonomy_id: str, user=Depends(current_user)):
    t = await db.taxonomies.find_one({"taxonomy_id": taxonomy_id}, {"_id": 0}, sort=[("version", -1)])
    if not t:
        raise HTTPException(404, "Not found")
    return t


# ---- B2 admin recovery (dry-run list / apply) – admin-only, own workspace ----
class RecoveryIn(BaseModel):
    since: Optional[str] = None  # ISO; None = all receipted evidence in this workspace
    stages: Optional[list[str]] = None  # e.g. ["depth"] (local, free); hosted image_analysis held for budget approval


@router.get("/admin/rail-surface/diagnostics")
async def rail_surface_diagnostics(user=Depends(require_role("admin"))):
    import rail_surface as RS
    runs = await db.image_analysis_runs.count_documents({"workspace_id": user["workspace_id"], "rail_surface": {"$exists": True}})
    partial = await db.image_analysis_runs.count_documents({"workspace_id": user["workspace_id"], "rail_surface.status": "partial"})
    return {**RS.DIAGNOSTICS, "classes": {k: v[0] for k, v in RS.CLASSES.items()}, "runs_with_rail_surface": runs, "runs_with_rejected_output": partial}


@router.post("/admin/jobs/release-blocked")
async def release_blocked_now(user=Depends(require_role("admin"))):
    """REQ-1225: run the blocked-work reconciliation now (same pass as the 5-min sweep; policy and budget re-checked per job)."""
    import jobs as J
    res = await J.release_blocked("sweep_manual")
    await audit(user, user["workspace_id"], "blocked_release_run", "workspace", user["workspace_id"], {"released": len(res["released"])})
    return res


@router.get("/admin/recovery")
async def recovery_preview(since: Optional[str] = None, user=Depends(require_role("admin"))):
    import jobs as J
    gaps = await J.missing_jobs(since, user["workspace_id"])
    by = {}
    for g in gaps:
        by[g["stage"]] = by.get(g["stage"], 0) + 1
    return {"missing": len(gaps), "by_stage": by, "items": [{k: g[k] for k in ("uuid", "stage", "visit_id", "created_at")} for g in gaps[:100]],
            "note": "Hosted stages (image_analysis) reserve the global image-call budget before each call."}


@router.post("/admin/recovery")
async def recovery_apply(body: RecoveryIn, user=Depends(require_role("admin"))):
    import jobs as J
    res = await J.recovery_pass(body.since, user["workspace_id"], getattr(body, "stages", None))
    await audit(user, user["workspace_id"], "jobs_recovery_applied", "workspace", user["workspace_id"], {"since": body.since, "enqueued": res["enqueued"]})
    return res
