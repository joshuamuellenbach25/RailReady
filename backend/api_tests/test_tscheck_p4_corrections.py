"""JRN-105 whole-number tie qty; JRN-109 publish→accept+duplicate accept→one work order."""
import uuid
import httpx
from p2helpers import demo, ready, publish, share, rev, eng, B


def test_tie_whole_number():
    c, D = demo()
    E = D["jobs"]["ready_to_estimate"]["engagement_id"]
    body = {"category": "material", "description": "tscheck-crosstie", "unit": "each", "unit_cost": "62.50",
            "markup_pct": "20", "taxable": True, "reason": "tscheck"}
    bad = c.post(f"/engagements/{E}/lines", json={**body, "expected_revision": rev(c, E), "quantity": "8.5"})
    assert bad.status_code == 422 and bad.json()["detail"]["message"] == "Whole number required", bad.text[:300]
    good = c.post(f"/engagements/{E}/lines", json={**body, "expected_revision": rev(c, E), "quantity": "8"})
    assert good.status_code == 200, good.text[:300]


def test_accept_duplicate_one_work_order():
    c, D, e, s = ready()
    r = publish(c, e)
    assert r.status_code == 200, r.text[:300]
    ver = r.json()
    sh = share(c, ver["uuid"])
    t = sh["token"]
    pub = httpx.get(f"{B}/public/proposals/{t}").json()
    key = uuid.uuid4().hex
    payloads = [{"name": "tscheck Customer", "email": "t@example.com", "agree": True}]
    a1 = httpx.post(f"{B}/public/proposals/{t}/accept", json=payloads[0])
    a2 = httpx.post(f"{B}/public/proposals/{t}/accept", json=payloads[0])
    assert a1.status_code == 200, a1.text[:400]
    assert a2.status_code == 200, a2.text[:300]
    assert a1.json()["work_order_id"] == a2.json()["work_order_id"]
    wos = [w for w in c.get("/work-orders").json() if (w.get("engagement_id") == e)]
    assert len(wos) == 1, wos
    after = httpx.get(f"{B}/public/proposals/{t}").json()
    assert after.get("version", {}).get("uuid", ver["uuid"]) == pub.get("version", {}).get("uuid", ver["uuid"])
