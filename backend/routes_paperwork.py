"""Phase 17 routes: Generic Repair Work Order selection, completed form / invoice / packet PDFs (Preview + Download), and the
immutable issued paperwork snapshot used by submission and the Test delivery channel. Workspace-scoped like the rest of repairs."""
import base64
import hashlib

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from pymongo.errors import DuplicateKeyError

import paperwork as P
import routes_repair as RR
from core import audit, clean, current_user, db, iso, require_role

router = APIRouter(prefix="/api")


class GenericFormIn(BaseModel):
    enabled: bool


@router.get("/form-templates/generic-repair-work-order", tags=["paperwork"])
async def generic_template(user=Depends(current_user)):
    return P.template_info()


@router.put("/operators/{oid}/generic-forms/{form_id}", tags=["paperwork"])
async def set_generic_form(oid: str, form_id: str, body: GenericFormIn, user=Depends(require_role("admin"))):
    """Select the generic form for an operator in a test workspace only (REQ-1705). The operator's own forms stay required (REQ-1707)."""
    if form_id != P.FORM_ID:
        raise HTTPException(404, "Not found")
    op = await db.operators.find_one({"uuid": oid, "workspace_id": user["workspace_id"]})
    if not op:
        raise HTTPException(404, "Not found")
    if not await RR.is_test_ws(user["workspace_id"]):
        raise HTTPException(409, {"code": "test_only", "message": "The generic form is available for the test operator only."})
    P.template()
    if body.enabled:
        await db.operators.update_one({"uuid": oid}, {"$addToSet": {"generic_forms": P.FORM_ID}})
    else:
        await db.operators.update_one({"uuid": oid}, {"$pull": {"generic_forms": P.FORM_ID}})
    await audit(user, user["workspace_id"], "operator.generic_form", "operator", oid, {"form": P.FORM_ID, "enabled": body.enabled})
    op = await db.operators.find_one({"uuid": oid})
    return {"operator_id": oid, "generic_forms": op.get("generic_forms") or [], "required_forms": [f["name"] for f in op.get("forms") or []]}


async def _facts(user: dict, visit_id: str) -> dict:
    r = await RR.get_repair(user, visit_id)  # 404 outside the workspace
    op = await RR.operator_for(r)
    wo = await db.work_orders.find_one({"uuid": r.get("work_order_id"), "workspace_id": r["workspace_id"]}) if r.get("work_order_id") else None
    eng = await db.engagements.find_one({"uuid": wo["engagement_id"]}) if wo else None
    cust = await db.customers.find_one({"uuid": eng.get("customer_id"), "workspace_id": r["workspace_id"]}) if eng and eng.get("customer_id") else None
    inv = await db.repair_invoices.find_one({"repair_id": r["uuid"]})
    ws = await db.workspaces.find_one({"uuid": r["workspace_id"]})
    ok = bool(inv) and RR.invoice_current(inv, r, op)
    b = P.blockers(r, wo, inv, cust, ok)
    a = r.get("approved_work")
    if a and not a.get("approved_by_name"):  # older approvals stored only the user id: show that user's name (still not a signature)
        u = await db.users.find_one({"uuid": a.get("approved_by")}, {"name": 1})
        r = {**r, "approved_work": {**a, "approved_by_name": (u or {}).get("name")}}
    base = {"r": r, "op": op, "wo": wo, "cust": cust, "inv": inv, "issuer": (ws or {}).get("legal_name") or (ws or {}).get("name") or ""}
    sub = await db.invoice_submissions.find_one({"invoice_id": inv["uuid"], "status": {"$in": ["Sent", "Submitting", "Unknown"]}, "paperwork_key": {"$exists": True}},
                                                sort=[("created_at", -1)]) if inv else None
    if sub:  # submitted: invoice facts are frozen; the delivered snapshot never changes. A newer layout may be re-issued (not re-sent).
        relayout = sub["paperwork_key"].split(":L")[0] if ":L" in sub["paperwork_key"] else sub["paperwork_key"]
        relayout = f"{relayout}:L{P.LAYOUT_VERSION}"
        has = await db.paperwork_snapshots.find_one({"key": relayout}, {"_id": 1})
        return base | {"blockers": [], "key": relayout if has else sub["paperwork_key"], "relayout_key": relayout, "delivered_key": sub["paperwork_key"],
                       "submitted": sub["status"]}
    return base | {"blockers": b, "key": P.snapshot_key(inv, r) if inv else None, "submitted": None, "relayout_key": None, "delivered_key": None}


def _render(f: dict) -> dict:
    roles = (f["op"] or {}).get("required_signoffs") or []
    wo_pdf = P.work_order_pdf(f["r"], f["wo"], f["inv"], f["cust"], f["issuer"], f["op"], roles) if (f["op"] or {}).get("generic_forms") else None
    inv_pdf = P.invoice_pdf(f["inv"], f["r"], f["wo"], f["cust"], f["issuer"])
    packet = P.merge([x for x in (wo_pdf, inv_pdf) if x])
    return {"work_order": wo_pdf, "invoice": inv_pdf, "packet": packet}


async def current_snapshot(f: dict):
    return await db.paperwork_snapshots.find_one({"key": f["key"]}) if f["key"] else None


@router.get("/repairs/{visit_id}/paperwork", tags=["paperwork"])
async def paperwork_status(visit_id: str, user=Depends(current_user)):
    f = await _facts(user, visit_id)
    snap = await current_snapshot(f)
    roles = (f["op"] or {}).get("required_signoffs") or []
    return {"generic_form": P.FORM_ID in ((f["op"] or {}).get("generic_forms") or []), "template": P.template_info(), "blockers": f["blockers"],
            "issued": bool(snap), "submitted": f["submitted"], "delivered_key": f["delivered_key"], "snapshot_key": (snap or {}).get("key"),
            "documents": {k: v["sha256"] for k, v in (snap or {}).get("docs", {}).items()},
            "issued_at": (snap or {}).get("issued_at"), "signoffs": P.signoff_lines(f["r"], roles),
            "work_order": {"uuid": f["wo"]["uuid"], "number": f["wo"].get("number")} if f["wo"] else None}


@router.get("/repairs/{visit_id}/paperwork/{doc}.pdf", tags=["paperwork"])
async def paperwork_pdf(visit_id: str, doc: str, download: bool = False, user=Depends(current_user)):
    """Preview (inline) or Download. Issued snapshot bytes when issued for the current revisions, else a live render of the same facts."""
    if doc not in ("work_order", "invoice", "packet"):
        raise HTTPException(404, "Not found")
    f = await _facts(user, visit_id)
    if f["blockers"]:
        raise HTTPException(409, {"code": "blocked", "blockers": f["blockers"]})
    snap = await current_snapshot(f)
    if snap and doc in snap["docs"]:
        data, status = base64.b64decode(snap["docs"][doc]["b64"]), "Issued"
    else:
        data, status = _render(f)[doc], "Draft"
    if data is None:
        raise HTTPException(409, {"code": "not_selected", "blockers": ["Generic Repair Work Order is not selected for this operator."]})
    name = f"{doc}-{f['r']['uuid']}.pdf"
    return Response(data, media_type="application/pdf", headers={"Content-Disposition": f"{'attachment' if download else 'inline'}; filename={name}",
                                                                 "X-Document-Status": status, "X-SHA256": hashlib.sha256(data).hexdigest()})


@router.post("/repairs/{visit_id}/paperwork/issue", tags=["paperwork"])
async def issue_paperwork(visit_id: str, user=Depends(RR.staff)):
    """Immutable snapshot for (invoice revision, repair revision): repeats return the same snapshot (unique key)."""
    f = await _facts(user, visit_id)
    b = list(f["blockers"])
    if f["inv"] and not f["submitted"]:
        b += (await RR.blockers(f["r"], user))["invoice"]  # rate confirmation, PO, required sign-offs (REQ-1749)
        b += [f"{s.capitalize()} sign-off missing." for s in RR.signoffs_missing(f["r"], f["op"])]
    if b:
        raise HTTPException(409, {"code": "blocked", "blockers": list(dict.fromkeys(b))})
    if f["submitted"] and f["key"] != f["relayout_key"]:
        f = {**f, "key": f["relayout_key"]}  # newer layout re-issue for a delivered invoice; the delivered snapshot stays as sent
    snap = await current_snapshot(f)
    if snap:
        return clean(snap) | {"docs": {k: {"sha256": v["sha256"]} for k, v in snap["docs"].items()}}
    docs = {k: {"b64": base64.b64encode(v).decode(), "sha256": hashlib.sha256(v).hexdigest(), "size": len(v)} for k, v in _render(f).items() if v}
    rec = {"key": f["key"], "workspace_id": f["r"]["workspace_id"], "repair_id": f["r"]["uuid"], "invoice_id": f["inv"]["uuid"],
           "invoice_revision": f["inv"].get("revision"), "repair_revision": f["r"].get("revision"), "invoice_checksum": f["inv"].get("checksum"),
           "docs": docs, "issued_by": user["uuid"], "issued_at": iso()}
    try:
        await db.paperwork_snapshots.insert_one(rec)
        await audit(user, user["workspace_id"], "paperwork.issued", "invoice", f["inv"]["uuid"], {"key": f["key"], "sha256": {k: v["sha256"] for k, v in docs.items()}})
    except DuplicateKeyError:
        pass
    snap = await current_snapshot(f)
    return clean(snap) | {"docs": {k: {"sha256": v["sha256"]} for k, v in snap["docs"].items()}}


async def ensure_indexes():
    await db.paperwork_snapshots.create_index("key", unique=True)
