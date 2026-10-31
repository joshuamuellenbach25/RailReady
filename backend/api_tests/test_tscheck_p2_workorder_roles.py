from p2helpers import *
import re, uuid
from conftest import login

OK = {"name": "tscheck WO", "email": "tscheck@example.com", "agree": True}


def test_work_order_access_flow_and_print():
    c, D, e, v = published(); t = share(c, v["uuid"])["token"]
    wid = httpx.post(B + f"/public/proposals/{t}/accept", json=OK).json()["work_order_id"]
    wo = c.get(f"/work-orders/{wid}").json(); wo = wo.get("work_order", wo)
    assert wo["access_status"] == "Not arranged"
    frozen = wo["frozen_scope"]
    crews = wo.get("crews") or c.get(f"/work-orders/{wid}").json().get("crews") or []
    body = {"expected_revision": wo["revision"], "access_status": "Requested", "scheduled_date": "2026-12-01"}
    if crews:
        body["crew_id"] = crews[0]["uuid"]
    r = c.patch(f"/work-orders/{wid}", json=body); assert r.status_code == 200, r.text[:300]
    w2 = r.json(); w2 = w2.get("work_order", w2)
    r = c.patch(f"/work-orders/{wid}", json={"expected_revision": w2["revision"], "access_status": "Confirmed"}); assert r.status_code == 200
    w3 = c.get(f"/work-orders/{wid}").json(); w3 = w3.get("work_order", w3)
    assert w3["access_status"] == "Confirmed" and w3["frozen_scope"] == frozen
    h = w3["access_history"]
    assert [x.get("to") or x.get("status") for x in h][-2:] == ["Requested", "Confirmed"] and all(x.get("by") or x.get("by_name") for x in h), h
    txt = str(w3).lower()
    assert "repaired" not in txt and "released" not in txt
    for pr in (c.get(f"/proposals/{v['uuid']}/print").text, httpx.get(B + f"/public/proposals/{t}/print").text):
        ns = re.sub(r"<style.*?</style>", "", pr, flags=re.S)
        for w in ("Ridgeline Rail Services", v["visit_id"], "Cascade", "3956.20", "Net 30", "America/Los_Angeles"):
            assert w in ns, w
        for w in ("unit_cost", "markup", "internal_cost", "transcript", "model_id"):
            assert w not in ns, w


def test_roles_and_cross_workspace():
    c, D, e, v = published()
    fm = login("foreman@ridgeline.example")
    assert fm.get(f"/engagements/{e}").status_code in (403, 404)
    r = fm.get("/office/inbox"); assert r.status_code == 403
    iso = login("foreman@isolation.example")
    assert iso.get("/office/inbox").status_code == 403
    est = login("estimator@ridgeline.example")  # other workspace than demo
    for p in (f"/engagements/{e}", f"/versions/{v['uuid']}", f"/proposals/{v['uuid']}/print"):
        assert est.get(p).status_code == 404, p
    assert est.post(f"/versions/{v['uuid']}/share").status_code == 404
    assert est.get(f"/work-orders/{uuid.uuid4()}").status_code == 404
    assert len(c.get(f"/engagements/{e}").json()["versions"]) == 1
