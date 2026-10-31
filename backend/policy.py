"""Organization processing policy (REQ-206..212): versioned per workspace; site/customer restrictions; evidence-level exceptions.
Legacy per-visit Denied/Unknown stay restrictions (REQ-209). Evaluated at enqueue AND at job execution (REQ-211)."""
import logging
from typing import Optional

from pymongo.errors import DuplicateKeyError

from core import db, iso, new_id

BLOCKED_MSG = "Analysis not enabled for this site. Contact your admin"
PENDING = "pending_policy_changes"
log = logging.getLogger("policy")


async def current(ws: str) -> dict:
    p = await db.processing_policies.find_one({"workspace_id": ws, "current": True}, {"_id": 0, PENDING: 0})
    if p:
        return p
    doc = {"uuid": new_id(), "workspace_id": ws, "version": 1, "current": True, "default": "allow", "restrictions": [], "evidence_exceptions": [],
           "note": "Initial policy (migration): processing allowed by default; legacy per-visit Denied/Unknown values remain visit restrictions.",
           "created_by": "system", "created_at": iso()}
    try:
        await db.processing_policies.insert_one(dict(doc))
    except Exception:
        return await db.processing_policies.find_one({"workspace_id": ws, "current": True}, {"_id": 0})
    return doc


async def evaluate(visit: dict, evidence_id: Optional[str] = None) -> dict:
    p = await current(visit["workspace_id"])
    out = lambda allowed, basis, detail=None: {"allowed": allowed, "basis": basis, "detail": detail, "policy_version": p["version"],
                                               "message": None if allowed else BLOCKED_MSG}
    if evidence_id:
        for e in p.get("evidence_exceptions", []):
            if e["evidence_id"] == evidence_id:
                return out(bool(e["allow"]), "evidence_exception", e.get("reason"))
    if visit.get("processing_permission") in ("Denied", "Unknown"):
        return out(False, f"legacy_visit_{visit['processing_permission'].lower()}", "Pre-policy per-visit value kept as a restriction")
    for r in p.get("restrictions", []):
        if (r["scope"] == "site" and r["id"] == visit.get("site_id")) or (r["scope"] == "customer" and r["id"] == visit.get("customer_id")) \
                or (r["scope"] == "visit" and r["id"] == visit.get("uuid")):
            return out(False, f"{r['scope']}_restriction", r.get("reason"))
    return out(p["default"] == "allow", "organization_default")


async def visit_allowed(visit: dict, evidence_id: Optional[str] = None) -> bool:
    return (await evaluate(visit, evidence_id))["allowed"]


async def evaluate_job(job: dict) -> dict:
    """Resolve the actual evidence, scoped to this job's workspace and current visit."""
    denied = {"allowed": False, "basis": "job_source_unavailable", "policy_version": None,
              "message": BLOCKED_MSG}
    scope = {"workspace_id": job["workspace_id"], "visit_id": job["visit_id"]}
    visit = await db.visits.find_one({"uuid": job["visit_id"], "workspace_id": job["workspace_id"]})
    if not visit or visit.get("status") == "Draft-deleted":
        return denied
    evidence_id = job["target_id"]
    if job["stage"] == "photo_analysis":
        source = await db.image_analysis_runs.find_one({"uuid": evidence_id, **scope})
        evidence_id = source.get("evidence_id") if source else None
    elif job.get("source_kind") == "transcript":
        source = await db.transcripts.find_one({"uuid": evidence_id, **scope})
        evidence_id = source.get("evidence_id") if source else None
    if not evidence_id or not await db.evidence.find_one({"uuid": evidence_id, **scope}, {"_id": 1}):
        return denied
    return await evaluate(visit, evidence_id)


def snapshot(document: dict) -> dict:
    return {key: value for key, value in document.items() if key not in ("_id", PENDING)}


def transition(previous: dict, updated: dict, user: dict) -> dict:
    return {
        "id": updated["uuid"],
        "previous": {**snapshot(previous), "current": False},
        "audit": {
            "uuid": "policy-change-" + updated["uuid"],
            "workspace_id": updated["workspace_id"],
            "actor_id": user["uuid"], "actor_role": user["role"],
            "action": "policy_changed", "target_type": "policy",
            "target_id": updated["uuid"], "detail": {"version": updated["version"]},
            "at": updated["created_at"],
        },
    }


async def flush_pending(ws: str) -> None:
    current_policy = await db.processing_policies.find_one({"workspace_id": ws, "current": True})
    if not current_policy:
        return
    for event in current_policy.get(PENDING, []):
        previous = event["previous"]
        key = {"workspace_id": ws, "version": previous["version"]}
        try:
            await db.processing_policies.update_one(key, {"$setOnInsert": previous}, upsert=True)
        except DuplicateKeyError:
            pass
        archived = await db.processing_policies.find_one(key)
        if not archived or snapshot(archived) != previous:
            raise RuntimeError("Policy history conflicts with its durable snapshot")
        audit_key = {"_id": "policy-change:" + event["id"]}
        try:
            await db.audit_events.update_one(audit_key, {"$setOnInsert": event["audit"]}, upsert=True)
        except DuplicateKeyError:
            pass
        stored_audit = await db.audit_events.find_one(audit_key)
        if not stored_audit or snapshot(stored_audit) != event["audit"]:
            raise RuntimeError("Policy audit conflicts with its durable snapshot")
        await db.processing_policies.update_one(
            {"workspace_id": ws, "current": True}, {"$pull": {PENDING: {"id": event["id"]}}})


async def recover_pending() -> None:
    async for document in db.processing_policies.find({"current": True}):
        if not document.get(PENDING):
            continue
        try:
            await flush_pending(document["workspace_id"])
        except Exception:
            log.exception("Policy history recovery remains pending for %s", document["workspace_id"])


async def versions(ws: str) -> list:
    documents = await db.processing_policies.find({"workspace_id": ws}, {"_id": 0}).sort("version", -1).to_list(100)
    result = {document["version"]: snapshot(document) for document in documents}
    for document in documents:
        for event in document.get(PENDING, []):
            previous = event["previous"]
            result.setdefault(previous["version"], previous)
    return sorted(result.values(), key=lambda item: item["version"], reverse=True)[:100]
