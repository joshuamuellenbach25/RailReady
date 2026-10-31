"""Phase 5 APIs: processing policy (admin), checklist templates (estimator/admin), inspection discovery (foreman scope)."""
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core import audit, current_user, db, get_visit, iso, new_id, require_role, visit_scope
import jobs
import policy

router = APIRouter(prefix="/api", tags=["phase5"])
LABEL = None  # no metacommentary label on templates


def e409(msg):
    raise HTTPException(409, {"code": "stale_version", "message": msg, "retryable": True})


# ---------------- policy ----------------
class Restriction(BaseModel):
    scope: Literal["site", "customer", "visit"]
    id: str
    reason: Optional[str] = Field(default=None, max_length=300)


class EvidenceException(BaseModel):
    evidence_id: str
    allow: bool
    reason: Optional[str] = Field(default=None, max_length=300)


class PolicyIn(BaseModel):
    expected_version: int
    default: Literal["allow", "restrict"]
    restrictions: List[Restriction] = []
    evidence_exceptions: List[EvidenceException] = []
    note: Optional[str] = Field(default=None, max_length=500)


@router.get("/policy")
async def get_policy(user=Depends(require_role("admin", "estimator"))):
    return await policy.current(user["workspace_id"])


@router.get("/policy/versions")
async def policy_versions(user=Depends(require_role("admin", "estimator"))):
    await policy.current(user["workspace_id"])
    return {"versions": await policy.versions(user["workspace_id"])}


@router.put("/policy")
async def put_policy(body: PolicyIn, user=Depends(require_role("admin"))):
    ws = user["workspace_id"]
    cur = await policy.current(ws)
    for r in body.restrictions:
        coll = {"site": db.sites, "customer": db.customers, "visit": db.visits}[r.scope]
        if not await coll.find_one({"uuid": r.id, "workspace_id": ws}):
            raise HTTPException(422, {"code": "field_error", "field": "restrictions", "message": f"Unknown {r.scope}", "retryable": False})
    for e in body.evidence_exceptions:
        if not await db.evidence.find_one({"uuid": e.evidence_id, "workspace_id": ws}):
            raise HTTPException(422, {"code": "field_error", "field": "evidence_exceptions", "message": "Unknown evidence", "retryable": False})
    doc = {"uuid": new_id(), "workspace_id": ws, "version": cur["version"] + 1, "current": True, "default": body.default,
           "restrictions": [r.model_dump() for r in body.restrictions], "evidence_exceptions": [e.model_dump() for e in body.evidence_exceptions],
           "note": body.note, "created_by": user["uuid"], "created_at": iso(), "previous_version": cur["version"]}
    event = policy.transition(cur, doc, user)
    # Current policy, previous snapshot and audit intent commit in the same document.
    old = await db.processing_policies.find_one_and_update(
        {"uuid": cur["uuid"], "workspace_id": ws, "current": True, "version": body.expected_version},
        {"$set": doc, "$push": {policy.PENDING: event}})
    if not old:
        e409("Policy was changed by someone else. Reload")
    history_pending = False
    try:
        await policy.flush_pending(ws)
    except Exception:
        history_pending = True
        policy.log.exception("Policy applied; durable history/audit completion is pending for %s", ws)
    # unblock/block queued work according to the new policy (jobs still recheck at execution)
    async for v in db.visits.find({"workspace_id": ws, "status": {"$ne": "Draft-deleted"}}, {"_id": 0}):
        await jobs.on_permission_change(v)
    return {**doc, "history_pending": history_pending}


@router.get("/visits/{visit_id}/processing-policy")
async def visit_policy(visit_id: str, user=Depends(current_user)):
    v = await get_visit(user, visit_id)
    r = await policy.evaluate(v)
    await db.visits.update_one({"uuid": visit_id}, {"$set": {"processing_policy": {"version": r["policy_version"], "basis": r["basis"], "allowed": r["allowed"], "at": iso()}}})
    return r


# ---------------- templates ----------------
def F(key, label, type_, stage="capture", unit=None, applies="inspection", required=False, options=None, when=None, allow=("unknown", "defer"), role="foreman", help_=None):
    return {"key": key, "label": label, "type": type_, "unit": unit, "applies_to": applies, "stage": stage, "required": required, "options": options,
            "conditional_on": when, "allowed_non_answers": list(allow), "confirming_role": role, "help": help_}


SHARED = [F("material_responsibility", "Who supplies material?", "choice", options=["Contractor", "Customer"], required=True, role="estimator",
            help_="Asked once per inspection; findings inherit unless overridden"),
          F("access", "Access / track time arrangement", "text", stage="handoff", required=True)]
SEED = {
    "tpl-tie-replacement": ("Tie replacement", "tie_replacement", SHARED + [
        F("repair_quantity", "Ties to replace", "integer", unit="each", applies="finding", required=True, allow=("unknown", "defer")),
        F("inspected_quantity", "Ties inspected (optional; never used to derive repair count)", "integer", unit="each", allow=("unknown", "not_applicable")),
        F("tie_specification", "Tie type / specification", "text", applies="finding", required=True, stage="pricing", role="estimator"),
        F("work_location", "Work location", "text", required=True)]),
    "tpl-fastener-repair": ("Fastener repair", "fastener_repair", SHARED + [
        F("fastener_count", "Fasteners to repair/replace", "integer", unit="each", applies="finding", required=True),
        F("fastener_type", "Fastener type", "choice", options=["Cut spike", "Screw spike", "Elastic clip", "Other"], applies="finding"),
        F("work_location", "Work location", "text", required=True)]),
    "tpl-pavement-edge": ("Pavement/track-edge repair", "pavement_repair", SHARED + [
        F("area", "Repair area", "number", unit="sq ft", applies="finding", required=True, options=["sq ft", "sq m"]),
        F("depth", "Repair depth", "number", unit="in", applies="finding", allow=("unknown", "defer", "not_applicable")),
        F("pavement_material", "Pavement material", "choice", options=["Asphalt", "Concrete", "Other"], applies="finding", required=True),
        F("traffic_control", "Traffic control needed?", "choice", options=["Yes", "No"], stage="handoff", when={"field": "access", "present": True}),
        F("work_location", "Work location", "text", required=True)]),
    "tpl-general": ("General observation", "general", [
        F("observation", "What did you see?", "text", required=True, applies="finding"),
        F("work_location", "Location", "text"),
        F("access", "Access notes", "text", stage="handoff")]),
}


async def ensure_templates(ws):
    for tid, (name, wt, fields) in SEED.items():
        if not await db.checklist_templates.find_one({"workspace_id": ws, "template_id": tid}):
            try:
                await db.checklist_templates.insert_one({"uuid": new_id(), "workspace_id": ws, "template_id": tid, "version": 1, "current": True, "name": name,
                    "work_type": wt, "label": LABEL, "fields": fields, "default_for": {"work_types": [wt], "site_ids": []}, "created_by": "system", "created_at": iso()})
            except Exception:
                pass


async def repair_current(ws):
    """V-a: every template must have exactly one current version; if none is current, the highest version becomes current."""
    for tid in await db.checklist_templates.distinct("template_id", {"workspace_id": ws}):
        if not await db.checklist_templates.find_one({"workspace_id": ws, "template_id": tid, "current": True}, {"_id": 1}):
            top = await db.checklist_templates.find_one({"workspace_id": ws, "template_id": tid}, sort=[("version", -1)])
            await db.checklist_templates.update_one({"_id": top["_id"]}, {"$set": {"current": True}})


@router.get("/templates")
async def list_templates(user=Depends(current_user)):
    await ensure_templates(user["workspace_id"])
    return {"templates": await db.checklist_templates.find({"workspace_id": user["workspace_id"], "current": True}, {"_id": 0}).sort("name", 1).to_list(100), "label": LABEL}


@router.get("/templates/{template_id}")
async def get_template(template_id: str, version: Optional[int] = None, user=Depends(current_user)):
    await ensure_templates(user["workspace_id"])
    q = {"workspace_id": user["workspace_id"], "template_id": template_id, **({"version": version} if version else {"current": True})}
    t = await db.checklist_templates.find_one(q, {"_id": 0})
    if not t:
        raise HTTPException(404, {"code": "not_found", "message": "Not found", "retryable": False})
    t["versions"] = [x["version"] async for x in db.checklist_templates.find({"workspace_id": user["workspace_id"], "template_id": template_id}, {"version": 1})]
    return t


class FieldIn(BaseModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,40}$")
    label: str = Field(max_length=120)
    type: Literal["text", "number", "integer", "choice"]
    unit: Optional[str] = None
    applies_to: Literal["inspection", "finding"] = "inspection"
    stage: Literal["capture", "handoff", "pricing"] = "capture"
    required: bool = False
    options: Optional[List[str]] = None
    conditional_on: Optional[dict] = None
    allowed_non_answers: List[Literal["unknown", "defer", "not_applicable"]] = ["unknown", "defer"]
    confirming_role: Literal["foreman", "estimator"] = "foreman"
    help: Optional[str] = None


class TemplateVersionIn(BaseModel):
    expected_version: int
    name: Optional[str] = Field(default=None, max_length=80)
    fields: List[FieldIn] = Field(min_length=1, max_length=40)
    default_for: Optional[dict] = None


@router.post("/templates/{template_id}/versions", status_code=201)
async def new_template_version(template_id: str, body: TemplateVersionIn, user=Depends(require_role("estimator", "admin"))):
    ws = user["workspace_id"]
    await ensure_templates(ws)
    cur = await db.checklist_templates.find_one({"workspace_id": ws, "template_id": template_id, "current": True})
    if not cur:
        raise HTTPException(404, {"code": "not_found", "message": "Not found", "retryable": False})
    if len({f.key for f in body.fields}) != len(body.fields):
        raise HTTPException(422, {"code": "field_error", "field": "fields", "message": "Duplicate field key", "retryable": False})
    if not await db.checklist_templates.find_one_and_update({"uuid": cur["uuid"], "current": True, "version": body.expected_version}, {"$set": {"current": False}}):
        e409("Template was changed by someone else. Reload")
    doc = {"uuid": new_id(), "workspace_id": ws, "template_id": template_id, "version": cur["version"] + 1, "current": True, "name": body.name or cur["name"],
           "work_type": cur["work_type"], "label": LABEL, "fields": [f.model_dump() for f in body.fields], "default_for": body.default_for or cur["default_for"],
           "created_by": user["uuid"], "created_at": iso(), "previous_version": cur["version"]}
    await db.checklist_templates.insert_one(dict(doc))
    await audit(user, ws, "template_version", "template", template_id, {"version": doc["version"]})
    doc.pop("_id", None)
    return doc  # active inspections keep their pinned version


async def default_template(v) -> dict:
    await ensure_templates(v["workspace_id"])
    ts = await db.checklist_templates.find({"workspace_id": v["workspace_id"], "current": True}).to_list(50)
    site = await db.sites.find_one({"uuid": v["site_id"]}) or {}
    for t in ts:
        if v["site_id"] in (t.get("default_for") or {}).get("site_ids", []):
            return t
    wt = v.get("work_type") or site.get("work_type") or "tie_replacement"
    return next((t for t in ts if wt in (t.get("default_for") or {}).get("work_types", [])),
                next((t for t in ts if t["template_id"] == "tpl-general"), ts[0] if ts else None))


class PinIn(BaseModel):
    template_id: str
    version: Optional[int] = None
    expected_revision: int


REPAIR_MSG = "Checklist version missing. Ask an admin to restore it."


def _repair_state(v, pin, reason):
    """C5: controlled state instead of a 500 or a silent swap to another version. The pin is preserved unchanged."""
    return {"visit_id": v["uuid"], "state": "needs_repair", "reason": reason, "message": REPAIR_MSG, "template": None, "pin": pin,
            "fields": [], "groups": {"needs_review": [], "missing": [], "ready": []}, "missing": [], "revision": v.get("revision"),
            "template_pin_missing": True, "repair": {"method": "POST", "path": f"/api/visits/{v['uuid']}/checklist/repair", "role": "admin"}}


@router.get("/visits/{visit_id}/checklist")
async def visit_checklist(visit_id: str, user=Depends(current_user)):
    v = await get_visit(user, visit_id)
    if "template" not in v:  # fresh / legacy unpinned visit: first pin = workspace default (this is pinning, not swapping)
        t = await default_template(v)
        if not t:
            return _repair_state(v, None, "no_current_template")
        pin = {"template_id": t["template_id"], "version": t["version"], "basis": "default", "at": iso()}
        await db.visits.update_one({"uuid": visit_id, "template": {"$exists": False}}, {"$set": {"template": pin}})
        v = await db.visits.find_one({"uuid": visit_id})
    pin = v.get("template")
    if not isinstance(pin, dict) or not pin.get("template_id") or not isinstance(pin.get("version"), int):
        return _repair_state(v, pin, "pin_null_or_invalid")
    t = await db.checklist_templates.find_one({"workspace_id": v["workspace_id"], "template_id": pin["template_id"], "version": pin["version"]}, {"_id": 0})
    if not t:
        return _repair_state(v, pin, "pinned_version_missing")
    if not isinstance(t.get("fields"), list) or not all(isinstance(f, dict) and f.get("key") and f.get("label") for f in t["fields"]):
        return _repair_state(v, pin, "template_fields_invalid")
    pin_missing = False
    ans = {**(v.get("answers") or {}), **(v.get("checklist_answers") or {})}
    props = {}
    async for p in db.proposed_fields.find({"visit_id": visit_id, "active": True}, {"_id": 0}):
        props.setdefault(PROPOSAL_KEY.get(p["field"], p["field"]), []).append(
            {k: p.get(k) for k in ("uuid", "field", "value", "excerpt", "source_evidence_id", "source_kind", "model_id", "untrusted")})
    items = []
    for f in t["fields"]:
        a = ans.get(f["key"]) or {}
        st = a.get("state")
        ps = props.get(f["key"], [])
        status = "confirmed" if st in ("Provided", "Confirmed") else ("deferred" if st in ("Unknown", "Unknown with reason", "Defer", "Not applicable", "Deferred") else
                                                                       "needs_estimator" if st == "Needs estimator input" else "missing")
        distinct = sorted({str(p["value"]) for p in ps})
        if status in ("confirmed", "deferred"):
            group, blocker = "ready", None
        elif status == "needs_estimator":
            group, blocker = "needs_review", f"Asked estimator: {a.get('reason')}"
        elif ps:
            group = "needs_review"
            blocker = f"Sources disagree ({' vs '.join(distinct)})" if len(distinct) > 1 else (
                "From untrusted text. Check before using" if any(p.get("untrusted") for p in ps) else "Proposed. Confirm or correct")
        else:
            group = "missing" if f.get("required") else "ready"
            blocker = "Required. Not stated in any note, voice note or photo yet." if f.get("required") else None
        items.append({**f, "answer": a or None, "status": status, "group": group, "blocker": blocker, "proposals": ps,
                      "discrepancy": len(distinct) > 1, "distinct_values": distinct,
                      "finding_overrides": (v.get("finding_overrides") or {}).get(f["key"], {}),
                      "inherited_by_findings": f.get("applies_to") == "inspection" and f["key"] in ("material_responsibility", "access")})
    groups = {g: [i["key"] for i in items if i["group"] == g] for g in ("needs_review", "missing", "ready")}
    return {"visit_id": visit_id, "state": "ok", "template": {k: t.get(k) for k in ("template_id", "version", "name", "work_type", "label")}, "pin": pin, "fields": items,
            "template_pin_missing": pin_missing,
            "groups": groups, "revision": v["revision"], "missing": [i["key"] for i in items if i.get("required") and i["status"] == "missing"]}


class RepairIn(BaseModel):
    expected_revision: int
    mode: Literal["restore_pinned", "repin"] = "restore_pinned"
    template_id: Optional[str] = None  # repin only: an explicit admin choice, recorded with reason
    version: Optional[int] = None
    reason: Optional[str] = Field(None, max_length=300)


@router.post("/visits/{visit_id}/checklist/repair")
async def repair_checklist(visit_id: str, body: RepairIn, user=Depends(require_role("admin"))):
    """C5 admin repair. restore_pinned: copy the exact pinned template version back into this workspace from another
    workspace that still has it (content-identical). repin: admin explicitly pins a named existing version (needs a reason)."""
    v = await get_visit(user, visit_id)
    if body.expected_revision != v["revision"]:
        raise HTTPException(409, {"code": "stale_revision", "message": "Changed elsewhere. Reload and try again.", "retryable": True})
    pin = v.get("template") if isinstance(v.get("template"), dict) else None
    if body.mode == "restore_pinned":
        if not pin or not pin.get("template_id") or not isinstance(pin.get("version"), int):
            raise HTTPException(422, {"code": "no_pin", "message": "There is no pinned version to restore. Choose a version to pin."})
        if await db.checklist_templates.find_one({"workspace_id": v["workspace_id"], "template_id": pin["template_id"], "version": pin["version"]}):
            return {"repaired": False, "message": "The pinned version is already present."}
        src = await db.checklist_templates.find_one({"template_id": pin["template_id"], "version": pin["version"], "fields": {"$type": "array"}}, {"_id": 0})
        if not src:
            raise HTTPException(404, {"code": "version_unrecoverable", "message": "This version cannot be found anywhere. Choose a version to pin."})
        await db.checklist_templates.insert_one({**src, "uuid": new_id(), "workspace_id": v["workspace_id"], "current": False,
                                                 "restored_from": src["uuid"], "restored_by": user["uuid"], "restored_at": iso()})
        await audit(user, v["workspace_id"], "checklist_version_restored", "visit", visit_id, {"pin": pin, "source": src["uuid"]})
        return {"repaired": True, "mode": "restore_pinned", "pin": pin}
    if not (body.template_id and isinstance(body.version, int) and (body.reason or "").strip()):
        raise HTTPException(422, {"code": "field_errors", "message": "Choose a template, a version and give a reason."})
    if not await db.checklist_templates.find_one({"workspace_id": v["workspace_id"], "template_id": body.template_id, "version": body.version, "fields": {"$type": "array"}}):
        raise HTTPException(404, {"code": "not_found", "message": "That template version is not in this workspace."})
    new_pin = {"template_id": body.template_id, "version": body.version, "basis": "admin_repair", "reason": body.reason.strip(),
               "previous": pin, "by": user["uuid"], "at": iso()}
    await db.visits.update_one({"uuid": visit_id, "revision": v["revision"]}, {"$set": {"template": new_pin}, "$inc": {"revision": 1}})
    await audit(user, v["workspace_id"], "checklist_repinned", "visit", visit_id, {"from": pin, "to": new_pin})
    return {"repaired": True, "mode": "repin", "pin": new_pin}


PROPOSAL_KEY = {"repair_area": "area", "repair_depth": "depth"}  # extraction → pavement template keys
CORE_FIELDS = {"inspected_quantity", "repair_quantity", "tie_specification", "material_responsibility", "work_location"}


class ChecklistAnswerIn(BaseModel):
    expected_revision: int
    action: Literal["confirm", "correct", "unknown", "defer", "not_applicable", "ask_estimator"]
    value: Optional[str] = None
    proposal_id: Optional[str] = None
    unit: Optional[str] = None
    reason: Optional[str] = Field(None, max_length=300)
    finding_id: Optional[str] = None  # per-finding override of an inherited inspection fact


@router.post("/visits/{visit_id}/checklist/{key}")
async def answer_checklist(visit_id: str, key: str, body: ChecklistAnswerIn, user=Depends(current_user)):
    """Template items outside the core estimating fields (core fields keep POST /visits/{id}/fields/{field})."""
    v = await get_visit(user, visit_id)
    if v["status"] == "Submitted" and user["role"] == "foreman":
        e409("Inspection submitted. Ask the office to reopen")
    if key in CORE_FIELDS and not body.finding_id:
        raise HTTPException(422, {"code": "use_fields_endpoint", "message": f"Use POST /api/visits/{visit_id}/fields/{key}", "retryable": False})
    if body.action == "ask_estimator" and not (body.reason or "").strip():
        raise HTTPException(422, {"code": "reason_required", "message": "Add a short reason for the estimator", "retryable": False})
    if body.action in ("unknown", "defer", "not_applicable") and not (body.reason or "").strip():
        raise HTTPException(422, {"code": "reason_required", "message": "Add a short reason", "retryable": False})
    value = body.value
    if body.action == "confirm" and body.proposal_id:
        p = await db.proposed_fields.find_one({"uuid": body.proposal_id, "visit_id": visit_id, "active": True})
        if not p:
            raise HTTPException(404, {"code": "not_found", "message": "Proposal not found", "retryable": False})
        value = p["value"]
    if body.action in ("confirm", "correct") and (value is None or str(value).strip() == ""):
        raise HTTPException(422, {"code": "value_required", "message": "A value is required", "retryable": False})
    state = {"confirm": "Confirmed", "correct": "Confirmed", "unknown": "Unknown", "defer": "Deferred", "not_applicable": "Not applicable",
             "ask_estimator": "Needs estimator input"}[body.action]
    rec = {"state": state, "value": value, "unit": body.unit, "reason": body.reason, "proposal_id": body.proposal_id, "source": body.action,
           "by": user["uuid"], "by_role": user["role"], "at": iso()}
    path = f"finding_overrides.{key}.{body.finding_id}" if body.finding_id else f"checklist_answers.{key}"
    r = await db.visits.update_one({"uuid": visit_id, "revision": body.expected_revision},
                                   {"$set": {path: rec, "updated_at": iso(), "updated_by": user["uuid"]}, "$inc": {"revision": 1}})
    if not r.modified_count:
        e409("Inspection changed. Reload")
    await audit(user, v["workspace_id"], "checklist_answer", "visit", visit_id, {"key": key, "action": body.action, "finding_id": body.finding_id})
    return await visit_checklist(visit_id, user)


@router.put("/visits/{visit_id}/template")
async def pin_template(visit_id: str, body: PinIn, user=Depends(require_role("estimator", "admin"))):
    v = await get_visit(user, visit_id)
    q = {"workspace_id": v["workspace_id"], "template_id": body.template_id, **({"version": body.version} if body.version else {"current": True})}
    t = await db.checklist_templates.find_one(q)
    if not t:
        raise HTTPException(404, {"code": "not_found", "message": "Not found", "retryable": False})
    pin = {"template_id": t["template_id"], "version": t["version"], "basis": "changed_by_" + user["role"], "by": user["uuid"], "at": iso()}
    r = await db.visits.update_one({"uuid": visit_id, "revision": body.expected_revision}, {"$set": {"template": pin, "updated_at": iso(), "updated_by": user["uuid"]}, "$inc": {"revision": 1}})
    if not r.modified_count:
        e409("Inspection changed. Reload")
    await audit(user, v["workspace_id"], "template_pinned", "visit", visit_id, pin)
    return {"visit_id": visit_id, "pin": pin}


# ---------------- discovery ----------------
@router.get("/inspections")
async def discover(status: Optional[str] = "in_progress", user=Depends(current_user)):
    """Server-side authorized inspections for this user (foreman: own; staff: workspace), not only ones created on this device."""
    q = {"workspace_id": user["workspace_id"], **visit_scope(user)}
    if status == "in_progress":
        q["status"] = {"$in": ["Draft", "Reopened"]}
    out = []
    for v in await db.visits.find(q, {"_id": 0}).sort("updated_at", -1).to_list(200):
        site = await db.sites.find_one({"uuid": v["site_id"]}, {"name": 1}) or {}
        pol = await policy.evaluate(v)
        out.append({"visit_id": v["uuid"], "title": v.get("title"), "status": v["status"], "site_id": v["site_id"], "site_name": site.get("name"),
                    "updated_at": v.get("updated_at"), "revision": v["revision"], "template": v.get("template"),
                    "evidence_count": await db.evidence.count_documents({"visit_id": v["uuid"]}),
                    "processing": {k: pol[k] for k in ("allowed", "basis", "policy_version", "message")}})
    return {"inspections": out}
