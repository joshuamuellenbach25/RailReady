"""C1: missing-analysis recovery, deduplicated by (original SHA-256, analysis version).
One real check per distinct image (tie/fastener + rail-surface, budget reserved before every send by the normal job);
every other copy gets its OWN run + candidates with a provenance link to the source run. Idempotent: one image_analysis
job per evidence id (unique index), copies are keyed by (evidence, source run) and never duplicated on re-run.
Policy is re-checked per photo at attach time."""
import asyncio
import logging

import ai_image
import jobs as J
import policy
import rail_surface as RS
from core import db, iso, new_id

log = logging.getLogger("recovery_c1")
VERSION = ai_image.PROMPT_VERSION


async def _source_runs(sha: str, ws: str):
    legacy = await db.image_analysis_runs.find_one({"photo_sha256": sha, "workspace_id": ws, "model_id": ai_image.PROVIDER.model_id, "prompt_version": VERSION, "status": "Done",
                                                    "pipeline": {"$exists": False}, "copied_from_run_id": None}, sort=[("created_at", -1)])
    rail = await db.image_analysis_runs.find_one({"photo_sha256": sha, "workspace_id": ws, "model_id": ai_image.PROVIDER.model_id,
                                                  "prompt_version": RS.PROMPT_VERSION, "pipeline": RS.PIPELINE, "schema_version": RS.SCHEMA_VERSION,
                                                  "$or": [{"status": "complete"}, {"status": "partial", "candidates": {"$gt": 0}}],
                                                  "copied_from_run_id": None}, sort=[("created_at", -1)])
    return legacy, rail


async def _copy_run(src: dict, ev: dict, job_id: str) -> str:
    existing = await db.image_analysis_runs.find_one({"evidence_id": ev["uuid"], "copied_from_run_id": src["uuid"]}, {"uuid": 1})
    if existing:
        return existing["uuid"]
    rid = new_id()
    doc = {k: v for k, v in src.items() if k not in ("_id", "uuid", "raw_responses")}
    doc.update({"uuid": rid, "workspace_id": ev["workspace_id"], "visit_id": ev["visit_id"], "evidence_id": ev["uuid"], "job_id": job_id,
                "copied_from_run_id": src["uuid"], "provenance": {"kind": "identical_bytes_copy", "source_run_id": src["uuid"],
                "source_evidence_id": src["evidence_id"], "sha256": src["photo_sha256"], "provider_calls": 0}, "raw_responses": [],
                "created_at": iso(), "updated_at": iso()})
    await db.image_analysis_runs.insert_one(doc)
    async for c in db.visual_candidates.find({"run_id": src["uuid"]}):
        await db.visual_candidates.insert_one({**{k: v for k, v in c.items() if k not in ("_id", "uuid")}, "uuid": new_id(), "run_id": rid,
                                               "workspace_id": ev["workspace_id"], "visit_id": ev["visit_id"], "evidence_id": ev["uuid"],
                                               "copied_from_candidate_id": c["uuid"], "review_state": "Pending", "decisions": [], "revision": 1,
                                               "linked_observation_id": None, "created_at": iso(), "updated_at": iso()})
    return rid


async def run(workspace_id: str, wait_s: int = 600) -> dict:
    gaps = [g for g in await J.missing_jobs(None, workspace_id, 10000) if g["stage"] == "image_analysis"]
    groups: dict = {}
    for g in gaps:
        ev = await db.evidence.find_one({"uuid": g["uuid"]}, {"_id": 0})
        groups.setdefault(ev["sha256"], []).append(ev)
    out = {"gaps": len(gaps), "distinct_images": len(groups), "groups": []}
    for sha, evs in groups.items():
        legacy, rail = await _source_runs(sha, workspace_id)
        src_ev = evs[0]
        if not (legacy and rail):  # one real check for this image through the normal leased job (policy + budget checks inside)
            v = await db.visits.find_one({"uuid": src_ev["visit_id"]})
            await J.enqueue(v, "image_analysis", src_ev["uuid"], "photo")
            t_end = asyncio.get_running_loop().time() + wait_s
            while asyncio.get_running_loop().time() < t_end:
                j = await db.jobs.find_one({"stage": "image_analysis", "target_id": src_ev["uuid"]})
                if j["status"] in ("Done", "Failed", "Blocked"):
                    break
                await asyncio.sleep(3)
            if j["status"] != "Done":
                out["groups"].append({"sha256": sha, "copies": len(evs), "source_evidence": src_ev["uuid"], "status": j["status"], "blocker": j.get("blocker"), "error": j.get("error")})
                continue
            legacy, rail = await _source_runs(sha, workspace_id)
            evs = evs[1:]  # the source photo already has its own real run
        attached, blocked = 0, 0
        for ev in evs:
            v = await db.visits.find_one({"uuid": ev["visit_id"]})
            pol = await policy.evaluate(v, ev["uuid"])  # re-check per photo at run time
            jid = new_id()
            try:
                await db.jobs.insert_one({"uuid": jid, "workspace_id": ev["workspace_id"], "visit_id": ev["visit_id"], "stage": "image_analysis",
                                          "target_id": ev["uuid"], "source_kind": "photo", "status": "Queued", "attempts": 0, "lease_owner": "recovery_c1",
                                          "lease_token": None, "created_at": iso(), "updated_at": iso(), "recovery": "c1_dedup"})
            except Exception:  # unique (stage, target_id): a job already exists -> idempotent re-run
                j = await db.jobs.find_one({"stage": "image_analysis", "target_id": ev["uuid"]})
                jid = j["uuid"]
                if j["status"] == "Done":
                    continue
            if not pol["allowed"]:
                await db.jobs.update_one({"uuid": jid}, {"$set": {"status": "Blocked", "blocker": J.BLOCKER, "updated_at": iso()}})
                blocked += 1
                continue
            lid = await _copy_run(legacy, ev, jid) if legacy else None
            if rail:
                await _copy_run(rail, ev, jid)
            await db.jobs.update_one({"uuid": jid}, {"$set": {"status": "Done", "last_run_id": lid, "finished_at": iso(), "updated_at": iso(),
                                                              "provenance": {"copied_from_run_id": legacy and legacy["uuid"], "rail_source_run_id": rail and rail["uuid"]}}})
            attached += 1
        out["groups"].append({"sha256": sha, "copies": len(groups[sha]), "source_evidence": src_ev["uuid"], "legacy_source_run": legacy and legacy["uuid"],
                              "legacy_outcome": legacy and legacy.get("outcome_label"), "rail_source_run": rail and rail["uuid"],
                              "rail_outcome": rail and rail.get("outcome_label"), "attached_copies": attached, "blocked": blocked})
    return out
