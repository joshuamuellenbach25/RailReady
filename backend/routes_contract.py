"""Contract-level documents for progress-payment operators (model taken from Tacoma Rail TR23-0037F; quotes in
the public bid documents). Per repair: the Repair record (routes_repair). Per contract/PO: progress-payment packets
(1-09.9, PDF p.88) and final closeout (General Release PDF p.37 + checklist PDF p.86). Closeout never blocks progress packets."""
import hashlib
import io
import json
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field

import routes_repair as RR
from core import audit, clean, db, iso, require_role

router = APIRouter(prefix="/api")
staff = RR.staff
admin = require_role("admin")
NOT_SET = RR.NOT_SET
PE_MISSING = "Project Engineer approval not recorded"
PE_STALE = "Packet changed after the Project Engineer approval. Record the approval again."
CENT = Decimal("0.01")


def cid_for(operator_id: str, po: str) -> str:
    return "ctr-" + hashlib.sha256(f"{operator_id}|{(po or '').strip()}".encode()).hexdigest()[:16]


def _d(x) -> Decimal:
    return Decimal(str(x))


def _m(x: Optional[Decimal]) -> str:
    return NOT_SET if x is None else str(x.quantize(CENT, ROUND_HALF_UP))


class ContractIn(BaseModel):
    operator_id: str
    po: str = Field(min_length=1, max_length=80)
    contract_no: Optional[str] = Field(None, max_length=80)  # "Project / Spec. #" as recorded for this contract
    contractor_legal_name: Optional[str] = Field(None, max_length=160)
    contract_date: Optional[str] = None  # YYYY-MM-DD
    retainage_pct: Optional[str] = None  # admin-entered; the spec states no rate


class PacketIn(BaseModel):
    period_start: str
    period_end: str


class EngineerIn(BaseModel):
    engineer_name: str = Field(min_length=1, max_length=120)


class CloseoutItemIn(BaseModel):
    received: bool
    note: Optional[str] = Field(None, max_length=300)


async def get_contract(user, cid: str) -> dict:
    c = await db.operator_contracts.find_one({"uuid": cid, "workspace_id": user["workspace_id"]})
    if not c:
        raise HTTPException(404, "Not found")
    return c


async def _op(c: dict) -> dict:
    return await db.operators.find_one({"uuid": c["operator_id"], "workspace_id": c["workspace_id"]})


@router.post("/operator-contracts", tags=["contracts"])
async def put_contract(body: ContractIn, user=Depends(admin)):
    op = await db.operators.find_one({"uuid": body.operator_id, "workspace_id": user["workspace_id"]})
    if not op or op.get("billing_model") != "progress_payments":
        raise HTTPException(404, "Not found")
    if body.contract_date and not RR._valid_date(body.contract_date):
        raise HTTPException(422, "Contract date must be a valid YYYY-MM-DD date.")
    if body.retainage_pct not in (None, ""):
        try:
            p = _d(body.retainage_pct)
        except InvalidOperation:
            raise HTTPException(422, "Retainage must be a percentage from 0 to 100.")
        if not (Decimal(0) <= p <= Decimal(100)):
            raise HTTPException(422, "Retainage must be a percentage from 0 to 100.")
    cid = cid_for(body.operator_id, body.po)
    vals = {k: (v.strip() if isinstance(v, str) and v.strip() else None) for k, v in body.model_dump().items()}
    await db.operator_contracts.update_one({"uuid": cid}, {"$set": {**vals, "uuid": cid, "workspace_id": user["workspace_id"], "updated_by": user["uuid"], "updated_at": iso()},
                                                           "$setOnInsert": {"created_at": iso(), "closeout_items": {}}}, upsert=True)
    await audit(user, user["workspace_id"], "contract.saved", "contract", cid, {"po": vals["po"], "retainage_pct": vals["retainage_pct"]})
    return await contract_detail(cid, user)


# ---------------- progress-payment packet ----------------
def _label(r: dict) -> str:
    return f"MP {r.get('milepost') or NOT_SET}, {(r.get('completion') or {}).get('completion_date') or NOT_SET}"


async def compute(c: dict, op: dict, p: dict) -> dict:
    """Cumulative progress estimate through period_end: approved completed quantities x confirmed unit prices,
    less retainage and the sum of prior issued packets (TR23-0037F 1-09.9, PDF p.88)."""
    start, end = p["period_start"], p["period_end"]
    reps = await db.repairs.find({"workspace_id": c["workspace_id"], "operator_id": op["uuid"], "po": c["po"]}).to_list(2000)

    def cd(r):
        return (r.get("completion") or {}).get("completion_date") or ""
    ok = [r for r in reps if r.get("completion") and r.get("approved_work") and r["approved_work"].get("repair_revision") == r.get("revision") and cd(r) <= end]
    in_period = [r for r in ok if cd(r) >= start]
    not_approved = [r for r in reps if r.get("completion") and start <= cd(r) <= end and r not in ok]
    b, agg = [], {}
    for r in sorted(ok, key=cd):
        ls, lb = RR.invoice_lines(r, op)
        b += [f"{_label(r)}: {x}" for x in lb]
        for ln in ls:
            k = (ln["rate_key"], ln["unit"], ln["unit_cost"])
            a = agg.setdefault(k, {"description": ln["description"], "unit": ln["unit"], "unit_cost": ln["unit_cost"], "q_todate": Decimal(0), "q_period": Decimal(0), "amount": Decimal(0)})
            a["q_todate"] += _d(ln["quantity"])
            a["amount"] += _d(ln["line_total"])
            if cd(r) >= start:
                a["q_period"] += _d(ln["quantity"])
    value = sum((a["amount"] for a in agg.values()), Decimal(0))
    pct = _d(c["retainage_pct"]) if c.get("retainage_pct") else None
    retainage = (value * pct / 100).quantize(CENT, ROUND_HALF_UP) if pct is not None else None
    prior = await db.progress_packets.find({"contract_id": c["uuid"], "period_end": {"$lt": start}}).sort("period_end", 1).to_list(500)
    previous = sum((_d(x["snapshot"]["amount_due"]) for x in prior if x["status"] == "Issued"), Decimal(0))
    due = value - retainage - previous if retainage is not None else None
    if pct is None:
        b.append("Retainage rate not set. An admin must enter the contract's retainage percentage.")
    if not c.get("contractor_legal_name"):
        b.append("Contractor legal name not set for this contract.")
    if op.get("rates_require_confirmation") and not await db.operator_rate_confirmations.find_one(
            {"operator_id": op["uuid"], "po": c["po"], "rates_sha": RR.rates_sha(op)}, {"_id": 1}):
        b.append(f"Confirm these {op.get('rates_label') or 'rates'} apply to this contract/PO")
    if op.get("required_signoffs") is None:
        b.append(f"Required {op.get('short_name') or op['name']} sign-offs not set")
    if not in_period:
        b.append("No approved completed work in this billing period.")
    b += [f"Repair record not issued: {_label(r)}" for r in in_period if not r.get("packet")]
    b += [f"Earlier packet {x['period_start']} to {x['period_end']} is not issued yet." for x in prior if x["status"] != "Issued"]
    lines = [{**{k: a[k] for k in ("description", "unit", "unit_cost")}, "q_period": str(a["q_period"]), "q_todate": str(a["q_todate"]), "amount_todate": _m(a["amount"])}
             for a in agg.values()]
    core = {"period_start": start, "period_end": end, "lines": lines, "value_todate": _m(value), "retainage_pct": c.get("retainage_pct"), "retainage": _m(retainage),
            "previous_payments": _m(previous), "amount_due": _m(due), "repairs": [r["uuid"] for r in in_period],
            "repair_documents": [d for r in in_period for d in (r.get("packet") or {}).get("documents", [])], "not_approved": [_label(r) for r in not_approved]}
    fp = hashlib.sha256(json.dumps(core, sort_keys=True).encode()).hexdigest()
    ap = p.get("engineer_approval")
    gate = [PE_MISSING] if not ap else ([PE_STALE] if ap.get("fingerprint") != fp else [])
    return {**core, "fingerprint": fp, "content_blockers": b, "blockers": b + gate}


def render_packet(c: dict, op: dict, p: dict, k: dict, company: str, draft: bool) -> str:
    e = RR._e
    rows = "".join(f"<tr><td>{e(l['description'])}</td><td>{e(l['unit'])}</td><td class=n>${e(l['unit_cost'])}</td><td class=n>{e(l['q_period'])}</td>"
                   f"<td class=n>{e(l['q_todate'])}</td><td class=n>${e(l['amount_todate'])}</td></tr>" for l in k["lines"]) or f"<tr><td colspan=6>{NOT_SET}</td></tr>"
    ap = p.get("engineer_approval") or {}
    na = "".join(f"<li>{e(x)}</li>" for x in k["not_approved"])
    pct = f"{k['retainage_pct']}%" if k["retainage_pct"] else NOT_SET
    return (f"<!doctype html><html><head><meta charset=utf-8><title>Progress payment request</title><style>{RR.CSS}</style></head><body>"
            f"<h1>Progress payment request</h1>{'<p class=draft>Draft. Not issued.</p>' if draft else ''}"
            f"<p>Contractor: {e(c.get('contractor_legal_name'))} ({e(company)})<br/>Operator: {e(op['name'])}<br/>Contract/PO: {e(c['po'])} &middot; Project/Spec. #: {e(c.get('contract_no'))}<br/>"
            f"Billing period: {e(k['period_start'])} to {e(k['period_end'])}</p>"
            f"<h2>Approved completed work x contract unit prices</h2><table><tr><th>Item</th><th>Unit</th><th>Unit price</th><th>This period</th><th>To date</th><th>Amount to date</th></tr>{rows}</table>"
            f"<table><tr><th>Value of completed work to date</th><td class=n>${e(k['value_todate'])}</td></tr>"
            f"<tr><th>Less retainage ({e(pct)})</th><td class=n>${e(k['retainage'])}</td></tr>"
            f"<tr><th>Less previous progress payments (sum of prior issued packets)</th><td class=n>${e(k['previous_payments'])}</td></tr>"
            f"<tr><th>Amount due this period</th><td class=n><strong>${e(k['amount_due'])}</strong></td></tr></table>"
            f"<p class=note>Unit-price work only. Lump sums, materials on hand, change orders and funds withheld by the operator are not recorded here. "
            f"Progress estimates are prepared by the Engineer and are tentative.</p>"
            f"{'<h2>Finished but not approved (not included)</h2><ul>' + na + '</ul>' if na else ''}"
            f"<h2>Repair records included</h2><ul>{''.join(f'<li>{e(x)}</li>' for x in k['repair_documents']) or '<li>' + NOT_SET + '</li>'}</ul>"
            f"<h2>Project Engineer approval</h2><p>Name: {e(ap.get('engineer_name'))} &middot; Recorded by: {e(ap.get('recorded_by_name'))} at {e(ap.get('recorded_at'))}</p>"
            f"</body></html>")


async def _company(ws_id: str) -> str:
    w = await db.workspaces.find_one({"uuid": ws_id}, {"name": 1})
    return (w or {}).get("name") or NOT_SET


async def _packet(user, cid: str, pid: str):
    c = await get_contract(user, cid)
    p = await db.progress_packets.find_one({"uuid": pid, "contract_id": cid})
    if not p:
        raise HTTPException(404, "Not found")
    return c, await _op(c), p


@router.post("/operator-contracts/{cid}/packets", tags=["contracts"])
async def new_packet(cid: str, body: PacketIn, user=Depends(staff)):
    c = await get_contract(user, cid)
    s, e = body.period_start, body.period_end
    if not (RR._valid_date(s) and RR._valid_date(e)) or s > e:
        raise HTTPException(422, "Billing period needs a valid start and end date (start on or before end).")
    if await db.progress_packets.find_one({"contract_id": cid, "period_start": {"$lte": e}, "period_end": {"$gte": s}}):
        raise HTTPException(409, "This billing period overlaps another packet for this contract/PO.")
    n = await db.progress_packets.count_documents({"contract_id": cid})
    pid = f"pp-{cid}-{s}"
    await db.progress_packets.insert_one({"uuid": pid, "contract_id": cid, "workspace_id": c["workspace_id"], "seq": n + 1, "period_start": s, "period_end": e,
                                          "status": "Draft", "created_by": user["uuid"], "created_at": iso()})
    return await packet_detail(cid, pid, user)


@router.get("/operator-contracts/{cid}/packets/{pid}", tags=["contracts"])
async def packet_detail(cid: str, pid: str, user=Depends(staff)):
    c, op, p = await _packet(user, cid, pid)
    sub = await db.invoice_submissions.find_one({"key": f"submit-{pid}"})
    if p["status"] == "Issued":
        k = p["snapshot"]
        blockers = []
    else:
        k = await compute(c, op, p)
        blockers = k["blockers"]
    out = {**clean(p), "computed": {x: k[x] for x in k if x not in ("html",)}, "blockers": blockers,
           "submit_blockers": await RR.channel_blockers(op, c["workspace_id"], user) + ([] if p["status"] == "Issued" else ["Packet not issued yet."]),
           "submission": clean(sub) if sub else None, "delivery_label": RR.TEST_DELIVERY if (sub or {}).get("test_delivery") else None}
    out.pop("snapshot", None)
    return out


@router.get("/operator-contracts/{cid}/packets/{pid}/print", response_class=HTMLResponse, tags=["contracts"])
async def packet_print(cid: str, pid: str, user=Depends(staff)):
    c, op, p = await _packet(user, cid, pid)
    if p["status"] == "Issued":
        return p["snapshot"]["html"]
    return render_packet(c, op, p, await compute(c, op, p), await _company(c["workspace_id"]), True)


@router.post("/operator-contracts/{cid}/packets/{pid}/engineer-approval", tags=["contracts"])
async def engineer_approval(cid: str, pid: str, body: EngineerIn, user=Depends(admin)):
    """Records that the Project Engineer approved this packet's content (name as given, who recorded it, when)."""
    c, op, p = await _packet(user, cid, pid)
    if p["status"] == "Issued":
        raise HTTPException(409, "Packet already issued.")
    k = await compute(c, op, p)
    if k["content_blockers"]:
        raise HTTPException(409, {"code": "blocked", "blockers": k["content_blockers"]})
    ap = {"engineer_name": body.engineer_name.strip(), "recorded_by": user["uuid"], "recorded_by_name": user.get("name"), "recorded_at": iso(), "fingerprint": k["fingerprint"]}
    await db.progress_packets.update_one({"uuid": pid}, {"$set": {"engineer_approval": ap}})
    await audit(user, user["workspace_id"], "packet.engineer_approval", "progress_packet", pid, {"engineer_name": ap["engineer_name"]})
    return await packet_detail(cid, pid, user)


@router.post("/operator-contracts/{cid}/packets/{pid}/issue", tags=["contracts"])
async def issue_packet(cid: str, pid: str, user=Depends(staff)):
    c, op, p = await _packet(user, cid, pid)
    if p["status"] == "Issued":
        return await packet_detail(cid, pid, user)
    k = await compute(c, op, p)
    if k["blockers"]:
        raise HTTPException(409, {"code": "blocked", "blockers": k["blockers"]})
    html = render_packet(c, op, p, k, await _company(c["workspace_id"]), False)
    snap = {**k, "html": html, "sha256": hashlib.sha256(html.encode()).hexdigest()}
    await db.repair_documents.update_one({"uuid": f"doc-{pid}"}, {"$setOnInsert": {"uuid": f"doc-{pid}", "kind": "progress_packet", "contract_id": cid, "name": "Progress payment request",
                                         "html": html, "sha256": snap["sha256"], "issued_at": iso(), "issued_by": user["uuid"]}}, upsert=True)
    await db.progress_packets.update_one({"uuid": pid, "status": "Draft"}, {"$set": {"status": "Issued", "snapshot": snap, "issued_by": user["uuid"], "issued_at": iso()}})
    await audit(user, user["workspace_id"], "packet.issued", "progress_packet", pid, {"amount_due": k["amount_due"]})
    return await packet_detail(cid, pid, user)


@router.post("/operator-contracts/{cid}/packets/{pid}/submit", tags=["contracts"])
async def submit_packet(cid: str, pid: str, body: RR.SubmitIn = RR.SubmitIn(), user=Depends(staff)):
    c, op, p = await _packet(user, cid, pid)
    key = f"submit-{pid}"
    cur = await db.invoice_submissions.find_one({"key": key})
    if cur and cur["status"] in ("Sent", "Submitting", "Unknown"):
        return clean(cur)
    b = [] if p["status"] == "Issued" else ["Packet not issued yet."]
    if p["status"] == "Issued":  # recheck the standing gates at submit time
        k = await compute(c, op, {**p, "period_start": p["snapshot"]["period_start"]})
        b += [x for x in k["content_blockers"] if x.startswith(("Confirm these", "Required "))]
        if not (p.get("engineer_approval") or {}).get("fingerprint") == p["snapshot"]["fingerprint"]:
            b.append(PE_MISSING)
    b += await RR.channel_blockers(op, c["workspace_id"], user)
    if b:
        raise HTTPException(409, {"code": "blocked", "blockers": b})
    s = p["snapshot"]
    inv = {"uuid": pid, "workspace_id": c["workspace_id"], "operator_name": op["name"], "po": c["po"], "totals": {"total": s["amount_due"]},
           "lines": [{"description": l["description"], "quantity": l["q_todate"], "unit": l["unit"], "unit_cost": l["unit_cost"], "line_total": l["amount_todate"]} for l in s["lines"]]}
    return await RR.deliver(key, {"invoice_id": pid, "packet_id": pid}, inv, {"documents": [f"doc-{pid}"] + s["repair_documents"]}, op["channel"], user,
                            body.confirm_recipient, {"invoice_revision": 1})


# ---------------- final closeout (contract level) ----------------
GR_FIELDS = [  # PDF p.37 blank lines (points; measured on a render of the source page)
    ("project_spec", (414, 651, 503, 664), "contract_no"), ("between_contractor", (181, 630, 376, 643), "contractor_legal_name"),
    ("dated", (164, 609, 376, 622), "date_md"), ("dated_year", (394, 609, 411, 622), "date_yy"), ("retained_sum", (199, 486, 306, 499), None),
    ("signed_day", (331, 436, 365, 449), None), ("signed_month", (405, 436, 448, 449), None), ("signed_year", (470, 436, 490, 449), None),
    ("contractor", (343, 353, 485, 367), "contractor_legal_name"), ("by_signature", (359, 312, 485, 326), "SIG"), ("title", (368, 284, 485, 298), None)]


def _gr_values(c: dict) -> dict:
    v = {"contract_no": c.get("contract_no"), "contractor_legal_name": c.get("contractor_legal_name")}
    if c.get("contract_date"):
        d = date.fromisoformat(c["contract_date"])
        v.update(date_md=f"{d.strftime('%B')} {d.day}", date_yy=d.strftime("%y"))
    return v


def build_general_release(src_pdf: bytes, c: dict) -> bytes:
    """The supplied page, unchanged, plus AcroForm fields. Prefill only recorded contract facts; signature, signing date,
    retained sum and title stay blank."""
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import ArrayObject, BooleanObject, DictionaryObject, FloatObject, NameObject, NumberObject, TextStringObject
    w = PdfWriter(clone_from=PdfReader(io.BytesIO(src_pdf)))
    page = w.pages[0]
    vals = _gr_values(c)
    helv = w._add_object(DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"),
                                           NameObject("/BaseFont"): NameObject("/Helvetica"), NameObject("/Encoding"): NameObject("/WinAnsiEncoding")}))
    fields, annots = ArrayObject(), ArrayObject(list(page.get("/Annots") or []))
    fill = {}
    for name, rect, src in GR_FIELDS:
        d = DictionaryObject({NameObject("/Type"): NameObject("/Annot"), NameObject("/Subtype"): NameObject("/Widget"),
                              NameObject("/FT"): NameObject("/Sig" if src == "SIG" else "/Tx"), NameObject("/T"): TextStringObject(name),
                              NameObject("/Rect"): ArrayObject([FloatObject(x) for x in rect]), NameObject("/F"): NumberObject(4),
                              NameObject("/DA"): TextStringObject("/Helv 9 Tf 0 0 0.6 rg"), NameObject("/P"): page.indirect_reference})
        ref = w._add_object(d)
        annots.append(ref)
        fields.append(ref)
        if src and src != "SIG" and vals.get(src):
            fill[name] = vals[src]
    page[NameObject("/Annots")] = annots
    w._root_object[NameObject("/AcroForm")] = DictionaryObject({NameObject("/Fields"): fields, NameObject("/DA"): TextStringObject("/Helv 9 Tf 0 g"),
                                                                NameObject("/DR"): DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/Helv"): helv})}),
                                                                NameObject("/NeedAppearances"): BooleanObject(True)})
    if fill:
        w.update_page_form_field_values(page, fill, auto_regenerate=False)
    out = io.BytesIO()
    w.write(out)
    return out.getvalue()


def _closeout(c: dict, op: dict) -> dict:
    items = []
    for it in (op.get("closeout") or {}).get("checklist", []):
        rec = (c.get("closeout_items") or {}).get(it["key"]) or {}
        items.append({**it, "received": bool(rec.get("received")), "recorded_by_name": rec.get("by_name"), "recorded_at": rec.get("at"), "note": rec.get("note")})
    b = [f"Missing closeout document: {i['label']}" for i in items if not i["received"]]
    if not items:
        b.append("Closeout checklist not set for this operator.")
    gr = [f"General Release: {lbl} not set (left blank)" for k, lbl in (("contract_no", "Project / Spec. #"), ("contractor_legal_name", "contractor legal name"),
                                                                        ("contract_date", "contract date")) if not c.get(k)]
    return {"items": items, "final_acceptance_blockers": b, "general_release_notes": gr, "final_acceptance": c.get("final_acceptance")}


@router.get("/operator-contracts/{cid}", tags=["contracts"])
async def contract_detail(cid: str, user=Depends(staff)):
    c = await get_contract(user, cid)
    op = await _op(c)
    pk = await db.progress_packets.find({"contract_id": cid}, {"_id": 0, "snapshot.html": 0}).sort("period_start", 1).to_list(500)
    return {"contract": clean(c), "operator": {"uuid": op["uuid"], "name": op["name"]}, "packets": [{k: x.get(k) for k in ("uuid", "seq", "period_start", "period_end", "status")} for x in pk],
            "closeout": _closeout(c, op), "general_release_available": bool((op.get("closeout") or {}).get("general_release_doc"))}


@router.post("/operator-contracts/{cid}/closeout/{key}", tags=["contracts"])
async def closeout_item(cid: str, key: str, body: CloseoutItemIn, user=Depends(staff)):
    c = await get_contract(user, cid)
    op = await _op(c)
    if key not in {i["key"] for i in (op.get("closeout") or {}).get("checklist", [])}:
        raise HTTPException(404, "Not found")
    await db.operator_contracts.update_one({"uuid": cid}, {"$set": {f"closeout_items.{key}": {"received": body.received, "note": body.note, "by": user["uuid"],
                                                                                              "by_name": user.get("name"), "at": iso()}}})
    await audit(user, user["workspace_id"], "contract.closeout_item", "contract", cid, {"key": key, "received": body.received})
    return await contract_detail(cid, user)


@router.post("/operator-contracts/{cid}/final-acceptance", tags=["contracts"])
async def final_acceptance(cid: str, body: EngineerIn, user=Depends(admin)):
    c = await get_contract(user, cid)
    co = _closeout(c, await _op(c))
    if co["final_acceptance_blockers"]:
        raise HTTPException(409, {"code": "blocked", "blockers": co["final_acceptance_blockers"]})
    fa = {"engineer_name": body.engineer_name.strip(), "recorded_by": user["uuid"], "recorded_at": iso()}
    await db.operator_contracts.update_one({"uuid": cid}, {"$set": {"final_acceptance": fa}})
    await audit(user, user["workspace_id"], "contract.final_acceptance", "contract", cid, fa)
    return await contract_detail(cid, user)


@router.get("/operator-contracts/{cid}/general-release.pdf", tags=["contracts"])
async def general_release(cid: str, user=Depends(staff)):
    c = await get_contract(user, cid)
    op = await _op(c)
    src = await db.operator_documents.find_one({"uuid": (op.get("closeout") or {}).get("general_release_doc")})
    if not src:
        raise HTTPException(404, {"code": "no_form", "message": "General Release page not stored for this operator."})
    return Response(build_general_release(src["pdf"], c), media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="general-release-{cid}.pdf"'})


# ---------------- per-repair view of the three documents ----------------
async def repair_documents_model(r: dict, op: dict, b: dict, issued: bool, user: dict) -> list:
    short = op.get("short_name") or op["name"]
    c = await db.operator_contracts.find_one({"uuid": cid_for(op["uuid"], r.get("po") or ""), "workspace_id": r["workspace_id"]})
    no_c = f"Contract record not set up for PO {r.get('po') or NOT_SET}. An admin must add it."
    pay = [x for x in b["invoice"] if not x.endswith("not per repair.")]
    pstatus, cdate = "Not in a packet yet", (r.get("completion") or {}).get("completion_date") or ""
    if c:
        p = await db.progress_packets.find_one({"contract_id": c["uuid"], "period_start": {"$lte": cdate}, "period_end": {"$gte": cdate}}) if cdate else None
        if p:
            pstatus = f"Packet {p['period_start']} to {p['period_end']}: {p['status']}"
            if p["status"] != "Issued":
                pay += (await compute(c, op, p))["blockers"]
        else:
            pay.append("Not in a progress-payment packet yet.")
            if not c.get("retainage_pct"):
                pay.append("Retainage rate not set. An admin must enter the contract's retainage percentage.")
    else:
        pay.append(no_c)
    seen = set()
    pay = [x for x in pay if not (x in seen or seen.add(x))]
    co = _closeout(c, op) if c else None
    return [{"kind": "repair_record", "title": "Repair record", "status": "Issued" if issued and not b["report"] else "Draft", "blockers": b["report"]},
            {"kind": "progress_payment", "title": "Progress-payment packet (contract/PO)", "status": pstatus, "blockers": pay, "contract_id": c["uuid"] if c else None},
            {"kind": "final_closeout", "title": f"Final closeout with {short} (contract level)", "status": "Accepted" if co and co["final_acceptance"] else "Open",
             "blockers": co["final_acceptance_blockers"] if co else [no_c]}]


async def ensure_indexes():
    await db.operator_contracts.create_index("uuid", unique=True)
    await db.progress_packets.create_index("uuid", unique=True)
    await db.progress_packets.create_index([("contract_id", 1), ("period_start", 1)])
    await db.invoice_submissions.create_index("key", unique=True)
