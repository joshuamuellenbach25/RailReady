"""Shared infrastructure: DB, auth, scoping, revisions, audit."""
import os
import uuid
import hashlib
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import pillow_heif

pillow_heif.register_heif_opener()  # B4: iPhone HEIC/HEIF photos decode everywhere PIL is used (analysis converts to JPEG)
import bcrypt
import jwt
from dotenv import load_dotenv
from fastapi import Depends, HTTPException, Request
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv(Path(__file__).parent / ".env")

client = AsyncIOMotorClient(os.environ["MONGO_URL"])
db = client[os.environ["DB_NAME"]]
JWT_SECRET = os.environ["JWT_SECRET"]
APP_NAME = os.environ.get("APP_NAME", "railready")
ACCESS_TTL_HOURS = 24 * 7  # field devices sync after long offline periods

SUBMITTED_MSG = "Submitted. Ask estimator to reopen"


def now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: Optional[datetime] = None) -> str:
    return (dt or now()).isoformat()


def new_id() -> str:
    return str(uuid.uuid4())


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def clean(doc):
    """Never return raw Mongo docs: drop _id and secrets."""
    if doc is None:
        return None
    doc = dict(doc)
    doc.pop("_id", None)
    doc.pop("password_hash", None)
    return doc


def clean_all(docs):
    return [clean(d) for d in docs]


def stamp(user: dict, create: bool = True) -> dict:
    t = iso()
    base = {"updated_at": t, "updated_by": user["uuid"]}
    if create:
        base.update({"created_at": t, "created_by": user["uuid"], "revision": 1})
    return base


# ---------------- auth ----------------
def hash_password(p: str) -> str:
    return bcrypt.hashpw(p.encode(), bcrypt.gensalt()).decode()


def verify_password(p: str, h: str) -> bool:
    return bcrypt.checkpw(p.encode(), h.encode())


def create_token(user: dict) -> str:
    payload = {"sub": user["uuid"], "type": "access", "exp": now() + timedelta(hours=ACCESS_TTL_HOURS)}
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


async def user_from_token(token: Optional[str]) -> dict:
    if not token:
        raise HTTPException(401, "Not authenticated")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Session expired. Sign in again")
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Invalid session")
    if payload.get("type") != "access":
        raise HTTPException(401, "Invalid session")
    user = await db.users.find_one({"uuid": payload["sub"]})
    if not user:
        raise HTTPException(401, "User not found")
    if user.get("demo_expires_at") and user["demo_expires_at"] <= iso():
        raise HTTPException(401, "Demo session expired. Open a new demo workspace")
    return clean(user)


def has_role(user: dict, *roles) -> bool:
    return user["role"] in roles or bool(set(user.get("roles") or []) & set(roles))


async def current_user(request: Request) -> dict:
    auth = request.headers.get("Authorization", "")
    token = auth[7:] if auth.startswith("Bearer ") else request.query_params.get("auth")
    return await user_from_token(token)


def require_role(*roles):
    async def dep(user: dict = Depends(current_user)):
        if not has_role(user, *roles):
            raise HTTPException(403, "Not permitted for your role")
        return user
    return dep


# ---------------- scoping (404 on foreign ids) ----------------
def visit_scope(user: dict) -> dict:
    q = {"workspace_id": user["workspace_id"]}
    if user["role"] == "foreman":
        q["foreman_id"] = user["uuid"]
    return q


async def get_visit(user: dict, visit_id: str) -> dict:
    v = await db.visits.find_one({"uuid": visit_id, **visit_scope(user)})
    if not v:
        raise HTTPException(404, "Not found")
    return v


async def get_scoped(collection: str, user: dict, item_id: str) -> tuple[dict, dict]:
    """Fetch a child doc by uuid, then verify its parent visit is in scope."""
    doc = await db[collection].find_one({"uuid": item_id, "workspace_id": user["workspace_id"]})
    if not doc:
        raise HTTPException(404, "Not found")
    visit = await get_visit(user, doc["visit_id"])
    return doc, visit


def assert_editable(visit: dict, user: dict):
    if visit["status"] == "Submitted" and user["role"] == "foreman":
        raise HTTPException(423, SUBMITTED_MSG)


def revision_conflict(current: dict, kind: str):
    raise HTTPException(409, {
        "code": "stale_revision",
        "message": f"This {kind} was changed elsewhere. Server value kept; your edit is kept as a recovery copy on this device.",
        "server": clean(current),
    })


async def bump_visit(visit: dict, user: dict, expected_revision: Optional[int], update: dict) -> dict:
    """Optimistic-concurrency write on a visit. 409 on stale expected revision."""
    if expected_revision is not None and expected_revision != visit["revision"]:
        revision_conflict(visit, "visit")
    q = {"uuid": visit["uuid"], "revision": visit["revision"]}
    res = await db.visits.find_one_and_update(
        q,
        {"$set": {**update, "updated_at": iso(), "updated_by": user["uuid"]}, "$inc": {"revision": 1}},
        return_document=True,
    )
    if not res:
        revision_conflict(await db.visits.find_one({"uuid": visit["uuid"]}), "visit")
    return res


async def audit(user: Optional[dict], workspace_id: str, action: str, target_type: str, target_id: str, detail: Optional[dict] = None):
    await db.audit_events.insert_one({
        "uuid": new_id(), "workspace_id": workspace_id, "actor_id": user["uuid"] if user else "system",
        "actor_role": user["role"] if user else "system", "action": action, "target_type": target_type,
        "target_id": target_id, "detail": detail or {}, "at": iso(),
    })


async def ensure_indexes():
    u = dict(unique=True)
    await db.users.create_index("email", **u)
    for c in ["workspaces", "users", "customers", "sites", "tracks", "crews", "visits", "evidence", "observations",
              "manifests", "receipts", "jobs", "transcripts", "extraction_runs", "proposed_fields",
              "image_analysis_runs", "visual_candidates", "candidate_decisions", "questions", "catalog_items", "text_checks", "engagements", "estimate_drafts", "scope_items", "proposal_versions", "share_links", "decisions", "work_orders", "packages"]:
        await db[c].create_index("uuid", **u)
    await db.manifests.create_index([("visit_id", 1), ("manifest_hash", 1)], **u)
    await db.receipts.create_index("manifest_id", **u)
    await db.jobs.create_index([("stage", 1), ("target_id", 1)], **u)
    await db.jobs.create_index([("status", 1), ("stage", 1)])
    await db.transcripts.create_index([("evidence_id", 1), ("version", 1)], **u)
    await db.questions.create_index(
        [("visit_id", 1), ("field", 1), ("visit_revision", 1)],
        unique=True, partialFilterExpression={"status": "open"},
    )
    await db.evidence.create_index("visit_id")
    await db.visual_candidates.create_index("evidence_id")
    await db.proposed_fields.create_index([("visit_id", 1), ("field", 1)])
    await db.login_attempts.create_index("identifier")
    await db.engagements.create_index("visit_id", **u)
    await db.proposal_versions.create_index([("engagement_id", 1), ("version_no", 1)], **u)
    await db.proposal_versions.create_index([("draft_id", 1), ("draft_revision", 1)], **u)
    await db.share_links.create_index("token_hash", **u)
    await db.decisions.create_index([("version_id", 1), ("request_key", 1)], **u)
    await db.work_orders.create_index("engagement_id", **u)
    await db.work_orders.create_index("accepted_version_id", **u)
    await db.scenes.create_index([("scene_id", 1), ("revision", 1)], **u)
    await db.scenes.create_index("uuid", **u)
    await db.scenes.create_index("scene_key")
    await db.anchors.create_index("uuid", **u)
    await db.anchors.create_index([("anchor_id", 1), ("version", 1)], **u)
    await db.anchors.create_index([("item_id", 1), ("scene_id", 1), ("scene_revision", 1), ("version", 1)], **u)
    await db.demo_sessions.create_index("uuid", **u)
    await db.anchors.create_index([("evidence_id", 1), ("scene_revision", 1), ("item_id", 1)], unique=True, name="one_current_anchor",
                                  partialFilterExpression={"current": True})
    await db.processing_policies.create_index([("workspace_id", 1), ("version", 1)], **u)
    await db.processing_policies.create_index("workspace_id", unique=True, name="one_current_policy", partialFilterExpression={"current": True})
    await db.checklist_templates.create_index([("workspace_id", 1), ("template_id", 1), ("version", 1)], **u)
    await db.checklist_templates.create_index([("workspace_id", 1), ("template_id", 1)], unique=True, name="one_current_template", partialFilterExpression={"current": True})
    await db.scene_views.create_index([("scene_uuid", 1), ("user_id", 1)], **u)


async def visit_location(visit_id: Optional[str]) -> Optional[dict]:
    """Phase 16: the selected inspection location (pin + its location record), shown on inspection, work order and repair."""
    if not visit_id:
        return None
    pin = await db.pins.find_one({"visit_id": visit_id})
    loc = await db.locations.find_one({"uuid": pin["location_id"]}) if pin else None
    if not pin or not loc:
        return None
    rw = loc.get("railway") or {}
    mp = (rw.get("milepost") or {}).get("text")
    return {"pin_id": pin["uuid"], "site_id": pin["site_id"], "location_id": loc["uuid"], "lat": loc.get("lat"), "lon": loc.get("lon"),
            "method": loc.get("method") or "pin", "method_label": loc.get("method_label") or "Map pin", "railroad": rw.get("railroad"),
            "subdivision": rw.get("subdivision"), "milepost": mp, "milepost_ref": loc.get("milepost_ref"), "label": loc.get("label"),
            "source": loc.get("source"), "accuracy_m": loc.get("accuracy_m"), "fixed_at": loc.get("fixed_at"), "recorded_at": loc.get("created_at")}
