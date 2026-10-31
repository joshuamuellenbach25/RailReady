"""Public demo sessions: each session = fresh workspace clone with NEW ids + one demo user (foreman+estimator).
Isolation is the normal workspace scoping (every query filters workspace_id → 404 outside). Expiry never deletes history."""
import asyncio
import secrets
from datetime import timedelta
from typing import Optional

import jwt
from fastapi import APIRouter, HTTPException, Request

from core import JWT_SECRET, clean, db, hash_password, iso, new_id, now, sha256_hex
import storage
from routes_public import _hits
from seed import E1, F1, WS1

router = APIRouter(prefix="/api/demo", tags=["demo"])
TTL = timedelta(hours=24)
RATE = (10, 60)
TOO_MANY = "Too many demo sessions. Try again in a minute"
VISIT_CHILDREN = ["evidence", "manifests", "receipts", "observations", "transcripts", "extraction_runs", "proposed_fields",
                  "text_checks", "image_analysis_runs", "visual_candidates", "candidate_decisions", "questions", "jobs"]


def _limit(request: Request):
    import time
    k = "demo:" + (request.client.host if request.client else "?")
    q, t = _hits[k], time.time()
    while q and q[0] < t - RATE[1]:
        q.popleft()
    if len(q) >= RATE[0]:
        raise HTTPException(429, TOO_MANY)
    q.append(t)


def remap(x, m: dict):
    if isinstance(x, str):
        return m.get(x, x)
    if isinstance(x, list):
        return [remap(i, m) for i in x]
    if isinstance(x, dict):
        return {k: remap(v, m) for k, v in x.items() if k != "_id"}
    return x


def stamp_sys(d: dict) -> dict:
    t = iso()
    return {**d, "created_at": d.get("created_at", t), "updated_at": t, "created_by": d.get("created_by", "demo-setup"), "updated_by": "demo-setup"}


class DemoStorageError(Exception):
    pass


async def _retry(fn, *a):
    """REQ-161: transient object-storage errors → up to 2 retries, then a clean 503 (never a raw 500)."""
    for i in range(3):
        try:
            return await asyncio.to_thread(fn, *a)
        except Exception as e:
            if i == 2:
                raise DemoStorageError(f"{type(e).__name__}") from e
            await asyncio.sleep(0.4 * (i + 1))


async def _copy_object(src_path: str, dst_path: str, mime: str) -> bytes:
    data = await _retry(storage.get_object, src_path)
    await _retry(storage.put_object, dst_path, data, mime)
    back = await _retry(storage.get_object, dst_path)
    if sha256_hex(back) != sha256_hex(data):
        raise HTTPException(500, "Demo media copy failed verification")
    return back


async def _clone_visit(src_vid: str, m: dict, ws: str, uid: str) -> str:
    """Copy a seeded visit and all its visit-scoped records with new ids (engagements are NOT copied)."""
    v = await db.visits.find_one({"uuid": src_vid})
    docs = {c: await db[c].find({"visit_id": src_vid}).to_list(500) for c in VISIT_CHILDREN}
    m[src_vid] = new_id()
    for c in docs.values():
        for d in c:
            m.setdefault(d["uuid"], new_id())
    await db.visits.insert_one(stamp_sys(remap(v, m)))
    for c, items in docs.items():
        for d in items:
            nd = remap(d, m)
            if c == "evidence" and d.get("storage_path"):
                nd["storage_path"] = f"railready/{ws}/{m[src_vid]}/{nd['uuid']}.{d['storage_path'].rsplit('.', 1)[-1]}"
                await _copy_object(d["storage_path"], nd["storage_path"], d.get("mime") or "application/octet-stream")
            if c == "jobs":
                nd.update({"lease_owner": None, "lease_until": None})
            await db[c].insert_one(stamp_sys(nd))
    return m[src_vid]


async def _saved_run():
    """A GENUINE earlier server run (current prompt, with candidates) on the seeded weathered-tie photo."""
    # source of the copied analysis: WS1 or the archived test-fixture workspace (moved there in Phase 8; read-only source, never shown)
    async for r in db.image_analysis_runs.find({"workspace_id": {"$in": [WS1, "ws-testfixtures"]}, "status": "Done", "saved_analysis": {"$exists": False}}).sort("created_at", -1):
        if not await db.visual_candidates.count_documents({"run_id": r["uuid"]}):
            continue
        e = await db.evidence.find_one({"uuid": r["evidence_id"]})
        if e and e.get("filename") == "tie_old_rotten.jpg" and e.get("storage_path") and e.get("server_sha256") == r["photo_sha256"]:
            return r, e
    raise HTTPException(503, "No saved analysis available to prepare the demo")


async def _ready_job(ws, uid, cust, site, track, sfx):
    run, src_ev = await _saved_run()
    vid, pid, rid = new_id(), new_id(), new_id()
    path = f"railready/{ws}/{vid}/{pid}.jpg"
    data = await _copy_object(src_ev["storage_path"], path, "image/jpeg")
    h = sha256_hex(data)
    ans = lambda val: {"state": "Provided", "value": val, "by": uid, "by_role": "estimator", "at": iso(), "source": "demo setup"}
    await db.visits.insert_one(stamp_sys({"uuid": vid, "workspace_id": ws, "site_id": site, "customer_id": cust, "track_id": track, "foreman_id": uid,
        "title": "Cascade Spur 1 survey - ready to estimate", "processing_permission": "Granted", "status": "Submitted", "submitted_at": iso(),
        "submitted_by": uid, "coverage_note": "Spur 1 gate to scale", "urgent_concern": None, "revision": 1,
        "answers": {"inspected_quantity": ans(12), "repair_quantity": ans(8), "tie_specification": ans("Crosstie 7x9x8'6\" hardwood grade 5"),
                    "material_responsibility": ans("Contractor"), "work_location": ans("Spur 1, gate to scale house")}}))
    await db.evidence.insert_one(stamp_sys({"uuid": pid, "workspace_id": ws, "visit_id": vid, "kind": "photo", "sha256": h, "size": len(data), "mime": "image/jpeg",
        "filename": "tie_old_rotten.jpg", "caption": "Weathered tie, Spur 1 (CC BY-SA 2.5, Per Erik Strandberg)", "upload_state": "Verified", "storage_path": path,
        "server_sha256": h, "server_size": len(data), "verified_at": iso(), "receipt_id": f"r-{vid}", "revision": 1}))
    members = [{"evidence_id": pid, "sha256": h, "size": len(data)}]
    await db.manifests.insert_one(stamp_sys({"uuid": f"m-{vid}", "workspace_id": ws, "visit_id": vid, "manifest_hash": sha256_hex(str(members).encode()),
                                             "members": members, "state": "Received complete", "receipt_id": f"r-{vid}", "missing": [], "revision": 1}))
    await db.receipts.insert_one(stamp_sys({"uuid": f"r-{vid}", "workspace_id": ws, "visit_id": vid, "manifest_id": f"m-{vid}", "member_count": 1,
                                            "issued_at": iso(), "issued_by": "server", "revision": 1}))
    saved = {"label": "Saved analysis", "original_run_id": run["uuid"], "model_id": run["model_id"], "prompt_version": run["prompt_version"],
             "run_at": run["created_at"], "copied_at": iso(), "note": "Genuine earlier server run on these exact photo bytes (sha256 match); no new model call"}
    m = {run["uuid"]: rid, run["evidence_id"]: pid, run["visit_id"]: vid, run["workspace_id"]: ws}
    await db.image_analysis_runs.insert_one({**remap(run, m), "job_id": None, "saved_analysis": saved})
    cands = await db.visual_candidates.find({"run_id": run["uuid"]}).sort("created_at", 1).to_list(20)
    for c in cands:
        m[c["uuid"]] = new_id()
    oid = new_id()
    for i, c in enumerate(cands):
        nc = {**remap(c, m), "saved_analysis": saved, "decisions": [], "review_state": "Pending", "linked_observation_id": None, "revision": 1}
        if i == 0:  # the confirmed tie observation, linked to the saved candidate
            dec = {"uuid": new_id(), "action": "confirm", "actor_id": uid, "actor_role": "estimator", "at": iso(), "candidate_revision": 1,
                   "note": "Confirmed during demo setup", "observation_id": oid}
            nc.update({"review_state": "Confirmed", "linked_observation_id": oid, "decisions": [dec], "revision": 2})
            await db.candidate_decisions.insert_one({**dec, "workspace_id": ws, "visit_id": vid, "candidate_id": nc["uuid"], "corrected_category": None})
        await db.visual_candidates.insert_one(nc)
    c0 = cands[0] if cands else None
    await db.observations.insert_one(stamp_sys({"uuid": oid, "workspace_id": ws, "visit_id": vid, "kind": "finding",
        "category": c0["category"] if c0 else "visible tie-surface deterioration", "region": c0["region"] if c0 else None,
        "text": "Confirmed: ties with visible deterioration on Spur 1 (human-reviewed)", "evidence_id": pid, "source_candidate_id": m.get(c0["uuid"]) if c0 else None,
        "human_reviewed": True, "quantity": None, "specification": None, "revision": 1}))
    eid, did, sid = new_id(), new_id(), new_id()
    wsd = await db.workspaces.find_one({"uuid": ws})
    exp = (now() + timedelta(days=30)).astimezone(__import__("zoneinfo").ZoneInfo(wsd["timezone"])).strftime("%Y-%m-%dT17:00")
    await db.engagements.insert_one(stamp_sys({"uuid": eid, "workspace_id": ws, "visit_id": vid, "site_id": site, "customer_id": cust, "draft_id": did,
        "status": "Open", "latest_version_id": None, "accepted_version_id": None, "changes_requested_version_ids": [], "proposal_number": f"RR-DEMO-{sfx}", "revision": 1}))
    await db.estimate_drafts.insert_one(stamp_sys({"uuid": did, "workspace_id": ws, "engagement_id": eid, "visit_id": vid, "lines": [], "tax_rate": wsd["tax_rate"],
        "terms": dict(wsd["default_terms"]), "terms_reviewed": True, "contractor_identity": wsd["legal_identity"], "selected_photo_ids": [pid],
        "expiry_local": exp, "agreement_preview": None, "feedback_history": [], "revision": 1}))
    await db.scope_items.insert_one(stamp_sys({"uuid": sid, "workspace_id": ws, "visit_id": vid, "engagement_id": eid, "kind": "tie_replacement",
        "location": "Spur 1, gate to scale house", "inspected_quantity": 12, "repair_quantity": 8, "unit": "each", "tie_type": "crosstie",
        "specification": "Crosstie 7x9x8'6\" hardwood grade 5", "material_responsibility": "Contractor", "observation_id": oid,
        "access_disposition": "Customer confirms track time; gate code at dispatch", "reason": None, "confirmed_by": uid, "revision": 1}))
    return {"visit_id": vid, "engagement_id": eid, "scope_item_id": sid, "evidence_id": pid, "saved_analysis_run_id": rid}


async def create_session(reset_from: Optional[str] = None) -> dict:
    sfx = secrets.token_hex(3).upper()
    sess_id, ws, uid = new_id(), f"ws-demo-{new_id()}", new_id()
    exp = now() + TTL
    src = await db.workspaces.find_one({"uuid": WS1})
    await db.workspaces.insert_one(stamp_sys({**{k: v for k, v in src.items() if k not in ("_id", "created_at", "created_by")}, "uuid": ws, "workspace_id": ws,
        "name": "Ridgeline Rail Services", "demo_suffix": sfx, "is_demo": True, "demo_session_id": sess_id, "revision": 1}))
    m = {WS1: ws, F1: uid, E1: uid}
    for coll in ("customers", "sites", "tracks", "crews", "catalog_items", "packages"):
        docs = await db[coll].find({"workspace_id": WS1}).to_list(200)
        for d in docs:
            m[d["uuid"]] = new_id()
        for d in docs:
            nd = stamp_sys(remap(d, m))
            if coll == "sites":
                nd["assigned_foreman_ids"] = [uid]
                nd["prior_findings"] = [{**f, "id": new_id()} for f in d.get("prior_findings", [])]
            await db[coll].insert_one(nd)
    # B1: copy every checklist template version so cloned visits keep their pinned template (no missing-pin 500s)
    for t in await db.checklist_templates.find({"workspace_id": WS1}).to_list(200):
        await db.checklist_templates.insert_one(stamp_sys({**{k: v for k, v in t.items() if k != "_id"}, "uuid": new_id(), "workspace_id": ws}))
    email = f"demo-{sfx.lower()}-{secrets.token_hex(2)}@demo.railready.example"
    user = {"uuid": uid, "workspace_id": ws, "email": email, "name": f"Demo User {sfx}", "role": "estimator", "roles": ["foreman", "estimator"],
            "is_demo": True, "demo_session_id": sess_id, "demo_expires_at": iso(exp), "password_hash": hash_password(secrets.token_urlsafe(24))}
    await db.users.insert_one(stamp_sys(user))
    ready = await _ready_job(ws, uid, m["c-cascade"], m["s-cascade"], m["t-c1"], sfx)
    blocked = await _clone_visit("v-seed-pinecrest", m, ws, uid)
    empty = new_id()
    await db.visits.insert_one(stamp_sys({"uuid": empty, "workspace_id": ws, "site_id": m["s-pinecrest"], "customer_id": m["c-pinecrest"], "track_id": m["t-p1"],
        "foreman_id": uid, "title": "New inspection - add your own photos", "processing_permission": "Granted", "status": "Draft",
        "answers": {}, "urgent_concern": None, "revision": 1}))
    jobs = {"ready_to_estimate": ready, "blocked_customer_supplied_8_vs_10": {"visit_id": blocked}, "empty_draft": {"visit_id": empty}}
    sess = {"uuid": sess_id, "workspace_id": ws, "user_id": uid, "created_at": iso(), "expires_at": iso(exp), "reset_from": reset_from, "jobs": jobs}
    await db.demo_sessions.insert_one(dict(sess))
    token = jwt.encode({"sub": uid, "type": "access", "demo": sess_id, "exp": exp}, JWT_SECRET, algorithm="HS256")
    wsd = await db.workspaces.find_one({"uuid": ws})
    return {"token": token, "session_id": sess_id, "expires_at": iso(exp), "reset_from": reset_from, "jobs": jobs,
            "user": {k: user[k] for k in ("uuid", "email", "name", "role", "roles", "workspace_id", "is_demo")},
            "workspace": {"uuid": ws, "name": wsd["name"], "timezone": wsd["timezone"], "is_demo": True}}


@router.post("/sessions", status_code=201)
async def start(request: Request):
    _limit(request)
    return await _guarded()


UNAVAILABLE = "Demo setup temporarily unavailable. Try again"


async def _guarded(reset_from=None):
    try:
        return await create_session(reset_from)
    except DemoStorageError:
        raise HTTPException(503, UNAVAILABLE)


@router.post("/sessions/{session_id}/reset", status_code=201)
async def reset(session_id: str, request: Request):
    _limit(request)
    if not await db.demo_sessions.find_one({"uuid": session_id}):
        raise HTTPException(404, "Not found")
    return await _guarded(reset_from=session_id)  # prior session's records are kept untouched
