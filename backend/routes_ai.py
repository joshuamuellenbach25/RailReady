"""Processing (jobs, transcripts, proposals, image candidates + review decisions) and office endpoints.
All GETs are read-only: reopening saved results makes zero model calls."""
import os
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core import (audit, clean, clean_all, current_user, db, get_scoped, get_visit, iso, new_id, require_role,
                  revision_conflict, assert_editable, sha256_hex)
import ai_image
import jobs
import readiness

router = APIRouter(prefix="/api")


RESULT_STATES = {"checking": "Checking {kind}", "needs_review": "Needs review", "complete": "Check complete",
                 "partial": "Partial result", "failed": "Could not finish the check", "unavailable": "Checking unavailable: {reason}"}
EMPTY_COPY = "No visible issue identified in this {kind}. This does not confirm the track is safe."  # REQ-1237
UNAVAILABLE_REASON = {"policy": "Photo checks are turned off for this site", "budget": "Check limit reached. An admin must approve more."}


def result_state(stages: dict, runs: list, pending: int) -> tuple[str | None, str | None]:
    """REQ-1236 (absorbs C4): returns (state, reason). 'complete' with zero findings renders EMPTY_COPY; rejected, failed or
    unreadable output is 'failed', never empty. Uncertain and partial results are review work ('needs_review')."""
    jobs_ = [stages.get(s) or {} for s in ("image_analysis", "photo_analysis", "video_analysis")]
    st = [j.get("status") for j in jobs_]
    if any(s in ("Queued", "Running") for s in st):
        return "checking", None
    blocked = next((j for j in jobs_ if j.get("status") == "Blocked"), None)
    if blocked:
        b = (blocked.get("blocker") or "")
        is_budget = b == __import__("calibration").BUDGET_MSG or "budget" in b.lower() or "check limit" in b.lower()
        return "unavailable", "budget" if is_budget else "policy"
    if pending:
        return "needs_review", None
    if any(s == "Failed" for s in st):
        return "failed", None
    if any(r.get("status") == "budget_limited" for r in runs):
        return "unavailable", "budget"
    bad = [r for r in runs if r.get("status") in ("Failed", "failed")]
    if bad:  # e.g. tie/fastener answered but rail surface failed: partial if something usable exists, else failed
        return ("partial" if any((r.get("candidates") or 0) for r in runs if r not in bad) else "failed"), None
    if not runs:
        return None, None  # never checked: not "complete"
    if any(r.get("image_assessability") == "cannot_assess" for r in runs):
        return "failed", None
    if any(r.get("status") == "partial" or r.get("rejected_candidates") or (r.get("rail_surface") or {}).get("status") == "partial" for r in runs):
        # rejected output with nothing usable = failed; partial with all findings reviewed = partial (pending -> needs_review above)
        return ("failed" if not any((r.get("candidates") or 0) for r in runs) else "partial"), None
    return "complete", None


def state_view(state, reason, kind: str, findings: int) -> dict:
    noun = "video" if kind == "video" else "photo"
    label = RESULT_STATES[state].format(kind=noun, reason=UNAVAILABLE_REASON.get(reason, "")) if state else None
    return {"result_state": state, "result_reason": reason, "result_label": label,
            "result_empty_copy": EMPTY_COPY.format(kind=noun) if state == "complete" and findings == 0 else None}


@router.get("/visits/{visit_id}/processing", tags=["processing"])
async def processing(visit_id: str, user=Depends(current_user)):
    v = await get_visit(user, visit_id)
    js = clean_all(await db.jobs.find({"visit_id": visit_id}).to_list(1000))
    run_ev = {r["uuid"]: r["evidence_id"] async for r in db.image_analysis_runs.find({"visit_id": visit_id, "pipeline": "two_stage_v1"}, {"uuid": 1, "evidence_id": 1})}
    by_target: dict = {}
    for j in js:
        tgt = run_ev.get(j["target_id"], j["target_id"]) if j["stage"] == "photo_analysis" else j["target_id"]  # Phase 7 jobs target the run
        by_target.setdefault(tgt, {})[j["stage"]] = {k: j.get(k) for k in (
            "uuid", "status", "blocker", "attempts", "error", "error_stage", "last_run_id", "updated_at", "retryable")}
    # C4: uncertain findings count too (no hidden filter); every pipeline incl. rail_surface_v1
    pending: dict = {}
    async for c in db.visual_candidates.find({"visit_id": visit_id, "review_state": "Pending"}, {"evidence_id": 1}):
        pending[c["evidence_id"]] = pending.get(c["evidence_id"], 0) + 1
        by_target.setdefault(c["evidence_id"], {})["needs_review"] = True
    latest: dict = {}
    async for r in db.image_analysis_runs.find({"visit_id": visit_id}, {"_id": 0, "raw_responses": 0}).sort("created_at", 1):
        latest.setdefault(r["evidence_id"], {})[r.get("pipeline") or "legacy"] = r
    async for e in db.evidence.find({"visit_id": visit_id, "kind": {"$in": ["photo", "video"]}}, {"uuid": 1, "kind": 1}):
        rs = list(latest.get(e["uuid"], {}).values())
        s, reason = result_state(by_target.get(e["uuid"], {}), rs, pending.get(e["uuid"], 0))
        by_target.setdefault(e["uuid"], {}).update(state_view(s, reason, e["kind"], sum((r.get("candidates") or 0) for r in rs)))
    pol = await __import__("policy").evaluate(v)
    return {"permission": v.get("processing_permission"), "blocker": None if pol["allowed"] else jobs.BLOCKER, "policy": pol,
            "result_states": RESULT_STATES, "by_evidence": by_target}


@router.post("/jobs/{job_id}/retry", tags=["processing"])
async def retry_job(job_id: str, user=Depends(current_user)):
    j, _ = await get_scoped("jobs", user, job_id)
    try:
        return clean(await jobs.retry(j, user))
    except jobs.RetryBlocked as exc:
        raise HTTPException(409, {"code": exc.code, "message": exc.message})


class FaultIn(BaseModel):
    visit_id: str
    stage: Literal["transcription", "extraction", "image_analysis", "text_checks", "depth"]
    target_id: Optional[str] = None
    mode: Optional[Literal["error", "storage", "uninformative", "checksum"]] = None  # depth only (V09)


@router.post("/dev/fault", tags=["dev"])
async def inject_fault(body: FaultIn, user=Depends(current_user)):
    """Test-only: make the next run of a stage for this visit fail (JRN-13/15). Disabled unless ALLOW_FAULT_INJECTION=true."""
    if os.environ.get("ALLOW_FAULT_INJECTION", "false").lower() != "true":
        raise HTTPException(404, "Not found")
    await get_visit(user, body.visit_id)
    await db.faults.insert_one({"visit_id": body.visit_id, "stage": body.stage, "target_id": body.target_id, "mode": body.mode, "at": iso()})
    return {"ok": True}


# ---------------- transcripts ----------------
@router.get("/evidence/{evidence_id}/transcripts", tags=["transcripts"])
async def transcripts(evidence_id: str, user=Depends(current_user)):
    await get_scoped("evidence", user, evidence_id)
    return clean_all(await db.transcripts.find({"evidence_id": evidence_id}).sort("version", 1).to_list(50))


class CorrectionIn(BaseModel):
    text: str
    base_version: int


@router.post("/evidence/{evidence_id}/transcripts", tags=["transcripts"])
async def correct_transcript(evidence_id: str, body: CorrectionIn, user=Depends(current_user)):
    ev, v = await get_scoped("evidence", user, evidence_id)
    assert_editable(v, user)
    latest = await db.transcripts.find_one({"evidence_id": evidence_id}, sort=[("version", -1)])
    if not latest:
        raise HTTPException(409, {"code": "no_transcript", "message": "No machine transcript yet"})
    if body.base_version != latest["version"]:
        revision_conflict(latest, "transcript")
    doc = {"uuid": new_id(), "workspace_id": ev["workspace_id"], "visit_id": ev["visit_id"], "evidence_id": evidence_id,
           "version": latest["version"] + 1, "kind": "corrected", "text": body.text.strip(), "model_id": None,
           "based_on_version": latest["version"], "source_sha256": ev["sha256"], "audio_ref": ev["storage_path"],
           "created_at": iso(), "created_by": user["uuid"], "updated_at": iso(), "updated_by": user["uuid"], "revision": 1}
    try:
        await db.transcripts.insert_one(doc)
    except Exception:
        revision_conflict(await db.transcripts.find_one({"evidence_id": evidence_id}, sort=[("version", -1)]), "transcript")
    await audit(user, v["workspace_id"], "transcript_corrected", "evidence", evidence_id, {"version": doc["version"]})
    await jobs.enqueue(v, "extraction", evidence_id, "audio", force_requeue=True)
    await jobs.enqueue(v, "text_checks", doc["uuid"], "transcript")
    return clean(doc)


@router.get("/evidence/{evidence_id}/text-checks", tags=["transcripts"])
async def text_checks(evidence_id: str, user=Depends(current_user)):
    """Jev flags for a note and each transcript version. Read-only (zero model calls). Not run = blocked/failed/missing."""
    ev, v = await get_scoped("evidence", user, evidence_id)
    targets = [evidence_id] if ev["kind"] == "note" else [t["uuid"] async for t in db.transcripts.find({"evidence_id": evidence_id}).sort("version", 1)]
    ws = await db.workspaces.find_one({"uuid": v["workspace_id"]})
    out = []
    for t in targets:
        job = await db.jobs.find_one({"stage": "text_checks", "target_id": t})
        chk = await db.text_checks.find_one({"target_id": t, "status": "Done"}, sort=[("created_at", -1)])
        out.append({"target_id": t, "status": "Done" if chk else "Not run",
                    "job_status": job["status"] if job else None, "blocker": job.get("blocker") if job else None,
                    "error": job.get("error") if job else None, "job_id": job["uuid"] if job else None, "check": clean(chk)})
    return {"checks": out, "escalation_text": ws.get("escalation_text")}


# ---------------- proposals ----------------
@router.get("/visits/{visit_id}/proposals", tags=["proposals"])
async def proposals(visit_id: str, user=Depends(current_user)):
    v = await get_visit(user, visit_id)
    r = await readiness.compute(v)
    runs = clean_all(await db.extraction_runs.find({"visit_id": visit_id}, {"raw_responses": 0, "input_text": 0}).sort("created_at", 1).to_list(100))
    return {"fields": r["fields"], "runs": runs, "visit_revision": v["revision"], "status": v["status"]}


@router.get("/extraction-runs/{run_id}", tags=["proposals"])
async def extraction_run(run_id: str, user=Depends(current_user)):
    run, _ = await get_scoped("extraction_runs", user, run_id)
    return clean(run)


# ---------------- image analysis + candidates ----------------
@router.get("/evidence/{evidence_id}/analysis", tags=["candidates"])
async def photo_analysis(evidence_id: str, user=Depends(current_user)):
    ev, v = await get_scoped("evidence", user, evidence_id)
    hide_dismissed = False  # customers never call this; staff history keeps dismissed candidates
    runs = clean_all(await db.image_analysis_runs.find({"evidence_id": evidence_id}).sort("created_at", 1).to_list(20))
    cands = clean_all(await db.visual_candidates.find({"evidence_id": evidence_id}).sort("created_at", 1).to_list(50))
    if hide_dismissed:
        cands = [c for c in cands if c["review_state"] != "Dismissed"]
    job = clean(await db.jobs.find_one({"stage": "image_analysis", "target_id": evidence_id}))
    latest = runs[-1] if runs else None
    label = latest["outcome_label"] if latest and latest["status"] == "Done" else None
    stages = {j["stage"]: j for j in clean_all(await db.jobs.find({"target_id": evidence_id}).to_list(20))}
    by_pipe = {}
    for r in runs:
        by_pipe[r.get("pipeline") or "legacy"] = r
    s, reason = result_state(stages, list(by_pipe.values()), sum(1 for c in cands if c["review_state"] == "Pending"))
    return {"evidence": clean(ev), "job": job, "runs": runs, "candidates": cands, "outcome_label": label,
            **state_view(s, reason, ev.get("kind"), sum((r.get("candidates") or 0) for r in by_pipe.values())),
            "visit_status": v["status"]}


class ManualCandidateIn(BaseModel):
    category: str
    region: object = "unlocalized"
    visible_reason: str
    assessability: str
    uncertainty: str
    alternatives: list[str] = []
    source: Literal["on_device_model", "reviewer"] = "reviewer"
    model_id: Optional[str] = None
    prompt_version: Optional[str] = None


@router.post("/evidence/{evidence_id}/candidates", tags=["candidates"])
async def post_candidate(evidence_id: str, body: ManualCandidateIn, user=Depends(current_user)):
    """Adapter seam (future on-device analyzer / reviewer-added). Same validation as server model output."""
    ev, v = await get_scoped("evidence", user, evidence_id)
    assert_editable(v, user)
    if ev["kind"] != "photo":
        raise HTTPException(422, "Candidates attach to photos only")
    raw = body.model_dump()
    try:
        c = ai_image.validate_candidate(raw)
    except ai_image.ValidationError as e:
        raise HTTPException(422, f"Candidate rejected: {e}")
    doc = {"uuid": new_id(), "workspace_id": ev["workspace_id"], "visit_id": ev["visit_id"], "evidence_id": evidence_id,
           "photo_sha256": ev["sha256"], "run_id": None, "source": body.source, **c, "raw_output": raw,
           "model_id": body.model_id or f"human:{user['uuid']}", "prompt_version": body.prompt_version or "n/a",
           "review_state": "Pending", "decisions": [], "revision": 1, "created_at": iso(), "created_by": user["uuid"],
           "updated_at": iso(), "updated_by": user["uuid"]}
    await db.visual_candidates.insert_one(doc)
    return clean(doc)


class DecisionIn(BaseModel):
    action: Literal["confirm", "correct", "dismiss", "request_closer_photo"]
    expected_revision: int
    corrected_category: Optional[str] = None
    note: Optional[str] = None


STATE = {"confirm": "Confirmed", "correct": "Corrected", "dismiss": "Dismissed", "request_closer_photo": "Closer photo requested"}


@router.post("/candidates/{cand_id}/decision", tags=["candidates"])
async def decide(cand_id: str, body: DecisionIn, user=Depends(current_user)):
    c, v = await get_scoped("visual_candidates", user, cand_id)
    assert_editable(v, user)
    if body.expected_revision != c["revision"]:
        last = (c.get("decisions") or [{}])[-1]
        if last.get("candidate_revision") == body.expected_revision and last.get("action") == body.action and last.get("actor_id") == user["uuid"]:
            # B5: lost-response retry of the decision that already won -> complete (idempotent) and return the same result
            await _complete_decision(v, {**c, "revision": body.expected_revision}, {
                "uuid": last["uuid"], "workspace_id": v["workspace_id"], "visit_id": v["uuid"], "candidate_id": cand_id, "action": last["action"],
                "actor_id": last["actor_id"], "actor_role": last.get("actor_role"), "at": last["at"], "candidate_revision": last["candidate_revision"],
                "corrected_category": body.corrected_category, "note": last.get("note"), "observation_id": last.get("observation_id")}, body, user)
            return clean(c)
        revision_conflict(c, "candidate")
    if body.action == "correct" and not (body.corrected_category or body.note):
        raise HTTPException(422, "Correction needs a category or note")
    if body.corrected_category and body.corrected_category not in ai_image.CATEGORIES + ["other visible condition"] + list(__import__("rail_surface").CHOICES):
        raise HTTPException(422, "Unknown category")
    # B5: the candidate CAS is the arbiter and happens FIRST; observation/decision ids are deterministic per
    # (candidate, revision), so a lost-response retry returns the same observation and a crash is completed on retry.
    obs_id = f"obs-{cand_id}-r{c['revision']}" if body.action in ("confirm", "correct") else None
    did = f"dec-{cand_id}-r{c['revision']}"
    decision = {"uuid": did, "workspace_id": v["workspace_id"], "visit_id": v["uuid"], "candidate_id": cand_id,
                "action": body.action, "actor_id": user["uuid"], "actor_role": user["role"], "at": iso(),
                "candidate_revision": c["revision"], "corrected_category": body.corrected_category, "note": body.note,
                "observation_id": obs_id}
    res = await db.visual_candidates.find_one_and_update(
        {"uuid": cand_id, "revision": c["revision"]},
        {"$set": {"review_state": STATE[body.action], "linked_observation_id": obs_id or c.get("linked_observation_id"),
                  "updated_at": iso(), "updated_by": user["uuid"]},
         "$push": {"decisions": {k: decision[k] for k in ("uuid", "action", "actor_id", "actor_role", "at", "candidate_revision", "note", "observation_id")}},
         "$inc": {"revision": 1}}, return_document=True)
    if not res:
        cur = await db.visual_candidates.find_one({"uuid": cand_id})
        last = (cur.get("decisions") or [{}])[-1]
        if not (last.get("uuid") == did and last.get("action") == body.action and last.get("actor_id") == user["uuid"]):
            revision_conflict(cur, "candidate")  # someone else decided first
        res, decision = cur, {**decision, **{k: last[k] for k in ("at", "note", "observation_id") if k in last}}
    await _complete_decision(v, c, decision, body, user)
    if res["revision"] == c["revision"] + 1:
        await audit(user, v["workspace_id"], f"candidate_{body.action}", "candidate", cand_id, {"observation_id": obs_id})
    return clean(res)


async def _complete_decision(v, c, decision, body, user):
    """Idempotent completion step (upserts by deterministic id): decision record + linked observation."""
    await db.candidate_decisions.update_one({"uuid": decision["uuid"]}, {"$setOnInsert": decision}, upsert=True)
    if decision["observation_id"]:
        await db.observations.update_one({"uuid": decision["observation_id"]}, {"$setOnInsert": {
            "uuid": decision["observation_id"], "workspace_id": v["workspace_id"], "visit_id": v["uuid"], "kind": "finding",
            "text": body.note or c["visible_reason"], "category": body.corrected_category or c["category"],
            "region": c["region"], "evidence_id": c["evidence_id"], "source_candidate_id": c["uuid"],
            "human_reviewed": True, "quantity": None, "specification": None, "method": None, "rate": None,
            "created_at": iso(), "created_by": user["uuid"], "updated_at": iso(), "updated_by": user["uuid"], "revision": 1}}, upsert=True)


# ---------------- office (estimator) ----------------
async def _summary(v):
    site = await db.sites.find_one({"uuid": v["site_id"]})
    fm = await db.users.find_one({"uuid": v["foreman_id"]})
    r = await readiness.compute(v)
    return {**clean(v), "site_name": site["name"] if site else None, "foreman_name": fm["name"] if fm else None,
            "evidence_count": await db.evidence.count_documents({"visit_id": v["uuid"]}),
            "complete_receipts": await db.receipts.count_documents({"visit_id": v["uuid"]}),
            "pending_candidates": await db.visual_candidates.count_documents({"visit_id": v["uuid"], "review_state": "Pending"}),
            "readiness_counts": r["counts"]}


@router.get("/office/inbox", tags=["office"])
async def inbox(user=Depends(require_role("estimator", "admin"))):
    ws = user["workspace_id"]
    submitted = [await _summary(v) for v in await db.visits.find({"workspace_id": ws, "status": "Submitted"}).sort("submitted_at", -1).to_list(200)]
    drafts = []
    for v in await db.visits.find({"workspace_id": ws, "status": "Draft"}).sort("updated_at", -1).to_list(200):
        if await db.manifests.count_documents({"visit_id": v["uuid"]}) or await db.evidence.count_documents({"visit_id": v["uuid"]}):
            drafts.append(await _summary(v))
    return {"submitted": submitted, "draft_transfers": drafts}


@router.get("/visits/{visit_id}/review", tags=["office"])
async def review(visit_id: str, user=Depends(current_user)):
    v = await get_visit(user, visit_id)
    site = await db.sites.find_one({"uuid": v["site_id"]})
    ev = clean_all(await db.evidence.find({"visit_id": visit_id}).sort("created_at", 1).to_list(500))
    for e in ev:
        e["transcripts"] = clean_all(await db.transcripts.find({"evidence_id": e["uuid"]}).sort("version", 1).to_list(20))
        run = await db.image_analysis_runs.find_one({"evidence_id": e["uuid"]}, sort=[("created_at", -1)])
        e["analysis_outcome"] = run.get("outcome_label") if run else None
        e["jobs"] = {j["stage"]: {"status": j["status"], "error": j.get("error"), "uuid": j["uuid"], "blocker": j.get("blocker")}
                     async for j in db.jobs.find({"target_id": e["uuid"]})}
    return {
        "visit": clean(v), "site": clean(site), "summary": await _summary(v),
        "prior_findings": [f for f in (site or {}).get("prior_findings", []) if f.get("status") == "Outstanding"],
        "evidence": ev,
        "candidates": clean_all(await db.visual_candidates.find({"visit_id": visit_id}).to_list(500)),
        "observations": clean_all(await db.observations.find({"visit_id": visit_id}).sort("created_at", 1).to_list(500)),
        "readiness": await readiness.compute(v),
        "manifests": clean_all(await db.manifests.find({"visit_id": visit_id}).to_list(50)),
        "audit": clean_all(await db.audit_events.find({"target_id": {"$in": [visit_id] + [e["uuid"] for e in ev]}}).sort("at", -1).to_list(100)),
    }
