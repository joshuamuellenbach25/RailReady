"""Phase 4b photo-scene API (REQ-174..176). Wraps photo_scene_processor via scenes.py; Phase 4 routes stay as aliases.
Scene ids here are revision-specific (scene document uuid). Errors are {code, message, retryable} — no paths, no traces."""
from datetime import timedelta
from typing import Optional

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from core import JWT_SECRET, audit, current_user, db, iso, now, user_from_token, visit_scope
import photo_scene_processor as P
import scenes
from routes_scene import _ensure_job, _photo

router = APIRouter(prefix="/api", tags=["photo-scenes"])
TTL = timedelta(minutes=10)
ASSETS = {"splat": "splat", "oriented_photo": "oriented_photo", "depth_grid": "display_z", "depth_png": "depth_png", "manifest": "manifest"}


def err(status, code, message, retryable=False):
    raise HTTPException(status, {"code": code, "message": message, "retryable": retryable})


def status_of(sc, job=None):
    """Lower-case Phase-4b vocabulary + structured error."""
    if job and job["status"] in ("Queued", "Running", "Blocked"):
        if job["status"] == "Blocked":
            return "queued", {"code": "blocked", "message": job.get("blocker") or "Processing not permitted for this visit", "retryable": False}
        return ("processing" if job["status"] == "Running" else "queued"), None
    if not sc:
        return "queued", None
    st = sc["status"]
    if st == "Ready":
        return "ready", None
    if st in ("Queued", "Processing"):
        return st.lower(), None
    e = {"code": sc.get("error_code") or "failed", "message": sc.get("error") or "Scene generation failed",
         "retryable": bool(sc.get("retryable")) if sc.get("retryable") is not None else sc.get("error_code") not in ("unsupported", "depth_uninformative")}
    return ("depth_uninformative" if e["code"] == "depth_uninformative" else "failed"), e


def sign(user, sc, kind):
    return jwt.encode({"typ": "scene_asset", "uid": user["uuid"], "ws": user["workspace_id"], "sid": sc["uuid"], "ev": sc["evidence_id"], "k": kind,
                       "exp": now() + TTL}, JWT_SECRET, algorithm="HS256")


async def _scene(user, scene_uuid):
    sc = await db.scenes.find_one({"uuid": scene_uuid, "workspace_id": user["workspace_id"]})
    if not sc or not await db.visits.find_one({"uuid": sc["visit_id"], **visit_scope(user)}):
        err(404, "not_found", "Not found")
    return sc


def _job_view(job, sc):
    st, e = status_of(sc, job)
    if job["status"] == "Done" and sc:
        st, e = status_of(sc)
    if job["status"] == "Failed" and sc and sc["status"] not in ("Ready",):
        st, e = status_of(sc)
    return {"job_id": job["uuid"], "evidence_id": job["target_id"], "status": st, "scene_id": job.get("scene_uuid") or (sc and sc["uuid"]),
            "error": e, "started_at": job.get("started_at"), "completed_at": job.get("completed_at")}


@router.post("/evidence/{evidence_id}/photo-scene")
async def create_photo_scene(evidence_id: str, user=Depends(current_user)):
    ev, v = await _photo(user, evidence_id)
    if ev.get("upload_state") != "Verified":
        err(409, "not_verified", "Photo upload is not verified yet", True)
    await _ensure_job(v, ev)
    sc = await scenes.latest(ev["uuid"])
    job = await db.jobs.find_one({"stage": "depth", "target_id": ev["uuid"]})
    if sc and sc["status"] == "Ready" and sc["scene_key"] == scenes.scene_key(ev["sha256"]):
        return {"status": "ready", "scene_id": sc["uuid"], "job_id": job and job["uuid"], "revision": sc["revision"]}
    if job["status"] == "Failed":  # explicit request on a failed generation = retry from stored bytes
        await db.jobs.update_one({"uuid": job["uuid"], "status": "Failed"}, {"$set": {"status": "Queued", "error": None, "updated_at": iso()}, "$inc": {"revision": 1}})
        job = await db.jobs.find_one({"uuid": job["uuid"]})
    return JSONResponse(status_code=202, content=_job_view(job, None if job["status"] in ("Queued", "Running") else sc))


@router.get("/photo-scene-jobs/{job_id}")
async def get_job(job_id: str, user=Depends(current_user)):
    job = await db.jobs.find_one({"uuid": job_id, "stage": "depth", "workspace_id": user["workspace_id"]})
    if not job or not await db.visits.find_one({"uuid": job["visit_id"], **visit_scope(user)}):
        err(404, "not_found", "Not found")
    sc = await db.scenes.find_one({"uuid": job.get("scene_uuid")}) if job.get("scene_uuid") else await scenes.latest(job["target_id"])
    return _job_view(job, sc)


async def _scene_payload(user, sc):
    st, e = status_of(sc)
    ev = await db.evidence.find_one({"uuid": sc["evidence_id"]})
    exp = iso(now() + TTL)
    assets = {}
    if st == "ready":
        for name, art in (("splat", "splat"), ("oriented_photo", "oriented_photo")):
            a = sc["artifacts"][art]
            assets[name] = {"kind": "signed_url", "url": f"/api/photo-scenes/{sc['uuid']}/assets/{name}?st={sign(user, sc, name)}",
                            "content_type": a["content_type"], "byte_length": a["byte_length"], "sha256": a["sha256"], "expires_at": exp}
        for name in ("depth_grid", "manifest"):
            a = sc["artifacts"][ASSETS[name]]
            assets[name] = {"kind": "authenticated_route", "url": f"/api/photo-scenes/{sc['uuid']}/assets/{name}", "content_type": a["content_type"],
                            "byte_length": a["byte_length"], "sha256": a["sha256"], "expires_at": None}
    assets["original"] = {"kind": "signed_url", "url": f"/api/photo-scenes/{sc['uuid']}/assets/original?st={sign(user, sc, 'original')}",
                          "content_type": ev["mime"], "byte_length": ev.get("server_size") or ev["size"], "sha256": ev["sha256"], "expires_at": exp}
    latest = await scenes.latest(sc["evidence_id"])
    job = await db.jobs.find_one({"stage": "depth", "target_id": sc["evidence_id"]}, {"status": 1})
    regenerating = bool(job and job["status"] in ("Queued", "Running"))
    last_ready = latest if latest["status"] == "Ready" else await db.scenes.find_one({"evidence_id": sc["evidence_id"], "status": "Ready"}, sort=[("revision", -1)])
    return {"scene_id": sc["uuid"], "evidence_id": sc["evidence_id"], "visit_id": sc["visit_id"], "revision": sc["revision"], "scene_hash": sc.get("scene_hash"),
            "status": st, "error": e, "processor_revision": sc.get("processor_revision"),
            "is_current": sc["scene_key"] == scenes.scene_key(ev["sha256"]) and latest["uuid"] == sc["uuid"] and not regenerating,
            "regenerating": regenerating, "latest_scene_id": latest["uuid"], "latest_revision": latest["revision"],
            "last_ready_scene_id": last_ready and last_ready["uuid"], "last_ready_revision": last_ready and last_ready["revision"],
            "previous_revision": last_ready["revision"] if last_ready and last_ready["uuid"] != latest["uuid"] else None,
            "manifest": sc.get("manifest"), "assets": assets, "label": "AI-estimated relative depth; no measured geometry",
            "created_at": sc.get("created_at"), "ready_at": sc.get("ready_at")}


@router.get("/photo-scenes/{scene_id}")
async def get_photo_scene(scene_id: str, user=Depends(current_user)):
    return await _scene_payload(user, await _scene(user, scene_id))


@router.get("/evidence/{evidence_id}/photo-scenes")
async def list_photo_scenes(evidence_id: str, user=Depends(current_user)):
    ev, _ = await _photo(user, evidence_id)
    out = []
    all_sc = await db.scenes.find({"evidence_id": ev["uuid"]}).sort("revision", -1).to_list(50)
    last_ready = next((s for s in all_sc if s["status"] == "Ready"), None)
    job = await db.jobs.find_one({"stage": "depth", "target_id": ev["uuid"]}, {"status": 1})
    for sc in all_sc:
        st, e = status_of(sc)
        out.append({"scene_id": sc["uuid"], "revision": sc["revision"], "status": st, "error": e, "processor_revision": sc.get("processor_revision"),
                    "scene_hash": sc.get("scene_hash"), "created_at": sc.get("created_at"), "is_last_ready": bool(last_ready and sc["uuid"] == last_ready["uuid"])})
    return {"evidence_id": ev["uuid"], "scenes": out, "regenerating": bool(job and job["status"] in ("Queued", "Running")),
            "last_ready_scene_id": last_ready and last_ready["uuid"], "last_ready_revision": last_ready and last_ready["revision"]}


@router.get("/photo-scenes/{scene_id}/assets/{name}")
async def get_asset(scene_id: str, name: str, request: Request):
    if name not in ("splat", "oriented_photo", "original", "depth_grid", "depth_png", "manifest"):
        err(404, "not_found", "Not found")
    st = request.query_params.get("st")
    if st:
        try:
            p = jwt.decode(st, JWT_SECRET, algorithms=["HS256"])
        except jwt.ExpiredSignatureError:
            err(401, "link_expired", "Asset link expired. Reload the scene for a fresh link", True)
        except jwt.InvalidTokenError:
            err(401, "invalid_link", "Invalid asset link")
        if p.get("typ") != "scene_asset" or p.get("sid") != scene_id or p.get("k") != name:
            err(404, "not_found", "Not found")
        user = await db.users.find_one({"uuid": p["uid"]})
        if not user or user["workspace_id"] != p["ws"] or (user.get("demo_expires_at") and user["demo_expires_at"] <= iso()):
            err(401, "invalid_link", "Asset link no longer valid")
    else:
        auth = request.headers.get("Authorization", "")
        user = await user_from_token(auth[7:] if auth.startswith("Bearer ") else None)
    sc = await _scene(user, scene_id)  # revalidated every request: workspace + visit scope
    if name == "original":
        ev = await db.evidence.find_one({"uuid": sc["evidence_id"]})
        path, ct = ev["storage_path"], ev["mime"]
    else:
        if sc["status"] != "Ready":
            err(404, "not_found", "Not found")
        a = sc["artifacts"][ASSETS[name]]
        path, ct = a["path"], a["content_type"]
    data = await scenes._io(__import__("storage").get_object, path)
    return Response(content=data, media_type=ct, headers={"Cache-Control": "private, no-store"})


def _anchor_out(a):
    return {"finding_id": a["item_id"], "kind": a["item_kind"], "anchor_id": a["anchor_id"], "version": a["version"],
            "u": a["image_point"][0] if a.get("image_point") else None, "v": a["image_point"][1] if a.get("image_point") else None,
            "xyz": a["xyz"], "placement_method": a.get("placement_method") or ("manual_point_estimated_depth" if a["placement"] == "manual" else P.PLACEMENT),
            "placement": a["placement"], "location_basis": a["location_basis"], "uncertainty": a["uncertainty"], "stale": bool(a.get("stale")),
            "stale_reason": a.get("stale_reason"), "source_region": a.get("source_region"), "actor": a["actor"], "at": a["at"]}


@router.get("/photo-scenes/{scene_id}/anchors")
async def get_anchors(scene_id: str, user=Depends(current_user)):
    sc = await _scene(user, scene_id)
    if sc["status"] == "Ready":
        await scenes.ensure_anchors(sc)
    ev = await db.evidence.find_one({"uuid": sc["evidence_id"]})
    cur = {a["item_id"]: a for a in await db.anchors.find({"evidence_id": sc["evidence_id"], "scene_revision": sc["revision"], "current": True}).to_list(500)}
    out, unplaced = [], []
    for kind, it in await scenes.items_for_evidence(sc["evidence_id"]):
        if it["uuid"] in cur:
            out.append(_anchor_out(cur[it["uuid"]]))
        else:
            unplaced.append({"finding_id": it["uuid"], "kind": kind, "reason": scenes.unplaced_reason({**it, "evidence_id": ev["uuid"]}, sc)})
    return {"scene_id": sc["uuid"], "revision": sc["revision"], "anchors": out, "unplaced": unplaced}


class PlaceIn(BaseModel):
    u: float
    v: float
    expected_version: int
    reason: Optional[str] = None


@router.put("/photo-scenes/{scene_id}/anchors/{finding_id}")
async def place_anchor(scene_id: str, finding_id: str, body: PlaceIn, user=Depends(current_user)):
    sc = await _scene(user, scene_id)
    if sc["status"] != "Ready":
        err(409, "scene_not_ready", "Scene is not ready", True)
    items = {it["uuid"]: (k, it) for k, it in await scenes.items_for_evidence(sc["evidence_id"])}
    if finding_id not in items:
        err(404, "not_found", "Not found")
    if not (0 <= body.u <= 1 and 0 <= body.v <= 1):
        err(422, "invalid_point", "u and v must be within 0..1")
    xyz = await scenes.point_to_xyz(sc, body.u, body.v)  # server computes from THIS revision's grid
    cur = await db.anchors.find_one({"evidence_id": sc["evidence_id"], "scene_revision": sc["revision"], "item_id": finding_id, "current": True})
    stale = {"code": "stale_version", "message": "This marker was changed elsewhere. Reload to see the latest position.", "retryable": True}
    if not cur:
        if body.expected_version != 0:
            raise HTTPException(409, stale)
        doc = scenes._anchor_doc(sc, items[finding_id][0], finding_id, scenes.new_id(), 1, xyz, [body.u, body.v], "manual", user["uuid"], body.reason,
                                 None, user["role"])
        try:
            await db.anchors.insert_one(doc)
        except scenes.DuplicateKeyError:
            raise HTTPException(409, stale)
        new = doc
    else:
        if body.expected_version != cur["version"]:
            raise HTTPException(409, {**stale, "server": _anchor_out(cur)})
        new = await scenes.new_version(cur, sc, xyz, [body.u, body.v], "manual", user["uuid"], body.reason, cur.get("source_region"), user["role"])
        if not new:
            raise HTTPException(409, stale)
    await audit(user, sc["workspace_id"], "anchor_placed", "anchor", new["anchor_id"], {"version": new["version"], "scene_revision": sc["revision"]})
    return _anchor_out(new)


class ViewIn(BaseModel):
    camera: dict
    selected_finding_id: Optional[str] = None


@router.get("/photo-scenes/{scene_id}/view")
async def get_view(scene_id: str, user=Depends(current_user)):
    sc = await _scene(user, scene_id)
    v = await db.scene_views.find_one({"scene_uuid": sc["uuid"], "user_id": user["uuid"]}, {"_id": 0})
    default = {"position": sc.get("camera", {}).get("position", [0, 0, 0]), "target": sc.get("camera", {}).get("target", [0, 0, -4]),
               "fov_deg": sc.get("camera", {}).get("fov_deg", 55.0)}
    return {"scene_id": sc["uuid"], "revision": sc["revision"], "camera": (v or {}).get("camera", default),
            "selected_finding_id": (v or {}).get("selected_finding_id"), "saved": bool(v), "updated_at": (v or {}).get("updated_at")}


def _vec(x, n=3):
    return isinstance(x, list) and len(x) == n and all(isinstance(c, (int, float)) and abs(c) < 1e4 and c == c for c in x)


@router.put("/photo-scenes/{scene_id}/view")
async def put_view(scene_id: str, body: ViewIn, user=Depends(current_user)):
    sc = await _scene(user, scene_id)
    c = body.camera
    fov = c.get("fov_deg", c.get("fov"))
    if not (_vec(c.get("position")) and _vec(c.get("target")) and isinstance(fov, (int, float)) and 1 <= fov <= 170):
        err(422, "invalid_view", "camera needs position [x,y,z], target [x,y,z] and fov_deg 1..170")
    if body.selected_finding_id and body.selected_finding_id not in {it["uuid"] for _, it in await scenes.items_for_evidence(sc["evidence_id"])}:
        err(404, "not_found", "Not found")
    doc = {"scene_uuid": sc["uuid"], "user_id": user["uuid"], "workspace_id": sc["workspace_id"], "revision": sc["revision"],
           "camera": {"position": c["position"], "target": c["target"], "fov_deg": float(fov)}, "selected_finding_id": body.selected_finding_id, "updated_at": iso()}
    await db.scene_views.update_one({"scene_uuid": sc["uuid"], "user_id": user["uuid"]}, {"$set": doc}, upsert=True)
    return {"scene_id": sc["uuid"], "revision": sc["revision"], "camera": doc["camera"], "selected_finding_id": body.selected_finding_id,
            "saved": True, "updated_at": doc["updated_at"]}
