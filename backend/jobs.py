"""Persisted processing jobs with leases (Mongo). One job per (stage, target); retry reuses the job (no reupload)."""
import asyncio
import logging
import os
import socket
from datetime import timedelta

from core import db, iso, now, new_id, sha256_hex, audit
import storage
import ai_image
import ai_local
import ai_jev

log = logging.getLogger("jobs")
OWNER = f"{socket.gethostname()}-{os.getpid()}"
LEASE = timedelta(minutes=5)
CONCURRENCY = {"image_analysis": 2, "transcription": 1, "extraction": 1, "text_checks": 2, "depth": 1, "photo_analysis": 1, "video_analysis": 1}
DEADLINE_S = {"image_analysis": 240, "transcription": 600, "extraction": 180, "text_checks": 120, "depth": 600, "photo_analysis": 900, "video_analysis": 1200}
BLOCKER = "Processing not permitted for this visit"
STAGES = ["transcription", "extraction", "image_analysis", "text_checks", "depth", "photo_analysis", "video_analysis"]
EXPECTED = {"audio": ["transcription"], "note": ["extraction", "text_checks"], "photo": ["image_analysis", "depth"], "video": ["video_analysis"]}


async def enqueue(visit: dict, stage: str, target_id: str, source_kind: str, force_requeue: bool = False):
    """Returns the job (existing or new). REQ-1223: a duplicate-key race returns the existing job; other errors propagate."""
    import policy
    from pymongo.errors import DuplicateKeyError
    decision = await policy.evaluate_job({"workspace_id": visit["workspace_id"], "visit_id": visit["uuid"],
                                          "stage": stage, "target_id": target_id, "source_kind": source_kind})
    permitted = decision["allowed"]
    status = "Queued" if permitted else "Blocked"
    existing = await db.jobs.find_one({"stage": stage, "target_id": target_id})
    if existing:
        if force_requeue and existing["status"] in ("Done", "Failed") and permitted and not _active_lease(existing):
            await db.jobs.update_one(_idle_snapshot(existing),
                                     {"$set": {"status": "Queued", "error": None, "updated_at": iso()}, "$inc": {"revision": 1}})
        return existing
    doc = {
            "uuid": new_id(), "workspace_id": visit["workspace_id"], "visit_id": visit["uuid"], "stage": stage,
            "target_id": target_id, "source_kind": source_kind, "status": status,
            "blocker": None if permitted else BLOCKER, "block_reason": None if permitted else policy_reason(decision),
            "attempts": 0, "lease_owner": None, "lease_until": None,
            "error": None, "error_stage": None, "created_at": iso(), "updated_at": iso(), "revision": 1,
            "created_by": "system", "updated_by": "system",
        }
    try:
        await db.jobs.insert_one(dict(doc))
        return doc
    except DuplicateKeyError:  # unique (stage,target): someone else enqueued first
        return await db.jobs.find_one({"stage": stage, "target_id": target_id})


async def enqueue_for_evidence(visit: dict, ev: dict):
    if ev["kind"] == "audio":
        await enqueue(visit, "transcription", ev["uuid"], "audio")
    elif ev["kind"] == "note":
        await enqueue(visit, "extraction", ev["uuid"], "note")
        await enqueue(visit, "text_checks", ev["uuid"], "note")
    elif ev["kind"] == "photo":
        await enqueue(visit, "image_analysis", ev["uuid"], "photo")
        await enqueue(visit, "depth", ev["uuid"], "photo")
    elif ev["kind"] == "video":
        await enqueue(visit, "video_analysis", ev["uuid"], "video")


async def queue_verified(ev: dict):
    """REQ-1220/1222: per-item analysis intent, persisted with the verified state, then enqueued (no manifest dependency).
    The reconciliation loop finishes any intent left 'pending' by a crash between the two writes."""
    await db.evidence.update_one({"uuid": ev["uuid"], "analysis_intent": {"$exists": False}}, {"$set": {"analysis_intent": {"state": "pending", "at": iso()}}})
    visit = await db.visits.find_one({"uuid": ev["visit_id"]})
    await enqueue_for_evidence(visit, ev)
    await db.evidence.update_one({"uuid": ev["uuid"]}, {"$set": {"analysis_intent.state": "enqueued", "analysis_intent.enqueued_at": iso()}})


async def on_permission_change(visit: dict, trigger: str = "visit_restriction_changed"):
    """Recheck every affected job; only policy-blocked, idle work can auto-resume."""
    import policy
    import calibration
    query = {"visit_id": visit["uuid"], "workspace_id": visit["workspace_id"],
             "status": {"$in": ["Blocked", "Queued"]}}
    async for job in db.jobs.find(query).sort([("created_at", 1), ("uuid", 1)]):
        if _active_lease(job):
            continue
        if job["status"] == "Blocked" and job.get("blocker") not in (BLOCKER, policy.BLOCKED_MSG):
            continue  # budget and other holds require their own explicit resolution
        decision = await policy.evaluate_job(job)
        if not decision["allowed"]:
            if job["status"] == "Blocked":
                continue
            fields = {"status": "Blocked", "blocker": BLOCKER, "block_reason": policy_reason(decision)}
        elif job["status"] == "Queued":
            continue
        elif not await _budget_available(job):
            fields = {"status": "Blocked", "blocker": calibration.BUDGET_MSG, "block_reason": await budget_reason()}
        else:
            fields = {"status": "Queued", "blocker": None, "block_reason": None, "released_at": iso(), "release_trigger": trigger, "error": None, "error_stage": None,
                      "last_block_reason": job.get("block_reason") or {"kind": "policy", "inferred": True},  # admin detail keeps the reason
                      "lease_owner": None, "lease_token": None, "lease_until": None}
        inc = {"revision": 1, **({"release_count": 1} if fields["status"] == "Queued" else {})}
        await db.jobs.update_one(_idle_snapshot(job),
                                 {"$set": {**fields, "updated_at": iso()}, "$inc": inc})


# ---------------------------------------------------------------- REQ-1225: blocked work resumes when its blocker clears
EV_STAGES = ("image_analysis", "depth", "video_analysis")  # stages whose policy check includes evidence exceptions (as _execute)
# Estimated hosted image calls per job, used only to decide how many budget-limited jobs to release; the send-time
# reserve_call stays authoritative (a job that runs out still re-blocks with a budget reason).
BUDGET_COST = {"image_analysis": 1, "photo_analysis": 1, "video_analysis": 4}
RELEASE_LOCK = "blocked_release_lock"
SWEEP_S, CAP_WATCH_S = 300, 30


def policy_reason(pe: dict) -> dict:
    kind = "visit_restriction" if str(pe.get("basis", "")).startswith("legacy_visit_") else "policy"
    return {"kind": kind, "basis": pe.get("basis"), "policy_version": pe.get("policy_version"), "at": iso()}


async def budget_reason() -> dict:
    b = await db.cal_budget.find_one({"_id": "hosted_image_calls"}, {"cap": 1, "used": 1}) or {}
    return {"kind": "budget", "budget_cap": b.get("cap"), "budget_used": b.get("used"), "at": iso()}


async def _release_pass(trigger: str) -> dict:
    import calibration
    import policy
    budget = await db.cal_budget.find_one({"_id": "hosted_image_calls"}) or {}
    available = max(0, budget.get("cap", 0) - budget.get("used", 0))
    async for queued in db.jobs.find({"status": "Queued", "stage": {"$in": list(BUDGET_COST)}}):
        available -= BUDGET_COST[queued["stage"]]
    released, kept = [], 0
    budget_trigger = trigger in ("budget_cap_raised", "budget_available")
    async for job in db.jobs.find({"status": "Blocked"}).sort("created_at", 1):
        is_budget = job.get("blocker") == calibration.BUDGET_MSG
        known_hold = job.get("blocker") in (BLOCKER, policy.BLOCKED_MSG, calibration.BUDGET_MSG)
        if not known_hold or _active_lease(job) or (is_budget and not budget_trigger):
            kept += 1
            continue
        decision = await policy.evaluate_job(job)
        if not decision["allowed"]:
            kept += 1
            continue
        cost = BUDGET_COST.get(job["stage"], 0)
        if cost and cost > available:
            kept += 1
            if not is_budget:
                await db.jobs.update_one(_idle_snapshot(job), {"$set": {
                    "blocker": calibration.BUDGET_MSG, "block_reason": await budget_reason(),
                    "updated_at": iso()}, "$inc": {"revision": 1}})
            continue
        result = await db.jobs.update_one(_idle_snapshot(job), {"$set": {
            "status": "Queued", "blocker": None, "block_reason": None,
            "last_block_reason": job.get("block_reason") or {"kind": "budget" if is_budget else "policy", "inferred": True},
            "error": None, "error_stage": None, "lease_owner": None, "lease_token": None, "lease_until": None,
            "released_at": iso(), "release_trigger": trigger, "updated_at": iso(), "updated_by": "system"},
            "$inc": {"release_count": 1, "revision": 1}})
        if result.modified_count:
            available -= cost
            released.append(job["uuid"])
    return {"released": released, "kept": kept}


async def release_blocked(trigger: str) -> dict:
    """Serialised across triggers/processes by a Mongo lock; a trigger arriving mid-pass asks the holder to run once more."""
    from pymongo.errors import DuplicateKeyError
    token = new_id()
    for _ in range(5):
        t = now()
        try:
            await db.meta.find_one_and_update({"_id": RELEASE_LOCK, "until": {"$lt": iso(t)}},
                                              {"$set": {"owner": token, "until": iso(t + timedelta(seconds=120)), "rerun": False}}, upsert=True)
            break
        except DuplicateKeyError:
            r = await db.meta.update_one({"_id": RELEASE_LOCK, "until": {"$gte": iso(t)}}, {"$set": {"rerun": True}})
            if r.matched_count:
                return {"deferred": True, "trigger": trigger, "released": []}
    else:
        return {"deferred": True, "trigger": trigger, "released": []}
    out = {"deferred": False, "trigger": trigger, "released": [], "kept": 0}
    try:
        while True:
            res = await _release_pass(trigger)
            out["released"] += res["released"]
            out["kept"] = res["kept"]
            r = await db.meta.update_one({"_id": RELEASE_LOCK, "owner": token, "rerun": {"$ne": True}}, {"$set": {"until": ""}})
            if r.modified_count:
                return out
            await db.meta.update_one({"_id": RELEASE_LOCK, "owner": token}, {"$set": {"rerun": False, "until": iso(now() + timedelta(seconds=120))}})
    except Exception:
        await db.meta.update_one({"_id": RELEASE_LOCK, "owner": token}, {"$set": {"until": ""}})
        raise


async def blocked_release_loop():
    """Safety net: full re-evaluation every 5 min. Every 30 s: a raised cap, or remaining calls while budget-blocked work waits
    (covers a cap changed twice between two ticks), releases budget-limited jobs."""
    loop, last_cap, last_sweep = asyncio.get_running_loop(), None, None
    while True:
        try:
            b = await db.cal_budget.find_one({"_id": "hosted_image_calls"}, {"cap": 1, "used": 1}) or {}
            cap = b.get("cap")
            waiting = cap is not None and cap > b.get("used", 0) and await db.jobs.find_one({"status": "Blocked", "block_reason.kind": "budget"}, {"_id": 1})
            if (last_cap is not None and cap is not None and cap > last_cap) or waiting:
                await release_blocked("budget_cap_raised" if last_cap is not None and cap > last_cap else "budget_available")
                last_sweep = loop.time()
            elif last_sweep is None or loop.time() - last_sweep >= SWEEP_S:
                await release_blocked("sweep")
                last_sweep = loop.time()
            last_cap = cap
        except Exception:
            log.exception("blocked release sweep")
        await asyncio.sleep(CAP_WATCH_S)


async def _claim(stage: str):
    """B3: every claim gets a fresh fencing token; all later writes for that execution must present it."""
    t = now()
    return await db.jobs.find_one_and_update(
        {"stage": stage, "$or": [{"status": "Queued"}, {"status": "Running", "lease_until": {"$lt": iso(t)}}]},
        {"$set": {"status": "Running", "lease_owner": OWNER, "lease_token": new_id(), "lease_until": iso(t + LEASE), "started_at": iso(t),
                  "updated_at": iso(t)}, "$inc": {"attempts": 1, "fence": 1}},
        sort=[("created_at", 1)], return_document=True,
    )


def _fence(job) -> dict:
    return {"uuid": job["uuid"], "lease_token": job.get("lease_token"), "status": "Running"}


async def holds_lease(job) -> bool:
    return bool(await db.jobs.find_one(_fence(job), {"_id": 1}))


async def renew(job) -> bool:
    r = await db.jobs.update_one(_fence(job), {"$set": {"lease_until": iso(now() + LEASE), "updated_at": iso()}})
    return r.modified_count == 1


async def _set_fenced(job, fields: dict) -> bool:
    r = await db.jobs.update_one(_fence(job), {"$set": {**fields, "lease_owner": None, "lease_token": None, "lease_until": None, "updated_at": iso()}})
    if not r.modified_count:
        log.warning("fenced: stale execution of job %s (%s) ignored", job["uuid"], job["stage"])
    return r.modified_count == 1


async def _take_fault(visit_id: str, stage: str, target_id: str = None):
    f = await db.faults.find_one_and_delete({"visit_id": visit_id, "stage": stage, "target_id": {"$in": [None, target_id]}})
    return f and f"Injected {stage} failure (test fault injection)"


async def _finish(job, status, error=None, error_stage=None, run_id=None) -> bool:
    return await _set_fenced(job, {"status": status, "error": error, "error_stage": error_stage, "last_run_id": run_id, "finished_at": iso()})


async def run_transcription(job, visit):
    ev = await db.evidence.find_one({"uuid": job["target_id"]})
    data = await asyncio.to_thread(storage.get_object, ev["storage_path"])
    if sha256_hex(data) != ev["sha256"]:
        return await _finish(job, "Failed", "Stored audio hash mismatch", "source")
    fault = await _take_fault(visit["uuid"], "transcription", ev["uuid"])
    if fault:
        return await _finish(job, "Failed", fault, "model")
    suffix = "." + (ev.get("filename", "a.m4a").rsplit(".", 1)[-1] or "m4a")
    res = await asyncio.to_thread(ai_local.transcribe, data, suffix)
    if not await holds_lease(job):  # C6: a reclaimed (stale) worker must not commit a transcript
        log.warning("fenced: transcription job %s lost its lease before commit", job["uuid"])
        return
    latest = await db.transcripts.find_one({"evidence_id": ev["uuid"]}, sort=[("version", -1)])
    version = (latest["version"] + 1) if latest else 1
    tid = new_id()
    await db.transcripts.insert_one({
        "uuid": tid, "workspace_id": ev["workspace_id"], "visit_id": ev["visit_id"], "evidence_id": ev["uuid"],
        "version": version, "kind": "machine", "text": res["text"], "model_id": res["model_id"],
        "source_sha256": ev["sha256"], "audio_ref": ev["storage_path"], "language": res["language"],
        "audio_duration_s": res["audio_duration_s"], "processing_s": res["processing_s"], "job_id": job["uuid"],
        "created_at": iso(), "created_by": "system", "updated_at": iso(), "updated_by": "system", "revision": 1,
    })
    await _finish(job, "Done", run_id=tid)
    await enqueue(visit, "extraction", ev["uuid"], "audio", force_requeue=True)
    await enqueue(visit, "text_checks", tid, "transcript")


async def source_text(ev) -> tuple[str, str, str]:
    """(text, source_sha256, transcript_id|None) for a note or audio evidence."""
    if ev["kind"] == "note":
        return ev["text"], ev["sha256"], None
    t = await db.transcripts.find_one({"evidence_id": ev["uuid"]}, sort=[("version", -1)])
    return (t["text"], sha256_hex(t["text"].encode()), t["uuid"]) if t else ("", "", None)


async def run_extraction(job, visit):
    ev = await db.evidence.find_one({"uuid": job["target_id"]})
    text, src_hash, tid = await source_text(ev)
    if not text.strip():
        return await _finish(job, "Failed", "No transcript text available yet", "source")
    fault = await _take_fault(visit["uuid"], "extraction", ev["uuid"])
    res = await asyncio.to_thread(ai_local.extract, text, fault)
    if not await holds_lease(job):  # C6: no extraction run / proposed fields from a stale worker
        log.warning("fenced: extraction job %s lost its lease before commit", job["uuid"])
        return
    run_id = new_id()
    await db.extraction_runs.insert_one({
        "uuid": run_id, "workspace_id": ev["workspace_id"], "visit_id": ev["visit_id"], "job_id": job["uuid"],
        "source_evidence_id": ev["uuid"], "source_kind": ev["kind"], "transcript_id": tid, "source_sha256": src_hash,
        "input_text": text, "model_id": res["model_id"], "prompt_version": ai_local.EXTRACT_PROMPT_VERSION,
        "status": res["status"], "fields": res["fields"], "rejected": res["rejected"], "raw_responses": res["raw_responses"],
        "attempts": res["attempts"], "duration_s": res["duration_s"], "error": res["error"], "error_stage": res["error_stage"],
        "created_at": iso(), "created_by": "system", "updated_at": iso(), "updated_by": "system", "revision": 1,
    })
    if res["status"] != "Done":
        if res["error_stage"] == "model_process":  # model child crashed/overran: retryable, same as the deadline path
            return await _set_fenced(job, {"status": "Failed", "error": res["error"], "error_stage": "model_process", "retryable": True,
                                           "last_run_id": run_id, "finished_at": iso()})
        return await _finish(job, "Failed", res["error"], res["error_stage"], run_id)
    if not await holds_lease(job):  # C6: re-check right before replacing the active proposed fields
        return
    await db.proposed_fields.update_many({"source_evidence_id": ev["uuid"], "active": True}, {"$set": {"active": False}})
    for k, item in res["fields"].items():
        if item is None:
            continue
        await db.proposed_fields.insert_one({
            "uuid": new_id(), "workspace_id": ev["workspace_id"], "visit_id": ev["visit_id"], "field": k,
            "value": item["value"], "excerpt": item["excerpt"], "source_evidence_id": ev["uuid"], "source_kind": ev["kind"],
            "transcript_id": tid, "run_id": run_id, "model_id": res["model_id"], "active": True,
            "created_at": iso(), "created_by": "system", "updated_at": iso(), "updated_by": "system", "revision": 1,
        })
    await _finish(job, "Done", run_id=run_id)


async def run_image(job, visit):
    ev = await db.evidence.find_one({"uuid": job["target_id"]})
    data = await asyncio.to_thread(storage.get_object, ev["storage_path"])
    if sha256_hex(data) != ev["sha256"]:
        return await _finish(job, "Failed", "Stored photo hash mismatch", "source")
    fault = await _take_fault(visit["uuid"], "image_analysis", ev["uuid"])
    import calibration
    # Reuse only this job's durable, verified primary result. A secondary retry must not pay for
    # the tie/fastener check again or create a second set of its review candidates.
    prior = None if fault else await db.image_analysis_runs.find_one({
        "job_id": job["uuid"], "evidence_id": ev["uuid"], "photo_sha256": ev["sha256"],
        "model_id": ai_image.PROVIDER.model_id, "prompt_version": ai_image.PROMPT_VERSION,
        "status": "Done", "candidate_payloads": {"$type": "array"}}, sort=[("created_at", -1)])
    if prior:
        run_id, payloads = prior["uuid"], prior["candidate_payloads"]
    else:
        # Reserve immediately before EVERY provider send, including retries and validation repair.
        res = await ai_image.analyze(data, f"img-{ev['uuid']}-{job['attempts']}", inject_failure=fault,
                                     reserve=None if fault else (lambda: calibration.reserve_call(1)))
        if res.get("error_stage") == "budget":
            await _set_fenced(job, {"status": "Blocked", "blocker": calibration.BUDGET_MSG, "block_reason": await budget_reason()})
            return
        if res.get("status") == "Done" and not res.get("candidates") and res.get("rejected"):
            res = {**res, "status": "Failed", "error_stage": "validation",
                   "error": "Photo check returned candidates that could not be validated. Retry the check."}
        if not await holds_lease(job):
            log.warning("fenced: image job %s lost its lease before commit", job["uuid"])
            return
        run_id = new_id()
        outcome, payloads = None, []
        if res["status"] == "Done":
            if res["image_assessability"] == "cannot_assess":
                outcome = "Cannot assess. Request closer photo"
            elif not res["candidates"] and res.get("rejected"):
                outcome = "Results could not be checked"
            elif not res["candidates"]:
                outcome = "No candidate identified in this image"
            else:
                outcome = f"{len(res['candidates'])} candidate(s) for review"
            cal_field = await calibration.live_candidate_calibration(ev["workspace_id"])
            payloads = [{"uuid": new_id(), "candidate": c, "calibration": cal_field} for c in res["candidates"]]
        if not await holds_lease(job):
            return
        await db.image_analysis_runs.insert_one({
            "uuid": run_id, "workspace_id": ev["workspace_id"], "visit_id": ev["visit_id"], "job_id": job["uuid"],
            "evidence_id": ev["uuid"], "photo_sha256": ev["sha256"], "provider": ai_image.PROVIDER.provider,
            "model_id": ai_image.PROVIDER.model_id, "prompt_version": ai_image.PROMPT_VERSION, "status": res["status"],
            "image_assessability": res.get("image_assessability"), "cannot_assess_reason": res.get("cannot_assess_reason"),
            "outcome_label": outcome, "candidates": len(res.get("candidates", [])), "rejected_candidates": res.get("rejected", []), "raw_responses": res["raw_responses"],
            "candidate_payloads": payloads,
            "attempts": res["attempts"], "duration_s": res["duration_s"], "error": res["error"], "error_stage": res["error_stage"],
            "created_at": iso(), "created_by": "system", "updated_at": iso(), "updated_by": "system", "revision": 1,
        })
        if res["status"] != "Done":
            return await _finish(job, "Failed", res["error"], res["error_stage"], run_id)
    # Candidate UUIDs were persisted with the primary result before any candidate write. A
    # restarted worker resumes these upserts, retaining prior review decisions and provenance.
    for payload in payloads:
        if not await holds_lease(job):
            return
        c = payload["candidate"]
        await db.visual_candidates.update_one({"uuid": payload["uuid"]}, {"$setOnInsert": {
            "calibration": payload["calibration"],
            "uuid": payload["uuid"], "workspace_id": ev["workspace_id"], "visit_id": ev["visit_id"], "evidence_id": ev["uuid"],
            "photo_sha256": ev["sha256"], "run_id": run_id, "source": "server_model", **c,
            "region_frame": {"kind": "oriented_full"},
            "raw_output": c, "model_id": ai_image.PROVIDER.model_id, "prompt_version": ai_image.PROMPT_VERSION,
            "review_state": "Pending", "decisions": [], "revision": 1,
            "created_at": iso(), "created_by": "system", "updated_at": iso(), "updated_by": "system",
        }}, upsert=True)
    if not await holds_lease(job):
        return
    import photo_pipeline
    secondary = await photo_pipeline.run_rail_surface_for_evidence(ev, data, job, run_id)
    if secondary.get("status") == "budget_limited":
        await _set_fenced(job, {"status": "Blocked", "blocker": calibration.BUDGET_MSG,
                                "block_reason": await budget_reason(), "last_run_id": run_id})
        return
    # Usable partial output stays reviewable; an entirely failed secondary check remains
    # retryable through the ordinary photo job and cannot be called a completed check.
    if secondary.get("status") not in ("complete", "partial") or (secondary.get("status") == "partial" and not secondary.get("candidates")):
        return await _finish(job, "Failed", "Rail-surface check could not be completed. Retry the photo check.", "rail_surface", run_id)
    await _finish(job, "Done", run_id=run_id)


async def run_text_checks(job, visit):
    """Jev urgent-concern + embedded-instruction flags on a note or transcript version. Replay by input hash = zero calls."""
    if job["source_kind"] == "note":
        src = await db.evidence.find_one({"uuid": job["target_id"]})
        evidence_id = src["uuid"]
    else:
        src = await db.transcripts.find_one({"uuid": job["target_id"]})
        evidence_id = src["evidence_id"]
    text = src["text"] or ""
    h = sha256_hex(text.encode())
    existing = await db.text_checks.find_one({"kind": "text_flags", "input_sha256": h, "status": "Done", "workspace_id": visit["workspace_id"]})
    if existing:
        result, model_id, reused = existing["result"], existing["model_id"], True
    else:
        if await _take_fault(visit["uuid"], "text_checks", job["target_id"]):
            return await _finish(job, "Failed", "Injected text_checks failure (test fault injection)", "provider")
        result = await ai_jev.text_flags(text)
        model_id, reused = result["model_id"], False
    cid = new_id()
    await db.text_checks.insert_one({
        "uuid": cid, "workspace_id": visit["workspace_id"], "visit_id": visit["uuid"], "kind": "text_flags",
        "target_id": job["target_id"], "target_kind": job["source_kind"], "evidence_id": evidence_id, "input_sha256": h,
        "model_id": model_id, "result": result, "reused_from_cache": reused, "status": "Done", "job_id": job["uuid"],
        "created_at": iso(), "created_by": "system", "updated_at": iso(), "updated_by": "system", "revision": 1})
    await _finish(job, "Done", run_id=cid)


async def run_depth(job, visit):
    import scenes
    await scenes.run_depth(job, visit, _finish, _take_fault)


async def run_video(job, visit):
    import video_pipeline
    await video_pipeline.run_video(job, visit, _finish, holds_lease)


async def run_photo_analysis(job, visit):
    """Phase 7 two-stage analysis as a durable leased job (target_id = image_analysis_runs.uuid); resumable, fenced."""
    import photo_pipeline
    await photo_pipeline.execute(job["target_id"], job=job)
    await _finish(job, "Done", run_id=job["target_id"])


HANDLERS = {"text_checks": run_text_checks, "transcription": run_transcription, "extraction": run_extraction, "image_analysis": run_image,
            "depth": run_depth, "photo_analysis": run_photo_analysis, "video_analysis": run_video}


async def _execute(job):
    import policy
    if not await holds_lease(job):
        return
    visit = await db.visits.find_one({"uuid": job["visit_id"], "workspace_id": job["workspace_id"]})
    ev = await policy.evaluate_job(job)  # fresh per-evidence policy, including photo-run/transcript targets
    await db.jobs.update_one(_fence(job), {"$set": {"policy": {k: ev[k] for k in ("allowed", "basis", "policy_version")}}})
    if not ev["allowed"]:
        await _set_fenced(job, {"status": "Blocked", "blocker": BLOCKER, "block_reason": policy_reason(ev)})
        return

    async def keepalive():  # B3: renew the lease while the handler runs; stop once fenced out
        while await renew(job):
            await asyncio.sleep(LEASE.total_seconds() / 3)
    ka = asyncio.create_task(keepalive())
    try:
        # C3: overall deadline per job; a stalled provider/processing call fails retryable and releases the lease
        await asyncio.wait_for(HANDLERS[job["stage"]](job, visit), timeout=DEADLINE_S[job["stage"]])
    except asyncio.TimeoutError:
        log.warning("job %s (%s) exceeded its %ss deadline", job["uuid"], job["stage"], DEADLINE_S[job["stage"]])
        await _set_fenced(job, {"status": "Failed", "error": "Check did not finish. Retry", "error_stage": "deadline", "retryable": True, "finished_at": iso()})
    except Exception as e:
        log.exception("job %s failed", job["uuid"])
        await _finish(job, "Failed", f"{type(e).__name__}: {e}"[:500], "worker")
    finally:
        ka.cancel()


async def _stage_loop(stage: str):
    running: set = set()
    while True:
        try:
            running = {t for t in running if not t.done()}
            while len(running) < CONCURRENCY[stage]:
                job = await _claim(stage)
                if not job:
                    break
                running.add(asyncio.create_task(_execute(job)))
        except Exception:
            log.exception("stage loop %s", stage)
        await asyncio.sleep(1.0)


async def recover_dead_leases():
    """Single worker process: a Running job leased by another owner was orphaned by a restart/reload -> requeue it."""
    r = await db.jobs.update_many({"status": "Running", "lease_owner": {"$ne": OWNER}},
                                  {"$set": {"status": "Queued", "lease_owner": None, "lease_token": None, "lease_until": None, "updated_at": iso()}})
    if r.modified_count:
        log.info("requeued %s orphaned jobs", r.modified_count)


async def missing_jobs(since: str | None = None, workspace_id: str | None = None, limit: int = 2000) -> list:
    """B2: received (receipted) evidence whose expected processing jobs do not exist. Demo workspaces copy analyses → excluded."""
    q = {"upload_state": "Verified", "workspace_id": {"$not": {"$regex": "^ws-demo-"}}}  # REQ-1221: receipts no longer gate analysis
    if workspace_id:
        q["workspace_id"] = workspace_id
    if since:
        q["created_at"] = {"$gte": since}
    out = []
    async for ev in db.evidence.find(q, {"_id": 0, "uuid": 1, "kind": 1, "visit_id": 1, "workspace_id": 1, "created_at": 1}).limit(limit):
        for st in EXPECTED.get(ev["kind"], []):
            if not await db.jobs.find_one({"stage": st, "target_id": ev["uuid"]}, {"_id": 1}):
                out.append({**ev, "stage": st})
    return out


async def recovery_pass(since: str | None, workspace_id: str | None = None, stages: list | None = None) -> dict:
    gaps = [g for g in await missing_jobs(since, workspace_id) if not stages or g["stage"] in stages]
    for g in gaps:
        v = await db.visits.find_one({"uuid": g["visit_id"]})
        if v:
            await enqueue(v, g["stage"], g["uuid"], g["kind"])
    if gaps:
        log.info("recovery pass enqueued %s missing jobs", len(gaps))
    return {"enqueued": len(gaps), "items": [{k: g[k] for k in ("uuid", "stage", "visit_id")} for g in gaps[:50]]}


async def recovery_loop():
    """Automatic B2 recovery for receipts after the fix (budget-safe); older gaps are admin-applied via /api/admin/recovery."""
    m = await db.meta.find_one_and_update({"_id": "b2_recovery_since"}, {"$setOnInsert": {"at": iso()}}, upsert=True, return_document=True)
    while True:
        try:
            import policy
            await policy.recover_pending()
            await recover_policy_blocked()
            await recovery_pass(m["at"])
        except Exception:
            log.exception("recovery pass")
        await asyncio.sleep(300)


async def release_own_leases():
    """On graceful shutdown/reload, hand this worker's Running jobs back to the queue instead of waiting for lease expiry."""
    await db.jobs.update_many({"status": "Running", "lease_owner": OWNER},
                              {"$set": {"status": "Queued", "lease_owner": None, "lease_token": None, "lease_until": None, "updated_at": iso()}})


def start_workers():
    for s in STAGES:
        asyncio.create_task(_stage_loop(s))
    asyncio.create_task(recovery_loop())
    asyncio.create_task(blocked_release_loop())


async def retry(job: dict, user: dict):
    import policy
    import calibration
    key = {"uuid": job["uuid"], "workspace_id": user["workspace_id"]}
    current = await db.jobs.find_one(key)
    if not current or current.get("visit_id") != job["visit_id"]:
        raise RetryBlocked("not_found", "Check not found.")
    if current["status"] in ("Queued", "Running"):
        return current  # lost-ack/concurrent retry; no new execution or lease write
    if current["status"] not in ("Failed", "Blocked"):
        raise RetryBlocked("not_retryable", "This check has already finished.")
    if _active_lease(current):
        raise RetryBlocked("active_lease", "This check is still running.")
    if current["status"] == "Blocked" and current.get("blocker") not in (BLOCKER, policy.BLOCKED_MSG, calibration.BUDGET_MSG):
        raise RetryBlocked("other_hold", "Resolve this check's existing hold before retrying.")
    if not (await policy.evaluate_job(current))["allowed"]:
        raise RetryBlocked("blocked", BLOCKER)
    if not await _budget_available(current):
        raise RetryBlocked("budget_reached", calibration.BUDGET_MSG)
    updated = await db.jobs.find_one_and_update(_idle_snapshot(current),
        {"$set": {"status": "Queued", "blocker": None, "error": None, "error_stage": None,
                  "lease_owner": None, "lease_token": None, "lease_until": None,
                  "updated_at": iso(), "updated_by": user["uuid"]}, "$inc": {"revision": 1}}, return_document=True)
    if updated:
        await audit(user, current["workspace_id"], "processing_retry", "job", current["uuid"], {"stage": current["stage"]})
        return updated
    return await db.jobs.find_one(key)


def _active_lease(job):
    return bool(job.get("lease_until") and job["lease_until"] > iso())


def _idle_snapshot(job):
    """CAS includes the observed state and lease, so a later claim always wins."""
    q = {"uuid": job["uuid"], "workspace_id": job["workspace_id"], "status": job["status"]}
    q.update({k: job.get(k) for k in ("lease_owner", "lease_token", "lease_until")})
    q.update({k: job[k] for k in ("revision", "updated_at") if k in job})
    return q


async def _budget_available(job):
    if job["stage"] not in ("image_analysis", "photo_analysis", "video_analysis"):
        return True
    # Do not call calibration.budget(): it can initialize or change the cap.
    b = await db.cal_budget.find_one({"_id": "hosted_image_calls"})
    return bool(b and b.get("cap", 0) > b.get("used", 0))


class RetryBlocked(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.message = code, message


async def recover_policy_blocked():
    """Finish a permission-change reconciliation interrupted by a crash or failed response."""
    import policy
    seen = set()
    async for job in db.jobs.find({"status": "Blocked", "blocker": {"$in": [BLOCKER, policy.BLOCKED_MSG]}}):
        key = (job["workspace_id"], job["visit_id"])
        if key in seen:
            continue
        seen.add(key)
        await on_permission_change({"workspace_id": key[0], "uuid": key[1]}, "sweep")
