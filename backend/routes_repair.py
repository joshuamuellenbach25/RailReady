"""Phase 15: authorized repair -> completion -> report/forms -> invoice (smallest patch).
A repair is keyed by its inspection (visit); capture, sync and photo/video analysis are the existing ones. Invoice lines come
ONLY from approved actual work (never from AI findings). Delivery goes through the one channel the operator config names."""
import asyncio
import hashlib
import html as H
import io
import json
import math
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
import paperwork  # Phase 17: layout version in the paperwork snapshot key
from core import audit, clean, current_user, db, get_visit, iso, require_role, visit_location

router = APIRouter(prefix="/api")
staff = require_role("estimator", "admin")
NOT_SET = "Not set"


# ---------------- models ----------------
class WorkItem(BaseModel):
    uuid: str = Field(min_length=4, max_length=64)
    kind: Literal["work", "material", "labor", "equipment"]
    description: str = Field(min_length=1, max_length=1000)  # Phase 17: long work descriptions carried in full on the forms
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
    required_location_fields: list[Literal["railroad", "track", "milepost"]] = []  # Additional requirements; operator form sources also apply.


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
    visits = list(dict.fromkeys(v for v in (r["visit_id"], r.get("inspection_visit_id")) if v))
    query = {"workspace_id": r["workspace_id"], "visit_id": {"$in": visits}}
    manual = [clean(o) async for o in db.observations.find(query)]
    ai = [{k: c.get(k) for k in ("uuid", "visit_id", "evidence_id", "category", "review_state", "timestamp_s", "schema")}
          async for c in db.visual_candidates.find(query)]
    ev = await db.evidence.find(query, {"_id": 0, "uuid": 1, "visit_id": 1, "kind": 1, "upload_state": 1, "sha256": 1, "captured_at": 1}).to_list(2000)
    return {"manual": manual, "ai": ai, "evidence": {"photo": sum(e["kind"] == "photo" for e in ev), "video": sum(e["kind"] == "video" for e in ev),
                                                     "not_verified": sum(e.get("upload_state") != "Verified" for e in ev),
                                                     "items": sorted(ev, key=lambda e: e["uuid"])}}


def signoffs_missing(r: dict, op: Optional[dict]) -> list[str]:
    have = {s["role"] for s in r.get("signoffs", []) if (s.get("name") or "").strip()} | ({"foreman"} if r.get("completion") else set())
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


LOC_FIELDS = (("railroad", "Railroad"), ("track", "Track"), ("milepost", "Milepost"))
MILEPOST_RE = re.compile(r"(?i)^(mp\s?)?\d{1,4}(\.\d{1,4})?$")


def loc_field_error(k: str, v: str) -> Optional[str]:
    """Same rules as the phone: railroad 2-120 chars, track 1-40, milepost a number such as 17 or 17.25 (optional MP prefix)."""
    v = (v or "").strip()
    if k == "railroad" and not 2 <= len(v) <= 120:
        return "Railroad must be 2 to 120 characters."
    if k == "track" and not 1 <= len(v) <= 40:
        return "Track must be 1 to 40 characters."
    if k == "milepost" and not MILEPOST_RE.match(v):
        return "Milepost must be a number such as 17 or 17.25."
    return None


def has_coords(loc: Optional[dict]) -> bool:
    lat, lon = (loc or {}).get("lat"), (loc or {}).get("lon")
    return isinstance(lat, (int, float)) and isinstance(lon, (int, float)) and math.isfinite(lat) and math.isfinite(lon) and abs(lat) <= 90 and abs(lon) <= 180


def effective_location_fields(op: Optional[dict]) -> list[str]:
    """Match packet requirements, including existing operator forms that predate the explicit setting."""
    needed = set((op or {}).get("required_location_fields") or [])
    for form in (op or {}).get("forms") or []:
        for field in form.get("fields") or []:
            source = field.get("source")
            needed.update(k for k, _ in LOC_FIELDS if source == f"repair.{k}")
    return [k for k, _ in LOC_FIELDS if k in needed]


def required_location_missing(r: dict, op: Optional[dict]) -> list[str]:
    """Use the same operator and form requirements before Finish, issuing and delivery."""
    req = effective_location_fields(op)
    errors = []
    for k, label in LOC_FIELDS:
        if k in req:
            value = (r.get(k) or "").strip()
            error = loc_field_error(k, value) if value else f"{label} missing."
            if error:
                errors.append(error)
    return errors


def finish_blockers(r: dict, op: Optional[dict]) -> list[str]:
    """Only facts the foreman must supply before the completion record becomes immutable."""
    errors = ([] if op else [NO_OPERATOR]) + required_location_missing(r, op)
    if not (r.get("po") or "").strip():
        errors.append("Contract or PO reference missing.")
    if not has_coords(r.get("location")):
        rr, mp = (r.get("railroad") or "").strip(), (r.get("milepost") or "").strip()
        if not rr or not mp:
            # one message for the location rule; operator-required "Railroad missing." / "Milepost missing." are not repeated
            if not any(e in errors for e in ("Railroad missing.", "Milepost missing.")) or (rr and not mp) or (mp and not rr):
                errors.append("Location missing. Add a pin or coordinates, or railroad/subdivision and milepost.")
        for k, value in (("railroad", rr), ("milepost", mp)):
            error = loc_field_error(k, value) if value else None
            if error and error not in errors:
                errors.append(error)
    if not _valid_date(r.get("completion_date")):
        errors.append("Completion date missing or not valid.")
    if not r.get("work"):
        errors.append("No actual work recorded.")
    for item in r.get("work") or []:
        try:
            quantity = Decimal(str(item.get("quantity", "")))
            valid = quantity.is_finite() and quantity > 0
        except Exception:
            valid = False
        if not valid or not (item.get("description") or "").strip() or not (item.get("unit") or "").strip():
            errors.append("Each work item needs a description, a positive finite quantity and a unit.")
            break
    return errors


async def packet_blockers(r: dict, op: Optional[dict], f: dict) -> list[str]:
    """Everything the issued packet needs. The same list blocks issuing AND (again, at submit time) invoice submission."""
    b = [] if op else [NO_OPERATOR]
    b += required_location_missing(r, op)
    if not has_coords(r.get("location")) and not ((r.get("railroad") or "").strip() and (r.get("milepost") or "").strip()):
        b.append("Location missing. Add coordinates, or railroad and milepost.")
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
                if fl.get("required", True) and (ctx.get(fl.get("source")) is None or not str(ctx.get(fl.get("source"))).strip()):
                    b.append(f"{fm['name']}: {fl['label']} not set.")
            pdf = await db.operator_form_pdfs.find_one({"workspace_id": r["workspace_id"], "operator_id": op["uuid"], "form_id": fm["uuid"]})
            if pdf:
                try:
                    _, errors = _pdf_values(fm, _pdf_fields(pdf["pdf"]), ctx)
                    b.extend(f"{fm['name']}: {e}" for e in errors)
                except Exception:
                    b.append(f"{fm['name']}: the operator's PDF could not be read.")
            elif any(fl.get("pdf_field") for fl in fm.get("fields", [])):
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
    if op:
        try:
            money.dec(op.get("tax_rate", "0"), "tax_rate", nonneg=True)
        except money.MoneyError as e:
            inv.append(f"Operator tax rate is invalid: {e}")
    if op and op.get("rates_require_confirmation") and not await db.operator_rate_confirmations.find_one(
            {"operator_id": op["uuid"], "po": (r.get("po") or "").strip(), "rates_sha": rates_sha(op)}, {"_id": 1}):
        inv.append(f"Confirm these {op.get('rates_label') or 'rates'} apply to this contract/PO")
    if op and op.get("billing_model") == "progress_payments":
        inv.append(f"{op.get('short_name') or op['name']} is billed by progress-payment packet for the contract/PO, not per repair.")
    sub = []
    if not r.get("packet"):
        sub.append("Documents not issued. Issue the report and forms first.")
    elif not packet and r["packet"]["fingerprint"] != (await _fingerprint(r, op, f, _tpl(r)))[0]:
        sub.append("Documents changed after issuing. Issue them again.")
    if ((op or {}).get("channel") or {}).get("type") == "email" and r.get("packet") and await db.repair_documents.find_one(
            {"uuid": {"$in": r["packet"]["documents"]}, "pdf": {"$exists": True}}, {"_id": 1}):
        sub.append(PDF_EMAIL_UNSUPPORTED)
    invoice = await db.repair_invoices.find_one({"repair_id": r["uuid"]})
    if invoice and not invoice_current(invoice, r, op):
        sub.append("Invoice is out of date. Build it again.")
    sub += await channel_blockers(op, r["workspace_id"], user)
    seen = set()
    submit = [x for x in packet + inv + sub if not (x in seen or seen.add(x))]
    return {"report": packet, "invoice": inv, "submit": submit}


def invoice_current(invoice: dict, r: dict, op: Optional[dict]) -> bool:
    """Compare billed facts, not just the approval timestamp; legacy invoices need no migration."""
    if not op or not r.get("approved_work"):
        return False
    lines, errors = invoice_lines(r, op)
    if errors:
        return False
    try:
        money.dec(op.get("tax_rate", "0"), "tax_rate", nonneg=True)
        expected = {"operator_id": op["uuid"], "operator_name": op["name"], "po": r.get("po"),
                    "lines": lines, "totals": money.totals(lines, op.get("tax_rate", "0")),
                    "approved_work_at": r["approved_work"].get("approved_at")}
    except (ArithmeticError, ValueError, TypeError):
        return False
    return all(invoice.get(k) == v for k, v in expected.items())


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
PDF_EMAIL_UNSUPPORTED = ("The current email integration does not send filled PDF attachments. Download the filled PDFs and use the operator's approved document-delivery channel; this app cannot confirm that delivery.")


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
    if any(did not in docs for did in packet["documents"]):
        raise ChannelError("An issued document is missing. Reissue the packet before submitting.")
    if any("pdf" in d for d in docs.values()):
        raise ChannelError(PDF_EMAIL_UNSUPPORTED)
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
    for item in (cur or {}).get("office_location_fields", []):
        if item["field"] in data and (not data[item["field"]] or item.get("while_open")):
            data[item["field"]] = cur.get(item["field"])  # office value kept over an empty or older phone value
    if cur and cur.get("completion"):
        office = {x["field"] for x in cur.get("office_location_fields", [])}  # added later by the office: an empty phone replay still matches
        same = all(cur.get(k) == v for k, v in data.items() if k != "work" and not (k in office and not v)) \
            and [w["uuid"] for w in cur["work"]] == [w["uuid"] for w in data["work"]]
        if same:
            return clean(cur)  # replay of the finished repair
        raise HTTPException(409, {"code": "finished", "message": "Repair is finished. Changes are locked."})
    upd = {**data, "visit_id": visit_id, "site_id": visit["site_id"], "workspace_id": user["workspace_id"], "updated_at": iso(), "updated_by": user["uuid"]}
    if cur and cur.get("approved_work") and [w for w in cur["work"]] != data["work"]:
        upd["approved_work"] = None  # work changed: approval must be redone
    if body.finish:
        candidate = {**(cur or {}), **upd}
        op = await operator_for(candidate)
        blocked = finish_blockers(candidate, op)
        if blocked:
            raise HTTPException(409, {"code": "finish_blocked", "message": "Repair remains open. Complete these items before finishing.",
                                      "blockers": blocked, "operator": {"uuid": (op or {}).get("uuid"),
                                      "name": (op or {}).get("short_name") or (op or {}).get("name") or "The operator",
                                      "required_location_fields": effective_location_fields(op)}})
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
    return [{"uuid": o["uuid"], "name": o["name"], "short_name": o.get("short_name"), "required_location_fields": effective_location_fields(o), "location_requirements_version": 1,
             "rate_items": [{"key": k, "description": v.get("description") or k, "unit": v.get("unit")} for k, v in (o.get("rates") or {}).items()]}
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
    facts = await findings(r)
    ctx = _context(r, op, facts)
    pdf_ids = {x["form_id"] async for x in db.operator_form_pdfs.find({"workspace_id": r["workspace_id"], "operator_id": (op or {}).get("uuid")}, {"form_id": 1})}
    fields = [{"source": fl.get("source"), "label": fl["label"], "form_name": fm["name"], "value": ctx.get(fl.get("source")),
               "editable": _manual_source(fl.get("source")), "required": fl.get("required", True)}
              for fm in (op or {}).get("forms", []) for fl in fm.get("fields", [])]
    return {"repair": rep, "operator": {"uuid": op["uuid"], "name": op["name"], "forms": [{"uuid": f["uuid"], "name": f["name"], "has_pdf": f["uuid"] in pdf_ids} for f in op.get("forms", [])],
                                         "channel": ch, "channel_label": TEST_DELIVERY if ch == "stub" else ch,
                                         "destination": chd.get("destination") if user["role"] in ("estimator", "admin") else None,
                                         "recipient_label": chd.get("recipient_label"), "contact_name": op.get("contact_name") or NOT_SET,
                                         "rates_source": op.get("rates_source") or NOT_SET} if op else None,
            "findings": facts, "form_fields": fields, "blockers": b, "documents": docs,
            "document_status": "Issued" if docs and not any("changed after issuing" in x for x in b["submit"]) else "Draft",
            "invoice": clean(inv) if inv else None, "submission": clean(sub) if sub else None,
            "invoice_status": (sub or {}).get("status") or ("Draft" if inv else None),
            "delivery_label": TEST_DELIVERY if (sub or {}).get("test_delivery") else None,
            "documents_model": await _documents_model(r, op, b, docs, user),
            "work_order": await _wo_ref(r), "location": r.get("location") or await visit_location(r.get("inspection_visit_id")),
            "missing_location_fields": [k for k in effective_location_fields(op) if not (r.get(k) or "").strip()],
            "next_action": next_action(r, op, docs, inv, sub, any(x.startswith("Confirm these") for x in b["invoice"]))}


async def _wo_ref(r: dict) -> Optional[dict]:
    if not r.get("work_order_id"):
        return None
    w = await db.work_orders.find_one({"uuid": r["work_order_id"], "workspace_id": r["workspace_id"]}, {"uuid": 1, "number": 1, "engagement_id": 1})
    return {"uuid": w["uuid"], "number": w["number"], "engagement_id": w.get("engagement_id")} if w else None


def next_action(r: dict, op: Optional[dict], docs: list, inv: Optional[dict], sub: Optional[dict], rates_pending: bool = False) -> str:
    """REQ-1615: the one next required step, in workflow order. Never implies an approval that was not recorded."""
    if not r.get("completion"):
        return "Foreman: record the actual work on the phone and tap Finish repair."
    if not r.get("approved_work"):
        return "Office: review the actual work and tap Approve actual work."
    missing = signoffs_missing(r, op)
    if missing:
        return f"Office: record the sign-off for {', '.join(missing)}."
    if not docs:
        return "Office: issue the report and forms."
    if not inv and rates_pending:
        return "Office: confirm the rates for this PO, then build the invoice."
    if not inv:
        return "Office: build the invoice."
    if not sub or sub.get("status") != "Sent":
        return "Office: submit the invoice."
    return "Done: invoice sent and acknowledged."


# ---------------- Phase 16: work order -> repair ----------------
class StartRepairIn(BaseModel):
    operator_id: str = Field(min_length=1, max_length=80)
    po: Optional[str] = Field(None, max_length=80)


@router.post("/work-orders/{wid}/start-repair", tags=["repairs"])
async def start_repair(wid: str, body: StartRepairIn, user=Depends(staff)):
    """REQ-1612/1613: one repair per work order (unique index on work_order_id). A repeat tap or retry returns the existing
    repair. The repair keeps work_order_id, engagement_id and the inspection location; the foreman of the inspection gets it."""
    w = await db.work_orders.find_one({"uuid": wid, "workspace_id": user["workspace_id"]})
    if not w:
        raise HTTPException(404, "Not found")
    existing = await db.repairs.find_one({"work_order_id": wid})
    if existing:
        return {"repair": clean(existing), "created": False}
    if not (body.po or "").strip():
        raise HTTPException(422, {"code": "po_required", "message": "Enter the contract or PO reference before starting the repair."})
    pv = await db.proposal_versions.find_one({"uuid": w.get("accepted_version_id"), "workspace_id": user["workspace_id"]})
    if not pv or pv.get("status") != "Accepted":
        raise HTTPException(409, {"code": "not_accepted", "message": "This work order is not from an accepted proposal."})
    op = await db.operators.find_one({"uuid": body.operator_id, "workspace_id": user["workspace_id"]})
    if not op:
        raise HTTPException(404, "Not found")
    insp = await db.visits.find_one({"uuid": pv["visit_id"], "workspace_id": user["workspace_id"]})
    if not insp:
        raise HTTPException(404, "Not found")
    loc = await visit_location(insp["uuid"])
    vid = f"wo-repair-{wid}"
    title = f"Repair - {w['number']}"
    await db.visits.update_one({"uuid": vid}, {"$setOnInsert": {
        "uuid": vid, "site_id": insp["site_id"], "track_id": insp.get("track_id"), "title": title, "processing_permission": "Policy",
        "coverage_note": None, "started_at": iso(), "workspace_id": user["workspace_id"], "customer_id": insp.get("customer_id"),
        "foreman_id": insp["foreman_id"], "status": "Draft", "answers": {}, "urgent_concern": None, "location_visit_id": insp["uuid"],
        "work_order_id": wid, "created_at": iso(), "created_by": user["uuid"], "updated_at": iso(), "updated_by": user["uuid"], "revision": 1}}, upsert=True)
    doc = {"uuid": f"rep-{vid}", "visit_id": vid, "site_id": insp["site_id"], "workspace_id": user["workspace_id"], "authorized": True,
           "work_order_id": wid, "engagement_id": w["engagement_id"], "accepted_version_id": pv["uuid"], "inspection_visit_id": insp["uuid"],
           "location": loc, "operator_id": op["uuid"], "operator_name": op["name"], "po": (body.po or "").strip() or None,
           "railroad": (loc or {}).get("railroad"), "track": None, "milepost": (loc or {}).get("milepost"), "work": [], "completion_date": None,
           "signoffs": [], "revision": 1, "created_at": iso(), "created_by": user["uuid"], "updated_at": iso(), "updated_by": user["uuid"]}
    try:
        await db.repairs.insert_one(doc)
        created = True
    except DuplicateKeyError:  # concurrent tap / retry: the first insert won
        created = False
    rep = await db.repairs.find_one({"work_order_id": wid})
    if loc:
        await db.locations.update_one({"uuid": f"repair-loc-{rep['visit_id']}"}, {"$setOnInsert": {
            "uuid": f"repair-loc-{rep['visit_id']}", "workspace_id": user["workspace_id"], "visit_id": rep["visit_id"], "role": "approximate_defect",
            "source": "manual", "lat": loc["lat"], "lon": loc["lon"], "label": "Repair location (from the inspection)",
            "railway": {"railroad": loc.get("railroad"), "subdivision": loc.get("subdivision"), "milepost": {"text": loc["milepost"]} if loc.get("milepost") else None},
            "from_location_id": loc["location_id"], "revision": 1, "history": [], "created_at": iso()}}, upsert=True)
    await db.work_orders.update_one({"uuid": wid, "repair_id": {"$exists": False}}, {"$set": {"repair_id": rep["uuid"], "repair_visit_id": rep["visit_id"]}})
    if created:
        await audit(user, user["workspace_id"], "repair.started_from_work_order", "repair", rep["uuid"], {"work_order_id": wid})
    return {"repair": clean(rep), "created": created}


@router.get("/repairs-assigned", tags=["repairs"])
async def assigned_repairs(user=Depends(require_role("foreman"))):
    """Repairs started in the office for this foreman's inspections, so the phone can open them (Open repair, Capture, Finish)."""
    out = []
    async for r in db.repairs.find({"workspace_id": user["workspace_id"], "work_order_id": {"$type": "string"}}):
        v = await db.visits.find_one({"uuid": r["visit_id"], "foreman_id": user["uuid"]})
        if not v:
            continue
        site = await db.sites.find_one({"uuid": v["site_id"]}, {"name": 1})
        out.append({"repair": clean(r), "visit": {k: v.get(k) for k in ("uuid", "site_id", "title", "status", "revision", "processing_permission", "created_at")},
                    "site_name": (site or {}).get("name"), "work_order": await _wo_ref(r)})
    return out


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
    snap = {"items": r["work"], "approved_by": user["uuid"], "approved_by_name": user.get("name"), "approved_at": iso(), "repair_revision": r["revision"]}
    await db.repairs.update_one({"uuid": r["uuid"], "revision": r["revision"]}, {"$set": {"approved_work": snap}})
    return clean(await db.repairs.find_one({"uuid": r["uuid"]}))


class LocationFieldsIn(BaseModel):
    railroad: Optional[str] = Field(None, max_length=120)
    track: Optional[str] = Field(None, max_length=40)
    milepost: Optional[str] = Field(None, max_length=40)


class POReferenceIn(BaseModel):
    po: str = Field(min_length=1, max_length=80)


@router.put("/repairs/{visit_id}/po-reference", tags=["repairs"])
async def add_po_reference(visit_id: str, body: POReferenceIn, user=Depends(staff)):
    r = await get_repair(user, visit_id)
    value = body.po.strip()
    if not value:
        raise HTTPException(422, "Enter the contract or PO reference.")
    if (r.get("po") or "").strip():
        if r["po"].strip() == value:
            return clean(r)
        raise HTTPException(409, "The recorded PO reference cannot be replaced here.")
    if await db.invoice_submissions.find_one({"invoice_id": f"inv-{r['uuid']}", "status": {"$in": ["Sent", "Submitting", "Unknown"]}}, {"_id": 1}):
        raise HTTPException(409, "The invoice has been submitted. Its PO reference is locked.")
    rec = {"field": "po", "value": value, "entered_by": user["uuid"], "entered_by_name": user.get("name"), "entered_at": iso()}
    changed = await db.repairs.update_one({"uuid": r["uuid"], "po": r.get("po")},
                                         {"$set": {"po": value}, "$push": {"office_location_fields": rec}})
    if not changed.modified_count:
        raise HTTPException(409, "Changed elsewhere. Reload.")
    await audit(user, user["workspace_id"], "repair.po_reference_added", "repair", r["uuid"], {"before": None, "after": value})
    return clean(await db.repairs.find_one({"uuid": r["uuid"]}))


@router.put("/repairs/{visit_id}/location-fields", tags=["repairs"])
async def add_location_fields(visit_id: str, body: LocationFieldsIn, user=Depends(staff)):
    """Location details. While the repair is OPEN (incl. after a rejected Finish), office users may add or correct railroad/track/
    milepost so Finish can be retried (REQ-1730/1731); values are recorded per field so a phone replay with empty values keeps them.
    After Finish: fills EMPTY operator-required fields only; work, completion, approval and revision stay locked. Always audited."""
    r = await get_repair(user, visit_id)
    is_open = not r.get("completion")
    req = effective_location_fields(await operator_for(r))
    vals = {k: v.strip() for k, v in body.model_dump().items() if v and v.strip()}
    if not vals:
        raise HTTPException(422, "Enter a value.")
    for k, v in vals.items():
        if not is_open and k not in req:
            raise HTTPException(422, f"{k.capitalize()} is not required by this operator.")
        if not is_open and (r.get(k) or "").strip():
            raise HTTPException(409, {"code": "already_set", "message": f"{k.capitalize()} is already recorded. It cannot be changed here."})
        err = loc_field_error(k, v)
        if err:
            raise HTTPException(422, err)
    rec = [{"field": k, "value": v, "previous": r.get(k), "entered_by": user["uuid"], "entered_by_name": user.get("name"), "entered_at": iso(),
            "while_open": is_open} for k, v in vals.items()]
    q = {"uuid": r["uuid"], "completion": None} if is_open else {"uuid": r["uuid"], **{k: {"$in": [None, ""]} for k in vals}}
    if is_open:
        q = {"uuid": r["uuid"], "$or": [{"completion": None}, {"completion": {"$exists": False}}]}
    res = await db.repairs.update_one(q, {"$set": vals, "$push": {"office_location_fields": {"$each": rec}}})
    if not res.modified_count:
        raise HTTPException(409, {"code": "already_set", "message": "Changed elsewhere. Reload."})
    await audit(user, user["workspace_id"], "repair.location_fields_added", "repair", r["uuid"], {"fields": vals})
    return clean(await db.repairs.find_one({"uuid": r["uuid"]}))


@router.post("/repairs/{visit_id}/signoffs", tags=["repairs"])
async def add_signoff(visit_id: str, body: SignoffIn, user=Depends(staff)):
    r = await get_repair(user, visit_id)
    s = {"role": body.role.strip(), "name": body.name.strip(), "recorded_by": user["uuid"], "recorded_by_name": user.get("name"), "recorded_at": iso(),
         "repair_revision": r.get("revision"), "signature": None}  # typed name only: "Name (not a signature)"
    if not s["role"] or not s["name"]:
        raise HTTPException(422, "Enter the signer's role and name.")
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
    loc = r.get("location") or {}
    if has_coords(loc):  # extra sources only; existing form renders are unchanged unless a form field names them
        ctx.update({"location.lat": f"{loc['lat']:.6f}", "location.lon": f"{loc['lon']:.6f}", "location.source": loc.get("method_label"),
                    "location.accuracy_m": loc.get("accuracy_m"), "location.fixed_at": loc.get("fixed_at"), "location.status": _loc_status(loc)})
    for role, s in sig.items():
        ctx[f"signoff.{role}.name"], ctx[f"signoff.{role}.at"] = s.get("name"), s.get("recorded_at")
    for k, v in (r.get("form_values") or {}).items():
        if k not in ctx and _manual_source(k) and isinstance(v, dict):
            ctx[k] = v.get("value")
    return ctx


DERIVED = {"repair.", "completion.", "work.", "findings.", "evidence.", "signoff.", "location."}


def _manual_source(source) -> bool:
    return isinstance(source, str) and bool(re.fullmatch(r"[a-z0-9_.]{1,60}", source)) and not any(source.startswith(p) for p in DERIVED)


DOC_TEMPLATE = 2  # 2 adds the location section (coordinates + provenance). Issued packets keep the template they were issued with.


def _tpl(r: dict) -> int:
    return (r.get("packet") or {}).get("template", 1) if r.get("packet") else DOC_TEMPLATE


def _loc_status(loc: dict) -> str:
    return "Confirmed" if loc.get("method") in ("milepost", "milepost_pin") else "Approximate"


def _location_html(r: dict) -> str:
    loc = r.get("location")
    if not has_coords(loc):
        return f"<h2>Location</h2><p>Coordinates: {NOT_SET}</p>"
    acc = loc.get("accuracy_m")
    return (f"<h2>Location</h2><table><tr><th>Coordinates (WGS84)</th><td>{loc['lat']:.6f}, {loc['lon']:.6f}</td></tr>"
            f"<tr><th>Source</th><td>{_e(loc.get('method_label'))} ({_e(loc.get('source'))})</td></tr>"
            f"<tr><th>Accuracy</th><td>{_e(f'{acc:.0f} m' if isinstance(acc, (int, float)) else None)}</td></tr>"
            f"<tr><th>Fix time</th><td>{_e(loc.get('fixed_at'))}</td></tr><tr><th>Recorded</th><td>{_e(loc.get('recorded_at'))}</td></tr>"
            f"<tr><th>Status</th><td>{_loc_status(loc)}</td></tr><tr><th>Location id</th><td>{_e(loc.get('location_id'))}</td></tr></table>")


def _render(r, op, f, kind: str, form_id: Optional[str], draft: bool, tpl: int = DOC_TEMPLATE) -> tuple[str, str]:
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
            f"Evidence: {f['evidence']['photo']} photo(s), {f['evidence']['video']} video(s)</p>{_location_html(r) if tpl >= 2 else ''}{summ}"
            f"<h2>Actual work</h2><table><tr><th>Type</th><th>Item</th><th>Quantity</th></tr>{work or '<tr><td colspan=3>' + NOT_SET + '</td></tr>'}</table>"
            f"<h2>Defects recorded by the crew</h2><ul>{man}</ul><h2>Photo and video check results</h2><ul>{ai}</ul>"
            f"<h2>Evidence references</h2><table><tr><th>Type</th><th>Evidence id</th><th>SHA-256</th><th>Captured</th></tr>{ev}</table>"
            f"<h2>Sign-offs</h2><table><tr><th>Role</th><th>Name</th><th>Recorded</th></tr>{sig}{req}</table>")
    return "Repair record", f"<!doctype html><html><head><meta charset=utf-8><title>Repair record {_e(r['uuid'])}</title><style>{CSS}</style></head><body>{body}</body></html>"


def _packet_docs(r, op, f) -> list:
    return [("report", None)] + [("form", x["uuid"]) for x in (op or {}).get("forms", [])]


async def _fingerprint(r, op, f, tpl: int = DOC_TEMPLATE) -> tuple[str, list]:
    """Hash of the final (non-draft) packet renders; submit compares it with the issued packet."""
    pages = [(kind, fid) + _render(r, op, f, kind, fid, False, tpl) for kind, fid in _packet_docs(r, op, f)]
    shas, sources = [], []
    for kind, fid, name, page in pages:
        payload = page.encode()
        pdf = None
        if fid:
            pdf = await db.operator_form_pdfs.find_one({"workspace_id": r["workspace_id"], "operator_id": (op or {}).get("uuid"), "form_id": fid})
            if pdf:
                form = next(x for x in op["forms"] if x["uuid"] == fid)
                identity = {"pdf_sha256": hashlib.sha256(pdf["pdf"]).hexdigest(), "fields": form.get("fields", [])}
                payload += b"\nPDF:" + json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
        shas.append(hashlib.sha256(payload).hexdigest())
        sources.append(pdf)
    return hashlib.sha256("|".join(shas).encode()).hexdigest(), [p + (s, src) for p, s, src in zip(pages, shas, sources)]


async def _submitted_packet(r: dict) -> Optional[dict]:
    sub = await db.invoice_submissions.find_one({"invoice_id": f"inv-{r['uuid']}", "status": {"$in": ["Sent", "Submitting", "Unknown"]}})
    if not sub:
        return None
    packet = sub.get("packet")
    if not packet or not packet.get("documents"):
        raise HTTPException(409, "The submitted document snapshot is missing. It cannot be recreated from current records.")
    return packet


async def _submitted_document(r: dict, kind: str, form_id: Optional[str]) -> Optional[dict]:
    packet = await _submitted_packet(r)
    if packet is None:
        return None
    doc = await db.repair_documents.find_one({"uuid": {"$in": packet["documents"]}, "repair_id": r["uuid"], "kind": kind, "form_id": form_id})
    if not doc:
        raise HTTPException(404, "This document is not in the submitted packet.")
    return doc


async def _doc_html(r, user, kind: str, form_id: Optional[str]) -> tuple[str, str]:
    doc = await _submitted_document(r, kind, form_id)
    if doc is not None:
        return doc["name"], doc["html"]
    op = await operator_for(r)
    f = await findings(r)
    return _render(r, op, f, kind, form_id, bool(await packet_blockers(r, op, f)), _tpl(r))


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
    op = await operator_for(r)
    allowed = {fl.get("source") for fm in (op or {}).get("forms", []) for fl in fm.get("fields", []) if _manual_source(fl.get("source"))}
    fv = {k: v for k, v in (r.get("form_values") or {}).items() if isinstance(v, dict) and "value" in v}  # keys contain dots: store as one map
    for k, v in body.values.items():
        if k not in allowed or len(v) > 200:
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


def _pdf_values(form: dict, fields: dict, ctx: dict) -> tuple[dict, list[str]]:
    """Map facts to actual AcroForm types; a required signature is never fabricated."""
    from pypdf.generic import NullObject
    values, errors, mapped = {}, [], set()
    for fl in form.get("fields", []):
        name = fl.get("pdf_field")
        if not name:
            continue
        if name in mapped:
            errors.append(f"PDF field {name} is mapped more than once.")
            continue
        mapped.add(name)
        field = fields.get(name)
        if field is None:
            errors.append(f"PDF field {name} does not exist. Correct the form mapping.")
            continue
        kind, value = field.get("/FT"), ctx.get(fl.get("source"))
        if kind == "/Sig":
            if fl.get("required", True) or int(field.get("/Ff", 0)) & 2:
                errors.append(f"PDF field {name} requires the operator's signing process.")
            continue
        if kind not in ("/Tx", "/Btn", "/Ch"):
            errors.append(f"PDF field {name} has an unsupported field type.")
            continue
        text = "" if value is None else str(value).strip()
        if not text:
            if fl.get("required", True) or int(field.get("/Ff", 0)) & 2:
                errors.append(f"PDF field {name} needs a recorded value.")
            else:
                values[name] = "/Off" if kind == "/Btn" else ""
            continue
        if kind == "/Tx":
            if field.get("/MaxLen") and len(text) > int(field["/MaxLen"]):
                errors.append(f"PDF field {name} exceeds its {field['/MaxLen']}-character limit.")
            else:
                values[name] = text
        elif kind == "/Btn":
            states = [str(s) for s in field.get("/_States_", [])]
            on = [s for s in states if s != "/Off"]
            picked = text if text.startswith("/") else "/" + text
            if text.lower() in ("false", "no", "off", "0", "unchecked"):
                picked = "/Off"
            elif text.lower() in ("true", "yes", "on", "1", "checked") and len(on) == 1:
                picked = on[0]
            if picked not in states:
                errors.append(f"PDF field {name} needs one of: {', '.join(states)}.")
            else:
                values[name] = picked
        else:
            options = {str(o[1] if isinstance(o, (list, tuple)) else o): str(o[0] if isinstance(o, (list, tuple)) else o)
                       for o in field.get("/Opt", [])}
            if text in options:
                values[name] = options[text]
            elif text in options.values() or int(field.get("/Ff", 0)) & (1 << 18):
                values[name] = text
            else:
                errors.append(f"PDF field {name} needs a listed choice.")
    for name, field in fields.items():
        value, kind = field.get("/V"), field.get("/FT")
        if hasattr(value, "get_object"):
            value = value.get_object()
        populated = value is not None and not isinstance(value, NullObject) and bool(str(value).strip()) and value != []
        if kind == "/Sig" and value is not None and not isinstance(value, NullObject):
            errors.append(f"PDF field {name} already contains a signature. Upload the unsigned blank original.")
        elif name not in mapped and kind in ("/Tx", "/Ch", "/Btn") and populated and not (kind == "/Btn" and value == "/Off"):
            errors.append(f"PDF field {name} contains an unmapped value. Map it to the current record or upload a blank template.")
        if int(field.get("/Ff", 0)) & 2 and name not in mapped:
            errors.append(f"Required PDF field {name} is not mapped to a recorded value or signing step.")
    return values, errors


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


async def _filled_pdf(r, user, form_id: str, source=None, source_loaded: bool = False, operator=None, facts=None) -> Optional[bytes]:
    from pypdf import PdfReader, PdfWriter
    op = operator if operator is not None else await operator_for(r)
    form = next((x for x in (op or {}).get("forms", []) if x["uuid"] == form_id), None)
    src = source if source_loaded else (await db.operator_form_pdfs.find_one({"workspace_id": r["workspace_id"], "operator_id": (op or {}).get("uuid"), "form_id": form_id}) if form else None)
    if not src:
        return None
    ctx = _context(r, op, facts if facts is not None else await findings(r))
    reader = PdfReader(io.BytesIO(src["pdf"]))
    vals, errors = _pdf_values(form, reader.get_fields() or {}, ctx)
    if errors:
        raise HTTPException(409, {"code": "form_blocked", "blockers": errors})
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
    doc = await _submitted_document(r, "form", form_id)
    data = doc.get("pdf") if doc is not None else await _filled_pdf(r, user, form_id)
    if data is None:
        if doc is not None:
            raise HTTPException(404, "No PDF was included for this form in the submitted packet.")
        raise HTTPException(404, {"code": "no_pdf", "message": "No fillable PDF uploaded for this form. An admin must upload the operator's form."})
    status = "Issued" if doc is not None else ("Draft" if (await blockers(r, user))["report"] else "Ready")
    return Response(data, media_type="application/pdf", headers={"X-Document-Status": status,
                    "Content-Disposition": f'inline; filename="{form_id}-{status.lower()}.pdf"'})


@router.post("/repairs/{visit_id}/issue", tags=["repairs"])
async def issue(visit_id: str, user=Depends(staff)):
    r = await get_repair(user, visit_id)
    submitted = await _submitted_packet(r)
    if submitted is not None:
        docs = {d["uuid"]: d async for d in db.repair_documents.find({"uuid": {"$in": submitted["documents"]}, "repair_id": r["uuid"]})}
        if any(did not in docs for did in submitted["documents"]):
            raise HTTPException(409, "A submitted document is missing. The packet cannot be replaced.")
        return {"documents": [{k: docs[did][k] for k in ("uuid", "kind", "name", "sha256")} for did in submitted["documents"]], "fingerprint": submitted["fingerprint"]}
    op = await operator_for(r)
    f = await findings(r)
    b = await packet_blockers(r, op, f)
    if b:
        raise HTTPException(409, {"code": "blocked", "blockers": b})
    tpl = _tpl(r)
    fp, pages = await _fingerprint(r, op, f, tpl)
    if fp != (r.get("packet") or {}).get("fingerprint") and tpl != DOC_TEMPLATE:
        tpl = DOC_TEMPLATE
        fp, pages = await _fingerprint(r, op, f, tpl)
    out = []
    for kind, fid, name, page, sha, source in pages:
        did = f"doc-{r['uuid']}-{fid or 'report'}-{sha[:12]}"
        doc = {"uuid": did, "repair_id": r["uuid"], "kind": kind, "form_id": fid, "name": name, "html": page, "sha256": sha,
               "evidence_ids": [e["uuid"] for e in f["evidence"]["items"]], "issued_at": iso(), "issued_by": user["uuid"]}
        pdf = await _filled_pdf(r, user, fid, source=source, source_loaded=True, operator=op, facts=f) if fid else None
        if pdf:
            doc["pdf"] = pdf
            doc["pdf_source_sha256"] = hashlib.sha256(source["pdf"]).hexdigest()
        await db.repair_documents.update_one({"uuid": did}, {"$setOnInsert": doc}, upsert=True)
        out.append({k: doc[k] for k in ("uuid", "kind", "name", "sha256")})
    if (r.get("packet") or {}).get("fingerprint") != fp:
        await db.repairs.update_one({"uuid": r["uuid"]}, {"$set": {"packet": {"documents": [x["uuid"] for x in out], "fingerprint": fp, "template": tpl,
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
    if await db.invoice_submissions.find_one({"invoice_id": iid, "status": {"$in": ["Sent", "Submitting", "Unknown"]}}):
        return clean(await db.repair_invoices.find_one({"uuid": iid}))  # accepted, sending, or uncertain: never rebuilt
    lines, _ = invoice_lines(r, op)
    used = {ln["rate_key"] for ln in lines}
    snap = {k: {kk: v.get(kk) for kk in ("unit_price", "unit", "taxable", "description")} for k, v in (op.get("rates") or {}).items() if k in used}
    conf = await db.operator_rate_confirmations.find_one({"operator_id": op["uuid"], "po": r["po"], "rates_sha": rates_sha(op)})
    rc = {"ref": f"rate-confirmation:{op['uuid']}:{r['po']}:{conf['rates_sha'][:12]}", "rates_sha": conf["rates_sha"], "confirmed_by_name": conf.get("confirmed_by_name"),
          "confirmed_at": conf.get("confirmed_at")} if conf else None  # reference only: the confirmation record itself is never changed
    inv = {"uuid": iid, "repair_id": r["uuid"], "visit_id": visit_id, "workspace_id": r["workspace_id"], "operator_id": op["uuid"], "operator_name": op["name"],
           "po": r["po"], "lines": lines, "totals": money.totals(lines, op.get("tax_rate", "0")), "approved_work_at": r["approved_work"]["approved_at"],
           "work_order_id": r.get("work_order_id"), "rate_snapshot": snap, "rate_confirmation": rc, "rates_sha": rates_sha(op), "tax_rate": str(op.get("tax_rate", "0"))}
    inv["checksum"] = hashlib.sha256(json.dumps({k: inv[k] for k in ("uuid", "po", "lines", "totals", "rate_snapshot", "rate_confirmation", "tax_rate",
                                                                    "approved_work_at", "work_order_id")}, sort_keys=True, default=str).encode()).hexdigest()
    try:  # same billed facts -> same invoice and revision (repeats/concurrent clicks change nothing)
        await db.repair_invoices.update_one({"uuid": iid, "checksum": {"$ne": inv["checksum"]}}, {"$set": {**inv, "updated_at": iso()}, "$inc": {"revision": 1},
                                            "$setOnInsert": {"created_at": iso()}}, upsert=True)
    except DuplicateKeyError:
        pass
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
    extra = {"invoice_revision": inv["revision"]}
    if op.get("generic_forms"):  # issued paperwork for exactly this invoice + repair revision (stale approval/regeneration blocks)
        if ch["type"] == "email":  # the managed email API documents no attachments: never send HTML while dropping the PDFs
            raise HTTPException(409, {"code": "blocked", "blockers": [PDF_EMAIL_UNSUPPORTED]})
        snap = await db.paperwork_snapshots.find_one({"key": f"{iid}:{inv.get('revision')}:{r.get('revision')}:L{paperwork.LAYOUT_VERSION}"})
        if not snap or snap.get("invoice_checksum") != inv.get("checksum"):
            raise HTTPException(409, {"code": "blocked", "blockers": ["Issue the work order and invoice PDFs for the current approved revision before submitting."]})
        extra["attachments"] = [{"doc": k, "sha256": v["sha256"], "size": v["size"]} for k, v in snap["docs"].items() if k != "packet"]
        extra["paperwork_key"] = snap["key"]
    return await deliver(key, {"invoice_id": iid}, inv, r["packet"], ch, user, body.confirm_recipient, extra)


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
        if extra.get("paperwork_key"):  # Test channel carries the exact issued PDF bytes (from the immutable snapshot)
            snap = await db.paperwork_snapshots.find_one({"key": extra["paperwork_key"]})
            await db.channel_stub_outbox.update_one({"key": key}, {"$set": {"attachments": [
                {"doc": k, "filename": f"{k}-{inv['repair_id']}.pdf", "b64": v["b64"]} for k, v in snap["docs"].items() if k != "packet"]}})
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
    await db.repair_invoices.create_index("uuid", unique=True, name="one_invoice_uuid")  # Phase 17: concurrent generate -> one invoice
    await db.pins.create_index("visit_id", unique=True, name="one_pin_per_inspection", partialFilterExpression={"visit_id": {"$type": "string"}})  # Phase 16
    await db.repairs.create_index("work_order_id", unique=True, name="one_repair_per_work_order",
                                  partialFilterExpression={"work_order_id": {"$type": "string"}})
    await db.invoice_submissions.create_index("key", unique=True)
    await db.channel_stub_outbox.create_index("key", unique=True)
    await db.operator_rate_confirmations.create_index([("operator_id", 1), ("po", 1), ("rates_sha", 1)], unique=True)
    await db.email_sends.create_index("key")
