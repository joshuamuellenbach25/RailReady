"""Field capture API: auth, sites/bundle, visits, observations, evidence upload/verify, manifests, readiness, submit."""
import asyncio
import json
from typing import Literal, Optional

from pymongo.errors import DuplicateKeyError
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator

from core import (APP_NAME, SUBMITTED_MSG, assert_editable, audit, bump_visit, clean, clean_all, create_token,
                  current_user, db, get_scoped, get_visit, iso, new_id, require_role, revision_conflict, sha256_hex,
                  stamp, verify_password, visit_scope)
import ai_jev
import jobs
import readiness
import storage

router = APIRouter(prefix="/api")
MAX_BYTES = 25 * 1024 * 1024
VIDEO_MAX_BYTES = 200 * 1024 * 1024


# ---------------- auth ----------------
class LoginIn(BaseModel):
    email: str
    password: str


@router.post("/auth/login", tags=["auth"])
async def login(body: LoginIn, request: Request):
    email = body.email.strip().lower()
    ident = f"{request.client.host if request.client else '?'}:{email}"
    att = await db.login_attempts.find_one({"identifier": ident})
    if att and att.get("count", 0) >= 5 and att.get("until", "") > iso():
        raise HTTPException(429, "Too many attempts. Try again in 15 minutes.")
    user = await db.users.find_one({"email": email})
    if not user or not verify_password(body.password, user["password_hash"]):
        from datetime import timedelta
        from core import now
        await db.login_attempts.update_one({"identifier": ident}, {"$inc": {"count": 1}, "$set": {"until": iso(now() + timedelta(minutes=15))}}, upsert=True)
        raise HTTPException(401, "Invalid email or password")
    await db.login_attempts.delete_many({"identifier": ident})
    ws = await db.workspaces.find_one({"uuid": user["workspace_id"]})
    return {"token": create_token(user), "user": clean(user), "workspace": clean(ws)}


@router.get("/auth/me", tags=["auth"])
async def me(user=Depends(current_user)):
    ws = await db.workspaces.find_one({"uuid": user["workspace_id"]})
    return {"user": user, "workspace": clean(ws)}


# ---------------- sites + offline bundle ----------------
def site_scope(user):
    q = {"workspace_id": user["workspace_id"]}
    if user["role"] == "foreman":
        q["assigned_foreman_ids"] = user["uuid"]
    return q


class SiteIn(BaseModel):
    uuid: str = Field(min_length=8, max_length=64)  # stable client id = idempotency key
    name: str = Field(max_length=120)
    address: Optional[str] = Field(None, max_length=300)
    lat: Optional[float] = Field(None, ge=-90, le=90)
    lon: Optional[float] = Field(None, ge=-180, le=180)
    location_accuracy_m: Optional[float] = Field(None, ge=0)
    description: Optional[str] = Field(None, max_length=500)


@router.post("/sites", tags=["sites"], status_code=200)
async def create_site(body: SiteIn, user=Depends(require_role("admin", "estimator", "foreman"))):
    """Create a site in the caller's workspace. Idempotent by client uuid: a retry with the same details returns the
    existing record; the same uuid with different details is 409; a uuid owned by another workspace is 404."""
    name = body.name.strip()
    if not name:
        raise HTTPException(422, {"code": "field_errors", "message": "Enter a site name.", "fields": {"name": "Enter a site name."}})
    payload = {"name": name, "address": (body.address or "").strip() or None, "lat": body.lat, "lon": body.lon,
               "location_accuracy_m": body.location_accuracy_m, "description": (body.description or "").strip() or None}
    phash = sha256_hex(json.dumps(payload, sort_keys=True).encode())
    doc = {"uuid": body.uuid, "workspace_id": user["workspace_id"], "customer_id": None, **payload, "payload_hash": phash,
           "access_notes": None, "prior_findings": [], "assigned_foreman_ids": [user["uuid"]] if user["role"] == "foreman" else [],
           "source": "created_in_app", **stamp(user)}
    try:
        await db.sites.insert_one(dict(doc))
        await audit(user, user["workspace_id"], "site_created", "site", body.uuid)
        created = True
    except DuplicateKeyError:
        created = False
    s = await db.sites.find_one({"uuid": body.uuid})
    if s["workspace_id"] != user["workspace_id"]:
        raise HTTPException(404, "Not found")
    if not created and s.get("payload_hash") != phash:
        raise HTTPException(409, {"code": "operation_id_reused", "message": "This site was already saved with different details."})
    if not created and user["role"] == "foreman" and user["uuid"] not in s.get("assigned_foreman_ids", []):
        raise HTTPException(404, "Not found")
    return {**clean(s), "customer_name": None, "replayed": not created}


@router.get("/sites", tags=["sites"])
async def list_sites(user=Depends(current_user)):
    sites = clean_all(await db.sites.find(site_scope(user)).sort("name", 1).to_list(200))
    for s in sites:
        c = await db.customers.find_one({"uuid": s["customer_id"]}) if s.get("customer_id") else None
        s["customer_name"] = c["name"] if c else None
    return sites


@router.get("/sites/{site_id}/bundle", tags=["sites"])
async def site_bundle(site_id: str, user=Depends(current_user)):
    site = await db.sites.find_one({"uuid": site_id, **site_scope(user)})
    if not site:
        raise HTTPException(404, "Not found")
    customer = await db.customers.find_one({"uuid": site["customer_id"]}) if site.get("customer_id") else None
    tracks = await db.tracks.find({"site_id": site_id}).to_list(50)
    ws = await db.workspaces.find_one({"uuid": user["workspace_id"]})
    payload = {"site": clean(site), "customer": clean(customer), "tracks": clean_all(tracks),
               "fields": readiness.FIELDS, "escalation_text": ws.get("escalation_text"),
               "generated_at": iso(), "bundle_version": f"{site['revision']}"}
    payload["bundle_hash"] = sha256_hex(json.dumps(payload, sort_keys=True, default=str).encode())
    return payload


# ---------------- visits ----------------
Permission = Literal["Granted", "Denied", "Unknown", "Policy"]


class VisitIn(BaseModel):
    uuid: str
    site_id: str
    track_id: Optional[str] = None
    title: str = Field(min_length=1, max_length=200)
    processing_permission: Permission = "Policy"  # Phase 5: org policy governs; legacy Denied/Unknown remain restrictions
    coverage_note: Optional[str] = None
    started_at: Optional[str] = None


class VisitPatch(BaseModel):
    expected_revision: int
    title: Optional[str] = None
    processing_permission: Optional[Permission] = None
    coverage_note: Optional[str] = None
    urgent_concern: Optional[str] = None


@router.post("/visits", tags=["visits"])
async def create_visit(body: VisitIn, user=Depends(require_role("foreman"))):
    existing = await db.visits.find_one({"uuid": body.uuid})
    if existing:
        if existing["workspace_id"] != user["workspace_id"] or existing["foreman_id"] != user["uuid"]:
            raise HTTPException(404, "Not found")
        return clean(existing)  # idempotent client-UUID create
    site = await db.sites.find_one({"uuid": body.site_id, **site_scope(user)})
    if not site:
        raise HTTPException(404, "Not found")
    doc = {**body.model_dump(), "workspace_id": user["workspace_id"], "customer_id": site["customer_id"],
           "foreman_id": user["uuid"], "status": "Draft", "answers": {}, "urgent_concern": None, **stamp(user)}
    try:
        await db.visits.insert_one(doc)
    except Exception:
        return clean(await db.visits.find_one({"uuid": body.uuid}))
    await audit(user, user["workspace_id"], "visit_created", "visit", body.uuid)
    return clean(doc)


@router.get("/visits", tags=["visits"])
async def list_visits(user=Depends(current_user)):
    return clean_all(await db.visits.find(visit_scope(user)).sort("created_at", -1).to_list(200))


@router.get("/visits/{visit_id}", tags=["visits"])
async def get_visit_api(visit_id: str, user=Depends(current_user)):
    return clean(await get_visit(user, visit_id))


@router.patch("/visits/{visit_id}", tags=["visits"])
async def patch_visit(visit_id: str, body: VisitPatch, user=Depends(current_user)):
    v = await get_visit(user, visit_id)
    assert_editable(v, user)
    upd = {k: val for k, val in body.model_dump(exclude={"expected_revision"}).items() if val is not None}
    res = await bump_visit(v, user, body.expected_revision, upd)
    if "processing_permission" in upd:
        await jobs.on_permission_change(res)
        await audit(user, v["workspace_id"], "processing_permission_set", "visit", visit_id, {"value": upd["processing_permission"]})
    return clean(res)


# ---------------- observations (measurement, location, not inspected, finding) ----------------
class ObservationIn(BaseModel):
    uuid: str
    kind: Literal["measurement", "location", "not_inspected", "finding"]
    label: Optional[str] = None
    value: Optional[str] = None
    unit: Optional[str] = None
    text: Optional[str] = None
    reason: Optional[str] = None
    area: Optional[str] = None
    quantity: Optional[int] = None
    captured_at: Optional[str] = None

    @field_validator("value")
    @classmethod
    def decimal_str(cls, v):
        if v is not None:
            from decimal import Decimal, InvalidOperation
            try:
                Decimal(v)
            except InvalidOperation:
                raise ValueError("value must be a decimal number")
        return v


def _check_obs(o: ObservationIn):
    if o.kind == "not_inspected":
        if not (o.reason or "").strip() or not (o.area or "").strip():
            raise HTTPException(422, "Not inspected area needs an area and a reason")
        if o.quantity is not None or o.value is not None:
            raise HTTPException(422, "Not inspected areas carry no quantities")
    if o.kind == "measurement" and (not o.label or o.value is None):
        raise HTTPException(422, "Measurement needs a label and a value")
    if o.kind in ("location", "finding") and not (o.text or "").strip():
        raise HTTPException(422, "Text required")
    if o.kind == "finding" and o.quantity is not None:
        raise HTTPException(422, "Findings carry no repair quantity; set quantities in the estimating fields")


@router.post("/visits/{visit_id}/observations", tags=["observations"])
async def add_observation(visit_id: str, body: ObservationIn, user=Depends(current_user)):
    v = await get_visit(user, visit_id)
    existing = await db.observations.find_one({"uuid": body.uuid})
    if existing:
        if existing["visit_id"] != visit_id:
            raise HTTPException(404, "Not found")
        return clean(existing)
    assert_editable(v, user)
    _check_obs(body)
    doc = {**body.model_dump(), "workspace_id": v["workspace_id"], "visit_id": visit_id, "human_reviewed": True,
           "source_candidate_id": None, "specification": None, **stamp(user)}
    try:
        await db.observations.insert_one(doc)
    except DuplicateKeyError:  # B5: concurrent lost-ack retries of the same client uuid → same record, never 500
        existing = await db.observations.find_one({"uuid": body.uuid})
        if existing["visit_id"] != visit_id:
            raise HTTPException(404, "Not found")
        return clean(existing)
    return clean(doc)


class ObservationPatch(BaseModel):
    expected_revision: int
    label: Optional[str] = None
    value: Optional[str] = None
    unit: Optional[str] = None
    text: Optional[str] = None
    reason: Optional[str] = None
    area: Optional[str] = None


@router.patch("/observations/{obs_id}", tags=["observations"])
async def patch_observation(obs_id: str, body: ObservationPatch, user=Depends(current_user)):
    o, v = await get_scoped("observations", user, obs_id)
    assert_editable(v, user)
    if body.expected_revision != o["revision"]:
        revision_conflict(o, "observation")
    upd = {k: val for k, val in body.model_dump(exclude={"expected_revision"}).items() if val is not None}
    res = await db.observations.find_one_and_update({"uuid": obs_id, "revision": o["revision"]},
                                                    {"$set": {**upd, "updated_at": iso(), "updated_by": user["uuid"]}, "$inc": {"revision": 1}},
                                                    return_document=True)
    if not res:
        revision_conflict(await db.observations.find_one({"uuid": obs_id}), "observation")
    await audit(user, v["workspace_id"], "observation_corrected", "observation", obs_id, upd)
    return clean(res)


@router.get("/visits/{visit_id}/observations", tags=["observations"])
async def list_observations(visit_id: str, user=Depends(current_user)):
    await get_visit(user, visit_id)
    return clean_all(await db.observations.find({"visit_id": visit_id}).sort("created_at", 1).to_list(500))


# ---------------- evidence: register → upload → verify ----------------
class EvidenceIn(BaseModel):
    uuid: str
    kind: Literal["photo", "audio", "note", "video"]
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    size: int = Field(ge=0, le=VIDEO_MAX_BYTES)  # per-kind limit checked in register
    mime: str
    filename: Optional[str] = None
    captured_at: Optional[str] = None
    text: Optional[str] = None
    caption: Optional[str] = None


@router.post("/visits/{visit_id}/evidence", tags=["evidence"])
async def register_evidence(visit_id: str, body: EvidenceIn, user=Depends(current_user)):
    v = await get_visit(user, visit_id)
    existing = await db.evidence.find_one({"uuid": body.uuid})
    if existing:
        if existing["visit_id"] != visit_id:
            raise HTTPException(404, "Not found")
        return clean(existing)  # lost-ack retry → same record
    assert_editable(v, user)
    if body.kind != "video" and body.size > MAX_BYTES:
        raise HTTPException(413, {"code": "too_large", "message": "This file is larger than 25 MB. It is kept on your phone."})
    if body.kind == "video" and body.mime.lower() not in __import__("video_pipeline").SUPPORTED_MIMES:
        raise HTTPException(415, {"code": "unsupported_video", "message": "This video format is not supported. Use MP4 or MOV. It is kept on your phone."})
    doc = {**body.model_dump(), "workspace_id": v["workspace_id"], "visit_id": visit_id,
           "upload_state": "Registered", "storage_path": None, "server_sha256": None, "server_size": None, **stamp(user)}
    if body.kind == "note":
        if body.text is None:
            raise HTTPException(422, "Note text required")
        data = body.text.encode("utf-8")
        ok = sha256_hex(data) == body.sha256 and len(data) == body.size
        doc.update({"server_sha256": sha256_hex(data), "server_size": len(data),
                    "upload_state": "Verified" if ok else "Hash mismatch", "verified_at": iso() if ok else None})
    try:
        await db.evidence.insert_one(doc)
    except DuplicateKeyError:
        return clean(await db.evidence.find_one({"uuid": body.uuid}))
    if doc["upload_state"] == "Verified":
        await jobs.queue_verified(doc)  # notes: per-item analysis right away
    return clean(doc)


@router.put("/evidence/{evidence_id}/content", tags=["evidence"])
async def upload_content(evidence_id: str, file: UploadFile = File(...), user=Depends(current_user)):
    ev, v = await get_scoped("evidence", user, evidence_id)
    if ev["kind"] == "note":
        raise HTTPException(422, "Notes have no binary content")
    if ev["upload_state"] == "Verified":
        return clean(ev)  # idempotent; no duplicate object
    assert_editable(v, user)
    data = await file.read()
    if len(data) > (VIDEO_MAX_BYTES if ev["kind"] == "video" else MAX_BYTES):
        raise HTTPException(413, {"code": "too_large", "message": "This file is over the size limit. It is kept on your phone."})
    ext = (ev.get("filename") or "bin").rsplit(".", 1)[-1][:5]
    path = f"{APP_NAME}/{ev['workspace_id']}/{ev['visit_id']}/{evidence_id}.{ext}"
    await asyncio.to_thread(storage.put_object, path, data, ev["mime"])
    res = await db.evidence.find_one_and_update({"uuid": evidence_id}, {"$set": {
        "storage_path": path, "upload_state": "Uploaded unverified", "uploaded_at": iso(), "updated_at": iso()}},
        return_document=True)
    return clean(res)


@router.post("/evidence/{evidence_id}/verify", tags=["evidence"])
async def verify_content(evidence_id: str, user=Depends(current_user)):
    """Server re-reads the stored bytes and checks SHA-256 + size before marking Verified."""
    ev, v = await get_scoped("evidence", user, evidence_id)
    if ev["upload_state"] == "Verified" or ev["kind"] == "note":
        if ev["upload_state"] == "Verified" and (ev.get("analysis_intent") or {}).get("state") != "enqueued":
            await jobs.queue_verified(ev)  # lost-ack retry finishes a half-done intent
        return clean(ev)
    if not ev.get("storage_path"):
        raise HTTPException(409, {"code": "not_uploaded", "message": "Upload bytes before verifying"})
    data = await asyncio.to_thread(storage.get_object, ev["storage_path"])
    h, n = sha256_hex(data), len(data)
    ok = h == ev["sha256"] and n == ev["size"]
    extra = {}
    if ok and ev["kind"] == "video":  # REQ-1244: type/size/duration/hash validated on the server; original kept either way
        pr = await asyncio.to_thread(__import__("video_pipeline").probe, data)
        extra = {"video": {k: pr.get(k) for k in ("duration_s", "width", "height", "codec", "container")}}
        if not pr["ok"]:
            res = await db.evidence.find_one_and_update({"uuid": evidence_id}, {"$set": {
                "server_sha256": h, "server_size": n, "upload_state": "Rejected", "reject_reason": pr["reason"], **extra, "updated_at": iso()}}, return_document=True)
            return clean(res)
    res = await db.evidence.find_one_and_update({"uuid": evidence_id}, {"$set": {
        "server_sha256": h, "server_size": n, "upload_state": "Verified" if ok else "Hash mismatch", **extra,
        "verified_at": iso() if ok else None, "updated_at": iso()}}, return_document=True)
    if ok:
        await jobs.queue_verified(res)  # REQ-1220: per verified item, no manifest dependency
    return clean(res)


HEIC_MIMES = {"image/heic", "image/heif", "image/heic-sequence", "image/heif-sequence"}


def _heic_to_jpeg(data: bytes) -> bytes:
    import io
    from PIL import Image, ImageOps
    im = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


@router.get("/evidence/{evidence_id}/content", tags=["evidence"])
async def download_content(evidence_id: str, request: Request, original: bool = False, user=Depends(current_user)):
    ev, _ = await get_scoped("evidence", user, evidence_id)
    if not ev.get("storage_path") or ev["upload_state"] != "Verified":
        raise HTTPException(404, "Not found")
    if ev.get("mime", "").lower() in HEIC_MIMES and not original:
        # B4: browsers can't show HEIC → serve a cached upright JPEG display copy; ?original=true returns the exact bytes
        dpath = ev["storage_path"] + ".display.jpg"
        try:
            data = await asyncio.to_thread(storage.get_object, dpath)
        except Exception:
            data = await asyncio.to_thread(_heic_to_jpeg, await asyncio.to_thread(storage.get_object, ev["storage_path"]))
            await asyncio.to_thread(storage.put_object, dpath, data, "image/jpeg")
        return Response(content=data, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600", "X-Display-Copy": "jpeg-from-heic"})
    data = await asyncio.to_thread(storage.get_object, ev["storage_path"])
    rng = request.headers.get("range") if request else None
    if rng and rng.startswith("bytes="):  # REQ-1245: range support for video playback
        a, _, b = rng[6:].partition("-")
        start = int(a) if a else max(0, len(data) - int(b))
        end = min(len(data) - 1, int(b)) if (a and b) else len(data) - 1
        if start >= len(data):
            return Response(status_code=416, headers={"Content-Range": f"bytes */{len(data)}"})
        return Response(content=data[start:end + 1], status_code=206, media_type=ev["mime"], headers={
            "Content-Range": f"bytes {start}-{end}/{len(data)}", "Accept-Ranges": "bytes", "Cache-Control": "private, max-age=3600"})
    return Response(content=data, media_type=ev["mime"], headers={"Cache-Control": "private, max-age=3600", "Accept-Ranges": "bytes"})


@router.get("/evidence/{evidence_id}/frames/{frame_id}", tags=["evidence"])
async def video_frame(evidence_id: str, frame_id: str, user=Depends(current_user)):
    """The exact JPEG frame that was analysed (boxes are normalized to this image). The original video is unchanged."""
    ev, _ = await get_scoped("evidence", user, evidence_id)
    run = await db.image_analysis_runs.find_one({"evidence_id": ev["uuid"], "frames.id": frame_id}, {"frames": 1})
    fr = next((f for f in (run or {}).get("frames", []) if f["id"] == frame_id), None)
    if not fr:
        raise HTTPException(404, "Not found")
    data = await asyncio.to_thread(storage.get_object, fr["storage_path"])
    return Response(content=data, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400", "X-Frame-Sha256": fr["sha256"],
                                                                    "X-Video-Timestamp-S": str(fr["t"])})


@router.get("/evidence/{evidence_id}/content-info", tags=["evidence"])
async def content_info(evidence_id: str, user=Depends(current_user)):
    """Plain state of one item (used by both clients): upload state, server-side rejection reason, video probe facts,
    playback URL. Video playback supports HTTP Range (206)."""
    ev, _ = await get_scoped("evidence", user, evidence_id)
    return {"evidence_id": evidence_id, "kind": ev["kind"], "upload_state": ev["upload_state"], "reject_reason": ev.get("reject_reason"),
            "video": ev.get("video"), "analysis_intent": ev.get("analysis_intent"), "playback_url": f"/api/evidence/{evidence_id}/content"
            if ev["upload_state"] == "Verified" else None}


@router.get("/visits/{visit_id}/evidence", tags=["evidence"])
async def list_evidence(visit_id: str, user=Depends(current_user)):
    await get_visit(user, visit_id)
    return clean_all(await db.evidence.find({"visit_id": visit_id}).sort("created_at", 1).to_list(500))


# ---------------- transfer manifest + single complete receipt ----------------
class Member(BaseModel):
    evidence_id: str
    sha256: str
    size: int


class ManifestIn(BaseModel):
    members: list[Member] = Field(min_length=1)
    device_id: Optional[str] = None


async def _evaluate_manifest(m: dict, visit: dict, user: dict) -> dict:
    missing = []
    for mem in m["members"]:
        ev = await db.evidence.find_one({"uuid": mem["evidence_id"], "visit_id": visit["uuid"]})
        if not ev:
            missing.append({**mem, "reason": "not received"})
        elif ev["upload_state"] != "Verified":
            missing.append({**mem, "reason": ev["upload_state"]})
        elif ev["server_sha256"] != mem["sha256"] or ev["server_size"] != mem["size"]:
            missing.append({**mem, "reason": "hash/size mismatch with manifest"})
    if missing:
        await db.manifests.update_one({"uuid": m["uuid"]}, {"$set": {"state": "Receiving partial", "missing": missing, "updated_at": iso()}})
        return {**m, "state": "Receiving partial", "missing": missing, "receipt_id": None}
    # one complete receipt per manifest (unique index on manifest_id)
    await db.receipts.update_one({"manifest_id": m["uuid"]}, {"$setOnInsert": {
        "uuid": new_id(), "manifest_id": m["uuid"], "workspace_id": visit["workspace_id"], "visit_id": visit["uuid"],
        "manifest_hash": m["manifest_hash"], "member_count": len(m["members"]), "issued_at": iso(), "issued_by": "server",
        "created_at": iso(), "created_by": user["uuid"], "revision": 1}}, upsert=True)
    r = await db.receipts.find_one({"manifest_id": m["uuid"]})
    # B2: enqueue (idempotent, unique stage+target) BEFORE the manifest is marked complete, so a crash can never leave a
    # "Received complete" transfer without its processing jobs; the recovery pass covers the receipt→enqueue window.
    for mem in m["members"]:
        ev = await db.evidence.find_one({"uuid": mem["evidence_id"]})
        await db.evidence.update_one({"uuid": ev["uuid"]}, {"$set": {"receipt_id": ev.get("receipt_id") or r["uuid"]}})
        await jobs.enqueue_for_evidence(visit, ev)
        await db.evidence.update_one({"uuid": ev["uuid"]}, {"$set": {"jobs_enqueued_at": iso()}})
    await db.manifests.update_one({"uuid": m["uuid"]}, {"$set": {"state": "Received complete", "missing": [], "receipt_id": r["uuid"], "updated_at": iso()}})
    return {**m, "state": "Received complete", "missing": [], "receipt_id": r["uuid"]}


@router.post("/visits/{visit_id}/manifests", tags=["transfer"])
async def finalize_manifest(visit_id: str, body: ManifestIn, user=Depends(current_user)):
    v = await get_visit(user, visit_id)
    members = sorted([m.model_dump() for m in body.members], key=lambda x: x["evidence_id"])
    mhash = sha256_hex(json.dumps({"visit_id": visit_id, "members": members}, sort_keys=True).encode())
    m = await db.manifests.find_one({"visit_id": visit_id, "manifest_hash": mhash})
    if not m:
        assert_editable(v, user)
        m = {"uuid": new_id(), "workspace_id": v["workspace_id"], "visit_id": visit_id, "manifest_hash": mhash,
             "members": members, "device_id": body.device_id, "state": "Receiving partial", "receipt_id": None, **stamp(user)}
        try:
            await db.manifests.insert_one(m)
        except Exception:
            m = await db.manifests.find_one({"visit_id": visit_id, "manifest_hash": mhash})
    if m.get("state") == "Received complete":
        return clean(m)  # lost-ack retry: same manifest + same receipt
    return clean(await _evaluate_manifest(m, v, user))


@router.get("/visits/{visit_id}/manifests", tags=["transfer"])
async def list_manifests(visit_id: str, user=Depends(current_user)):
    await get_visit(user, visit_id)
    return clean_all(await db.manifests.find({"visit_id": visit_id}).sort("created_at", 1).to_list(100))


async def upload_gaps(visit_id: str) -> dict:
    not_verified = await db.evidence.count_documents({"visit_id": visit_id, "upload_state": {"$ne": "Verified"}})
    no_receipt = await db.evidence.count_documents({"visit_id": visit_id, "upload_state": "Verified", "receipt_id": None})
    return {"not_verified": not_verified, "no_receipt": no_receipt, "missing": not_verified + no_receipt}


# ---------------- readiness, departure check, submit ----------------
@router.get("/visits/{visit_id}/readiness", tags=["readiness"])
async def get_readiness(visit_id: str, user=Depends(current_user)):
    v = await get_visit(user, visit_id)
    r = await readiness.compute(v)
    r["uploads"] = await upload_gaps(visit_id)
    r["visit_revision"] = v["revision"]
    r["status"] = v["status"]
    return r


@router.get("/visits/{visit_id}/departure", tags=["readiness"])
async def departure(visit_id: str, user=Depends(current_user)):
    """One missing-field question at a time; one open question per field/revision (unique index)."""
    v = await get_visit(user, visit_id)
    r = await readiness.compute(v)
    pending = [f for f in r["fields"] if f["state"] in ("Missing required", "Needs review")]
    q = None
    if pending and v["status"] == "Draft":
        f = pending[0]
        await db.questions.update_one(
            {"visit_id": visit_id, "field": f["field"], "visit_revision": v["revision"], "status": "open"},
            {"$setOnInsert": {"uuid": new_id(), "workspace_id": v["workspace_id"], "prompt": f["question"], "created_at": iso(),
                              "created_by": user["uuid"], "revision": 1}}, upsert=True)
        q = {**clean(await db.questions.find_one({"visit_id": visit_id, "field": f["field"], "visit_revision": v["revision"], "status": "open"})),
             "field_info": f}
    return {"question": q, "remaining": len(pending), "readiness": r, "visit_revision": v["revision"],
            "uploads": await upload_gaps(visit_id), "status": v["status"]}


class FieldAction(BaseModel):
    expected_revision: int
    action: Literal["answer", "accept_proposal", "needs_estimator_input", "unknown", "not_applicable"]
    value: Optional[str] = None
    proposal_id: Optional[str] = None
    reason: Optional[str] = None
    source: Literal["typed", "departure_check", "review"] = "typed"


@router.post("/visits/{visit_id}/fields/{field}", tags=["readiness"])
async def set_field(visit_id: str, field: str, body: FieldAction, user=Depends(current_user)):
    v = await get_visit(user, visit_id)
    assert_editable(v, user)
    if field not in readiness.FIELD_KEYS:
        raise HTTPException(404, "Unknown field")
    fdef = next(f for f in readiness.FIELDS if f["key"] == field)
    props = (await readiness.proposals_by_field(visit_id)).get(field, [])
    entry = {"by": user["uuid"], "by_role": user["role"], "at": iso(), "source": body.source}
    if body.action == "answer":
        val = (body.value or "").strip()
        if not val:
            raise HTTPException(422, "Typed value required (audio alone never satisfies a field)")
        if fdef["type"] == "integer":
            if not val.isdigit():
                raise HTTPException(422, "Whole number required")
            val = int(val)
        if fdef["type"] == "enum" and val not in fdef["options"]:
            raise HTTPException(422, f"One of {fdef['options']}")
        entry.update({"state": "Provided", "value": val, "resolves_discrepancy": len({str(p['value']) for p in props}) > 1,
                      "relevance": await _relevance(v, fdef, str(val))})
    elif body.action == "accept_proposal":
        p = next((x for x in props if x["uuid"] == body.proposal_id), None)
        if not p:
            raise HTTPException(404, "Not found")
        entry.update({"state": "Provided", "value": p["value"], "proposal_id": p["uuid"], "excerpt": p["excerpt"],
                      "resolves_discrepancy": True, "rejected_values": sorted({str(x["value"]) for x in props if x["uuid"] != p["uuid"]})})
    else:
        if not (body.reason or "").strip():
            raise HTTPException(422, "Reason required")
        entry.update({"state": {"needs_estimator_input": "Needs estimator input", "unknown": "Unknown with reason",
                                "not_applicable": "Not applicable"}[body.action], "value": None, "reason": body.reason.strip()})
    res = await bump_visit(v, user, body.expected_revision, {f"answers.{field}": entry})
    await db.questions.update_many({"visit_id": visit_id, "field": field, "status": "open"},
                                   {"$set": {"status": "closed", "closed_with": entry["state"], "closed_at": iso()}})
    await audit(user, v["workspace_id"], "field_" + body.action, "visit", visit_id, {"field": field, "entry": entry})
    return clean(res)


async def _relevance(v: dict, fdef: dict, answer: str) -> dict:
    """Jev relevance of a typed answer vs the question. Flag only; gated by processing permission; cached by input hash."""
    if not await __import__("policy").visit_allowed(v):
        return {"status": "Not run", "reason": jobs.BLOCKER, "low": False}
    h = sha256_hex(json.dumps([fdef["question"], answer]).encode())
    hit = await db.text_checks.find_one({"kind": "answer_relevance", "input_sha256": h, "status": "Done", "workspace_id": v["workspace_id"]})
    if hit:
        return {"status": "Done", **hit["result"], "check_id": hit["uuid"], "reused_from_cache": True}
    try:
        res = await ai_jev.answer_relevance(fdef["question"], answer)
    except Exception as e:
        return {"status": "Not run", "reason": f"Jev unavailable: {type(e).__name__}", "low": False}
    cid = new_id()
    await db.text_checks.insert_one({"uuid": cid, "workspace_id": v["workspace_id"], "visit_id": v["uuid"], "kind": "answer_relevance",
                                     "target_id": f"{v['uuid']}:{fdef['key']}", "input_sha256": h, "model_id": res["model_id"],
                                     "result": res, "status": "Done", "created_at": iso(), "created_by": "system"})
    return {"status": "Done", **res, "check_id": cid}


class SubmitIn(BaseModel):
    expected_revision: int
    device_unsynced: int = 0


@router.post("/visits/{visit_id}/submit", tags=["visits"])
async def submit_visit(visit_id: str, body: SubmitIn, user=Depends(require_role("foreman"))):
    v = await get_visit(user, visit_id)
    if v["status"] == "Submitted":
        raise HTTPException(423, SUBMITTED_MSG)
    gaps = await upload_gaps(visit_id)
    missing = gaps["missing"] + max(0, body.device_unsynced)
    if missing:
        raise HTTPException(409, {"code": "uploads_incomplete", "missing": missing,
                                  "message": f"Submit blocked: {missing} item(s) not yet verified on the server."})
    res = await bump_visit(v, user, body.expected_revision, {"status": "Submitted", "submitted_at": iso(), "submitted_by": user["uuid"]})
    await audit(user, v["workspace_id"], "visit_submitted", "visit", visit_id)
    return clean(res)


@router.post("/visits/{visit_id}/reopen", tags=["visits"])
async def reopen_visit(visit_id: str, body: SubmitIn, user=Depends(require_role("estimator", "admin"))):
    v = await get_visit(user, visit_id)
    if v["status"] != "Submitted":
        raise HTTPException(409, {"code": "not_submitted", "message": "Only submitted visits can be reopened"})
    res = await bump_visit(v, user, body.expected_revision, {"status": "Draft", "reopened_at": iso(), "reopened_by": user["uuid"]})
    await audit(user, v["workspace_id"], "visit_reopened", "visit", visit_id)
    return clean(res)
