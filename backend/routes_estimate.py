"""Phase 2 staff API: engagement/estimate drafts, tie package, lines, agreement preview, publish gate,
versions, share links, change requests, work orders. Estimator/admin only (foreman → 403)."""
import json
import math
import secrets
from datetime import datetime
from typing import Literal, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from pymongo.errors import DuplicateKeyError

from core import audit, clean, clean_all, db, get_visit, iso, new_id, now, require_role, revision_conflict, sha256_hex
import agreement
import money
import readiness

router = APIRouter(prefix="/api", tags=["estimate"])
staff = require_role("estimator", "admin")
SCOPE_FACTS = [("location", "Location missing"), ("repair_quantity", "Repair quantity missing"), ("unit", "Unit missing"),
               ("specification", "Specification missing"), ("material_responsibility", "Material responsibility missing"),
               ("access_disposition", "Access disposition missing")]
TIE_TYPES = {"crosstie": "cat-crosstie", "switch_tie": "cat-switchtie"}


async def get_eng(user, eid):
    e = await db.engagements.find_one({"uuid": eid, "workspace_id": user["workspace_id"]})
    if not e:
        raise HTTPException(404, "Not found")
    return e


async def get_draft(eng):
    return await db.estimate_drafts.find_one({"uuid": eng["draft_id"]})


async def ws_settings(wsid):
    return await db.workspaces.find_one({"uuid": wsid})


def field_err(e: money.MoneyError):
    raise HTTPException(422, {"code": "field_error", "field": e.field, "message": e.msg})


async def cas_draft(draft, user, expected_revision, update: dict, push: Optional[dict] = None):
    if expected_revision != draft["revision"]:
        revision_conflict(draft, "estimate draft")
    op = {"$set": {**update, "updated_at": iso(), "updated_by": user["uuid"]}, "$inc": {"revision": 1}}
    if push:
        op["$push"] = push
    res = await db.estimate_drafts.find_one_and_update({"uuid": draft["uuid"], "revision": draft["revision"]}, op, return_document=True)
    if not res:
        revision_conflict(await db.estimate_drafts.find_one({"uuid": draft["uuid"]}), "estimate draft")
    return res


def version_status(v, eng):
    if eng.get("accepted_version_id") == v["uuid"]:
        return "Accepted"
    if v.get("status") == "Void":
        return "Void"
    if v["uuid"] in eng.get("changes_requested_version_ids", []):
        return "Changes requested"
    if eng.get("latest_version_id") != v["uuid"]:
        return "Superseded"
    if v["expiry_utc"] <= iso():
        return "Expired"
    return "Published"


def contract_status(vs):
    return {"Published": "Issued", "Accepted": "Accepted"}.get(vs, vs)


def expiry_utc(local: str, tz: str) -> str:
    dt = datetime.fromisoformat(local).replace(tzinfo=ZoneInfo(tz))
    return dt.astimezone(ZoneInfo("UTC")).isoformat()


# ---------------- engagement + draft ----------------
@router.post("/visits/{visit_id}/engagement")
async def open_engagement(visit_id: str, user=Depends(staff)):
    v = await get_visit(user, visit_id)
    if v["status"] != "Submitted":
        raise HTTPException(409, {"code": "not_submitted", "message": "Only submitted visits can be estimated"})
    e = await db.engagements.find_one({"visit_id": visit_id})
    if e:
        return {"engagement_id": e["uuid"]}
    ws = await ws_settings(v["workspace_id"])
    missing = [k for k in ("tax_rate", "default_terms", "legal_identity") if not (ws or {}).get(k)]
    if missing:  # a workspace without estimate settings must not 500; say what is missing
        raise HTTPException(409, {"code": "workspace_not_configured", "missing": missing,
                                  "message": "Estimate settings are not set for this company (tax rate, default terms, legal identity). Ask your admin."})
    eid, did = new_id(), new_id()
    d = {"uuid": did, "workspace_id": v["workspace_id"], "engagement_id": eid, "visit_id": visit_id, "lines": [],
         "tax_rate": ws["tax_rate"], "terms": dict(ws["default_terms"]), "terms_reviewed": True,
         "contractor_identity": ws["legal_identity"], "selected_photo_ids": [], "expiry_local": None,
         "agreement_preview": None, "feedback_history": [], "revision": 1, "created_at": iso(), "created_by": user["uuid"],
         "updated_at": iso(), "updated_by": user["uuid"]}
    try:
        await db.engagements.insert_one({"uuid": eid, "workspace_id": v["workspace_id"], "visit_id": visit_id, "site_id": v["site_id"],
                                         "customer_id": v["customer_id"], "draft_id": did, "status": "Open", "latest_version_id": None,
                                         "accepted_version_id": None, "changes_requested_version_ids": [], "proposal_number": f"RR-{visit_id[:6].upper()}",
                                         "revision": 1, "created_at": iso(), "created_by": user["uuid"]})
        await db.estimate_drafts.insert_one(d)
    except DuplicateKeyError:
        e = await db.engagements.find_one({"visit_id": visit_id})
        return {"engagement_id": e["uuid"]}
    await audit(user, v["workspace_id"], "engagement_opened", "engagement", eid)
    return {"engagement_id": eid}


def view_line(l):
    return {**l, **money.line_amounts(l)}


async def warnings_for(draft):
    mob = [l for l in draft["lines"] if l["category"] == "mobilization" and l.get("included", True)]
    w = []
    if len(mob) > 1:
        w.append({"code": "duplicate_mobilization", "message": "Duplicate mobilization",
                  "resolved": all(l.get("duplicate_reason") for l in mob[1:])})
    return w


@router.get("/engagements/{eid}")
async def engagement_view(eid: str, user=Depends(staff)):
    eng = await get_eng(user, eid)
    d = await get_draft(eng)
    v = await db.visits.find_one({"uuid": eng["visit_id"]})
    ws = await ws_settings(eng["workspace_id"])
    versions = clean_all(await db.proposal_versions.find({"engagement_id": eid}, {"snapshot": 0, "internal_snapshot": 0}).sort("version_no", 1).to_list(50))
    for x in versions:
        x["status"] = version_status(x, eng)
        x["contract_status"] = contract_status(x["status"])
        x["links"] = clean_all(await db.share_links.find({"version_id": x["uuid"]}, {"token_hash": 0}).to_list(20))
        x["change_requests"] = [{"decision_id": c["uuid"], "name": c.get("name"), "comment": c.get("comment"), "at": c.get("at"),
                                 "topic_suggestion": c.get("topic_suggestion"), "topic_suggestion_note": "Suggestion only (staff-only); does not change scope, price or status"}
                                async for c in db.decisions.find({"version_id": x["uuid"], "type": "changes"})]
    photos = clean_all(await db.evidence.find({"visit_id": eng["visit_id"], "kind": "photo", "upload_state": "Verified"}, {"text": 0}).to_list(50))
    return {"engagement": clean(eng), "draft": {**clean(d), "lines": [view_line(l) for l in d["lines"]]},
            "totals": money.totals(d["lines"], d["tax_rate"]), "warnings": await warnings_for(d),
            "tax_treatment_text": ws["tax_treatment_text"], "visit": clean(v), "photos": photos,
            "scope_items": clean_all(await db.scope_items.find({"visit_id": eng["visit_id"]}).to_list(50)),
            "versions": versions, "work_order": clean(await db.work_orders.find_one({"engagement_id": eid})),
            "decisions": clean_all(await db.decisions.find({"engagement_id": eid}).sort("at", 1).to_list(50))}


# ---------------- scope items (confirmed tie observations) ----------------
class ScopeIn(BaseModel):
    kind: Literal["tie_replacement", "further_assessment"] = "tie_replacement"
    location: Optional[str] = None
    inspected_quantity: Optional[int] = None
    repair_quantity: Optional[int] = None
    unit: Optional[str] = "each"
    tie_type: Literal["crosstie", "switch_tie"] = "crosstie"
    specification: Optional[str] = None
    material_responsibility: Optional[Literal["Contractor", "Customer", "Unresolved"]] = None
    access_disposition: Optional[str] = None
    reason: Optional[str] = None


class ScopePatch(ScopeIn):
    expected_revision: int
    kind: Optional[Literal["tie_replacement", "further_assessment"]] = None
    tie_type: Optional[Literal["crosstie", "switch_tie"]] = None


@router.post("/engagements/{eid}/scope-items")
async def add_scope(eid: str, body: ScopeIn, user=Depends(staff)):
    eng = await get_eng(user, eid)
    if body.repair_quantity is not None and body.repair_quantity <= 0:
        raise HTTPException(422, {"code": "field_error", "field": "repair_quantity", "message": "must be greater than 0"})
    doc = {"uuid": new_id(), "workspace_id": eng["workspace_id"], "visit_id": eng["visit_id"], "engagement_id": eid,
           **body.model_dump(), "confirmed_by": user["uuid"], "revision": 1, "created_at": iso(), "created_by": user["uuid"],
           "updated_at": iso(), "updated_by": user["uuid"]}
    await db.scope_items.insert_one(doc)
    await audit(user, eng["workspace_id"], "scope_confirmed", "scope_item", doc["uuid"])
    return clean(doc)


@router.patch("/scope-items/{sid}")
async def patch_scope(sid: str, body: ScopePatch, user=Depends(staff)):
    s = await db.scope_items.find_one({"uuid": sid, "workspace_id": user["workspace_id"]})
    if not s:
        raise HTTPException(404, "Not found")
    if body.expected_revision != s["revision"]:
        revision_conflict(s, "scope item")
    upd = {k: v for k, v in body.model_dump(exclude={"expected_revision"}, exclude_unset=True).items()}
    changed = [k for k, v in upd.items() if s.get(k) != v]
    res = await db.scope_items.find_one_and_update({"uuid": sid, "revision": s["revision"]},
                                                   {"$set": {**upd, "updated_at": iso(), "updated_by": user["uuid"]}, "$inc": {"revision": 1}}, return_document=True)
    if not res:
        revision_conflict(await db.scope_items.find_one({"uuid": sid}), "scope item")
    if changed:  # dependent lines → Needs review, estimator edits kept (REQ-59)
        eng = await db.engagements.find_one({"uuid": s["engagement_id"]})
        d = await get_draft(eng)
        lines = [{**l, "reviewed": False, "needs_review_reason": f"Source fact changed: {', '.join(changed)}"} if l.get("observation_id") == sid else l for l in d["lines"]]
        await db.estimate_drafts.update_one({"uuid": d["uuid"]}, {"$set": {"lines": lines, "updated_at": iso()}, "$inc": {"revision": 1}})
    await audit(user, s["workspace_id"], "scope_corrected", "scope_item", sid, {"changed": changed})
    return clean(res)


async def package_lines(s, user, ws) -> tuple[list, list]:
    blockers = [msg for f, msg in SCOPE_FACTS if s.get(f) in (None, "")] if s["kind"] == "tie_replacement" else ["Further assessment items are not priced"]
    if s.get("material_responsibility") == "Unresolved":
        blockers.append("Material responsibility unresolved")
    if blockers:
        return [], blockers
    pkg = await db.packages.find_one({"workspace_id": s["workspace_id"]}, sort=[("version", -1)])
    q = s["repair_quantity"]
    flags = ws["taxable_flags"]
    mk = lambda key, cat, desc, qty, unit, origin, allowance: {
        "uuid": new_id(), "source_key": f"{s['uuid']}:{s['revision']}:{key}", "category": cat, "description": desc,
        "quantity": str(qty), "unit": unit, "unit_cost": pkg["rates"][key]["unit_cost"], "markup_pct": pkg["rates"][key]["markup_pct"],
        "taxable": flags.get(cat, False), "rate_version": pkg["rates_version"], "package_version": pkg["version"],
        "observation_id": s["uuid"], "observation_revision": s["revision"], "quantity_origin": origin,
        "assumption": pkg["rates"][key].get("assumption"), "included": True, "reviewed": False,
        "needs_review_reason": "Configured allowance. Needs review" if allowance else "New package line", "created_by": user["uuid"], "created_at": iso()}
    out = []
    tt = s["tie_type"]
    if s["material_responsibility"] == "Contractor":
        key = "crosstie" if tt == "crosstie" else "switch_tie"
        out.append(mk(key, "material", f"{'Crosstie' if tt == 'crosstie' else 'Switch tie'}: {s['specification']}", q, s["unit"], "confirmed repair count", False))
    hpt = money.Decimal(pkg["rates"]["labor"]["allowance_per_tie"])
    out.append(mk("labor", "labor", "Tie replacement labor", money.s(hpt * q), "hour", f"configured allowance {pkg['rates']['labor']['allowance_per_tie']} h per tie × confirmed repair count", True))
    out.append(mk("handling", "handling", "Material handling" + (" (customer-supplied ties)" if s["material_responsibility"] == "Customer" else ""), q, "tie", "confirmed repair count", False))
    days = math.ceil(q / int(pkg["rates"]["equipment"]["ties_per_day"]))
    out.append(mk("equipment", "equipment", "Tie inserter + hi-rail equipment", days, "equipment-day", f"configured allowance 1 day per {pkg['rates']['equipment']['ties_per_day']} ties", True))
    out.append(mk("mobilization", "mobilization", "Mobilization / trip", 1, "trip", "configured allowance 1 trip", True))
    return out, []


@router.get("/scope-items/{sid}/package-preview")
async def preview_package(sid: str, user=Depends(staff)):
    s = await db.scope_items.find_one({"uuid": sid, "workspace_id": user["workspace_id"]})
    if not s:
        raise HTTPException(404, "Not found")
    lines, blockers = await package_lines(s, user, await ws_settings(s["workspace_id"]))
    return {"blockers": blockers, "lines": [view_line(l) for l in lines], "ties_supplied_by_customer": s.get("material_responsibility") == "Customer"}


@router.post("/scope-items/{sid}/package")
async def add_package(sid: str, user=Depends(staff)):
    s = await db.scope_items.find_one({"uuid": sid, "workspace_id": user["workspace_id"]})
    if not s:
        raise HTTPException(404, "Not found")
    eng = await db.engagements.find_one({"uuid": s["engagement_id"]})
    for _ in range(3):
        d = await get_draft(eng)
        prefix = f"{sid}:{s['revision']}:"
        existing = [l for l in d["lines"] if l.get("source_key", "").startswith(prefix)]
        if existing:
            return {"added": False, "lines": [view_line(l) for l in existing]}
        if any(l.get("observation_id") == sid for l in d["lines"]):
            raise HTTPException(409, {"code": "package_exists", "message": "Package already added for an earlier revision; its lines are marked Needs review."})
        lines, blockers = await package_lines(s, user, await ws_settings(s["workspace_id"]))
        if blockers:
            raise HTTPException(422, {"code": "blocked", "blockers": blockers})
        res = await db.estimate_drafts.find_one_and_update({"uuid": d["uuid"], "revision": d["revision"]},
                                                           {"$push": {"lines": {"$each": lines}}, "$inc": {"revision": 1}, "$set": {"updated_at": iso()}}, return_document=True)
        if res:
            await audit(user, s["workspace_id"], "package_added", "scope_item", sid)
            return {"added": True, "lines": [view_line(l) for l in lines]}
    raise HTTPException(409, {"code": "busy", "message": "Draft changed, retry"})


# ---------------- lines ----------------
class LineIn(BaseModel):
    expected_revision: int
    category: Literal["material", "labor", "handling", "equipment", "mobilization", "general_repair", "other"]
    description: str
    quantity: object
    unit: str
    unit_cost: object
    markup_pct: object
    taxable: bool
    reason: str
    material_dependent: bool = False
    specification: Optional[str] = None
    material_responsibility: Optional[Literal["Contractor", "Customer"]] = None
    duplicate_reason: Optional[str] = None
    total: Optional[object] = None  # ignored: server recomputes (REQ-65)


def whole_each(category, unit, q):
    """REQ-158: each-priced tie (material) lines take whole positive numbers only."""
    if category == "material" and (unit or "").strip().lower() in ("each", "ea") and money.Decimal(q) != money.Decimal(q).to_integral_value():
        raise HTTPException(422, {"code": "field_error", "field": "quantity", "message": "Whole number required"})


def check_money(q, c, m):
    try:
        return money.s(money.dec(q, "quantity", positive=True)), money.s(money.dec(c, "unit_cost", nonneg=True)), money.s(money.dec(m, "markup_pct", nonneg=True))
    except money.MoneyError as e:
        field_err(e)


@router.post("/engagements/{eid}/lines")
async def add_line(eid: str, body: LineIn, user=Depends(staff)):
    eng = await get_eng(user, eid)
    if eng.get("accepted_version_id"):
        raise HTTPException(409, {"code": "accepted", "message": "Engagement already accepted"})
    d = await get_draft(eng)
    q, c, m = check_money(body.quantity, body.unit_cost, body.markup_pct)
    whole_each(body.category, body.unit, q)
    for f in ("description", "unit", "reason"):
        if not getattr(body, f).strip():
            raise HTTPException(422, {"code": "field_error", "field": f, "message": "required"})
    if body.category == "mobilization" and any(l["category"] == "mobilization" and l.get("included", True) for l in d["lines"]) and not (body.duplicate_reason or "").strip():
        raise HTTPException(422, {"code": "duplicate_mobilization", "field": "duplicate_reason", "message": "Duplicate mobilization. Give a reason to keep it"})
    line = {"uuid": new_id(), "source_key": f"manual:{new_id()}", "category": body.category, "description": body.description.strip(),
            "quantity": q, "unit": body.unit.strip(), "unit_cost": c, "markup_pct": m, "taxable": body.taxable,
            "rate_version": None, "package_version": None, "observation_id": None, "observation_revision": None,
            "quantity_origin": "manual entry", "assumption": body.reason.strip(), "reason": body.reason.strip(), "included": True,
            "material_dependent": body.material_dependent, "specification": body.specification, "material_responsibility": body.material_responsibility,
            "duplicate_reason": body.duplicate_reason, "reviewed": money.Decimal(c) > 0 and money.Decimal(m) >= 0 and False,
            "needs_review_reason": "New line", "created_by": user["uuid"], "created_at": iso()}
    line["reviewed"] = False
    res = await cas_draft(d, user, body.expected_revision, {}, push={"lines": line})
    return {"line": view_line(line), "draft_revision": res["revision"], "totals": money.totals(res["lines"], res["tax_rate"])}


class LinePatch(BaseModel):
    expected_revision: int
    quantity: Optional[object] = None
    unit_cost: Optional[object] = None
    markup_pct: Optional[object] = None
    taxable: Optional[bool] = None
    included: Optional[bool] = None
    reviewed: Optional[bool] = None
    description: Optional[str] = None
    duplicate_reason: Optional[str] = None
    specification: Optional[str] = None
    material_responsibility: Optional[Literal["Contractor", "Customer"]] = None


@router.patch("/engagements/{eid}/lines/{lid}")
async def patch_line(eid: str, lid: str, body: LinePatch, user=Depends(staff)):
    eng = await get_eng(user, eid)
    d = await get_draft(eng)
    idx = next((i for i, l in enumerate(d["lines"]) if l["uuid"] == lid), None)
    if idx is None:
        raise HTTPException(404, "Not found")
    l = dict(d["lines"][idx])
    vals = body.model_dump(exclude_unset=True, exclude={"expected_revision"})
    if any(k in vals for k in ("quantity", "unit_cost", "markup_pct")):
        l["quantity"], l["unit_cost"], l["markup_pct"] = check_money(vals.get("quantity", l["quantity"]), vals.get("unit_cost", l["unit_cost"]), vals.get("markup_pct", l["markup_pct"]))
        whole_each(l["category"], l["unit"], l["quantity"])
        l["quantity_origin"] = l["quantity_origin"] if "quantity" not in vals else f"estimator edit (was {l['quantity_origin']})"
        l["reviewed"], l["needs_review_reason"] = False, "Edited. Review"
    for k in ("taxable", "included", "description", "duplicate_reason", "specification", "material_responsibility"):
        if k in vals:
            l[k] = vals[k]
    if vals.get("reviewed"):
        l.update({"reviewed": True, "needs_review_reason": None, "reviewed_by": user["uuid"], "reviewed_at": iso()})
    res = await cas_draft(d, user, body.expected_revision, {f"lines.{idx}": l})
    await audit(user, eng["workspace_id"], "line_reviewed" if vals.get("reviewed") else "line_edited", "engagement", eid, {"line": lid})
    return {"line": view_line(l), "draft_revision": res["revision"], "totals": money.totals(res["lines"], res["tax_rate"])}


class DraftPatch(BaseModel):
    expected_revision: int
    terms: Optional[dict] = None
    terms_reviewed: Optional[bool] = None
    selected_photo_ids: Optional[list[str]] = None
    expiry_local: Optional[str] = None
    contractor_identity: Optional[str] = None
    tax_rate: Optional[object] = None


@router.patch("/engagements/{eid}/draft")
async def patch_draft(eid: str, body: DraftPatch, user=Depends(staff)):
    eng = await get_eng(user, eid)
    d = await get_draft(eng)
    upd = {}
    if body.terms is not None:
        allowed = {"payment_terms", "schedule_wording", "assumptions", "exclusions", "validity", "acceptance_wording"}
        new_terms = {**d["terms"], **{k: str(v) for k, v in body.terms.items() if k in allowed}}
        if new_terms != d["terms"]:
            upd.update({"terms": new_terms, "terms_reviewed": False})
    if body.terms_reviewed:
        upd["terms_reviewed"] = True
    if body.selected_photo_ids is not None:
        ok = {e["uuid"] async for e in db.evidence.find({"visit_id": eng["visit_id"], "kind": "photo", "upload_state": "Verified"})}
        if not set(body.selected_photo_ids) <= ok:
            raise HTTPException(404, "Not found")
        upd["selected_photo_ids"] = body.selected_photo_ids
    if body.expiry_local is not None:
        try:
            datetime.fromisoformat(body.expiry_local)
        except ValueError:
            raise HTTPException(422, {"code": "field_error", "field": "expiry_local", "message": "use YYYY-MM-DDTHH:MM site-local"})
        upd["expiry_local"] = body.expiry_local
    if body.contractor_identity is not None:
        upd["contractor_identity"] = body.contractor_identity.strip()
    if body.tax_rate is not None:
        try:
            upd["tax_rate"] = money.s(money.dec(body.tax_rate, "tax_rate", nonneg=True))
        except money.MoneyError as e:
            field_err(e)
    res = await cas_draft(d, user, body.expected_revision, upd)
    return {**clean(res), "lines": [view_line(l) for l in res["lines"]], "totals": money.totals(res["lines"], res["tax_rate"])}


# ---------------- agreement, snapshot, validate, publish ----------------
async def build_snapshot(eng, d):
    v = await db.visits.find_one({"uuid": eng["visit_id"]})
    site = await db.sites.find_one({"uuid": eng["site_id"]})
    cust = await db.customers.find_one({"uuid": eng["customer_id"]}) if eng.get("customer_id") else None
    cust = cust or {"name": "Not set"}  # sites created from the map have no customer yet; blockers_for lists it
    ws = await ws_settings(eng["workspace_id"])
    scopes = await db.scope_items.find({"visit_id": v["uuid"]}).to_list(50)
    inc = [l for l in d["lines"] if l.get("included", True)]
    t = money.totals(inc, d["tax_rate"])
    tz = ws["timezone"]
    exp = {"local": d.get("expiry_local"), "timezone": tz, "utc": expiry_utc(d["expiry_local"], tz) if d.get("expiry_local") else None}
    findings = [f"{s['location']}: replace {s['repair_quantity']} {s['unit']} {s['tie_type'].replace('_', ' ')}(s), {s['specification']} (inspected {s.get('inspected_quantity') or 'n/a'}). Access: {s['access_disposition']}"
                for s in scopes if s["kind"] == "tie_replacement"]
    findings += [f"Further assessment: {s.get('location') or ''}. {s.get('reason') or ''} (no quantities or charges)" for s in scopes if s["kind"] == "further_assessment"]
    ni = [{"area": o["area"], "reason": o["reason"]} async for o in db.observations.find({"visit_id": v["uuid"], "kind": "not_inspected"})]
    photos = [{"evidence_id": e["uuid"], "sha256": e["sha256"], "caption": e.get("caption")} async for e in db.evidence.find({"uuid": {"$in": d["selected_photo_ids"]}, "upload_state": "Verified"})]
    cust_supplied = any(s.get("material_responsibility") == "Customer" for s in scopes if s["kind"] == "tie_replacement")
    qty_text = "; ".join(f"{s['repair_quantity']} {s['unit']} {s['tie_type'].replace('_', ' ')}" for s in scopes if s["kind"] == "tie_replacement" and s.get("repair_quantity")) or None
    pub_lines = [{"description": l["description"], "quantity": l["quantity"], "unit": l["unit"], "taxable": l["taxable"],
                  "unit_price": money.s(money.r2(money.Decimal(l["unit_cost"]) * (1 + money.Decimal(l["markup_pct"]) / 100))),
                  "line_total": money.line_amounts(l)["line_total"]} for l in inc]
    terms = d["terms"]
    variables = {"contractor_legal_identity": d.get("contractor_identity"), "customer_site": f"{cust['name']}. {site['name']}, {site.get('address', '')}",
                 "proposal_version": f"{eng['proposal_number']} (next version)", "scope": " ".join(findings) or None, "quantities": qty_text,
                 "total_currency_tax": f"USD {t['total']} total (subtotal {t['subtotal']}, tax {t['tax']} at {t['tax_rate']}%). {ws['tax_treatment_text']}",
                 "schedule_wording": terms.get("schedule_wording"), "assumptions_exclusions": f"{terms.get('assumptions', '')} Exclusions: {terms.get('exclusions', '')}".strip() if terms.get("assumptions") else None,
                 "payment_terms": terms.get("payment_terms"), "validity": f"{terms.get('validity', '')} Valid until {exp['local']} {tz}." if exp["local"] else None,
                 "acceptance_wording": terms.get("acceptance_wording")}
    customer_t = {k: t[k] for k in ("subtotal", "taxable_subtotal", "tax_rate", "tax", "total", "currency")}
    snap = {"proposal_number": eng["proposal_number"], "visit_id": v["uuid"], "customer_site": variables["customer_site"],
            "contractor": {"legal_identity": d.get("contractor_identity")}, "findings": findings, "not_inspected": ni,
            "ties_supplied_by_customer": cust_supplied, "lines": pub_lines, "totals": customer_t, "tax_treatment_text": ws["tax_treatment_text"],
            "terms": terms, "expiry": exp, "photos": photos, "coverage_note": v.get("coverage_note")}
    internal = {"lines": [view_line(l) for l in d["lines"]], "totals": t}
    return snap, internal, variables, scopes, v


async def blockers_for(eng, d):
    snap, internal, variables, scopes, v = await build_snapshot(eng, d)
    b = []
    if not eng.get("customer_id"):
        b.append("Choose the customer for this site")
    if eng.get("accepted_version_id"):
        b.append("Engagement already accepted")
    inc = [l for l in d["lines"] if l.get("included", True)]
    if not any(money.Decimal(money.line_amounts(l)["line_total"]) > 0 for l in inc):
        b.append("No included paid line")
    ties = [s for s in scopes if s["kind"] == "tie_replacement"]
    if not ties:
        b.append("No confirmed tie scope")
    for s in ties:
        for f, msg in SCOPE_FACTS:
            if s.get(f) in (None, ""):
                b.append(f"{msg} ({s.get('location') or 'tie scope'})")
        if s.get("material_responsibility") == "Unresolved":
            b.append("Material responsibility unresolved")
    r = await readiness.compute(v)
    for f in r["fields"]:
        if f["discrepancy"] and f["state"] == "Needs review":
            b.append(f"Unresolved discrepancy: {f['label'].lower().replace('ties to replace (count)', 'repair quantity')}")
    for l in inc:
        if not l.get("reviewed"):
            b.append(f"Unreviewed line: {l['description']}" + (" (zero price)" if money.Decimal(money.line_amounts(l)["line_total"]) == 0 else ""))
        if l["category"] == "general_repair" and l.get("material_dependent") and not (l.get("specification") and l.get("material_responsibility")):
            b.append(f"General repair needs specification and material responsibility: {l['description']}")
    for w in await warnings_for(d):
        if not w["resolved"]:
            b.append("Duplicate mobilization. Reason required")
    if not d["selected_photo_ids"]:
        b.append("No selected photo")
    elif len(snap["photos"]) != len(d["selected_photo_ids"]):
        b.append("Selected media missing")
    if not d.get("expiry_local"):
        b.append("Expiry missing")
    elif snap["expiry"]["utc"] <= iso():
        b.append("Expiry in the past")
    rendered = agreement.render(variables)
    for k in rendered["missing"]:
        b.append(f"Missing agreement variable: {k}")
    if not d.get("terms_reviewed"):
        b.append("Unreviewed term edit")
    p = d.get("agreement_preview")
    if not p:
        b.append("Agreement not previewed")
    elif p["revision"] != d["revision"]:
        b.append("Stale price. Reopen Agreement preview")
    return b, snap, internal, variables


@router.get("/engagements/{eid}/agreement-preview")
async def agreement_preview(eid: str, user=Depends(staff)):
    eng = await get_eng(user, eid)
    d = await get_draft(eng)
    snap, internal, variables, _, _ = await build_snapshot(eng, d)
    r = agreement.render(variables)
    await db.estimate_drafts.update_one({"uuid": d["uuid"], "revision": d["revision"]}, {"$set": {"agreement_preview": {"revision": d["revision"], "hash": r["document_hash"], "at": iso()}}})
    return {**r, "draft_revision": d["revision"], "totals": internal["totals"], "status": "Draft"}


@router.post("/engagements/{eid}/validate")
async def validate(eid: str, user=Depends(staff)):
    eng = await get_eng(user, eid)
    d = await get_draft(eng)
    b, *_ = await blockers_for(eng, d)
    return {"blockers": b, "ok": not b, "draft_revision": d["revision"]}


class PublishIn(BaseModel):
    expected_revision: int
    idempotency_key: str


@router.post("/engagements/{eid}/publish")
async def publish(eid: str, body: PublishIn, user=Depends(staff)):
    eng = await get_eng(user, eid)
    d = await get_draft(eng)
    prior = await db.proposal_versions.find_one({"draft_id": d["uuid"], "draft_revision": body.expected_revision, "status": {"$ne": "Void"}})
    if prior:
        return {**clean(prior), "status": version_status(prior, eng), "idempotent_replay": True}
    if eng.get("accepted_version_id"):
        raise HTTPException(409, {"code": "accepted", "message": "Engagement already accepted"})
    if body.expected_revision != d["revision"]:
        revision_conflict(d, "estimate draft")
    b, snap, internal, variables = await blockers_for(eng, d)
    if b:
        raise HTTPException(422, {"code": "publish_blocked", "blockers": b})
    last = await db.proposal_versions.find_one({"engagement_id": eid}, sort=[("version_no", -1)])
    vno = (last["version_no"] + 1) if last else 1
    variables["proposal_version"] = f"{eng['proposal_number']} version {vno}"
    ag = agreement.render(variables)
    snap["agreement"] = {k: ag[k] for k in ("template_version", "template_hash", "label", "variables", "document_text", "document_hash")}
    snap["agreement"]["status"] = "Issued"
    vid = new_id()
    snapshot_hash = sha256_hex(json.dumps({"snapshot": snap, "internal": internal}, sort_keys=True, default=str).encode())
    doc = {"uuid": vid, "workspace_id": eng["workspace_id"], "engagement_id": eid, "visit_id": eng["visit_id"], "version_no": vno,
           "draft_id": d["uuid"], "draft_revision": d["revision"], "idempotency_key": body.idempotency_key, "status": "Published",
           "snapshot": snap, "internal_snapshot": internal, "snapshot_hash": snapshot_hash, "document_hash": ag["document_hash"],
           "expiry_utc": snap["expiry"]["utc"], "published_by": user["uuid"], "published_at": iso(), "created_at": iso(), "created_by": user["uuid"], "revision": 1}
    try:
        await db.proposal_versions.insert_one(doc)
    except DuplicateKeyError:
        prior = await db.proposal_versions.find_one({"draft_id": d["uuid"], "draft_revision": d["revision"]}) or \
            await db.proposal_versions.find_one({"engagement_id": eid, "version_no": vno})
        return {**clean(prior), "status": version_status(prior, eng), "idempotent_replay": True}
    won = await db.engagements.find_one_and_update({"uuid": eid, "accepted_version_id": None},
                                                   {"$set": {"latest_version_id": vid, "updated_at": iso()}, "$inc": {"revision": 1}}, return_document=True)
    if not won:
        await db.proposal_versions.update_one({"uuid": vid}, {"$set": {"status": "Void"}})
        raise HTTPException(409, {"code": "accepted", "message": "Engagement already accepted"})
    await db.proposal_versions.update_many({"engagement_id": eid, "uuid": {"$ne": vid}, "status": "Published"}, {"$set": {"status": "Superseded"}})
    await audit(user, eng["workspace_id"], "version_published", "proposal_version", vid, {"version_no": vno, "snapshot_hash": snapshot_hash})
    return {**clean(doc), "status": "Published"}


async def get_version(user, vid):
    v = await db.proposal_versions.find_one({"uuid": vid, "workspace_id": user["workspace_id"]})
    if not v:
        raise HTTPException(404, "Not found")
    return v, await db.engagements.find_one({"uuid": v["engagement_id"]})


@router.get("/versions/{vid}")
async def get_version_api(vid: str, user=Depends(staff)):
    v, eng = await get_version(user, vid)
    st = version_status(v, eng)
    return {**clean(v), "status": st, "contract_status": contract_status(st),
            "decisions": clean_all(await db.decisions.find({"version_id": vid}).to_list(20))}


@router.get("/proposals/{vid}/print", response_class=HTMLResponse)
async def staff_print(vid: str, request: Request, user=Depends(staff)):
    v, _ = await get_version(user, vid)
    tok = request.query_params.get("auth", "")
    v = await __import__("routes_public").with_correction(v)
    return agreement.print_html(v.get("display_snapshot") or v["snapshot"], v, lambda eid: f"/api/proposals/{vid}/media/{eid}?auth={tok}")


@router.get("/proposals/{vid}/media/{eid}")
async def staff_media(vid: str, eid: str, user=Depends(staff)):
    from routes_public import stream_snapshot_media
    v, _ = await get_version(user, vid)
    return await stream_snapshot_media(v, eid)


# ---------------- share links ----------------
@router.post("/versions/{vid}/share")
async def share(vid: str, user=Depends(staff)):
    v, eng = await get_version(user, vid)
    if version_status(v, eng) not in ("Published", "Accepted"):
        raise HTTPException(409, {"code": "not_shareable", "message": f"Version is {version_status(v, eng)}"})
    token = secrets.token_urlsafe(32)  # 256 bits; only the hash is stored, token never logged
    lid = new_id()
    await db.share_links.insert_one({"uuid": lid, "workspace_id": v["workspace_id"], "version_id": vid, "engagement_id": eng["uuid"],
                                     "token_hash": sha256_hex(token.encode()), "revoked": False, "created_at": iso(), "created_by": user["uuid"]})
    await audit(user, v["workspace_id"], "link_shared", "proposal_version", vid, {"link_id": lid})
    return {"link_id": lid, "token": token, "path": f"/p/{token}"}


@router.post("/links/{lid}/revoke")
async def revoke(lid: str, user=Depends(staff)):
    l = await db.share_links.find_one_and_update({"uuid": lid, "workspace_id": user["workspace_id"]},
                                                 {"$set": {"revoked": True, "revoked_at": iso(), "revoked_by": user["uuid"]}}, return_document=True)
    if not l:
        raise HTTPException(404, "Not found")
    await audit(user, user["workspace_id"], "link_revoked", "share_link", lid)
    return {"link_id": lid, "revoked": True}


@router.post("/versions/{vid}/copy-to-draft")
async def copy_to_draft(vid: str, user=Depends(staff)):
    v, eng = await get_version(user, vid)
    if eng.get("accepted_version_id"):
        raise HTTPException(409, {"code": "accepted", "message": "Engagement already accepted"})
    d = await get_draft(eng)
    fb = [{"version_id": vid, "version_no": v["version_no"], "name": x["name"], "comment": x.get("comment"), "at": x["at"],
           "topic_suggestion": x.get("topic_suggestion")} async for x in db.decisions.find({"version_id": vid, "type": "changes"})]
    lines = [{**l, "reviewed": False, "needs_review_reason": f"Copied from version {v['version_no']}. Review"} for l in v["internal_snapshot"]["lines"]]
    for l in lines:
        for k in ("internal_cost", "line_total"):
            l.pop(k, None)
    res = await cas_draft(d, user, d["revision"], {"lines": lines, "terms": v["snapshot"]["terms"], "from_version_id": vid,
                                                   "selected_photo_ids": [p["evidence_id"] for p in v["snapshot"]["photos"]]},
                          push={"feedback_history": {"$each": fb or [{"version_id": vid, "version_no": v["version_no"], "comment": None, "at": iso()}]}})
    await audit(user, v["workspace_id"], "copied_to_draft", "proposal_version", vid)
    return {"draft_revision": res["revision"], "feedback_history": res["feedback_history"]}


# ---------------- Phase 16: customer for sites created from the map ----------------
class CustomerPick(BaseModel):
    customer_id: str


@router.get("/customers")
async def list_customers(user=Depends(staff)):
    return [{"uuid": c["uuid"], "name": c["name"]} async for c in db.customers.find({"workspace_id": user["workspace_id"]})]


@router.put("/engagements/{eid}/customer")
async def set_customer(eid: str, body: CustomerPick, user=Depends(staff)):
    """Sets the customer once on an engagement (and its site/inspection when they have none). Never changes an accepted one."""
    eng = await db.engagements.find_one({"uuid": eid, "workspace_id": user["workspace_id"]})
    c = await db.customers.find_one({"uuid": body.customer_id, "workspace_id": user["workspace_id"]})
    if not eng or not c:
        raise HTTPException(404, "Not found")
    if eng.get("accepted_version_id") or (eng.get("customer_id") and eng["customer_id"] != c["uuid"]):
        raise HTTPException(409, {"code": "customer_set", "message": "The customer is already set for this estimate."})
    await db.engagements.update_one({"uuid": eid}, {"$set": {"customer_id": c["uuid"]}})
    await db.sites.update_one({"uuid": eng["site_id"], "customer_id": None}, {"$set": {"customer_id": c["uuid"]}})
    await db.visits.update_one({"uuid": eng["visit_id"], "customer_id": None}, {"$set": {"customer_id": c["uuid"]}})
    await audit(user, user["workspace_id"], "engagement.customer_set", "engagement", eid, {"customer_id": c["uuid"]})
    return {"customer_id": c["uuid"], "customer_name": c["name"]}


# ---------------- work orders ----------------
@router.get("/work-orders")
async def list_wos(user=Depends(staff)):
    return clean_all(await db.work_orders.find({"workspace_id": user["workspace_id"]}).sort("created_at", -1).to_list(100))


@router.get("/work-orders/{wid}")
async def get_wo(wid: str, user=Depends(staff)):
    w = await db.work_orders.find_one({"uuid": wid, "workspace_id": user["workspace_id"]})
    if not w:
        raise HTTPException(404, "Not found")
    crews = clean_all(await db.crews.find({"workspace_id": user["workspace_id"]}).to_list(20))
    import routes_repair as RR  # late import (Phase 16 link): repair -> work order
    from core import visit_location
    eng = await db.engagements.find_one({"uuid": w["engagement_id"]}, {"visit_id": 1})
    rep = await db.repairs.find_one({"work_order_id": wid, "workspace_id": user["workspace_id"]})
    pv = await db.proposal_versions.find_one({"uuid": w.get("accepted_version_id")}, {"status": 1, "visit_id": 1})
    eligible = bool(pv and pv.get("status") == "Accepted")
    insp_id = (eng or {}).get("visit_id") or (pv or {}).get("visit_id")
    nxt = None
    if rep:
        op = await RR.operator_for(rep)
        inv = await db.repair_invoices.find_one({"repair_id": rep["uuid"]})
        sub = await db.invoice_submissions.find_one({"invoice_id": inv["uuid"]}) if inv else None
        docs = (rep.get("packet") or {}).get("documents") or []
        nxt = RR.next_action(rep, op, docs, inv, sub)
    return {**clean(w), "crews": crews, "inspection_visit_id": insp_id,
            "location": await visit_location(insp_id), "start_repair_eligible": eligible and not rep,
            "repair": {"uuid": rep["uuid"], "visit_id": rep["visit_id"], "status": "Finished" if rep.get("completion") else "Open"} if rep else None,
            "next_action": nxt or ("Office: tap Start repair." if eligible else "Waiting for the customer to accept the proposal.")}


class WOPatch(BaseModel):
    expected_revision: int
    crew_id: Optional[str] = None
    scheduled_date: Optional[str] = None
    access_status: Optional[Literal["Not arranged", "Requested", "Confirmed"]] = None
    access_note: Optional[str] = None


ACCESS_NEXT = {"Not arranged": "Requested", "Requested": "Confirmed"}


@router.patch("/work-orders/{wid}")
async def patch_wo(wid: str, body: WOPatch, user=Depends(staff)):
    w = await db.work_orders.find_one({"uuid": wid, "workspace_id": user["workspace_id"]})
    if not w:
        raise HTTPException(404, "Not found")
    if body.expected_revision != w["revision"]:
        revision_conflict(w, "work order")
    upd, push = {}, None
    if body.crew_id is not None:
        if not await db.crews.find_one({"uuid": body.crew_id, "workspace_id": user["workspace_id"]}):
            raise HTTPException(404, "Not found")
        upd["crew_id"] = body.crew_id
    if body.scheduled_date is not None:
        upd["scheduled_date"] = body.scheduled_date
    if body.access_status and body.access_status != w["access_status"]:
        if ACCESS_NEXT.get(w["access_status"]) != body.access_status:
            raise HTTPException(422, {"code": "invalid_transition", "message": f"Access can go {w['access_status']} → {ACCESS_NEXT.get(w['access_status'], 'nothing')}"})
        upd["access_status"] = body.access_status
        push = {"access_history": {"from": w["access_status"], "to": body.access_status, "by": user["uuid"], "by_name": user["name"], "at": iso(), "note": body.access_note}}
    op = {"$set": {**upd, "updated_at": iso(), "updated_by": user["uuid"]}, "$inc": {"revision": 1}}
    if push:
        op["$push"] = push
    res = await db.work_orders.find_one_and_update({"uuid": wid, "revision": w["revision"]}, op, return_document=True)
    if not res:
        revision_conflict(await db.work_orders.find_one({"uuid": wid}), "work order")
    await audit(user, w["workspace_id"], "work_order_updated", "work_order", wid, upd)
    return clean(res)
