"""Phase 2 API journeys: money (JRN-36..39), package (31-35), gates (43-45), publish (49-52), link (53-58), accept + race (60-63), WO (64), isolation (66-67)."""
import os, time, uuid, threading, json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import requests

API = os.environ.get("API", "http://localhost:8001/api")
PW = os.environ["SEED_PASSWORD"]


def login(email):
    s = requests.Session()
    s.headers["Authorization"] = "Bearer " + s.post(f"{API}/auth/login", json={"email": email, "password": PW}).json()["token"]
    return s


def ok(c, m):
    print(("PASS " if c else "FAIL ") + m)


est, fm, iso = login("estimator@ridgeline.example"), login("foreman@ridgeline.example"), login("foreman@isolation.example")
import asyncio, sys
sys.path.insert(0, "/app/backend"); os.chdir("/app/backend")
import seed
SFX = "-t" + uuid.uuid4().hex[:6]
_loop = asyncio.new_event_loop()
_loop.run_until_complete(seed.seed_ready_visit("v-seed-ready" + SFX, SFX))
_loop.run_until_complete(seed.seed_ready_visit("v-seed-ready" + SFX + "m", SFX + "m"))
E = "eng-seed-ready" + SFX
SCOPE = "scope-seed-ready" + SFX
view = lambda: est.get(f"{API}/engagements/{E}").json()
rev = lambda: view()["draft"]["revision"]

# JRN-31/32 package
pv = est.get(f"{API}/scope-items/{SCOPE}/package-preview").json()
mat = [l for l in pv["lines"] if l["category"] == "material"]
ok(not pv["blockers"] and mat and mat[0]["quantity"] == "8" and mat[0]["unit"] == "each" and mat[0]["quantity_origin"] == "confirmed repair count", f"JRN-31 preview material {mat and mat[0]['quantity']} {mat and mat[0]['quantity_origin']}")
ok(all(l["needs_review_reason"] == "Configured allowance – Needs review" for l in pv["lines"] if l["category"] in ("labor", "equipment", "mobilization")), "JRN-31 allowances Needs review")
n0 = len(view()["draft"]["lines"])
a1 = est.post(f"{API}/scope-items/{SCOPE}/package").json()
a2 = est.post(f"{API}/scope-items/{SCOPE}/package").json()
n1 = len(view()["draft"]["lines"])
ok(a2["added"] is False and n1 - n0 in (0, 5), f"JRN-32 add twice -> lines {n0}->{n1}")

# JRN-36/37 money on a fresh scratch engagement (no stale lines across runs)
M = "eng-seed-ready" + SFX + "m"
mr = lambda: est.get(f"{API}/engagements/{M}").json()
r = est.patch(f"{API}/engagements/{M}/draft", json={"expected_revision": mr()["draft"]["revision"], "tax_rate": "7.5"}).json()
r = est.post(f"{API}/engagements/{M}/lines", json={"expected_revision": r["revision"], "category": "other", "description": "JRN-36", "quantity": "3", "unit": "ea", "unit_cost": "0.335", "markup_pct": "25", "taxable": True, "reason": "test", "total": "999"}).json()
ok(r["line"]["internal_cost"] == "1.01" and r["line"]["line_total"] == "1.26" and r["totals"]["tax"] == "0.09" and r["totals"]["total"] == "1.35", f"JRN-36 {r['line']['internal_cost']} {r['line']['line_total']} tax {r['totals']['tax']} total {r['totals']['total']} (client 999 ignored)")
P2 = None
# JRN-37 on another fresh visit-less calc: use pure function check via a scratch draft line set
import sys; sys.path.insert(0, "/app/backend"); import money
t = money.totals([{"quantity": "1", "unit_cost": "0.05", "markup_pct": "0", "taxable": True}, {"quantity": "1", "unit_cost": "0.05", "markup_pct": "0", "taxable": True}], "5")
ok(t["subtotal"] == "0.10" and t["tax"] == "0.01" and t["total"] == "0.11", f"JRN-37 subtotal {t['subtotal']} tax {t['tax']} total {t['total']}")
ok(money.totals([], "0")["margin_pct"] == "N/A", "JRN-39 margin N/A at zero subtotal")
for bad in [{"quantity": "0"}, {"quantity": "-1"}, {"unit_cost": "-5"}, {"markup_pct": "NaN"}, {"unit_cost": "1.12345"}]:
    body = {"expected_revision": mr()["draft"]["revision"], "category": "other", "description": "bad", "quantity": "1", "unit": "ea", "unit_cost": "1", "markup_pct": "0", "taxable": False, "reason": "x", **bad}
    rr = est.post(f"{API}/engagements/{M}/lines", json=body)
    ok(rr.status_code == 422 and rr.json()["detail"].get("field"), f"JRN-38 reject {bad} -> {rr.json()['detail'].get('field')}")
ok(mr()["totals"]["total"] == "1.35", "JRN-38 server total unchanged")
P = est.post(f"{API}/visits/v-seed-pinecrest/engagement").json()["engagement_id"]
pr = lambda: est.get(f"{API}/engagements/{P}").json()
# JRN-44 pinecrest discrepancy + JRN-33 customer supplied
s = est.post(f"{API}/engagements/{P}/scope-items", json={"location": "Siding A", "inspected_quantity": 12, "repair_quantity": 8, "specification": "Crosstie 7x9x8'6\" hardwood", "material_responsibility": "Customer", "access_disposition": "Mill super escorts"}).json()
pv = est.get(f"{API}/scope-items/{s['uuid']}/package-preview").json()
ok(not any(l["category"] == "material" for l in pv["lines"]) and pv["ties_supplied_by_customer"] and any(l["category"] == "handling" for l in pv["lines"]), "JRN-33 customer-supplied: no material line, handling kept")
est.post(f"{API}/scope-items/{s['uuid']}/package")
s2 = est.patch(f"{API}/scope-items/{s['uuid']}", json={"expected_revision": s["revision"], "material_responsibility": "Contractor"}).json()
ok(all(l["needs_review_reason"].startswith("Source fact changed") for l in pr()["draft"]["lines"] if l.get("observation_id") == s["uuid"]), "JRN-34 supplier change -> dependent lines Needs review")
b = est.post(f"{API}/engagements/{P}/validate").json()["blockers"]
ok(any(x.startswith("Unresolved discrepancy: repair quantity") for x in b), f"JRN-44 {[x for x in b if 'discrepancy' in x]}")
ok("No selected photo" in b and "Expiry missing" in b and any(x.startswith("Unreviewed line") for x in b), "JRN-45 unreviewed/photo/expiry blockers")
s3 = est.post(f"{API}/engagements/{P}/scope-items", json={"location": "East leg", "repair_quantity": 4, "material_responsibility": "Contractor", "access_disposition": "ok"}).json()
pv = est.get(f"{API}/scope-items/{s3['uuid']}/package-preview").json()
ok("Specification missing" in pv["blockers"] and not pv["lines"], "JRN-35 spec missing blocker")
ok(any("Specification missing" in x for x in est.post(f"{API}/engagements/{P}/validate").json()["blockers"]), "JRN-43 spec still blocks validate")
d = pr()["draft"]
rr = est.post(f"{API}/engagements/{P}/lines", json={"expected_revision": d["revision"], "category": "mobilization", "description": "2nd trip", "quantity": "1", "unit": "trip", "unit_cost": "100", "markup_pct": "0", "taxable": False, "reason": "x"})
ok(rr.status_code == 422 and "Duplicate mobilization" in rr.text, "JRN-41 duplicate mobilization needs reason")

# Ready engagement: review all lines, preview, publish
for l in view()["draft"]["lines"]:
    est.patch(f"{API}/engagements/{E}/lines/{l['uuid']}", json={"expected_revision": rev(), "reviewed": True})
b = est.post(f"{API}/engagements/{E}/validate").json()["blockers"]
ok(b == ["Agreement not previewed"], f"gate before preview: {b}")
ag = est.get(f"{API}/engagements/{E}/agreement-preview").json()
ok(not ag.get("label") and "Illustrative sample" not in json.dumps(ag) and not ag["missing"], f"JRN-47 agreement preview (no metacommentary label) missing={ag['missing']}")
d = view()["draft"]
est.patch(f"{API}/engagements/{E}/draft", json={"expected_revision": d["revision"], "terms": {"payment_terms": "Net 45"}})
b = est.post(f"{API}/engagements/{E}/validate").json()["blockers"]
ok("Unreviewed term edit" in b and any(x.startswith("Stale price") for x in b), f"JRN-48 {b}")
est.patch(f"{API}/engagements/{E}/draft", json={"expected_revision": rev(), "terms_reviewed": True})
est.get(f"{API}/engagements/{E}/agreement-preview")
key = str(uuid.uuid4())
R = rev()
v1 = est.post(f"{API}/engagements/{E}/publish", json={"expected_revision": R, "idempotency_key": key}).json()
v1b = est.post(f"{API}/engagements/{E}/publish", json={"expected_revision": R, "idempotency_key": key}).json()
ok(v1.get("version_no") and v1["uuid"] == v1b["uuid"], f"JRN-49/50 published v{v1.get('version_no')} same on retry; hash {v1.get('snapshot_hash','')[:12]} doc {v1.get('document_hash','')[:12]}")
VID = v1["uuid"]
h_before = est.get(f"{API}/versions/{VID}").json()["snapshot_hash"]
p_before = est.get(f"{API}/proposals/{VID}/print").text
l0 = view()["draft"]["lines"][0]
est.patch(f"{API}/engagements/{E}/lines/{l0['uuid']}", json={"expected_revision": rev(), "unit_cost": "99"})
ok(est.get(f"{API}/versions/{VID}").json()["snapshot_hash"] == h_before and est.get(f"{API}/proposals/{VID}/print").text == p_before, "JRN-51 v1 unchanged after draft edit")
# share
sh = est.post(f"{API}/versions/{VID}/share").json()
tok = sh["token"]
pub = requests.get(f"{API}/public/proposals/{tok}").json()
txt = str(pub).lower()
ok(pub["status"] == "Published" and not any(k in txt for k in ["unit_cost", "markup", "margin", "internal_cost", "transcript", "model_id", "audio"]), "JRN-53/Q-13 allowlist (no cost/markup/margin/model)")
ok(requests.get(f"{API}/public/proposals/{tok}/media/{uuid.uuid4()}").status_code == 404 and requests.get(API + pub["photos"][0]["url"][4:]).status_code == 200, "JRN-54 unselected media 404, selected 200")
pp = requests.get(f"{API}/public/proposals/{tok}/print").text
ok("Illustrative sample" not in pp and "markup" not in pp.lower() and "unit_cost" not in pp, "JRN-65 public print allowlisted, no metacommentary")
r = requests.post(f"{API}/public/proposals/{tok}/accept", json={"name": "", "email": "bad", "agree": False})
ok(r.status_code == 422 and set(r.json()["detail"]["errors"]) == {"name", "email", "agree"}, "JRN-56 field errors")
# revoke
sh2 = est.post(f"{API}/versions/{VID}/share").json()
est.post(f"{API}/links/{sh2['link_id']}/revoke")
ok(requests.get(f"{API}/public/proposals/{sh2['token']}").status_code == 404 and requests.post(f"{API}/public/proposals/{sh2['token']}/accept", json={"name": "a", "email": "a@example.com", "agree": True}).status_code == 404, "JRN-55 revoked link denied")
# JRN-61 race: 10 concurrent accepts
res = []
def go():
    res.append(requests.post(f"{API}/public/proposals/{tok}/accept", json={"name": "Pat Customer", "email": "pat@example.com", "agree": True}))
ts = [threading.Thread(target=go) for _ in range(10)]
[t.start() for t in ts]; [t.join() for t in ts]
wos = {x.json().get("work_order_id") for x in res if x.status_code == 200}
retry = requests.post(f"{API}/public/proposals/{tok}/accept", json={"name": "Pat Customer", "email": "pat@example.com", "agree": True}).json()
nwo = len([w for w in est.get(f"{API}/work-orders").json() if w["engagement_id"] == E])
ok(len(wos) == 1 and retry["work_order_id"] in wos and nwo == 1, f"JRN-61 statuses {[x.status_code for x in res]} -> work orders {nwo}, ids {len(wos)}")
ok(est.get(f"{API}/versions/{VID}").json()["contract_status"] == "Accepted", "JRN-60 contract Accepted")
r = est.post(f"{API}/engagements/{E}/publish", json={"expected_revision": rev(), "idempotency_key": "x2"})
ok(r.status_code == 409 and "already accepted" in r.text, "JRN-63 publish after accept 409")
wo = [w for w in est.get(f"{API}/work-orders").json() if w["engagement_id"] == E][0]
ok(wo["access_status"] == "Not arranged", "JRN-64 access starts Not arranged")
w = est.patch(f"{API}/work-orders/{wo['uuid']}", json={"expected_revision": wo["revision"], "crew_id": "crew-1", "scheduled_date": "2026-11-20", "access_status": "Requested"}).json()
w = est.patch(f"{API}/work-orders/{wo['uuid']}", json={"expected_revision": w["revision"], "access_status": "Confirmed"}).json()
ok(w["access_status"] == "Confirmed" and len(w["access_history"]) == 2 and w["frozen_scope"] == wo["frozen_scope"], "JRN-64 transitions attributed, scope frozen")
# JRN-66/67
ok(fm.get(f"{API}/engagements/{E}").status_code == 403 and fm.post(f"{API}/engagements/{E}/publish", json={"expected_revision": 1, "idempotency_key": "f"}).status_code == 403, "JRN-66 foreman 403")
ok(iso.get(f"{API}/work-orders/{wo['uuid']}").status_code == 403, "JRN-67 iso foreman blocked (role)")
print("VERSION", VID, "WO", wo["uuid"])  # share token intentionally not printed
