"""Phase 17 paperwork: the "Generic Repair Work Order" template (page 3 of the public Smartsheet simple work order), the filled form
with continuation pages, the invoice PDF and the complete packet. Every value comes from stored records: the linked work order,
the approved billing lines of the invoice, completion, approval and sign-offs. Nothing is read from photos or analysis results.
PDFs are written with pypdf plus a small built-in text-page writer (no extra dependency). Output is deterministic for equal inputs."""
import hashlib
import io
import json
import os
import textwrap
from typing import Optional

from pypdf import PdfReader, PdfWriter

HERE = os.path.join(os.path.dirname(__file__), "form_templates")
TEMPLATE_PDF = os.path.join(HERE, "generic_repair_work_order_v1.pdf")
TEMPLATE_META = os.path.join(HERE, "generic_repair_work_order_v1.json")
FORM_ID = "generic-repair-work-order"
LAYOUT_VERSION = 2  # v2: page-1 "+N more lines" row, Subtotal/Tax beside TOTAL, Work Approved By from the approval record
ROWS_ON_FORM = 3
ROW_CHARS = 52     # DescriptionRow width at 10 pt
BOX_CHARS = 84     # multi-line boxes (Request / Work completed) width at 10 pt
BOX_LINES = 3


class TemplateError(Exception):
    pass


def template() -> tuple[bytes, dict]:
    """Install check (REQ-1701..1703): exactly one page, 33 text fields + the logo button, no example content, checksum matches."""
    data = open(TEMPLATE_PDF, "rb").read()
    meta = json.load(open(TEMPLATE_META))
    if hashlib.sha256(data).hexdigest() != meta["sha256"]:
        raise TemplateError("Template checksum does not match its record.")
    rd = PdfReader(io.BytesIO(data))
    if len(rd.pages) != 1:
        raise TemplateError("Template must be the single blank page; the example pages are not allowed.")
    annots = [a.get_object() for a in rd.pages[0].get("/Annots") or []]
    tx = sum(1 for a in annots if a.get("/FT") == "/Tx")
    btn = sum(1 for a in annots if a.get("/FT") == "/Btn")
    text = rd.pages[0].extract_text() or ""
    if tx != meta["text_fields"] or btn != meta["button_fields"] or "Romy" in text or "Example" in text:
        raise TemplateError("Template is not the blank work order page (field count or example content).")
    return data, meta


def template_info() -> dict:
    _, meta = template()
    return {k: meta[k] for k in ("id", "name", "version", "source_url", "sha256", "publisher", "disclaimer", "text_fields", "button_fields", "note")}


# ---------------- small text-page PDF writer ----------------
def _esc(s: str) -> str:
    s = s.encode("latin-1", "replace").decode("latin-1")
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def snapshot_key(inv: dict, r: dict) -> str:
    return f"{inv['uuid']}:{inv.get('revision')}:{r.get('revision')}:L{LAYOUT_VERSION}"


def _money(v) -> str:
    from decimal import Decimal
    return f"{Decimal(str(v)):,.2f}"


def overlay_pdf(items: list[tuple[float, float, str, int]]) -> bytes:
    """One letter page of positioned Helvetica text (x, y, text, size), merged over a filled form page."""
    ops = ["BT"] + [f"/F1 {sz} Tf 1 0 0 1 {x:.1f} {y:.1f} Tm ({_esc(t)}) Tj" for x, y, t, sz in items] + ["ET"]
    stream = "\n".join(ops).encode("latin-1")
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [4 0 R] /Count 1 >>",
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> /Contents 5 0 R >>",
            f"<< /Length {len(stream)} >>\nstream\n".encode("latin-1") + stream + b"\nendstream"]
    out, offs = bytearray(b"%PDF-1.4\n"), []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n".encode() + (o if isinstance(o, bytes) else o.encode("latin-1")) + b"\nendobj\n"
    x = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode() + b"".join(f"{o:010d} 00000 n \n".encode() for o in offs)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{x}\n%%EOF\n".encode()
    return bytes(out)


def text_pdf(lines: list[tuple[str, bool]], title: str) -> bytes:
    """Letter pages, Helvetica 10 pt, long lines wrapped (never cut). lines: (text, bold)."""
    wrapped: list[tuple[str, bool]] = []
    for t, b in lines:
        parts = textwrap.wrap(t, 95, break_long_words=True, replace_whitespace=False) if t else [""]
        wrapped += [(p, b) for p in parts]
    per = 60
    pages = [wrapped[i:i + per] for i in range(0, len(wrapped), per)] or [[]]
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", None,
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>"]
    kids = []
    for n, pg in enumerate(pages, 1):
        ops = ["BT", "/F2 12 Tf", "50 750 Td", f"({_esc(title)}  -  page {n} of {len(pages)}) Tj", "/F1 10 Tf", "0 -22 Td", "12 TL"]
        for t, b in pg:
            ops += [f"/{'F2' if b else 'F1'} 10 Tf", f"({_esc(t)}) Tj", "T*"]
        ops.append("ET")
        stream = "\n".join(ops).encode("latin-1")
        objs.append(f"<< /Length {len(stream)} >>\nstream\n".encode("latin-1") + stream + b"\nendstream")
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents {len(objs)} 0 R >>")
        kids.append(len(objs))
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] /Count {len(kids)} >>"
    out, offs = bytearray(b"%PDF-1.4\n"), []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n".encode() + (o if isinstance(o, bytes) else o.encode("latin-1")) + b"\nendobj\n"
    x = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode() + b"".join(f"{o:010d} 00000 n \n".encode() for o in offs)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{x}\n%%EOF\n".encode()
    return bytes(out)


def merge(parts: list[bytes]) -> bytes:
    w = PdfWriter()
    for p in parts:
        w.append(PdfReader(io.BytesIO(p)))
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


# ---------------- facts ----------------
def location_text(r: dict) -> str:
    loc = r.get("location") or {}
    rail = " / ".join(x for x in (r.get("railroad"), f"Track {r['track']}" if r.get("track") else None,
                                  f"MP {r['milepost']}" if r.get("milepost") else None) if x)
    coords = f"{loc['lat']:.6f}, {loc['lon']:.6f} ({loc.get('method_label') or 'pin'})" if isinstance(loc.get("lat"), (int, float)) else ""
    return "; ".join(x for x in (rail, coords) if x)


def request_text(wo: dict) -> str:
    fs = wo.get("frozen_scope") or {}
    items = [s.get("description") or s.get("location") or "" for s in (fs.get("scope") or fs.get("lines") or []) if isinstance(s, dict)]
    head = f"Accepted proposal version {fs.get('version_no')}" if fs.get("version_no") else ""
    return ". ".join(x for x in [head] + [i for i in items if i] if x)


def signoff_lines(r: dict, required: list[str]) -> list[str]:
    out = []
    for s in r.get("signoffs") or []:
        sig = "signature captured" if s.get("signature") else "Name (not a signature)"
        out.append(f"{s.get('role')}: {s.get('name')} [{sig}] - recorded by {s.get('recorded_by_name') or s.get('recorded_by')} at {s.get('recorded_at')} - repair revision {s.get('repair_revision') or 'not recorded'}")
    if r.get("completion"):
        c = r["completion"]
        out.append(f"foreman (Finish repair): {c.get('confirmed_by_name')} [Name (not a signature)] - recorded by {c.get('confirmed_by_name')} at {c.get('received_at')}"
                   f" - repair revision {c.get('repair_revision') or r.get('revision')}")
    have = {s.get("role") for s in r.get("signoffs") or []} | ({"foreman"} if r.get("completion") else set())
    out += [f"Outstanding: {role} sign-off not recorded" for role in required if role not in have]
    return out


def blockers(r: dict, wo: Optional[dict], inv: Optional[dict], customer: Optional[dict], invoice_ok: bool) -> list[str]:
    """Required facts, each named, each fixable with a normal control on the repair or estimate page (REQ-1711, 1716)."""
    b = []
    if not wo:
        b.append("Work order not linked. Start the repair from its work order; the repair ID is never used as the work order number.")
    if not r.get("completion"):
        b.append("Finish repair not recorded. The foreman finishes the repair on the phone.")
    if not r.get("approved_work"):
        b.append("Actual work not approved. Use Approve actual work.")
    if not inv or not invoice_ok:
        b.append("Invoice not built for the approved work. Use Build invoice.")
    if not customer:
        b.append("Customer (requester) not set. Choose the customer on the estimate page.")
    if not location_text(r):
        b.append("Location missing. Add coordinates, or railroad and milepost.")
    return b


def work_order_pdf(r: dict, wo: dict, inv: dict, customer: dict, issuer: str, operator: dict, required_roles: list[str]) -> bytes:
    data, meta = template()
    lines = inv["lines"]
    t = inv["totals"]
    work = "; ".join(f"{w['description']} ({w['quantity']} {w['unit']})" for w in (r.get("approved_work") or {}).get("items", []))
    req = request_text(wo)

    def box(text: str) -> tuple[str, bool]:
        parts = textwrap.wrap(text, BOX_CHARS) or [""]
        if len(parts) <= BOX_LINES:
            return "\n".join(parts), False
        return "\n".join(parts[:BOX_LINES - 1] + ["(continued on the next page)"]), True

    req_box, req_more = box(req)
    work_box, work_more = box(work)
    c, a = r.get("completion") or {}, r.get("approved_work") or {}
    from decimal import Decimal
    shown = lines if len(lines) <= ROWS_ON_FORM else lines[:ROWS_ON_FORM - 1]  # v2: the last row carries the rest when lines do not fit
    rest = lines[len(shown):]
    vals = {"Your Organization Name": issuer, "Requester Name": customer.get("name") or "", "Phone": customer.get("phone") or "",
            "Email": customer.get("email") or "", "Work Order ID": wo.get("number") or wo["uuid"], "Location Address": location_text(r),
            "Order Date and Time": (wo.get("created_at") or "")[:16].replace("T", " "), "Date Delivered": r.get("completion_date") or "",
            "Work Assigned To": c.get("confirmed_by_name") or "", "Work Billed To": operator.get("name") or "",
            "Request Description": req_box, "Description of Work Completed": work_box,
            "AmountTOTAL": f"${_money(t['total'])}", "Work Completed By": c.get("confirmed_by_name") or "",
            "Date and Time Completed": (c.get("received_at") or "")[:16].replace("T", " "),
            # from the recorded office approval (repair.approved_work); a name, not a signature. Blank only if no approval record exists.
            "Work Approved By": a.get("approved_by_name") or "" if a else "", "Date": (a.get("approved_at") or "")[:10] if a else ""}
    for i, ln in enumerate(shown, 1):
        d = ln["description"]
        vals[f"DescriptionRow{i}"] = d if len(d) <= ROW_CHARS else d[:ROW_CHARS - 22].rstrip() + "... (full text page 2)"
        vals[f"QuantityRow{i}"] = f"{ln['quantity']} {ln['unit']}"
        vals[f"Price per UnitRow{i}"] = f"${_money(ln['unit_cost'])}"
        vals[f"AmountRow{i}"] = f"${_money(ln['line_total'])}"
    if rest:
        n = len(shown) + 1
        vals[f"DescriptionRow{n}"] = f"+{len(rest)} more line{'s' if len(rest) > 1 else ''} on continuation page (lines {n}-{len(lines)})"
        vals[f"AmountRow{n}"] = f"${_money(sum(Decimal(str(x['line_total'])) for x in rest))}"
    w = PdfWriter(clone_from=PdfReader(io.BytesIO(data)))
    w.set_need_appearances_writer(False)
    w.update_page_form_field_values(w.pages[0], vals, auto_regenerate=False, flatten=True)
    w.remove_annotations(subtypes="/Widget")  # completed document: values are part of the page, not editable fields
    if "/AcroForm" in w._root_object:
        del w._root_object["/AcroForm"]
    tot = f"Subtotal ${_money(t['subtotal'])}    Tax ${_money(t['tax'])}"
    w.pages[0].merge_page(PdfReader(io.BytesIO(overlay_pdf([(462 - len(tot) * 4.75, 118, tot, 9)]))).pages[0])
    buf = io.BytesIO()
    w.write(buf)
    appr = (f"Work approved by {a.get('approved_by_name') or 'name not recorded'} at {a.get('approved_at')} (record: repair approved_work, repair revision "
            f"{a.get('repair_revision')}). Name (not a signature).") if a else "Work approval: no approval record."
    cont: list[tuple[str, bool]] = [
        (f"Work order {wo.get('number')} (work order id {wo['uuid']})  |  Repair {r['uuid']} revision {r.get('revision')}", True),
        (f"Invoice {inv['uuid']} revision {inv.get('revision')}  |  PO {inv.get('po')}  |  layout v{LAYOUT_VERSION}", False), ("", False),
        ("All billing lines (same approved lines as the invoice)", True)]
    for i, ln in enumerate(lines, 1):
        cont.append((f"{i}. {ln['description']}", False))
        cont.append((f"    {ln['quantity']} {ln['unit']} x ${_money(ln['unit_cost'])} = ${_money(ln['line_total'])}", False))
    cont += [("", False), (f"Subtotal: ${_money(t['subtotal'])}", True), (f"Tax: ${_money(t['tax'])}", True), (f"Invoice total: ${_money(t['total'])}", True), ("", False)]
    if req_more:
        cont += [("Request description (full)", True), (req, False), ("", False)]
    if work_more:
        cont += [("Description of work completed (full)", True), (work, False), ("", False)]
    cont += [("Sign-offs", True)] + [(s, False) for s in signoff_lines(r, required_roles)] + [(appr, False), ("", False),
             (f"Form: {meta['name']}, version {meta['version']}, template SHA-256 {meta['sha256']}", False),
             (f"Template source: {meta['source_url']}", False), (meta["note"], False), (f"Publisher disclaimer: {meta['disclaimer']}", False)]
    return merge([buf.getvalue(), text_pdf(cont, f"{meta['name']} - continued")])


def invoice_pdf(inv: dict, r: dict, wo: Optional[dict], customer: Optional[dict], issuer: str) -> bytes:
    t = inv["totals"]
    rc = inv.get("rate_confirmation") or {}
    rows: list[tuple[str, bool]] = [
        (f"Invoice number: {inv['uuid']}  (revision {inv.get('revision')})", True),
        (f"Issuer: {issuer}", False), (f"Customer: {(customer or {}).get('name') or 'Not set'}", False),
        (f"Billed to (operator): {inv.get('operator_name')}", False), (f"PO / contract reference: {inv.get('po')}", False),
        (f"Linked repair: {r['uuid']}", False),
        (f"Linked work order: {(wo or {}).get('number') or 'Not linked'} (id {(wo or {}).get('uuid') or 'none'})", False), ("", False),
        ("Lines: description | quantity | unit | rate | line total", True)]
    for i, ln in enumerate(inv["lines"], 1):
        rows.append((f"{i}. {ln['description']}", False))
        rows.append((f"    {ln['quantity']} | {ln['unit']} | ${ln['unit_cost']} | ${ln['line_total']}", False))
    rows += [("", False), (f"Subtotal: ${t['subtotal']}", True), (f"Tax: ${t['tax']}", True), (f"Total: ${t['total']}", True), ("", False),
             (f"Rate confirmation: reference {rc['ref']}, confirmed by {rc.get('confirmed_by_name') or 'name not recorded'} at {rc.get('confirmed_at') or 'time not recorded'}"
              if rc.get("ref") else "Rate confirmation: not required by this operator's setup", False),
             (f"Rate snapshot SHA-256: {rc.get('rates_sha') or inv.get('rates_sha') or '-'}", False),
             (f"Invoice checksum (SHA-256): {inv.get('checksum')}", False)]
    return text_pdf(rows, "Invoice")
