"""Phase 15: authorized repair -> completion -> report/forms -> invoice (smallest patch).
A repair is keyed by its inspection (visit); capture, sync and photo/video analysis are the existing ones. Invoice lines come
ONLY from approved actual work (never from AI findings). Delivery goes through the one channel the operator config names."""
import asyncio
import hashlib
import html as H
import io
import json
import os
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

import emailer
import money
from core import audit, clean, current_user, db, get_visit, iso, require_role

router = APIRouter(prefix="/api")
staff = require_role("estimator", "admin")
NOT_SET = "Not set"


# ---------------- models ----------------
class WorkItem(BaseModel):
    uuid: str = Field(min_length=4, max_length=64)
    kind: Literal["work", "material", "labor", "equipment"]
    description: str = Field(min_length=1, max_length=200)
    quantity: str = Field(min_length=1, max_length=20)
    unit: str = Field(min_length=1, max_length=20)
    rate_key: Optional[str] = Field(None, max_length=60)


class RepairIn(BaseModel):
    operator_id: Optional[str] = None
    operator_name: Optional[str] = Field(None, max_length=120)
    po: Optional[str] = Field(None, max_length=80)
    railroad: Optional[str] = Field(None, max_length=120)
    track: Optional[str] = Field(None, max_length=40)
    milepost: Optional[str] = Field(None, max_length=40)
    work: list[WorkItem] = []
    completion_date: Optional[str] = Field(None, max_length=10)
    finish: bool = False  # the one "Finish repair" tap
    finished_at_client: Optional[str] = None


class OperatorIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)  # legal name
    short_name: Optional[str] = Field(None, max_length=60)  # used in operator-specific blockers, e.g. "Tacoma Rail"
    contact_name: Optional[str] = Field(None, max_length=120)  # None shows "Not set"
    rates: dict = {}  # rate_key -> {"unit_price": "12.50", "unit": "each", "description": "..."}
    rates_source: Optional[str] = Field(None, max_length=120)
    rates_label: Optional[str] = Field(None, max_length=60)  # e.g. "2023 bid rates"
    rates_require_confirmation: bool = False  # an admin must confirm the rates per contract/PO
    billing_model: Optional[str] = None  # None = per-repair invoice; "progress_payments" = contract-level progress packets
    closeout: Optional[dict] = None  # {"checklist": [{"key","label","source"}], "general_release_doc": "<operator_documents uuid>"}
    channel: Optional[dict] = None  # {"type": "stub"|"email", "destination": "...", "recipient_label": "..."}
    forms: list = []  # [{"uuid","name","fields":[{"label","source"}]}]
    required_signoffs: Optional[list[str]] = ["foreman"]  # None = not set yet by the operator/admin (a blocker)
    tax_rate: str = "0"


class SubmitIn(BaseModel):
    confirm_recipient: Optional[str] = None  # required for email: must equal the configured destination


class RateConfirmIn(BaseModel):
    po: str = Field(min_length=1, max_length=80)


class SignoffIn(BaseModel):
    role: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=120)  # the name of the person who signed, as entered by the recorder


# ---------------- helpers ----------------
async def get_repair(user, visit_id: str) -> dict:
    await get_visit(user, visit_id)
    r = await db.repairs.find_one({"visit_id": visit_id, "workspace_id": user["workspace_id"]})
    if not r:
        raise HTTPException(404, "Not found")
    return r


async def operator_for(r: dict) -> Optional[dict]:
    return await db.operators.find_one({"uuid": r.get("operator_id"), "workspace_id": r["workspace_id"]}) if r.get("operator_id") else None


async def findings(r: dict) -> dict:
    manual = [clean(o) async for o in db.observations.find({"visit_id": r["visit_id"]})]
    ai = [{k: c.get(k) for k in ("uuid", "evidence_id", "category", "review_state", "timestamp_s", "schema")}
          async for c in db.visual_candidates.find({"visit_id": r["visit_id"]})]
    ev = await db.evidence.find({"visit_id": r["visit_id"]}, {"_id": 0, "uuid": 1, "kind": 1, "upload_state": 1, "sha256": 1, "captured_at": 1}).to_list(2000)
    return {"manual": manual, "ai": ai, "evidence": {"photo": sum(e["kind"] == "photo" for e in ev), "video": sum(e["kind"] == "video" for e in ev),
                                                     "not_verified": sum(e.get("upload_state") != "Verified" for e in ev),
                                                     "items": sorted(ev, key=lambda e: e["uuid"])}}


def signoffs_missing(r: dict, op: Optional[dict]) -> list[str]:
    have = {s["role"] for s in r.get("signoffs", [])} | ({"foreman"} if r.get("completion") else set())
    req = (op or {}).get("required_signoffs", ["foreman"])
    return [] if req is None else [s for s in req if s not in have]  # None: roles not set (separate blocker)


def rates_sha(op: dict) -> str:
    return hashlib.sha256(json.dumps(op.get("rates") or {}, sort_keys=True).encode()).hexdigest()


def invoice_lines(r: dict, op: dict) -> tuple[list, list]:
    """Approved actual work x operator rates. Returns (lines, blockers). Nothing from AI findings."""
    lines, blockers = [], []
    for w in (r.get("approved_work") or {}).get("items", []):
        key = w.get("rate_key") or w["kind"]
        rate = (op.get("rates") or {}).get(key)
        if not rate or rate.get("unit_price") in (None, ""):
            blockers.append(f"No rate for {w['description']} ({key}). Ask an admin to add it to the operator rates.")
            continue
        if (rate.get("unit") or "").strip().lower() != w["unit"].strip().lower():
            blockers.append(f"Unit mismatch for {w['description']}: work recorded per {w['unit']}, rate is per {rate.get('unit') or NOT_SET}.")
            continue
        try:
            q = money.dec(w["quantity"], "quantity", positive=True)
            c = money.dec(rate["unit_price"], "unit_price", nonneg=True)
        except money.MoneyError as e:
            blockers.append(f"{w['description']}: {e}")
            continue
        lines.append({"work_item_id": w["uuid"], "source": "approved_actual_work", "description": w["description"], "kind": w["kind"],
                      "quantity": money.s(q), "unit": w["unit"], "unit_cost": money.s(c), "markup_pct": "0", "taxable": bool(rate.get("taxable")),
                      "rate_key": key, "line_total": money.line_amounts({"quantity": q, "unit_cost": c, "markup_pct": 0})["line_total"]})
    return lines, blockers


NO_OPERATOR = "Operator not set up. Ask an admin to add this operator (forms, rates, approvals, channel)."


def _valid_date(s) -> bool:
    if not s or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return False
    try:
        return date.fromisoformat(s) <= datetime.now(timezone.utc).date() + timedelta(days=1)
    except ValueError:
        return False


async def is_test_ws(ws_id: str) -> bool:
    w = await db.workspaces.find_one({"uuid": ws_id}, {"is_test": 1})
    return bool(w and w.get("is_test"))


async def packet_blockers(r: dict, op: Optional[dict], f: dict) -> list[str]:
    """Everything the issued packet needs. The same list blocks issuing AND (again, at submit time) invoice submission."""
    b = [] if op else [NO_OPERATOR]
    for k, label in (("railroad", "Railroad"), ("track", "Track"), ("milepost", "Milepost")):
        if not (r.get(k) or "").strip():
            b.append(f"{label} missing.")
    c = r.get("completion")
    if not c:
        b.append("Repair not finished. The foreman must tap Finish repair.")
    elif not _valid_date(c.get("completion_date")):
        b.append("Completion date missing or not valid.")
    if not r.get("work"):
        b.append("No actual work recorded.")
    if f["evidence"]["not_verified"]:
        b.append(f"{f['evidence']['not_verified']} photo/video file(s) not uploaded yet.")
    if op:
        if not op.get("forms") and op.get("billing_model") != "progress_payments":  # progress-payment operators: no per-repair form
            b.append(f"{op['short_name']} completion form not supplied" if op.get("short_name")
                     else "No certification form from this operator. An admin must add the operator's form.")
        if op.get("required_signoffs") is None:
            b.append(f"Required {op.get('short_name') or op['name']} sign-offs not set")
        ctx = _context(r, op, f)
        for fm in op.get("forms") or []:
            for fl in fm.get("fields", []):
                if not (fl.get("source") or "").startswith("signoff.") and ctx.get(fl.get("source")) in (None, ""):
                    b.append(f"{fm['name']}: {fl['label']} not set.")
            if any(fl.get("pdf_field") for fl in fm.get("fields", [])) and not await db.operator_form_pdfs.find_one(
                    {"operator_id": op["uuid"], "form_id": fm["uuid"]}, {"_id": 1}):
                b.append(f"{fm['name']}: the operator's PDF is not uploaded.")
    for s in signoffs_missing(r, op):
        b.append(f"Sign-off missing: {s}.")
    if (r.get("summary") or {}).get("status") == "draft":
        b.append("Summary is a draft. Approve or edit it before issuing.")
    return b


async def blockers(r: dict, user: dict) -> dict:
    op = await operator_for(r)
    f = await findings(r)
    packet = await packet_blockers(r, op, f)
    inv = [] if op else [NO_OPERATOR]
    if not r.get("completion"):
        inv.append("Repair not finished. The foreman must tap Finish repair.")
    if not (r.get("po") or "").strip():
        inv.append("Contract or PO reference missing.")
    aw = r.get("approved_work")
    if not aw:
        inv.append("Actual work not approved yet. Office must approve it.")
    elif aw.get("repair_revision") != r.get("revision"):
        inv.append("Actual work changed after approval. Approve it again.")
    if op and aw:
        inv += invoice_lines(r, op)[1]
    if op and op.get("rates_require_confirmation") and not await db.operator_rate_confirmations.find_one(
            {"operator_id": op["uuid"], "po": (r.get("po") or "").strip(), "rates_sha": rates_sha(op)}, {"_id": 1}):
        inv.append(f"Confirm these {op.get('rates_label') or 'rates'} apply to this contract/PO")
    if op and op.get("billing_model") == "progress_payments":
        inv.append(f"{op.get('short_name') or op['name']} is billed by progress-payment packet for the contract/PO, not per repair.")
    sub = []
    if not r.get("packet"):
        sub.append("Documents not issued. Issue the report and forms first.")
    elif not packet and r["packet"]["fingerprint"] != _fingerprint(r, op, f)[0]:
        sub.append("Documents changed after issuing. Issue them again.")
    invoice = await db.repair_invoices.find_one({"repair_id": r["uuid"]})
    if invoice and aw and invoice.get("approved_work_at") != aw.get("approved_at"):
        sub.append("Invoice is out of date. Build it again.")
    sub += await channel_blockers(op, r["workspace_id"], user)
    seen = set()
    submit = [x for x in packet + inv + sub if not (x in seen or seen.add(x))]
    return {"report": packet, "invoice": inv, "submit": submit}


async def channel_blockers(op: Optional[dict], ws_id: str, user: dict) -> list[str]:
    sub = []
    ch = (op or {}).get("channel") or {}
    if op and not ch.get("type"):
        sub.append("No submission channel set for this operator. An admin must set the one channel the operator accepts.")
    elif ch.get("type") == "stub" and not await is_test_ws(ws_id):
        sub.append("Test delivery is only allowed in test workspaces. An admin must set the operator's real channel.")
    elif ch.get("type") == "email":
        if not emailer.connected():
            sub.append("Email sending not connected")
        if await is_test_ws(ws_id):
            sub.append("Test workspaces use Test delivery only. Email is never sent from a test workspace.")
    elif ch.get("type") and ch["type"] not in CHANNELS:
        sub.append(f"Channel {ch['type']} is not supported.")
    if op and ch.get("type") and not ch.get("destination"):
        sub.append("Submission destination missing for this operator.")
    if user["role"] not in ("estimator", "admin"):
        sub.append("You need office access to submit invoices.")
    return sub


# ---------------- channel adapter ----------------
class ChannelError(Exception):
    pass


TEST_DELIVERY = "Test delivery"


async def _stub(ch: dict, inv: dict, key: str, packet: dict) -> dict:
    """Test delivery (test workspaces only): records the invoice + packet locally, never leaves the server.
    stub_mode 'fail' simulates a refused delivery."""
    if ch.get("stub_mode") == "fail":
        raise ChannelError("Test delivery refused the invoice.")
    await asyncio.sleep(0.2)  # widen the race window for the concurrency test
    try:
        await db.channel_stub_outbox.insert_one({"key": key, "destination": ch.get("destination"), "invoice_id": inv["uuid"], "total": inv["totals"]["total"],
                                                 "packet_documents": packet["documents"], "at": iso()})
    except DuplicateKeyError:
        pass  # same key = same delivery
    return {"ack_id": "stub-ack-" + hashlib.sha256(key.encode()).hexdigest()[:16], "channel": "stub", "destination": ch.get("destination"), "label": TEST_DELIVERY}


class DeliveryUnknown(Exception):
    pass


def _body(page: str) -> str:
    m = re.search(r"<body>(.*)</body>", page, re.S)
    return m.group(1) if m else ""


async def _email(ch: dict, inv: dict, key: str, packet: dict) -> dict:
    """Live email through Emergent-managed Resend. Recipient = the operator's configured destination only (never caller input).
    Body = server template: the invoice and the issued packet (report + forms)."""
    ws = await db.workspaces.find_one({"uuid": inv["workspace_id"]}, {"name": 1})
    company = (ws or {}).get("name") or NOT_SET
    docs = {d["uuid"]: d async for d in db.repair_documents.find({"uuid": {"$in": packet["documents"]}})}
    rows = "".join(f"<tr><td style='padding:4px;border:1px solid #999'>{_e(l['description'])}</td><td style='padding:4px;border:1px solid #999'>{_e(l['quantity'])} {_e(l['unit'])}</td>"
                   f"<td style='padding:4px;border:1px solid #999'>${_e(l['unit_cost'])}</td><td style='padding:4px;border:1px solid #999;text-align:right'>${_e(l['line_total'])}</td></tr>"
                   for l in inv["lines"])
    packet_html = "".join(f"<hr/><div>{_body(docs[i]['html'])}</div>" for i in packet["documents"] if i in docs)
    html = (f"<table role='presentation' width='100%'><tr><td style='padding:16px;font-family:Arial,sans-serif;color:#111'>"
            f"<p>Attention: {_e(ch.get('recipient_label'))}, {_e(inv['operator_name'])}</p>"
            f"<p>Invoice {_e(inv['uuid'])} from {_e(company)}. Contract/PO: {_e(inv['po'])}.</p>"
            f"<table style='border-collapse:collapse'><tr><th>Item</th><th>Quantity</th><th>Rate</th><th>Amount</th></tr>{rows}</table>"
            f"<p><strong>Total ${_e(inv['totals']['total'])} USD</strong></p><h3>Completed repair packet</h3>{packet_html}"
            f"<p style='font-size:12px;color:#555'>Sent by RailReady for {_e(company)}. Reply to {_e(company)} with any questions.</p></td></tr></table>")
    try:
        pid = await emailer.send(to=ch["destination"], subject=f"Invoice {inv['uuid']} - PO {inv['po']} - {company}", html=html, key=key, workspace_id=inv["workspace_id"])
    except emailer.EmailRefused as e:
        raise ChannelError(str(e))
    except emailer.EmailUnknown as e:
        raise DeliveryUnknown(str(e))
    return {"ack_id": pid or NOT_SET, "channel": "email", "destination": ch["destination"], "label": None}


CHANNELS = {"stub": _stub, "email": _email}


# ---------------- phone: repair record ----------------
@router.put("/repairs/{visit_id}", tags=["repairs"])
async def put_repair(visit_id: str, body: RepairIn, user=Depends(require_role("foreman"))):
    """Client-authoritative while open (offline edits replay safely). Locked after Finish repair."""
    visit = await get_visit(user, visit_id)
    cur = await db.repairs.find_one({"visit_id": visit_id})
    data = body.model_dump(exclude={"finish", "finished_at_client"})
    if cur and cur.get("completion"):
        same = all(cur.get(k) == v for k, v in data.items() if k != "work") and [w["uuid"] for w in cur["work"]] == [w["uuid"] for w in data["work"]]
        if same:
            return clean(cur)  # replay of the finished repair
        raise HTTPException(409, {"code": "finished", "message": "Repair is finished. Changes are locked."})
    upd = {**data, "visit_id": visit_id, "site_id": visit["site_id"], "workspace_id": user["workspace_id"], "updated_at": iso(), "updated_by": user["uuid"]}
    if cur and cur.get("approved_work") and [w for w in cur["work"]] != data["work"]:
        upd["approved_work"] = None  # work changed: approval must be redone
    if body.finish:
        upd["completion"] = {"confirmed_by": user["uuid"], "confirmed_by_name": user.get("name"), "confirmed_at_client": body.finished_at_client,
                             "received_at": iso(), "completion_date": body.completion_date}
    await db.repairs.update_one({"visit_id": visit_id}, {"$set": upd, "$setOnInsert": {"uuid": f"rep-{visit_id}", "authorized": True, "signoffs": [], "created_at": iso(), "created_by": user["uuid"]},
                                                       "$inc": {"revision": 1}}, upsert=True)
    rail = {"railroad": body.railroad, "track": body.track, "milepost": {"text": body.milepost} if body.milepost else None}
    await db.locations.update_one({"uuid": f"repair-loc-{visit_id}"}, {"$set": {"railway": rail, "updated_at": iso()}, "$setOnInsert": {
        "uuid": f"repair-loc-{visit_id}", "workspace_id": user["workspace_id"], "visit_id": visit_id, "role": "confirmed_onsite", "source": "manual",
        "lat": None, "lon": None, "label": "Repair location", "revision": 1, "history": [], "created_at": iso()}}, upsert=True)
    if body.finish:
        await audit(user, user["workspace_id"], "repair.finished", "repair", f"rep-{visit_id}", {"at": iso()})
    return clean(await db.repairs.find_one({"visit_id": visit_id}))


@router.get("/operators", tags=["repairs"])
async def list_operators(user=Depends(current_user)):
    return [{"uuid": o["uuid"], "name": o["name"], "rate_items": [{"key": k, "description": v.get("description") or k, "unit": v.get("unit")}
                                                                 for k, v in (o.get("rates") or {}).items()]}
            async for o in db.operators.find({"workspace_id": user["workspace_id"]})]


@router.get("/operators/{oid}", tags=["repairs"])
async def get_operator(oid: str, user=Depends(staff)):
    op = await db.operators.find_one({"uuid": oid, "workspace_id": user["workspace_id"]})
    if not op:
        raise HTTPException(404, "Not found")
    out = clean(op)
    out["rate_confirmations"] = [clean(x) for x in await db.operator_rate_confirmations.find({"operator_id": oid}).to_list(200)]
    return out


@router.post("/operators/{oid}/rate-confirmations", tags=["repairs"])
async def confirm_rates(oid: str, body: RateConfirmIn, user=Depends(require_role("admin"))):
    """An admin records that the operator's current rates apply to one contract/PO (who and when)."""
    op = await db.operators.find_one({"uuid": oid, "workspace_id": user["workspace_id"]})
    if not op:
        raise HTTPException(404, "Not found")
    doc = {"operator_id": oid, "po": body.po.strip(), "rates_sha": rates_sha(op), "rates_label": op.get("rates_label"), "confirmed_by": user["uuid"],
           "confirmed_by_name": user.get("name"), "confirmed_at": iso(), "workspace_id": user["workspace_id"]}
    await db.operator_rate_confirmations.update_one({k: doc[k] for k in ("operator_id", "po", "rates_sha")}, {"$setOnInsert": doc}, upsert=True)
    await audit(user, user["workspace_id"], "operator.rates_confirmed", "operator", oid, {"po": doc["po"]})
    return clean(await db.operator_rate_confirmations.find_one({k: doc[k] for k in ("operator_id", "po", "rates_sha")}))


@router.put("/operators/{oid}", tags=["repairs"])
async def put_operator(oid: str, body: OperatorIn, user=Depends(require_role("admin"))):
    old = await db.operators.find_one({"uuid": oid})
    if old and old["workspace_id"] != user["workspace_id"]:
        raise HTTPException(404, "Not found")
    ch = (body.channel or {}).get("type")
    if ch and ch not in CHANNELS:
        raise HTTPException(422, f"Channel {ch} is not supported.")
    if ch == "stub" and not await is_test_ws(user["workspace_id"]):
        raise HTTPException(422, "Test delivery can only be selected in a test workspace.")
    await db.operators.update_one({"uuid": oid}, {"$set": {**body.model_dump(), "uuid": oid, "workspace_id": user["workspace_id"], "updated_at": iso()}}, upsert=True)
    return clean(await db.operators.find_one({"uuid": oid}))


# ---------------- office ----------------
@router.get("/repairs", tags=["repairs"])
async def list_repairs(user=Depends(current_user)):
    return [clean(r) for r in await db.repairs.find({"workspace_id": user["workspace_id"]}).sort("created_at", -1).to_list(500)]


@router.get("/repairs/{visit_id}", tags=["repairs"])
async def repair_detail(visit_id: str, user=Depends(current_user)):
    r = await get_repair(user, visit_id)
    op = await operator_for(r)
    inv = await db.repair_invoices.find_one({"repair_id": r["uuid"]})
    sub = await db.invoice_submissions.find_one({"invoice_id": inv["uuid"]}, sort=[("created_at", -1)]) if inv else None
    ids = (r.get("packet") or {}).get("documents") or []
    docs = [{k: d[k] for k in ("uuid", "kind", "name", "sha256", "issued_at")} async for d in db.repair_documents.find({"uuid": {"$in": ids}})]
    b = await blockers(r, user)
    rep = clean(r)
    if user["role"] != "admin":
        rep.pop("summary_provenance", None)  # REQ-1523: admin-only
    ch = (op.get("channel") or {}).get("type") if op else None
    chd = (op.get("channel") or {}) if op else {}
    return {"repair": rep, "operator": {"uuid": op["uuid"], "name": op["name"], "forms": [{"uuid": f["uuid"], "name": f["name"]} for f in op.get("forms", [])],
                                         "channel": ch, "channel_label": TEST_DELIVERY if ch == "stub" else ch,
                                         "destination": chd.get("destination") if user["role"] in ("estimator", "admin") else None,
                                         "recipient_label": chd.get("recipient_label"), "contact_name": op.get("contact_name") or NOT_SET,
                                         "rates_source": op.get("rates_source") or NOT_SET} if op else None,
            "findings": await findings(r), "blockers": b, "documents": docs,
            "document_status": "Issued" if docs and not any("changed after issuing" in x for x in b["submit"]) else "Draft",
            "invoice": clean(inv) if inv else None, "submission": clean(sub) if sub else None,
            "invoice_status": (sub or {}).get("status") or ("Draft" if inv else None),
            "delivery_label": TEST_DELIVERY if (sub or {}).get("test_delivery") else None,
            "documents_model": await _documents_model(r, op, b, docs, user)}


async def _documents_model(r, op, b, docs, user) -> Optional[list]:
    """Progress-payment operators: the three documents shown separately, each with its own blockers."""
    if not op or op.get("billing_model") != "progress_payments":
        return None
    import routes_contract as RC  # late import: routes_contract imports this module
    return await RC.repair_documents_model(r, op, b, bool(docs), user)


@router.post("/repairs/{visit_id}/approve-work", tags=["repairs"])
async def approve_work(visit_id: str, user=Depends(staff)):
    r = await get_repair(user, visit_id)
    if not r.get("completion"):
        raise HTTPException(409, {"code": "not_finished", "message": "Repair not finished. The foreman must tap Finish repair."})
    snap = {"items": r["work"], "approved_by": user["uuid"], "approved_at": iso(), "repair_revision": r["revision"]}
    await db.repairs.update_one({"uuid": r["uuid"], "revision": r["revision"]}, {"$set": {"approved_work": snap}})
    return clean(await db.repairs.find_one({"uuid": r["uuid"]}))


@router.post("/repairs/{visit_id}/signoffs", tags=["repairs"])
async def add_signoff(visit_id: str, body: SignoffIn, user=Depends(staff)):
    r = await get_repair(user, visit_id)
    s = {"role": body.role.strip(), "name": body.name.strip(), "recorded_by": user["uuid"], "recorded_at": iso()}
    await db.repairs.update_one({"uuid": r["uuid"], "signoffs.role": {"$ne": s["role"]}}, {"$push": {"signoffs": s}})
    return clean(await db.repairs.find_one({"uuid": r["uuid"]}))


def _e(x) -> str:
    return H.escape(NOT_SET if x in (None, "") else str(x))


CSS = ("body{font-family:Georgia,serif;color:#111;margin:24px;max-width:820px}h1{font-size:22px;border-bottom:3px solid #111}"
       "h2{font-size:16px;margin-top:22px;border-bottom:1px solid #999}table{width:100%;border-collapse:collapse}td,th{border:1px solid #999;padding:6px;font-size:13px}"
       ".n{text-align:right}.draft{border:2px solid #b45309;padding:6px;font-weight:bold}@media print{table,tr{break-inside:avoid}}")


def _context(r, op, f) -> dict:
    """Values for documents/forms: recorded facts first; office-entered form values only fill sources no record provides."""
    c = r.get("completion") or {}
    sig = {s["role"]: s for s in r.get("signoffs", [])}
    if c:
        sig.setdefault("foreman", {"name": c.get("confirmed_by_name"), "recorded_at": c.get("received_at")})
    ctx = {"repair.operator_name": (op or {}).get("name") or r.get("operator_name"), "repair.po": r.get("po"), "repair.railroad": r.get("railroad"),
           "repair.track": r.get("track"), "repair.milepost": r.get("milepost"), "repair.id": r["uuid"],
           "completion.date": c.get("completion_date"), "completion.confirmed_by_name": c.get("confirmed_by_name"), "completion.confirmed_at": c.get("received_at"),
           "work.summary": "; ".join(f"{w['description']} {w['quantity']} {w['unit']}" for w in r.get("work", [])) or None,
           "findings.manual_count": len(f["manual"]), "findings.ai_count": len(f["ai"]),
           "evidence.photo_count": f["evidence"]["photo"], "evidence.video_count": f["evidence"]["video"]}
    for role, s in sig.items():
        ctx[f"signoff.{role}.name"], ctx[f"signoff.{role}.at"] = s.get("name"), s.get("recorded_at")
    for k, v in (r.get("form_values") or {}).items():
        if k not in ctx and isinstance(v, dict):
            ctx[k] = v.get("value")
    return ctx


DERIVED = {"repair.", "completion.", "work.", "findings.", "evidence.", "signoff."}


def _render(r, op, f, kind: str, form_id: Optional[str], draft: bool) -> tuple[str, str]:
    ctx = _context(r, op, f)
    dl = "<p class=draft>Draft. Not issued.</p>" if draft else ""
    if kind == "form":
        form = next((x for x in (op or {}).get("forms", []) if x["uuid"] == form_id), None)
        if not form:
            raise HTTPException(404, "Not found")
        rows = "".join(f"<tr><th>{_e(fl['label'])}</th><td>{_e(ctx.get(fl.get('source')))}</td></tr>" for fl in form.get("fields", []))
        return form["name"], f"<!doctype html><html><head><meta charset=utf-8><title>{_e(form['name'])}</title><style>{CSS}</style></head><body>{dl}<h1>{_e(form['name'])}</h1><table>{rows}</table></body></html>"
    work = "".join(f"<tr><td>{_e(w['kind'])}</td><td>{_e(w['description'])}</td><td class=n>{_e(w['quantity'])} {_e(w['unit'])}</td></tr>" for w in r.get("work", []))
    man = "".join(f"<li>{_e(o.get('text') or o.get('description') or o.get('kind'))}</li>" for o in f["manual"]) or f"<li>{NOT_SET}</li>"
    ai = "".join(f"<li>{_e(c['category'])} ({_e(c['review_state'])}), evidence {_e(c['evidence_id'])}. Suggested by the photo check. Not billed.</li>" for c in f["ai"]) or "<li>None</li>"
    ev = "".join(f"<tr><td>{_e(e['kind'])}</td><td>{_e(e['uuid'])}</td><td>{_e((e.get('sha256') or '')[:16])}</td><td>{_e(e.get('captured_at'))}</td></tr>"
                 for e in f["evidence"]["items"]) or f"<tr><td colspan=4>{NOT_SET}</td></tr>"
    sig = "".join(f"<tr><td>{_e(k.split('.')[1])}</td><td>{_e(v)}</td><td>{_e(ctx.get(k[:-5] + '.at'))}</td></tr>" for k, v in ctx.items() if k.startswith("signoff.") and k.endswith(".name"))
    req = "".join(f"<tr><td>{_e(s)}</td><td>{NOT_SET}</td><td>{NOT_SET}</td></tr>" for s in signoffs_missing(r, op))
    sm = r.get("summary") or {}
    summ = ""
    if sm.get("text"):
        summ = f"<h2>Summary</h2>{'<p class=draft>Draft. Review before issuing.</p>' if sm.get('status') == 'draft' else ''}<p>{_e(sm['text'])}</p>"
    body = (f"<h1>Repair record</h1><p class=note>Contractor's record of the work performed. Not an operator or Tacoma Rail certification.</p>{dl}"
            f"<p>Operator: {_e(ctx['repair.operator_name'])}<br/>Contract/PO: {_e(ctx['repair.po'])}<br/>"
            f"Railroad: {_e(ctx['repair.railroad'])} &middot; Track: {_e(ctx['repair.track'])} &middot; Milepost: {_e(ctx['repair.milepost'])}<br/>"
            f"Completion date: {_e(ctx['completion.date'])} &middot; Confirmed by: {_e(ctx['completion.confirmed_by_name'])} at {_e(ctx['completion.confirmed_at'])}<br/>"
            f"Evidence: {f['evidence']['photo']} photo(s), {f['evidence']['video']} video(s)</p>{summ}"
            f"<h2>Actual work</h2><table><tr><th>Type</th><th>Item</th><th>Quantity</th></tr>{work or '<tr><td colspan=3>' + NOT_SET + '</td></tr>'}</table>"
            f"<h2>Defects recorded by the crew</h2><ul>{man}</ul><h2>Photo and video check results</h2><ul>{ai}</ul>"
            f"<h2>Evidence references</h2><table><tr><th>Type</th><th>Evidence id</th><th>SHA-256</th><th>Captured</th></tr>{ev}</table>"
            f"<h2>Sign-offs</h2><table><tr><th>Role</th><th>Name</th><th>Recorded</th></tr>{sig}{req}</table>")
    return "Repair record", f"<!doctype html><html><head><meta charset=utf-8><title>Repair record {_e(r['uuid'])}</title><style>{CSS}</style></head><body>{body}</body></html>"


def _packet_docs(r, op, f) -> list:
    return [("report", None)] + [("form", x["uuid"]) for x in (op or {}).get("forms", [])]


def _fingerprint(r, op, f) -> tuple[str, list]:
    """Hash of the final (non-draft) packet renders; submit compares it with the issued packet."""
    pages = [(kind, fid) + _render(r, op, f, kind, fid, False) for kind, fid in _packet_docs(r, op, f)]
    shas = [hashlib.sha256(p[3].encode()).hexdigest() for p in pages]
    return hashlib.sha256("|".join(shas).encode()).hexdigest(), [p + (s,) for p, s in zip(pages, shas)]


async def _doc_html(r, user, kind: str, form_id: Optional[str]) -> tuple[str, str]:
    op = await operator_for(r)
    f = await findings(r)
    return _render(r, op, f, kind, form_id, bool(await packet_blockers(r, op, f)))


@router.get("/repairs/{visit_id}/report", response_class=HTMLResponse, tags=["repairs"])
async def report(visit_id: str, user=Depends(current_user)):
    return (await _doc_html(await get_repair(user, visit_id), user, "report", None))[1]


@router.get("/repairs/{visit_id}/forms/{form_id}", response_class=HTMLResponse, tags=["repairs"])
async def form(visit_id: str, form_id: str, user=Depends(current_user)):
    return (await _doc_html(await get_repair(user, visit_id), user, "form", form_id))[1]


class FormValuesIn(BaseModel):
    values: dict[str, str]  # source -> value, for form fields no record provides (for example an inspector license number)


@router.put("/repairs/{visit_id}/form-values", tags=["repairs"])
async def put_form_values(visit_id: str, body: FormValuesIn, user=Depends(staff)):
    r = await get_repair(user, visit_id)
    fv = {k: v for k, v in (r.get("form_values") or {}).items() if isinstance(v, dict) and "value" in v}  # keys contain dots: store as one map
    for k, v in body.values.items():
        if any(k.startswith(p) for p in DERIVED) or not re.fullmatch(r"[a-z0-9_.]{1,60}", k) or len(v) > 200:
            raise HTTPException(422, f"{k} cannot be entered by hand. It comes from the recorded repair.")
        if v.strip():
            fv[k] = {"value": v.strip(), "entered_by": user["uuid"], "entered_at": iso()}
        else:
            fv.pop(k, None)
    await db.repairs.update_one({"uuid": r["uuid"]}, {"$set": {"form_values": fv}})
    return clean(await db.repairs.find_one({"uuid": r["uuid"]}))


# ---------------- operator-supplied fillable PDF (pypdf AcroForm) ----------------
def _pdf_fields(data: bytes) -> dict:
    from pypdf import PdfReader
    return PdfReader(io.BytesIO(data)).get_fields() or {}


@router.post("/operators/{oid}/forms/{form_id}/pdf", tags=["repairs"])
async def upload_form_pdf(oid: str, form_id: str, file: UploadFile = File(...), user=Depends(require_role("admin"))):
    op = await db.operators.find_one({"uuid": oid, "workspace_id": user["workspace_id"]})
    if not op or not any(f["uuid"] == form_id for f in op.get("forms", [])):
        raise HTTPException(404, "Not found")
    data = await file.read()
    if len(data) > 10_000_000 or not data.startswith(b"%PDF"):
        raise HTTPException(422, "Upload the operator's form as a PDF under 10 MB.")
    try:
        fields = _pdf_fields(data)
    except Exception:
        raise HTTPException(422, "This PDF could not be read.")
    if not fields:
        raise HTTPException(422, "This PDF has no fillable fields. Ask the operator for the fillable version.")
    doc = {"operator_id": oid, "form_id": form_id, "workspace_id": user["workspace_id"], "pdf": data, "sha256": hashlib.sha256(data).hexdigest(),
           "field_names": sorted(fields), "uploaded_by": user["uuid"], "uploaded_at": iso()}
    await db.operator_form_pdfs.update_one({"operator_id": oid, "form_id": form_id}, {"$set": doc}, upsert=True)
    await audit(user, user["workspace_id"], "operator_form.upload", "operator", oid, {"form_id": form_id, "sha256": doc["sha256"]})
    return {k: doc[k] for k in ("form_id", "sha256", "field_names")}


async def _filled_pdf(r, user, form_id: str) -> Optional[bytes]:
    from pypdf import PdfReader, PdfWriter
    op = await operator_for(r)
    form = next((x for x in (op or {}).get("forms", []) if x["uuid"] == form_id), None)
    src = await db.operator_form_pdfs.find_one({"operator_id": (op or {}).get("uuid"), "form_id": form_id}) if form else None
    if not src:
        return None
    ctx = _context(r, op, await findings(r))
    reader = PdfReader(io.BytesIO(src["pdf"]))
    kinds = {k: v.get("/FT") for k, v in (reader.get_fields() or {}).items()}
    vals = {}
    for fl in form.get("fields", []):
        name = fl.get("pdf_field")
        if name in kinds and kinds[name] == "/Tx":  # text fields only; signature fields are never filled
            v = ctx.get(fl.get("source"))
            vals[name] = NOT_SET if v in (None, "") else str(v)
    w = PdfWriter(clone_from=reader)
    for page in w.pages:
        w.update_page_form_field_values(page, vals, auto_regenerate=False)
    w.set_need_appearances_writer(True)
    out = io.BytesIO()
    w.write(out)
    return out.getvalue()


@router.get("/repairs/{visit_id}/forms/{form_id}/pdf", tags=["repairs"])
async def form_pdf(visit_id: str, form_id: str, user=Depends(current_user)):
    r = await get_repair(user, visit_id)
    data = await _filled_pdf(r, user, form_id)
    if data is None:
        raise HTTPException(404, {"code": "no_pdf", "message": "No fillable PDF uploaded for this form. An admin must upload the operator's form."})
    status = "Draft" if (await blockers(r, user))["report"] else "Ready"
    return Response(data, media_type="application/pdf", headers={"X-Document-Status": status,
                    "Content-Disposition": f'inline; filename="{form_id}-{status.lower()}.pdf"'})


@router.post("/repairs/{visit_id}/issue", tags=["repairs"])
async def issue(visit_id: str, user=Depends(staff)):
    r = await get_repair(user, visit_id)
    op = await operator_for(r)
    f = await findings(r)
    b = await packet_blockers(r, op, f)
    if b:
        raise HTTPException(409, {"code": "blocked", "blockers": b})
    fp, pages = _fingerprint(r, op, f)
    out = []
    for kind, fid, name, page, sha in pages:
        did = f"doc-{r['uuid']}-{fid or 'report'}-{sha[:12]}"
        doc = {"uuid": did, "repair_id": r["uuid"], "kind": kind, "form_id": fid, "name": name, "html": page, "sha256": sha,
               "evidence_ids": [e["uuid"] for e in f["evidence"]["items"]], "issued_at": iso(), "issued_by": user["uuid"]}
        pdf = await _filled_pdf(r, user, fid) if fid else None
        if pdf:
            doc["pdf"] = pdf
        await db.repair_documents.update_one({"uuid": did}, {"$setOnInsert": doc}, upsert=True)
        out.append({k: doc[k] for k in ("uuid", "kind", "name", "sha256")})
    if (r.get("packet") or {}).get("fingerprint") != fp:
        await db.repairs.update_one({"uuid": r["uuid"]}, {"$set": {"packet": {"documents": [x["uuid"] for x in out], "fingerprint": fp,
                                                                              "issued_at": iso(), "issued_by": user["uuid"]}}})
        await audit(user, user["workspace_id"], "repair.packet_issued", "repair", r["uuid"], {"fingerprint": fp})
    return {"documents": out, "fingerprint": fp}


@router.post("/repairs/{visit_id}/invoice", tags=["repairs"])
async def make_invoice(visit_id: str, user=Depends(staff)):
    r = await get_repair(user, visit_id)
    b = await blockers(r, user)
    if b["invoice"]:
        raise HTTPException(409, {"code": "blocked", "blockers": b["invoice"]})
    op = await operator_for(r)
    iid = f"inv-{r['uuid']}"
    if await db.invoice_submissions.find_one({"invoice_id": iid, "status": {"$in": ["Sent", "Submitting"]}}):
        return clean(await db.repair_invoices.find_one({"uuid": iid}))  # sent or sending: never rebuilt
    lines, _ = invoice_lines(r, op)
    inv = {"uuid": iid, "repair_id": r["uuid"], "visit_id": visit_id, "workspace_id": r["workspace_id"], "operator_id": op["uuid"], "operator_name": op["name"],
           "po": r["po"], "lines": lines, "totals": money.totals(lines, op.get("tax_rate", "0")), "approved_work_at": r["approved_work"]["approved_at"],
           "updated_at": iso()}
    await db.repair_invoices.update_one({"uuid": iid}, {"$set": inv, "$inc": {"revision": 1}, "$setOnInsert": {"created_at": iso()}}, upsert=True)
    return clean(await db.repair_invoices.find_one({"uuid": iid}))


@router.post("/invoices/{iid}/submit", tags=["repairs"])
async def submit_invoice(iid: str, body: SubmitIn = SubmitIn(), user=Depends(staff)):
    """One submission per invoice: unique key + compare-and-set claim before any send. Every gate is rechecked here.
    Email (live) also needs the caller to confirm the exact configured recipient."""
    inv = await db.repair_invoices.find_one({"uuid": iid, "workspace_id": user["workspace_id"]})
    if not inv:
        raise HTTPException(404, "Not found")
    key = f"submit-{iid}"
    cur = await db.invoice_submissions.find_one({"key": key})
    if cur and cur["status"] in ("Sent", "Submitting", "Unknown"):
        return clean(cur)  # idempotent: the existing submission (Unknown is never auto-resent)
    r = await db.repairs.find_one({"uuid": inv["repair_id"]})
    b = await blockers(r, user)
    if b["submit"]:
        raise HTTPException(409, {"code": "blocked", "blockers": b["submit"]})
    op = await operator_for(r)
    ch = op["channel"]
    return await deliver(key, {"invoice_id": iid}, inv, r["packet"], ch, user, body.confirm_recipient, {"invoice_revision": inv["revision"]})


async def deliver(key: str, ids: dict, inv: dict, packet: dict, ch: dict, user: dict, confirm_recipient: Optional[str], extra: dict) -> dict:
    """Shared by per-repair invoices and progress-payment packets: recipient confirm (email), unique key, compare-and-set claim, send once."""
    if ch["type"] == "email" and (confirm_recipient or "").strip().lower() != ch["destination"].strip().lower():
        raise HTTPException(409, {"code": "confirm_recipient", "blockers": [f"Confirm the recipient: {ch['destination']}"]})
    claim = {"status": "Submitting", "claimed_at": iso(), "by": user["uuid"], "packet": packet,
             "channel": ch["type"], "destination": ch.get("destination"), "test_delivery": ch["type"] == "stub", **extra}
    try:
        await db.invoice_submissions.insert_one({"key": key, **ids, "attempts": 1, "created_at": iso(), **claim})
    except DuplicateKeyError:
        got = await db.invoice_submissions.find_one_and_update({"key": key, "status": "Failed"}, {"$set": claim, "$inc": {"attempts": 1}},
                                                               return_document=ReturnDocument.AFTER)
        if not got:
            return clean(await db.invoice_submissions.find_one({"key": key}))  # another request holds the claim
    try:
        ack = await CHANNELS[ch["type"]](ch, inv, key, packet)
        await db.invoice_submissions.update_one({"key": key, "status": "Submitting"}, {"$set": {"status": "Sent", "ack": ack, "acknowledged_at": iso(), "error": None}})
        await audit(user, user["workspace_id"], "invoice.sent", "invoice", inv["uuid"], {"ack": ack["ack_id"], "test_delivery": claim["test_delivery"]})
    except ChannelError as e:
        await db.invoice_submissions.update_one({"key": key, "status": "Submitting"}, {"$set": {"status": "Failed", "error": str(e)}})
    except DeliveryUnknown as e:
        await db.invoice_submissions.update_one({"key": key, "status": "Submitting"}, {"$set": {"status": "Unknown", "error": str(e)}})
    return clean(await db.invoice_submissions.find_one({"key": key}))


# ---------------- Step 2: AI draft summary (GPT-6 Luna via the Emergent Universal Key) ----------------
SUMMARY_PROVIDER, SUMMARY_MODEL, SUMMARY_PROMPT_VERSION = "openai", "gpt-6-luna", "repair-summary-v1"
SUMMARY_FAILED = "Summary not drafted. Write it yourself or try again."
SUMMARY_SYSTEM = ("You write the summary paragraph of a completed railroad track repair report. Use ONLY the facts in the JSON list. "
                  "Do not add facts, causes, judgments, safety or compliance statements, certification, signatures, prices or totals. "
                  "Copy quantities and units exactly as given. Leave out anything not in the facts. Plain ASCII text, 2 to 5 sentences, no headings, no lists.")


def summary_facts(r: dict, f: dict) -> list[dict]:
    facts = [{"id": r["uuid"], "fact": f"Repair for {r.get('operator_name') or NOT_SET}, PO {r.get('po') or NOT_SET}, railroad {r.get('railroad') or NOT_SET}, "
                                      f"track {r.get('track') or NOT_SET}, milepost {r.get('milepost') or NOT_SET}."}]
    c = r.get("completion") or {}
    if c:
        facts.append({"id": f"{r['uuid']}:completion", "fact": f"Completed {c.get('completion_date') or NOT_SET}, confirmed by foreman {c.get('confirmed_by_name') or NOT_SET}."})
    facts += [{"id": w["uuid"], "fact": f"Actual {w['kind']}: {w['description']}, {w['quantity']} {w['unit']}."} for w in r.get("work", [])]
    facts += [{"id": o["uuid"], "fact": f"Crew recorded defect: {o.get('text') or o.get('kind')}."} for o in f["manual"]]
    facts += [{"id": c2["uuid"], "fact": f"Reviewed photo/video finding: {c2['category']} ({c2['review_state']}), evidence {c2['evidence_id']}."}
              for c2 in f["ai"] if c2.get("review_state") not in ("Pending", "Dismissed")]
    facts += [{"id": e["uuid"], "fact": f"Evidence {e['kind']} {e['uuid']}."} for e in f["evidence"]["items"]]
    return facts


async def _llm_summary(facts: list[dict], session: str) -> str:
    from emergentintegrations.llm.chat import LlmChat, UserMessage
    chat = LlmChat(api_key=os.environ["EMERGENT_LLM_KEY"], session_id=session, system_message=SUMMARY_SYSTEM).with_model(SUMMARY_PROVIDER, SUMMARY_MODEL)
    out = await asyncio.wait_for(chat.send_message(UserMessage(text="Facts:\n" + json.dumps(facts, ensure_ascii=True))), timeout=90)
    text = " ".join(str(out or "").split()).encode("ascii", "ignore").decode()
    if not text:
        raise ValueError("empty draft")
    return text[:2000]


@router.post("/repairs/{visit_id}/summary/draft", tags=["repairs"])
async def draft_summary(visit_id: str, user=Depends(staff)):
    """Internal one-shot draft (non-streaming by design: the text is stored for review, not shown token by token)."""
    r = await get_repair(user, visit_id)
    if not r.get("completion"):
        raise HTTPException(409, {"code": "not_finished", "message": "Repair not finished. The foreman must tap Finish repair."})
    facts = summary_facts(r, await findings(r))
    try:
        text = await _llm_summary(facts, f"repair-summary-{r['uuid']}-{iso()}")
    except Exception as e:
        await audit(user, user["workspace_id"], "repair.summary_failed", "repair", r["uuid"], {"error": type(e).__name__})
        raise HTTPException(502, {"code": "summary_failed", "message": SUMMARY_FAILED})
    prov = {"provider": SUMMARY_PROVIDER, "model": SUMMARY_MODEL, "prompt_version": SUMMARY_PROMPT_VERSION,
            "prompt_sha256": hashlib.sha256(SUMMARY_SYSTEM.encode()).hexdigest(), "fact_ids": [x["id"] for x in facts], "drafted_by": user["uuid"], "drafted_at": iso()}
    await db.repairs.update_one({"uuid": r["uuid"]}, {"$set": {"summary": {"text": text, "status": "draft", "source": "ai_draft", "updated_at": iso()},
                                                               "summary_provenance": prov}})
    await audit(user, user["workspace_id"], "repair.summary_drafted", "repair", r["uuid"], {"model": SUMMARY_MODEL})
    return {"summary": {"text": text, "status": "draft", "label": "Draft. Review before issuing."}}


class SummaryIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    approve: bool = True


@router.put("/repairs/{visit_id}/summary", tags=["repairs"])
async def put_summary(visit_id: str, body: SummaryIn, user=Depends(staff)):
    """A person approves the draft as is, or edits/writes it. Only then can the report be issued."""
    r = await get_repair(user, visit_id)
    old = r.get("summary") or {}
    text = " ".join(body.text.split())
    s = {"text": text, "status": "approved" if body.approve else "draft", "source": old.get("source") if text == old.get("text") else "human",
         "edited": bool(old.get("text")) and text != old.get("text"), "approved_by": user["uuid"] if body.approve else None,
         "approved_at": iso() if body.approve else None, "updated_at": iso()}
    await db.repairs.update_one({"uuid": r["uuid"]}, {"$set": {"summary": s}})
    return {"summary": s}


async def ensure_indexes():
    await db.repairs.create_index("visit_id", unique=True)
    await db.invoice_submissions.create_index("key", unique=True)
    await db.channel_stub_outbox.create_index("key", unique=True)
    await db.operator_rate_confirmations.create_index([("operator_id", 1), ("po", 1), ("rates_sha", 1)], unique=True)
    await db.email_sends.create_index("key")
