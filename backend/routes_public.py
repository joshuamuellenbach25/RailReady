"""Customer bearer-link API. Allowlisted serializers only; token stored hashed; never logged. Rate-limited decisions."""
import asyncio
import hashlib
import json
import re
import time
from collections import defaultdict, deque
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel

from core import audit, db, iso, new_id, sha256_hex
import agreement
import ai_jev
import storage
from routes_estimate import contract_status, version_status

router = APIRouter(prefix="/api/public", tags=["public"])
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_hits: dict = defaultdict(deque)
GONE = "This link is no longer valid"


def rate_limit(request: Request, n=20, window=60):
    k = request.client.host if request.client else "?"
    q, t = _hits[k], time.time()
    while q and q[0] < t - window:
        q.popleft()
    if len(q) >= n:
        raise HTTPException(429, "Too many requests. Try again in a minute")
    q.append(t)


async def resolve(token: str):
    link = await db.share_links.find_one({"token_hash": sha256_hex(token.encode())})
    if not link or link["revoked"]:
        raise HTTPException(404, GONE)
    v = await with_correction(await db.proposal_versions.find_one({"uuid": link["version_id"]}))
    eng = await db.engagements.find_one({"uuid": v["engagement_id"]})
    return link, v, eng


def public_view(v, eng, token):
    """Allowlist: no cost, markup, margin, audio, transcripts, audit, candidates, model data, internal ids."""
    s = v.get("display_snapshot") or v["snapshot"]  # versioned display correction, original snapshot/hash untouched
    st = version_status(v, eng)
    return {
        "version_no": v["version_no"], "proposal_number": s["proposal_number"], "status": st, "contract_status": contract_status(st),
        "can_decide": st == "Published", "published_at": v["published_at"], "contractor": s["contractor"], "customer_site": s["customer_site"],
        "findings": s["findings"], "not_inspected": s["not_inspected"], "ties_supplied_by_customer": s["ties_supplied_by_customer"],
        "lines": [{k: l[k] for k in ("description", "quantity", "unit", "unit_price", "line_total", "taxable")} for l in s["lines"]],
        "totals": {k: s["totals"][k] for k in ("subtotal", "tax_rate", "tax", "total", "currency")},
        "tax_treatment_text": s["tax_treatment_text"], "terms": s["terms"], "expiry": s["expiry"],
        "photos": [{"url": f"/api/public/proposals/{token}/media/{p['evidence_id']}", "caption": p.get("caption")} for p in s["photos"]],
        "agreement": {k: s["agreement"][k] for k in ("label", "document_text", "document_hash", "template_version")},
        "snapshot_hash": v["snapshot_hash"],
    }


@router.get("/proposals/{token}")
async def public_get(token: str):
    _, v, eng = await resolve(token)
    out = public_view(v, eng, token)
    if out["status"] == "Accepted":
        wo = await db.work_orders.find_one({"engagement_id": eng["uuid"]})
        out["accepted"] = {"at": eng.get("accepted_at"), "work_order_number": wo and wo["number"]}
    return out


async def stream_snapshot_media(v, eid):
    p = next((p for p in v["snapshot"]["photos"] if p["evidence_id"] == eid), None)
    if not p:
        raise HTTPException(404, "Not found")
    ev = await db.evidence.find_one({"uuid": eid})
    data = await asyncio.to_thread(storage.get_object, ev["storage_path"])
    if sha256_hex(data) != p["sha256"]:
        raise HTTPException(404, "Not found")
    return Response(content=data, media_type=ev["mime"], headers={"Cache-Control": "private, max-age=600"})


@router.get("/proposals/{token}/media/{eid}")
async def public_media(token: str, eid: str):
    _, v, _ = await resolve(token)
    return await stream_snapshot_media(v, eid)


@router.get("/proposals/{token}/print", response_class=HTMLResponse)
async def public_print(token: str):
    _, v, _ = await resolve(token)
    return agreement.print_html(v.get("display_snapshot") or v["snapshot"], v, lambda eid: f"/api/public/proposals/{token}/media/{eid}")


async def with_correction(v):
    """Attach the latest display-copy correction (if any). The issued version, its hashes and signatures are not modified."""
    c = await db.document_corrections.find_one({"version_id": v["uuid"], "kind": "display_copy"}, sort=[("correction_no", -1)])
    if c:
        v["display_snapshot"] = c["corrected_snapshot"]
        v["correction"] = {"correction_no": c["correction_no"], "original_document_hash": c["original_document_hash"], "at": c["at"]}
    return v


class AcceptIn(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    agree: bool = False


class ChangesIn(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    comment: Optional[str] = None
    request_key: Optional[str] = None


def check_person(name, email, extra: dict):
    errs = dict(extra)
    if not (name or "").strip():
        errs["name"] = "Name is required"
    if not EMAIL.match((email or "").strip()):
        errs["email"] = "Valid email is required"
    if errs:
        raise HTTPException(422, {"code": "field_errors", "errors": errs})


async def _wo_response(eng):
    wo = await db.work_orders.find_one({"engagement_id": eng["uuid"]})
    return {"status": "Accepted", "work_order_number": wo["number"], "work_order_id": wo["uuid"], "accepted_at": eng.get("accepted_at")}


def _deny(st):
    msg = {"Expired": "This proposal has expired", "Superseded": "This version was replaced by a newer version",
           "Changes requested": "Changes were requested on this version; acceptance is disabled"}.get(st, f"This proposal is {st}")
    raise HTTPException(409, {"code": st.lower().replace(" ", "_"), "message": msg})


async def ensure_work_order(eng, v, decision_id):
    await db.work_orders.update_one({"engagement_id": eng["uuid"]}, {"$setOnInsert": {
        "uuid": new_id(), "workspace_id": eng["workspace_id"], "engagement_id": eng["uuid"], "accepted_version_id": v["uuid"],
        "number": f"WO-{eng['proposal_number'][3:]}-{v['version_no']}", "decision_id": decision_id,
        "frozen_scope": {"version_no": v["version_no"], "snapshot_hash": v["snapshot_hash"], "document_hash": v["document_hash"],
                         "findings": v["snapshot"]["findings"], "lines": v["snapshot"]["lines"], "totals": v["snapshot"]["totals"],
                         "not_inspected": v["snapshot"]["not_inspected"], "ties_supplied_by_customer": v["snapshot"]["ties_supplied_by_customer"]},
        "crew_id": None, "scheduled_date": None, "access_status": "Not arranged", "access_history": [],
        "status": "Planning", "created_at": iso(), "created_by": "customer", "updated_at": iso(), "revision": 1}}, upsert=True)


@router.post("/proposals/{token}/accept")
async def accept(token: str, body: AcceptIn, request: Request):
    rate_limit(request)
    link, v, eng = await resolve(token)
    check_person(body.name, body.email, {} if body.agree else {"agree": "You must check the agreement box"})
    if eng.get("accepted_version_id") == v["uuid"]:
        return await complete_acceptance(eng, v, body, link)  # retry after lost response -> same complete result
    st = version_status(v, eng)
    if st != "Published":
        _deny(st)
    t = iso()
    # B6 step 1: canonical decision document is written FIRST (state Pending = outbox); nothing is accepted yet.
    await _accept_decision(eng, v, body, link, t)
    # step 2: single-document CAS on the engagement = the acceptance arbiter
    won = await db.engagements.find_one_and_update(
        {"uuid": eng["uuid"], "accepted_version_id": None, "latest_version_id": v["uuid"], "changes_requested_version_ids": {"$ne": v["uuid"]},
         **({} if v["expiry_utc"] > t else {"_never": True})},
        {"$set": {"accepted_version_id": v["uuid"], "accepted_at": t, "status": "Accepted"}, "$inc": {"revision": 1}}, return_document=True)
    if not won:
        eng = await db.engagements.find_one({"uuid": eng["uuid"]})
        if eng.get("accepted_version_id") == v["uuid"]:
            return await complete_acceptance(eng, v, body, link)
        await db.decisions.update_one({"version_id": v["uuid"], "request_key": "accept", "state": "Pending"}, {"$set": {"state": "Void", "voided_at": iso()}})
        _deny(version_status(v, eng) if v["expiry_utc"] > t else "Expired")
    # step 3: completion (idempotent; also run by the startup recovery pass)
    return await complete_acceptance(won, v, body, link)


async def _accept_decision(eng, v, body, link, t):
    await db.decisions.update_one({"version_id": v["uuid"], "request_key": "accept"}, {"$setOnInsert": {
        "uuid": new_id(), "workspace_id": v["workspace_id"], "engagement_id": eng["uuid"], "version_id": v["uuid"], "version_no": v["version_no"],
        "type": "accept", "name": body.name.strip(), "email": body.email.strip(), "agreement_checked": True,
        "agreement_hash": v["document_hash"], "snapshot_hash": v["snapshot_hash"], "link_id": link["uuid"], "at": t, "state": "Pending"}}, upsert=True)
    # a previously voided intent for this version is revived only by a new attempt
    await db.decisions.update_one({"version_id": v["uuid"], "request_key": "accept", "state": "Void"},
                                  {"$set": {"state": "Pending", "name": body.name.strip(), "email": body.email.strip(), "at": t}})


async def complete_acceptance(eng, v, body=None, link=None):
    """Decision + work order + version status as one recoverable unit. Returns the same complete result every time."""
    d = await db.decisions.find_one({"version_id": v["uuid"], "request_key": "accept"})
    if not d and body is not None:  # legacy engagement accepted before decision-first ordering
        await _accept_decision(eng, v, body, link, eng.get("accepted_at") or iso())
        d = await db.decisions.find_one({"version_id": v["uuid"], "request_key": "accept"})
    if not d:
        return None  # recovery pass without person details: left for admin (reported, never fabricated)
    await ensure_work_order(eng, v, d["uuid"])
    await db.work_orders.update_one({"engagement_id": eng["uuid"], "decision_id": None}, {"$set": {"decision_id": d["uuid"]}})
    await db.proposal_versions.update_one({"uuid": v["uuid"]}, {"$set": {"status": "Accepted"}})
    if d.get("state") != "Complete":
        if (await db.decisions.update_one({"uuid": d["uuid"], "state": {"$ne": "Complete"}}, {"$set": {"state": "Complete", "completed_at": iso()}})).modified_count:
            await audit(None, v["workspace_id"], "customer_accepted", "proposal_version", v["uuid"])
    return await _wo_response(eng)


async def recover_acceptances():
    """Startup recovery: finish Pending accept decisions whose engagement won; void stale losers; report legacy gaps."""
    out = {"completed": 0, "voided": 0, "legacy_without_decision": []}
    for d in await db.decisions.find({"type": "accept", "state": {"$in": ["Pending", None]}}).to_list(5000):
        eng = await db.engagements.find_one({"uuid": d["engagement_id"]})
        v = await db.proposal_versions.find_one({"uuid": d["version_id"]})
        if eng and v and eng.get("accepted_version_id") == v["uuid"]:
            await complete_acceptance(eng, v); out["completed"] += 1
        elif d.get("state") == "Pending":
            await db.decisions.update_one({"uuid": d["uuid"], "state": "Pending"}, {"$set": {"state": "Void", "voided_at": iso()}}); out["voided"] += 1
    for wo in await db.work_orders.find({"decision_id": None}).to_list(5000):
        eng = await db.engagements.find_one({"uuid": wo["engagement_id"]})
        v = await db.proposal_versions.find_one({"uuid": wo["accepted_version_id"]})
        if eng and v and not await complete_acceptance(eng, v):
            out["legacy_without_decision"].append(wo["number"])
    return out


@router.post("/proposals/{token}/changes")
async def request_changes(token: str, body: ChangesIn, request: Request):
    rate_limit(request)
    link, v, eng = await resolve(token)
    check_person(body.name, body.email, {} if (body.comment or "").strip() else {"comment": "Comment is required"})
    st = version_status(v, eng)
    if st not in ("Published", "Changes requested"):
        _deny(st)
    # B6 idempotency: stable client operation id + payload hash. Same id + same payload = replay of the same
    # request; same id + different payload = 409 (never a silent success for discarded input).
    payload = {"name": body.name.strip(), "email": body.email.strip().lower(), "comment": body.comment.strip()}
    phash = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    key = f"chg:{body.request_key}" if body.request_key else f"chg:{new_id()}"
    prior = await db.decisions.find_one({"version_id": v["uuid"], "request_key": key})
    if prior:
        if prior.get("payload_hash") != phash:
            raise HTTPException(409, {"code": "operation_id_reused", "message": "This request was already sent with different details. Please send it again."})
        return {"status": "Changes requested", "replayed": True, "message": "Your request was sent to the contractor. This version can no longer be accepted."}
    won = await db.engagements.find_one_and_update({"uuid": eng["uuid"], "accepted_version_id": None},
                                                   {"$addToSet": {"changes_requested_version_ids": v["uuid"]}, "$inc": {"revision": 1}})
    if not won:
        _deny("Accepted")
    did = new_id()
    visit = await db.visits.find_one({"uuid": v["visit_id"]})
    r = await db.decisions.update_one({"version_id": v["uuid"], "request_key": key}, {"$setOnInsert": {
        "uuid": did, "workspace_id": v["workspace_id"], "engagement_id": eng["uuid"], "version_id": v["uuid"], "version_no": v["version_no"],
        "type": "changes", "name": payload["name"], "email": body.email.strip(), "comment": payload["comment"], "payload_hash": phash,
        "link_id": link["uuid"], "at": iso(), "topic_suggestion": None, "state": "Complete"}}, upsert=True)
    if not r.upserted_id:  # concurrent twin with the same id
        prior = await db.decisions.find_one({"version_id": v["uuid"], "request_key": key})
        if prior.get("payload_hash") != phash:
            raise HTTPException(409, {"code": "operation_id_reused", "message": "This request was already sent with different details. Please send it again."})
    topic = {"status": "Not run", "reason": "Processing not permitted for this visit"}
    if await __import__("policy").visit_allowed(visit):
        try:
            topic = {"status": "Done", **await ai_jev.change_topic(body.comment.strip())}
        except Exception as e:
            topic = {"status": "Not run", "reason": f"Jev unavailable: {type(e).__name__}"}
    await db.decisions.update_one({"version_id": v["uuid"], "request_key": key, "topic_suggestion": None}, {"$set": {"topic_suggestion": topic}})
    await db.proposal_versions.update_one({"uuid": v["uuid"], "status": "Published"}, {"$set": {"status": "Changes requested"}})
    await audit(None, v["workspace_id"], "customer_changes_requested", "proposal_version", v["uuid"])
    return {"status": "Changes requested", "message": "Your request was sent to the contractor. This version can no longer be accepted."}
