"""Depth-scene job + anchors service (persisted in Mongo, assets in private object storage)."""
import asyncio
import hashlib
import io
import logging
import os
import shutil
import tempfile
import time
from datetime import datetime

import numpy as np
from pymongo.errors import DuplicateKeyError

from core import db, iso, new_id, sha256_hex
import depth
import photo_scene_processor as P
import storage

log = logging.getLogger("scenes")
_grid_cache: dict = {}
RETRIES = 2


def scene_id_for(evidence_id: str) -> str:
    return f"scn-{evidence_id}"


def scene_key(source_sha: str) -> str:
    return P.processing_key(source_sha)


STAGING = "/tmp/railready-scene-staging"
os.makedirs(STAGING, exist_ok=True)


async def _io(fn, *a):
    """Object storage with bounded retries (transient errors)."""
    for i in range(RETRIES + 1):
        try:
            return await asyncio.to_thread(fn, *a)
        except Exception:
            if i == RETRIES:
                raise
            await asyncio.sleep(0.5 * (i + 1))


async def latest(evidence_id: str):
    return await db.scenes.find_one({"evidence_id": evidence_id}, sort=[("revision", -1)])


PROC_SESSION = {"session": None, "error": None, "provision": None}


def prepare_model():
    """Startup prep only (never per request): provision/verify the pinned model and open one CPU session."""
    path = os.environ["RAILREADY_DEPTH_MODEL_PATH"]
    try:
        PROC_SESSION["provision"] = P.provision_model(path)
        PROC_SESSION["session"], PROC_SESSION["error"] = P.DepthSession(path), None
        log.info("depth model ready (%s)", PROC_SESSION["provision"]["source"])
    except P.ProcessorError as e:
        PROC_SESSION["session"], PROC_SESSION["error"] = None, e.as_dict()
        log.error("depth model unavailable: %s", e.message)


async def _take_depth_fault(visit_id, evidence_id):
    f = await db.faults.find_one_and_delete({"visit_id": visit_id, "stage": "depth", "target_id": {"$in": [evidence_id, None]}})
    return (f.get("mode") or "error") if f else None


async def run_depth(job, visit, finish, take_fault):
    ev = await db.evidence.find_one({"uuid": job["target_id"]})
    sid = scene_id_for(ev["uuid"])
    key = scene_key(ev["sha256"])
    cur = await latest(ev["uuid"])
    await db.jobs.update_one({"uuid": job["uuid"]}, {"$set": {"started_at": iso(), "completed_at": None}})
    if cur and cur["scene_key"] == key and cur["status"] == "Ready" and not job.get("regenerate"):
        await ensure_anchors(cur)
        await db.jobs.update_one({"uuid": job["uuid"]}, {"$set": {"completed_at": iso(), "scene_uuid": cur["uuid"]}})
        return await finish(job, "Done", run_id=cur["uuid"])  # same photo + same processing key → same scene, no inference
    rev = (cur["revision"] + (1 if (cur["status"] == "Ready" or cur["scene_key"] != key) else 0)) if cur else 1
    import jobs as J
    if not await J.holds_lease(job):  # C6: stale worker writes no scene
        return
    t_start = time.time()
    base = {"scene_id": sid, "revision": rev, "workspace_id": ev["workspace_id"], "visit_id": ev["visit_id"], "evidence_id": ev["uuid"],
            "scene_key": key, "processor_revision": P.PROCESSOR_REVISION, "source_sha256": ev["sha256"], "source_filename": ev.get("filename"),
            "model": depth.MODEL, "projection": depth.PROJECTION, "camera": depth.CAMERA, "label": depth.LABEL, "mode": "photo_derived_depth", "job_id": job["uuid"]}
    await db.scenes.update_one({"scene_id": sid, "revision": rev}, {"$set": {**base, "status": "Processing", "error": None, "error_code": None, "retryable": None,
                                "updated_at": iso()}, "$setOnInsert": {"uuid": new_id(), "created_at": iso()}}, upsert=True)
    sdoc = await db.scenes.find_one({"scene_id": sid, "revision": rev})
    await db.jobs.update_one({"uuid": job["uuid"]}, {"$set": {"scene_uuid": sdoc["uuid"]}})

    async def fail(err: dict):
        status = "Unsupported" if err["code"] == "unsupported" else "Failed"
        await db.scenes.update_one({"scene_id": sid, "revision": rev}, {"$set": {"status": status, "error": err["message"], "error_code": err["code"],
                                    "retryable": err["retryable"], "updated_at": iso()}})
        await db.jobs.update_one({"uuid": job["uuid"]}, {"$set": {"completed_at": iso(), "error_code": err["code"], "retryable": err["retryable"]}})
        return await finish(job, "Failed" if err["retryable"] else "Done", err["message"], "depth")

    fault = await _take_depth_fault(visit["uuid"], ev["uuid"])
    try:
        data = await _io(storage.get_object, ev["storage_path"])
    except Exception:
        return await fail({"code": "storage_unavailable", "message": "Photo storage temporarily unavailable", "retryable": True})
    if sha256_hex(data) != ev["sha256"]:
        return await fail({"code": "source_mismatch", "message": "Stored photo does not match its recorded hash", "retryable": False})
    if PROC_SESSION["session"] is None and fault != "checksum":
        await asyncio.to_thread(prepare_model)  # worker context only (job), never in a request
    try:
        out = await asyncio.to_thread(P.build, data, PROC_SESSION["session"], fault=fault, source_sha256=ev["sha256"])
    except P.ProcessorError as e:
        return await fail(e.as_dict())
    except Exception as e:
        return await fail({"code": "depth_failed", "message": f"Depth processing failed ({type(e).__name__})", "retryable": True})
    m = out["manifest"]
    src = m["source"]
    transform = {"exif_orientation": src["exif_orientation"], "applied": depth._OPS.get(src["exif_orientation"], "none"), "raw_width": src["raw_width"],
                 "raw_height": src["raw_height"], "oriented_width": src["oriented_width"], "oriented_height": src["oriented_height"]}
    await db.evidence.update_one({"uuid": ev["uuid"]}, {"$set": {"exif_transform": transform, "oriented_width": src["oriented_width"],
                                                                  "oriented_height": src["oriented_height"]}})
    # unique staging dir per generation (job + revision + worker); cleaned in finally
    stage_dir = tempfile.mkdtemp(prefix=f"scene-{job['uuid'][:8]}-r{rev}-{jobs_owner()}-", dir=STAGING)
    prefix = f"railready/{ev['workspace_id']}/{ev['visit_id']}/scenes/{sid}/r{rev}"
    arts = {}
    t_up = time.time()
    try:
        files = {k: v for k, v in out["artifacts"].items()}
        mb = P.manifest_bytes(m)
        files["manifest"] = (mb, "application/json", "manifest.json")
        for k, (b, ct, fn) in files.items():
            with open(os.path.join(stage_dir, fn), "wb") as fh:
                fh.write(b)
        for k, (b, ct, fn) in files.items():
            if fault == "storage":
                raise ConnectionError("injected storage failure")
            path = f"{prefix}/{fn}"
            await _io(storage.put_object, path, open(os.path.join(stage_dir, fn), "rb").read(), ct)
            arts[k] = {"path": path, "sha256": hashlib.sha256(b).hexdigest(), "byte_length": len(b), "content_type": ct, "file": fn}
    except Exception:
        return await fail({"code": "storage_unavailable", "message": "Scene storage temporarily unavailable. Retry", "retryable": True})
    finally:
        shutil.rmtree(stage_dir, ignore_errors=True)
    ready = iso()
    vt = ev.get("verified_at")
    lat = round((datetime.fromisoformat(ready) - datetime.fromisoformat(vt)).total_seconds(), 2) if vt else None
    tm = {"decode_orient_s": m["timings_s"]["decode"], "inference_s": m["timings_s"]["inference"], "backproject_ply_s": m["timings_s"]["build"],
          "upload_s": round(time.time() - t_up, 3), "job_total_s": round(time.time() - t_start, 3), "verified_to_ready_s": lat}
    # Ready only after every artifact is stored privately (and only by the current lease holder - C6)
    if not await J.holds_lease(job):
        log.warning("fenced: depth job %s lost its lease before commit", job["uuid"])
        return
    await db.scenes.update_one({"scene_id": sid, "revision": rev}, {"$set": {
        "manifest": m, "scene_hash": hashlib.sha256(mb).hexdigest(), "artifacts": arts, "focal": out["focal"], "display_width": out["width"],
        "display_height": out["height"], "exif_transform": transform, "oriented_width": src["oriented_width"], "oriented_height": src["oriented_height"],
        "captured_at": ev.get("captured_at_exif") or ev.get("created_at"), "sample_width": out["width"], "sample_height": out["height"],
        "gaussians": m["splat"]["vertex_count"], "timings": tm, "inference_run": True, "reused_from_scene": None,
        "asset_path": arts["splat"]["path"], "depth_path": arts["display_z"]["path"], "asset_bytes": arts["splat"]["byte_length"],
        "asset_sha256": arts["splat"]["sha256"], "asset_format": "ply (3DGS binary_little_endian, 14 float props)",
        "status": "Ready", "error": None, "error_code": None, "ready_at": ready, "updated_at": ready}})
    await db.jobs.update_one({"uuid": job["uuid"]}, {"$set": {"regenerate": False, "completed_at": iso()}})
    sc = await db.scenes.find_one({"scene_id": sid, "revision": rev})
    await ensure_anchors(sc)
    await finish(job, "Done", run_id=sc["uuid"])


def jobs_owner():
    import jobs
    return jobs.OWNER.replace("/", "_")[-12:]


async def grid(scene):
    k = (scene["scene_id"], scene["revision"])
    if k not in _grid_cache:
        if len(_grid_cache) > 64:
            _grid_cache.clear()
        raw = await _io(storage.get_object, scene["depth_path"])
        _grid_cache[k] = np.load(io.BytesIO(raw), allow_pickle=False)
    return _grid_cache[k]


async def point_to_xyz(scene, u: float, v: float) -> list:
    """Through THAT revision's own grid only (old-processor revisions keep their own projection)."""
    g = await grid(scene)
    if scene.get("processor_revision") == P.PROCESSOR_REVISION:
        return P.anchor_from_point(g, scene["focal"], u, v)["xyz"]
    return [float(c) for c in depth.unproject(g, u, v, scene["oriented_width"] / scene["oriented_height"])]


def xyz_to_point(scene, xyz):
    if scene.get("processor_revision") == P.PROCESSOR_REVISION:
        return P.project(xyz, scene["focal"], scene["display_width"], scene["display_height"])
    return depth.project(xyz, scene["oriented_width"] / scene["oriented_height"])


def _valid_region(r):
    try:
        P.validate_box(r)
        return True
    except (ValueError, TypeError):
        return False


def oriented_region(it, ev=None):
    """Item region in the EXIF-oriented full-image frame (REQ-170). Current analysis already runs on oriented images
    (region_frame oriented_full) so it is never transformed twice; raw/crop frames are converted."""
    r = it.get("region")
    if not _valid_region(r):
        return None
    try:
        return [round(c, 6) for c in P.region_to_oriented(r, it.get("region_frame"), ((ev or {}).get("exif_transform") or {}).get("exif_orientation", 1))]
    except (ValueError, KeyError, TypeError):
        return None


async def items_for_evidence(evidence_id: str):
    """Candidates on this photo + observations on this photo that are not a candidate's linked observation."""
    cands = await db.visual_candidates.find({"evidence_id": evidence_id}).sort("created_at", 1).to_list(500)
    linked = {c.get("linked_observation_id") for c in cands if c.get("linked_observation_id")}
    obs = [o for o in await db.observations.find({"evidence_id": evidence_id, "kind": "finding"}).sort("created_at", 1).to_list(500)
           if o["uuid"] not in linked and not o.get("source_candidate_id")]
    return [("candidate", c) for c in cands] + [("observation", o) for o in obs]


def _anchor_doc(scene, kind, item_id, aid, version, xyz, ip, placement, actor, reason, source_region, actor_role=None, prev=None):
    return {"uuid": f"{aid}:v{version}", "anchor_id": aid, "version": version, "current": True, "workspace_id": scene["workspace_id"],
            "visit_id": scene["visit_id"], "evidence_id": scene["evidence_id"], "scene_id": scene["scene_id"], "scene_uuid": scene["uuid"],
            "scene_revision": scene["revision"], "item_id": item_id, "finding_id": item_id, "item_kind": kind, "xyz": xyz,
            "image_point": [round(c, 6) for c in ip] if ip else None, "location_basis": P.LOCATION_BASIS,
            "placement": "auto_box_center" if placement == "auto" else "manual",
            "placement_method": P.PLACEMENT if placement == "auto" else "manual_point_estimated_depth",
            "uncertainty": ("Position estimated from one photo's AI relative depth at the box centre; depth and scale unverified, may sit on a nearer/farther surface."
                            if placement == "auto" else "Manually placed by reviewer on AI-estimated depth; geometry and scale unverified."),
            "source_region": source_region, "stale": False, "actor": actor, "actor_role": actor_role, "at": iso(), "reason": reason, "previous_version": prev}


async def new_version(cur, scene, xyz, ip, placement, actor, reason, source_region, actor_role=None):
    """CAS: retire exactly the expected current version, then insert the next one (unique keys reject concurrent writers)."""
    old = await db.anchors.find_one_and_update({"uuid": cur["uuid"], "current": True, "version": cur["version"]}, {"$set": {"current": False}})
    if not old:
        return None
    doc = _anchor_doc(scene, cur["item_kind"], cur["item_id"], cur["anchor_id"], cur["version"] + 1, xyz, ip, placement, actor, reason,
                      source_region, actor_role, cur["version"])
    try:
        await db.anchors.insert_one(doc)
    except DuplicateKeyError:
        await db.anchors.update_one({"uuid": cur["uuid"]}, {"$set": {"current": True}})
        return None
    doc.pop("_id", None)
    return doc


async def ensure_anchors(scene):
    """Auto anchors at box centre for each validated region on THIS photo + revision (never transferred between photos/revisions).
    Duplicate deliveries upsert; manual placements survive auto refresh; a changed region refreshes only auto anchors (manual → stale flag)."""
    if scene["status"] != "Ready":
        return
    ev = await db.evidence.find_one({"uuid": scene["evidence_id"]})
    for kind, it in await items_for_evidence(scene["evidence_id"]):
        region = oriented_region(it, ev)
        cur = await db.anchors.find_one({"evidence_id": scene["evidence_id"], "scene_revision": scene["revision"], "item_id": it["uuid"], "current": True})
        if region is None:
            if cur and cur["placement"] != "manual" and not cur.get("stale"):
                await db.anchors.update_one({"uuid": cur["uuid"]}, {"$set": {"stale": True, "stale_reason": "Region no longer localized"}})
            continue
        x, y, w, h = region
        u, v = x + w / 2, y + h / 2
        if not cur:
            try:
                await db.anchors.insert_one(_anchor_doc(scene, kind, it["uuid"], new_id(), 1, await point_to_xyz(scene, u, v), [u, v], "auto", "system", None, region))
            except DuplicateKeyError:
                pass  # duplicate delivery – first one wins
        elif cur.get("source_region") is not None and cur["source_region"] != region:
            if cur["placement"] == "manual":
                if not cur.get("stale"):
                    await db.anchors.update_one({"uuid": cur["uuid"]}, {"$set": {"stale": True, "stale_reason": "Finding region changed after manual placement"}})
            else:
                await new_version(cur, scene, await point_to_xyz(scene, u, v), [u, v], "auto", "system", "Finding region changed", region)


def unplaced_reason(it, scene):
    if not it.get("evidence_id"):
        return "Not linked to a photo"
    if it.get("region") == "unlocalized" or it.get("region") is None:
        return "No localized region on this photo (unlocalized)"
    if not _valid_region(it.get("region")):
        return "Region failed validation"
    if not scene:
        return "No scene for this photo yet"
    if scene["status"] != "Ready":
        return f"Scene {scene['status']}" + (f": {scene.get('error')}" if scene.get("error") else "")
    return "Anchor not yet placed"
