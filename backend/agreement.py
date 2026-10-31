"""Illustrative agreement template rendering + printable HTML. Print renders ONLY from frozen snapshots."""
import html
import re

from core import sha256_hex

LABEL = ""  # no metacommentary in generated documents (overview.md UI/UX Rules)
REQUIRED_VARS = ["contractor_legal_identity", "customer_site", "proposal_version", "scope", "quantities",
                 "total_currency_tax", "schedule_wording", "assumptions_exclusions", "payment_terms", "validity",
                 "acceptance_wording"]
TEMPLATE_BODY = """AGREEMENT FOR TIE REPLACEMENT SERVICES

1. Parties. This agreement is between {{contractor_legal_identity}} ("Contractor") and the customer at {{customer_site}}.
2. Proposal. This agreement incorporates proposal {{proposal_version}}.
3. Scope of work. {{scope}}
4. Quantities. {{quantities}}
5. Price. {{total_currency_tax}}
6. Schedule. {{schedule_wording}}
7. Assumptions and exclusions. {{assumptions_exclusions}}
8. Payment terms. {{payment_terms}}
9. Validity. {{validity}}
10. Acceptance. {{acceptance_wording}}
"""
TEMPLATE_HASH = sha256_hex(TEMPLATE_BODY.encode())


def render(variables: dict) -> dict:
    missing = [k for k in REQUIRED_VARS if not str(variables.get(k) or "").strip()]
    text = TEMPLATE_BODY.replace("{{label}}", LABEL)
    for k in REQUIRED_VARS:
        text = text.replace("{{" + k + "}}", str(variables.get(k) or f"[MISSING: {k}]"))
    return {"template_version": 2, "template_hash": TEMPLATE_HASH, "label": LABEL, "variables": variables,
            "document_text": text, "document_hash": sha256_hex(text.encode()), "missing": missing}


def e(x) -> str:
    return html.escape(str(x if x is not None else ""))


def print_html(snap: dict, version: dict, photo_url) -> str:
    """photo_url(evidence_id) -> URL. Only snapshot fields are used."""
    lines = "".join(
        f"<tr><td>{e(l['description'])}</td><td class=n>{e(l['quantity'])} {e(l['unit'])}</td>"
        f"<td class=n>${e(l['unit_price'])}</td><td class=n>${e(l['line_total'])}</td></tr>" for l in snap["lines"])
    photos = "".join(f"<figure><img src='{e(photo_url(p['evidence_id']))}' alt='Site photo'/><figcaption>{e(p.get('caption') or 'Site photo')}</figcaption></figure>"
                     for p in snap["photos"])
    findings = "".join(f"<li>{e(f)}</li>" for f in snap["findings"]) or "<li>—</li>"
    coverage = "".join(f"<li><b>Not inspected:</b> {e(c['area'])} — {e(c['reason'])} (no quantities or charges)</li>" for c in snap["not_inspected"]) or "<li>None recorded</li>"
    doc = re.sub(r"\n", "<br/>", e(snap["agreement"]["document_text"]))
    t = snap["totals"]
    return f"""<!doctype html><html><head><meta charset=utf-8><title>Proposal {e(snap['proposal_number'])} v{version['version_no']}</title>
<style>body{{font-family:Georgia,serif;color:#111;margin:24px;max-width:820px}}h1{{font-size:22px;border-bottom:3px solid #111}}
h2{{font-size:16px;margin-top:22px;border-bottom:1px solid #999}}table{{width:100%;border-collapse:collapse}}td,th{{border:1px solid #999;padding:6px;font-size:13px;vertical-align:top}}
.n{{text-align:right;white-space:nowrap}}figure{{display:inline-block;width:48%;margin:0 1% 12px 0;break-inside:avoid}}img{{width:100%;height:auto}}
.lbl{{border:2px solid #b45309;padding:6px;font-weight:bold}}.doc{{font-size:13px;line-height:1.5}}
@media print{{h2{{break-after:avoid}}table,tr,figure,.keep{{break-inside:avoid}}.pb{{break-before:page}}}}</style></head><body>
<h1>{e(snap['contractor']['legal_identity'])} — Proposal {e(snap['proposal_number'])}, version {version['version_no']}</h1>
<p>Customer/site: {e(snap['customer_site'])}<br/>Visit: {e(snap['visit_id'])} · Proposal id: {e(version['uuid'])} · Issued {e(version['published_at'])}<br/>
Valid until: {e(snap['expiry']['local'])} {e(snap['expiry']['timezone'])} ({e(snap['expiry']['utc'])} UTC)</p>
{'<p class=lbl>Ties supplied by customer</p>' if snap['ties_supplied_by_customer'] else ''}
<h2>Findings</h2><ul>{findings}</ul><h2>Coverage exclusions</h2><ul>{coverage}</ul>
<h2>Price</h2><table class=keep><tr><th>Item</th><th>Qty</th><th>Unit price</th><th>Total</th></tr>{lines}
<tr><td colspan=3 class=n>Subtotal</td><td class=n>${e(t['subtotal'])}</td></tr><tr><td colspan=3 class=n>Tax ({e(t['tax_rate'])}%)</td><td class=n>${e(t['tax'])}</td></tr>
<tr><td colspan=3 class=n><b>Total ({e(t['currency'])})</b></td><td class=n><b>${e(t['total'])}</b></td></tr></table>
<p>{e(snap['tax_treatment_text'])}</p><h2>Assumptions</h2><p>{e(snap['terms']['assumptions'])}</p><p>Exclusions: {e(snap['terms']['exclusions'])}</p>
<h2>Terms</h2><p>Payment: {e(snap['terms']['payment_terms'])}<br/>Schedule: {e(snap['terms']['schedule_wording'])}</p>
<h2>Photos</h2>{photos or '<p>None selected</p>'}
<div class=pb></div><h2>Agreement</h2><p class=lbl>{e(snap['agreement']['label'])}</p><div class=doc>{doc}</div>
<p style='font-size:11px'>Snapshot hash {e(version['snapshot_hash'])} · Agreement document hash {e(snap['agreement']['document_hash'])} · Template v{snap['agreement']['template_version']}</p>
</body></html>"""
