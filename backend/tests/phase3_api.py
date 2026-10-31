"""Phase 3 API: demo sessions (create/reset/expiry/isolation probes), office jobs, contracts, full demo flow to work order."""
import os, uuid
import requests

API = os.environ.get("API", "http://localhost:8001/api")
PW = os.environ["SEED_PASSWORD"]


def ok(c, m):
    print(("PASS " if c else "FAIL ") + m)


def sess(tok):
    s = requests.Session(); s.headers["Authorization"] = "Bearer " + tok; return s


def login(email):
    return sess(requests.post(f"{API}/auth/login", json={"email": email, "password": PW}).json()["token"])


r = requests.post(f"{API}/demo/sessions")
ok(r.status_code == 201, f"REQ-98 create demo session {r.status_code}")
D = r.json(); dm = sess(D["token"])
J = D["jobs"]; RV, BV, EV = J["ready_to_estimate"]["visit_id"], J["blocked_customer_supplied_8_vs_10"]["visit_id"], J["empty_draft"]["visit_id"]
E = J["ready_to_estimate"]["engagement_id"]
me = dm.get(f"{API}/auth/me").json()
ok(set(D["user"]["roles"]) == {"foreman", "estimator"} and D["workspace"]["is_demo"] and "Fictional" in D["workspace"]["label"], "demo user foreman+estimator, workspace labeled")
ok(all(x not in RV for x in ("seed", "ridgeline")) and D["workspace"]["uuid"].startswith("ws-demo-"), "new ids")

# office jobs
jobs = dm.get(f"{API}/office/jobs").json()["jobs"]
ok({j["visit_id"] for j in jobs} == {RV, BV, EV}, f"REQ-103 office/jobs lists only demo jobs ({len(jobs)})")
jr = next(j for j in jobs if j["visit_id"] == RV)
ok(jr["engagement_id"] == E and jr["findings_count"] >= 1 and jr["candidate_count"] >= 1 and jr["estimate_status"] == "Empty draft", f"job row {jr['findings_count']} findings {jr['candidate_count']} cands {jr['estimate_status']}")

# saved analysis
rv = dm.get(f"{API}/visits/{RV}/review").json()
cs = rv["candidates"]
sa = cs[0].get("saved_analysis") or {}
ok(sa.get("label") == "Saved analysis" and sa.get("model_id") and sa.get("prompt_version") and sa.get("run_at"), f"REQ-108 saved analysis {sa.get('model_id')} {sa.get('prompt_version')} {sa.get('run_at')}")
ok(any(c["review_state"] == "Confirmed" for c in cs) and any(o.get("source_candidate_id") for o in rv["observations"]), "confirmed observation linked to saved candidate")
ok(dm.get(f"{API}/evidence/{J['ready_to_estimate']['evidence_id']}/content").status_code == 200, "demo photo streams (copied, verified)")

# blocked case
bl = dm.post(f"{API}/visits/{BV}/engagement").json()["engagement_id"]
b = dm.post(f"{API}/engagements/{bl}/validate").json()["blockers"]
ok(any(x.startswith("Unresolved discrepancy") for x in b), f"blocked 8 vs 10 case: {[x for x in b if 'discrepancy' in x]}")

# full flow on ready job
view = lambda: dm.get(f"{API}/engagements/{E}").json()
rev = lambda: view()["draft"]["revision"]
sid = view()["scope_items"][0]["uuid"]
dm.post(f"{API}/scope-items/{sid}/package")
for l in view()["draft"]["lines"]:
    dm.patch(f"{API}/engagements/{E}/lines/{l['uuid']}", json={"expected_revision": rev(), "reviewed": True})
dm.get(f"{API}/engagements/{E}/agreement-preview")
b = dm.post(f"{API}/engagements/{E}/validate").json()["blockers"]
ok(b == [], f"ready demo job validates clean: {b}")
v = dm.post(f"{API}/engagements/{E}/publish", json={"expected_revision": rev(), "idempotency_key": str(uuid.uuid4())}).json()
VID = v["uuid"]
ok(v["status"] == "Published", f"publish v{v.get('version_no')} total {v['snapshot']['totals']['total']}")
cl = dm.get(f"{API}/contracts").json()
ok(any(c["contract_id"] == VID and c["status"] == "Issued" for c in cl["contracts"]), "REQ-112 contracts list Issued")
sh = dm.post(f"{API}/versions/{VID}/share").json()
tok = sh["token"]
pub = requests.get(f"{API}/public/proposals/{tok}").json()
ok(not any(k in str(pub).lower() for k in ["demo_session", "ws-demo", "unit_cost", "markup", "model_id", "saved_analysis"]), "REQ-119 public page has no demo/staff fields")
a = requests.post(f"{API}/public/proposals/{tok}/accept", json={"name": "Demo Customer", "email": "customer@example.com", "agree": True}).json()
c = dm.get(f"{API}/contracts/{VID}").json()
ok(c["status"] == "Accepted" and c["acceptance_evidence"]["name"] == "Demo Customer" and c["document"]["document_hash"] == v["document_hash"] and c["template_hash"], "contract detail Accepted + evidence + frozen hashes")
ok("Illustrative sample" not in dm.get(f"{API}/contracts/{VID}/print").text, "contract print HTML (no metacommentary)")
wo = dm.get(f"{API}/work-orders/{a['work_order_id']}").json()
crew = wo["crews"][0]["uuid"]
w = dm.patch(f"{API}/work-orders/{wo['uuid']}", json={"expected_revision": wo["revision"], "crew_id": crew, "scheduled_date": "2026-11-20", "access_status": "Requested"}).json()
ok(w["crew_id"] == crew and w["access_status"] == "Requested", "work order crew/date/access with demo crew")
jr = next(j for j in dm.get(f"{API}/office/jobs").json()["jobs"] if j["visit_id"] == RV)
ok(jr["contract_status"] == "Accepted" and jr["work_order_id"] == wo["uuid"] and jr["latest_version_no"] == 1, "office/jobs reflects version/contract/WO")

# foreman powers in demo: create + use the empty draft visit
sites = dm.get(f"{API}/sites").json()
nv = dm.post(f"{API}/visits", json={"uuid": str(uuid.uuid4()), "site_id": sites[0]["uuid"], "title": "demo visit", "processing_permission": "Granted"})
ok(nv.status_code == 200, f"demo user can create a field visit {nv.status_code}")

# Q-18 isolation: 10 probes, must all be 404 (or 403 for role)
est = login("estimator@ridgeline.example")
D2 = requests.post(f"{API}/demo/sessions").json(); d2 = sess(D2["token"])
probes = [dm.get(f"{API}/visits/v-seed-pinecrest"), dm.get(f"{API}/engagements/eng-seed-ready"), dm.get(f"{API}/sites/s-cascade/bundle"),
          dm.get(f"{API}/contracts/{est.get(f'{API}/contracts').json()['contracts'][0]['contract_id']}"),
          d2.get(f"{API}/visits/{RV}"), d2.get(f"{API}/engagements/{E}"), d2.get(f"{API}/work-orders/{wo['uuid']}"), d2.get(f"{API}/contracts/{VID}"),
          est.get(f"{API}/visits/{RV}"), est.get(f"{API}/evidence/{J['ready_to_estimate']['evidence_id']}/content")]
ok(all(p.status_code == 404 for p in probes), f"Q-18 isolation probes {[p.status_code for p in probes]}")
ok(not any(j["visit_id"] in (RV, BV) for j in d2.get(f"{API}/office/jobs").json()["jobs"]) and
   not any(j["visit_id"] == RV for j in est.get(f"{API}/office/jobs").json()["jobs"]), "office/jobs isolated both ways")
ok(dm.get(f"{API}/auth/me").json().get("role") != "admin" and dm.post(f"{API}/visits/{RV}/reopen", json={"expected_revision": 1}).status_code != 500, "no admin role")

# reset: new session, old history intact
R2 = requests.post(f"{API}/demo/sessions/{D['session_id']}/reset").json()
ok(R2["session_id"] != D["session_id"] and R2["reset_from"] == D["session_id"] and dm.get(f"{API}/contracts/{VID}").status_code == 200, "REQ-100 reset → new session, old kept")
fm = login("foreman@ridgeline.example")
ok(fm.get(f"{API}/office/jobs").status_code == 403 and fm.get(f"{API}/contracts").status_code == 403, "REQ-118 foreman 403 on office/contracts")
sp = requests.get(f"{API}/openapi.json").json()["paths"]
ok(all(p in sp for p in ["/api/demo/sessions", "/api/demo/sessions/{session_id}/reset", "/api/office/jobs", "/api/contracts", "/api/contracts/{cid}", "/api/contracts/{cid}/print"]), "OpenAPI current")
