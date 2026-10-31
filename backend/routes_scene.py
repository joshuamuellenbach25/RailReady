"""Phase 4 scene / inventory / anchor API. Every route is auth + workspace/parent scoped (404 foreign).
Browser media (<img>, viewer fetch) use short-lived scoped media tokens (?st=, ≤10 min) revalidated on every request."""
import asyncio
from datetime import timedelta
from typing import List, Optional

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel

from core import JWT_SECRET, audit, current_user, db, get_visit, iso, now, user_from_token, visit_scope
import depth
import jobs
import scenes
import storage

router = APIRouter(prefix="/api", tags=["scenes"])
MEDIA_TTL = timedelta(minutes=10)
JOB_STATUS = {"Queued": "Queued", "Running": "Processing", "Blocked": "Blocked", "Failed": "Failed"}


def media_token(user, evidence_id: str, scene_id: Optional[str] = None) -> str:
    return jwt.encode({"typ": "media", "uid": user["uuid"], "ws": user["workspace_id"], "ev": evidence_id, "sid": scene_id,
                       "exp": now() + MEDIA_TTL}, JWT_SECRET, algorithm="HS256")


async def media_access(request: Request, evidence_id: str):
    """Bearer/auth user, or a scoped media token for exactly this evidence. Re-checked on every request."""
    st = request.query_params.get("st")
    if st:
        try:
            p = jwt.decode(st, JWT_SECRET, algorithms=["HS256"])
        except jwt.ExpiredSignatureError:
            raise HTTPException(401, "Media link expired. Reopen the scene")
        except jwt.InvalidTokenError:
            raise HTTPException(401, "Invalid media link")
        if p.get("typ") != "media" or p.get("ev") != evidence_id:
            raise HTTPException(404, "Not found")
        user = await db.users.find_one({"uuid": p["uid"]})
        if not user or user["workspace_id"] != p["ws"] or (user.get("demo_expires_at") and user["demo_expires_at"] <= iso()):
            raise HTTPException(401, "Media link no longer valid")
    else:
        auth = request.headers.get("Authorization", "")
        user = await user_from_token(auth[7:] if auth.startswith("Bearer ") else request.query_params.get("auth"))
    ev = await db.evidence.find_one({"uuid": evidence_id, "workspace_id": user["workspace_id"]})
    if not ev or not await db.visits.find_one({"uuid": ev["visit_id"], **visit_scope(user)}):
        raise HTTPException(404, "Not found")
    return user, ev


async def _photo(user, evidence_id):
    ev = await db.evidence.find_one({"uuid": evidence_id, "workspace_id": user["workspace_id"], "kind": "photo"})
    if not ev:
        raise HTTPException(404, "Not found")
    v = await get_visit(user, ev["visit_id"])
    return ev, v


async def _ensure_job(v, ev):
    """Enqueue once per verified photo; if the processing key changed (new processor/model/settings) regenerate lazily on open."""
    if ev.get("upload_state") != "Verified":
        return
    job = await db.jobs.find_one({"stage": "depth", "target_id": ev["uuid"]})
    if not job:
        await jobs.enqueue(v, "depth", ev["uuid"], "photo")
        return
    sc = await scenes.latest(ev["uuid"])
    if job["status"] == "Done" and sc and sc["scene_key"] != scenes.scene_key(ev["sha256"]):
        await db.jobs.update_one({"uuid": job["uuid"], "status": "Done"}, {"$set": {"status": "Queued", "regenerate": False, "error": None, "updated_at": iso()}})


async def _status(ev):
    """Returns (scene, status, error, code, extra). While regenerating, the previous Ready revision is served explicitly
    (status "Regenerating", is_current False) – never a blank scene id while an older ready revision exists."""
    sc = await scenes.latest(ev["uuid"])
    job = await db.jobs.find_one({"stage": "depth", "target_id": ev["uuid"]})
    running = bool(job and job["status"] in ("Queued", "Running"))
    ready = sc if sc and sc["status"] == "Ready" else await db.scenes.find_one({"evidence_id": ev["uuid"], "status": "Ready"}, sort=[("revision", -1)])
    current = bool(ready and not running and ready["uuid"] == (sc or {}).get("uuid") and ready["scene_key"] == scenes.scene_key(ev["sha256"]))
    extra = {"is_current": current, "regenerating": running and ready is not None,
             "previous_revision": ready["revision"] if ready and not current else None,
             "pending_revision": sc["revision"] if sc and ready and sc["uuid"] != ready["uuid"] else None}
    if running and ready:
        return ready, "Regenerating", None, "regenerating", extra
    if sc and sc["status"] in ("Ready", "Failed", "Unsupported") and not running:
        if sc["status"] != "Ready" and ready:  # failed regeneration: keep serving the last ready revision, flag the failure
            return ready, "Ready", sc.get("error"), "regeneration_failed", extra
        return sc, sc["status"], sc.get("error"), sc.get("error_code"), extra
    if job:
        st = JOB_STATUS.get(job["status"], "Processing")
        return sc, st, job.get("blocker") if st == "Blocked" else None, "processing_not_permitted" if st == "Blocked" else None, extra
    if ev.get("upload_state") != "Verified":
        return sc, "Queued", "Waiting for verified upload", "awaiting_upload", extra
    return sc, "Queued", None, None, extra


@router.get("/visits/{visit_id}/scenes")
async def visit_scenes(visit_id: str, user=Depends(current_user)):
    v = await get_visit(user, visit_id)
    out = []
    for ev in await db.evidence.find({"visit_id": visit_id, "kind": "photo"}).sort("created_at", 1).to_list(200):
        await _ensure_job(v, ev)
        sc, st, err, code, extra = await _status(ev)
        out.append({"evidence_id": ev["uuid"], "filename": ev.get("filename"), "scene_id": scenes.scene_id_for(ev["uuid"]) if sc else None,
                    "scene_revision": sc["revision"] if sc else None, "status": st, "error": err, "error_code": code, **extra,
                    "oriented_width": (sc or ev).get("oriented_width"), "oriented_height": (sc or ev).get("oriented_height"),
                    "thumbnail_url": f"/api/media/evidence/{ev['uuid']}/thumbnail?st={media_token(user, ev['uuid'])}" if ev.get("upload_state") == "Verified" else None})
    return {"scenes": out, "label": depth.LABEL}


def _scene_view(user, ev, sc, st, err, code, extra=None):
    tok = media_token(user, ev["uuid"], sc["scene_id"] if sc else None)
    return {"scene_id": sc["scene_id"] if sc else None, "scene_revision": sc["revision"] if sc else None, "status": st, "error": err, "error_code": code,
            **(extra or {}),
            "source_sha256": ev["sha256"], "source_filename": ev.get("filename"),
            "captured_at": (sc or {}).get("captured_at") or ev.get("captured_at_exif") or ev.get("created_at"),
            "exif_transform": (sc or ev).get("exif_transform"), "oriented_width": (sc or ev).get("oriented_width"), "oriented_height": (sc or ev).get("oriented_height"),
            "model": depth.MODEL, "projection": (sc or {}).get("projection", depth.PROJECTION), "camera": (sc or {}).get("camera", depth.CAMERA),
            "sample_width": (sc or {}).get("sample_width"), "sample_height": (sc or {}).get("sample_height"), "gaussians": (sc or {}).get("gaussians"),
            "asset_bytes": (sc or {}).get("asset_bytes"), "asset_format": (sc or {}).get("asset_format"), "inference_run": (sc or {}).get("inference_run"),
            "reused_from_scene": (sc or {}).get("reused_from_scene"), "timings": (sc or {}).get("timings"),
            "asset_url": f"/api/scenes/{sc['scene_id']}/asset?rev={sc['revision']}&st={tok}" if sc and st in ("Ready", "Regenerating") else None,
            "asset_url_expires_at": iso(now() + MEDIA_TTL), "original_url": f"/api/media/evidence/{ev['uuid']}/original?st={tok}",
            "label": depth.LABEL, "mode": "photo_derived_depth"}


@router.get("/evidence/{evidence_id}/scene")
async def evidence_scene(evidence_id: str, user=Depends(current_user)):
    ev, v = await _photo(user, evidence_id)
    await _ensure_job(v, ev)
    return _scene_view(user, ev, *await _status(ev))


class RetryIn(BaseModel):
    regenerate: bool = False


@router.post("/evidence/{evidence_id}/scene/retry")
async def retry_scene(evidence_id: str, body: Optional[RetryIn] = None, user=Depends(current_user)):
    ev, v = await _photo(user, evidence_id)
    regen = bool(body and body.regenerate)
    await _ensure_job(v, ev)
    job = await db.jobs.find_one({"stage": "depth", "target_id": ev["uuid"]})
    sc = await scenes.latest(ev["uuid"])
    if job["status"] in ("Failed", "Done") and (regen or not (sc and sc["status"] == "Ready" and sc["scene_key"] == scenes.scene_key(ev["sha256"]))):
        await db.jobs.update_one({"uuid": job["uuid"], "status": job["status"]}, {"$set": {"status": "Queued", "error": None, "regenerate": regen,
                                 "updated_at": iso(), "updated_by": user["uuid"]}, "$inc": {"revision": 1}})
        await audit(user, ev["workspace_id"], "scene_regenerate" if regen else "scene_retry", "evidence", ev["uuid"])
    return _scene_view(user, ev, *await _status(ev))


async def _stream(path, mime):
    data = await scenes._io(storage.get_object, path)
    return Response(content=data, media_type=mime, headers={"Cache-Control": "private, no-store"})


@router.get("/scenes/{scene_id}/asset")
async def scene_asset(scene_id: str, request: Request, rev: Optional[int] = None):
    if not scene_id.startswith("scn-"):
        raise HTTPException(404, "Not found")
    user, ev = await media_access(request, scene_id[4:])
    q = {"scene_id": scene_id, "workspace_id": user["workspace_id"], "status": "Ready"}
    if rev is not None:
        q["revision"] = rev
    sc = await db.scenes.find_one(q, sort=[("revision", -1)])
    if not sc:
        raise HTTPException(404, "Not found")
    return await _stream(sc["asset_path"], "application/octet-stream")


@router.get("/media/evidence/{evidence_id}/original")
async def media_original(evidence_id: str, request: Request):
    _, ev = await media_access(request, evidence_id)
    return await _stream(ev["storage_path"], ev["mime"])


@router.get("/media/evidence/{evidence_id}/thumbnail")
async def media_thumb(evidence_id: str, request: Request):
    _, ev = await media_access(request, evidence_id)
    data = await scenes._io(storage.get_object, ev["storage_path"])
    try:
        jpg = await asyncio.to_thread(depth.oriented_jpeg, data, None, 320)
    except depth.UnsupportedPhoto:
        raise HTTPException(415, depth.UNSUPPORTED)
    return Response(content=jpg, media_type="image/jpeg", headers={"Cache-Control": "private, no-store"})


# ---------------- inventory ----------------
REVIEW = {"Pending": "Pending", "Confirmed": "Confirmed", "Corrected": "Corrected", "Dismissed": "Dismissed", "Closer photo requested": "Needs evidence"}


async def _anchor(item_id, sc):
    if not sc or sc["status"] != "Ready":
        return None
    a = await db.anchors.find_one({"item_id": item_id, "scene_id": sc["scene_id"], "scene_revision": sc["revision"], "current": True})
    return a and {k: a[k] for k in ("anchor_id", "version", "scene_id", "scene_revision", "xyz", "image_point", "location_basis", "placement", "uncertainty", "actor", "at")}


@router.get("/visits/{visit_id}/inventory")
async def inventory(visit_id: str, evidence_id: Optional[str] = None, include_review: bool = False, user=Depends(current_user)):
    v = await get_visit(user, visit_id)
    eng = await db.engagements.find_one({"visit_id": visit_id})
    q = {"visit_id": visit_id, "kind": "photo"}
    if evidence_id:
        q["uuid"] = evidence_id
    photos = await db.evidence.find(q).sort("created_at", 1).to_list(200)
    if evidence_id and not photos:
        raise HTTPException(404, "Not found")
    items, nc, no = [], 0, 0
    for ev in photos:
        sc = await scenes.latest(ev["uuid"])
        ready = sc if sc and sc["status"] == "Ready" else await db.scenes.find_one({"evidence_id": ev["uuid"], "status": "Ready"}, sort=[("revision", -1)])
        if ready:
            await scenes.ensure_anchors(ready)
        for kind, it in await scenes.items_for_evidence(ev["uuid"]):
            # Phase 7 §J: two-stage candidates are admitted by default only when Suggested (or human-confirmed identity)
            if kind == "candidate" and it.get("pipeline") == "two_stage_v1" and not (it.get("admitted") or it.get("human_identity")) and not include_review:
                continue
            run = await db.image_analysis_runs.find_one({"uuid": it.get("run_id")}) if kind == "candidate" else None
            if kind == "candidate":
                nc += 1
                obs_id = it.get("linked_observation_id")
                d = (it.get("decisions") or [None])[-1]
                hr = d and {"decision": d["action"], "actor": d["actor_id"], "actor_role": d.get("actor_role"), "at": d["at"], "note": d.get("note")}
                state = REVIEW.get(it["review_state"], it["review_state"])
                ident = "Saved analysis (copied genuine model run)" if it.get("saved_analysis") else f"Model candidate ({it.get('model_id')})"
            else:
                no += 1
                obs_id, hr, state = it["uuid"], {"decision": "observed", "actor": it.get("created_by"), "at": it.get("created_at")}, "Confirmed"
                ident = "Human observation"
            scope = await db.scope_items.find_one({"visit_id": visit_id, "observation_id": obs_id}) if obs_id else None
            if not scope and obs_id and eng:
                scope = await db.scope_items.find_one({"engagement_id": eng["uuid"], "kind": "tie_replacement"})
            anc = await _anchor(it["uuid"], ready)
            items.append({"item_id": it["uuid"], "short_id": f"C{nc}" if kind == "candidate" else f"O{no}", "kind": kind,
                          "scene_id": ready and ready["scene_id"], "scene_revision": ready and ready["revision"],
                          "scene_is_current": bool(ready and sc and ready["uuid"] == sc["uuid"] and ready["scene_key"] == scenes.scene_key(ev["sha256"])),
                          "scene_regenerating": bool(sc and ready and sc["uuid"] != ready["uuid"] and sc["status"] in ("Queued", "Processing")),
                          "label": (it.get("category") or "finding").capitalize(), "category": it.get("category"), "review_state": state,
                          "evidence_id": ev["uuid"], "region": it.get("region"), "located": anc is not None,
                          "unplaced_reason": None if anc else scenes.unplaced_reason({**it, "evidence_id": ev["uuid"]}, ready or sc),
                          "anchor": anc, "observation_id": obs_id, "scope_item_id": scope and scope["uuid"], "engagement_id": eng and eng["uuid"],
                          "visible_reason": it.get("visible_reason") or it.get("text"), "identity_source": ident,
                          "visible_condition": it.get("category"), "uncertainty": it.get("uncertainty"), "alternatives": it.get("alternatives"),
                          "human_review": hr, "source_time": ev.get("captured_at_exif") or ev.get("created_at"), "revision": it.get("revision"),
                          "provenance": {"model_id": it.get("model_id"), "prompt_version": it.get("prompt_version"), "run_id": it.get("run_id"),
                                         "run_at": run and run.get("created_at"), "saved_analysis": it.get("saved_analysis")}})
    return {"items": items, "label": depth.LABEL}


async def _item(user, item_id):
    it = await db.visual_candidates.find_one({"uuid": item_id, "workspace_id": user["workspace_id"]}) or \
        await db.observations.find_one({"uuid": item_id, "workspace_id": user["workspace_id"]})
    if not it:
        raise HTTPException(404, "Not found")
    await get_visit(user, it["visit_id"])
    return it


@router.get("/inventory-items/{item_id}/crop")
async def item_crop(item_id: str, request: Request):
    st = request.query_params.get("st")
    if st:
        try:
            p = jwt.decode(st, JWT_SECRET, algorithms=["HS256"])
        except jwt.ExpiredSignatureError:
            raise HTTPException(401, "Media link expired. Reopen the scene")
        except jwt.InvalidTokenError:
            raise HTTPException(401, "Invalid media link")
        user, ev = await media_access(request, p.get("ev") or "")
    else:
        auth = request.headers.get("Authorization", "")
        user = await user_from_token(auth[7:] if auth.startswith("Bearer ") else request.query_params.get("auth"))
        ev = None
    it = await _item(user, item_id)
    if not it.get("evidence_id") or (ev and ev["uuid"] != it["evidence_id"]):
        raise HTTPException(404, "Not found")
    ev = ev or await db.evidence.find_one({"uuid": it["evidence_id"], "workspace_id": user["workspace_id"]})
    region = it.get("region") if scenes._valid_region(it.get("region")) else None
    data = await scenes._io(storage.get_object, ev["storage_path"])
    try:
        jpg = await asyncio.to_thread(depth.oriented_jpeg, data, region, 512)
    except depth.UnsupportedPhoto:
        raise HTTPException(415, depth.UNSUPPORTED)
    return Response(content=jpg, media_type="image/jpeg", headers={"Cache-Control": "private, no-store", "X-Crop-Region": "full" if not region else ",".join(map(str, region))})


class AnchorPut(BaseModel):
    expected_version: int
    xyz: Optional[List[float]] = None
    image_point: Optional[List[float]] = None
    reason: Optional[str] = None


@router.put("/anchors/{anchor_id}")
async def move_anchor(anchor_id: str, body: AnchorPut, user=Depends(current_user)):
    cur = await db.anchors.find_one({"anchor_id": anchor_id, "current": True, "workspace_id": user["workspace_id"]})
    if not cur:
        raise HTTPException(404, "Not found")
    await get_visit(user, cur["visit_id"])
    if body.expected_version != cur["version"]:
        raise HTTPException(409, {"code": "stale_revision", "message": "This marker was moved elsewhere. Reload to see the latest position.",
                                  "server": {k: cur[k] for k in ("anchor_id", "version", "xyz", "image_point", "placement", "actor", "at")}})
    sc = await db.scenes.find_one({"scene_id": cur["scene_id"], "revision": cur["scene_revision"]})
    if body.image_point is not None:
        if len(body.image_point) != 2 or not all(0 <= c <= 1 for c in body.image_point):
            raise HTTPException(422, {"code": "field_error", "field": "image_point", "message": "image_point must be [u, v] within 0..1"})
        xyz, ip = await scenes.point_to_xyz(sc, *body.image_point), list(body.image_point)
    elif body.xyz is not None and len(body.xyz) == 3 and all(abs(c) < 1e4 for c in body.xyz):
        xyz, ip = [float(c) for c in body.xyz], scenes.xyz_to_point(sc, body.xyz)
        if ip is None:
            raise HTTPException(422, {"code": "field_error", "field": "xyz", "message": "Point is behind the capture camera"})
    else:
        raise HTTPException(422, {"code": "field_error", "field": "xyz", "message": "Provide xyz [x,y,z] or image_point [u,v]"})
    new = await scenes.new_version(cur, sc, xyz, ip, "manual", user["uuid"], body.reason, cur.get("source_region"), user["role"])
    if not new:
        raise HTTPException(409, {"code": "stale_revision", "message": "This marker was moved elsewhere. Reload to see the latest position."})
    await audit(user, cur["workspace_id"], "anchor_moved", "anchor", anchor_id, {"version": new["version"], "reason": body.reason})
    new.pop("_id", None)
    return new
