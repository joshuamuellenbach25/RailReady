from p2helpers import *

OK = {"name": "tscheck Customer", "email": "tscheck@example.com", "agree": True}


def test_accept_field_errors_no_decision():
    c, D, e, v = published(); t = share(c, v["uuid"])["token"]
    for bad in [{**OK, "name": ""}, {**OK, "email": "not-an-email"}, {**OK, "agree": False}]:
        r = httpx.post(B + f"/public/proposals/{t}/accept", json=bad)
        assert r.status_code == 422 and r.json()["detail"]["errors"], r.text[:200]
    g = eng(c, e)
    assert g["decisions"] == [] and g["work_order"] is None


def test_change_request_topic_and_copy():
    c, D, e, v = published(); t = share(c, v["uuid"])["token"]
    r = httpx.post(B + f"/public/proposals/{t}/changes", json={**OK, "comment": "Can you lower the trip charge?", "request_key": "tscheck-cr"})
    assert r.status_code == 200, r.text[:300]
    assert "price" not in r.text.lower() or "topic" not in r.text
    pub = httpx.get(B + f"/public/proposals/{t}")
    assert pub.json()["can_decide"] is False and "topic" not in pub.text
    assert httpx.post(B + f"/public/proposals/{t}/accept", json=OK).status_code >= 400
    d = eng(c, e)["decisions"]
    cr = [x for x in d if "trip charge" in str(x)]
    assert cr and cr[0].get("email") == OK["email"] and cr[0].get("version_id") == v["uuid"], cr
    assert "price" in str(cr[0]).lower(), cr[0]
    r = c.post(f"/versions/{v['uuid']}/copy-to-draft"); assert r.status_code == 200, r.text[:300]
    dr = eng(c, e)["draft"]
    assert any("trip charge" in str(h) for h in dr["feedback_history"])
    l = dr["lines"][0]
    assert c.patch(f"/engagements/{e}/lines/{l['uuid']}", json={"expected_revision": dr["revision"], "unit_cost": "60.00", "reviewed": True}).status_code == 200


def test_valid_accept_binds_and_one_work_order():
    c, D, e, v = published(); t = share(c, v["uuid"])["token"]
    r = httpx.post(B + f"/public/proposals/{t}/accept", json=OK)
    assert r.status_code == 200 and r.json()["status"] == "Accepted", r.text[:300]
    g = eng(c, e)
    acc = [x for x in g["decisions"] if "ccept" in str(x.get("kind", x.get("type", x)))]
    assert acc and acc[0].get("version_id") == v["uuid"] and acc[0].get("agreement_hash") == v["document_hash"], acc
    assert g["work_order"]["uuid"] == r.json()["work_order_id"]
    j = c.get("/work-orders").json(); j = j if isinstance(j, list) else (j.get("work_orders") or j.get("items"))
    wos = [w for w in j if w["engagement_id"] == e]
    assert len(wos) == 1
    assert any(x["status"] == "Accepted" for x in c.get("/contracts").json()["contracts"] if x["version_id"] == v["uuid"])
