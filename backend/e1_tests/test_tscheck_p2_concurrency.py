from p2helpers import *
import asyncio

OK = {"name": "tscheck Racer", "email": "tscheck@example.com", "agree": True}


def wo_count(c, e):
    j = c.get("/work-orders").json(); j = j if isinstance(j, list) else (j.get("work_orders") or j.get("items"))
    return [w for w in j if w["engagement_id"] == e]


async def _burst(calls):
    async with httpx.AsyncClient(timeout=60) as a:
        return await asyncio.gather(*[a.request(m, u, json=b, headers=h) for m, u, b, h in calls])


def test_ten_concurrent_accepts_one_work_order():
    c, D, e, v = published(); t = share(c, v["uuid"])["token"]
    rs = asyncio.run(_burst([("POST", B + f"/public/proposals/{t}/accept", OK, {})] * 10))
    ids = {r.json().get("work_order_id") for r in rs if r.status_code == 200}
    assert len(ids) == 1, [(r.status_code, r.text[:80]) for r in rs]
    r = httpx.post(B + f"/public/proposals/{t}/accept", json=OK)
    assert r.status_code == 200 and r.json()["work_order_id"] in ids
    assert len(wo_count(c, e)) == 1
    assert len([d for d in eng(c, e)["decisions"] if d.get("request_key") == "accept" or "ccept" in str(d.get("kind", ""))]) == 1


def test_accept_races_revoke_publish_changes():
    c, D, e, v = published(); sh = share(c, v["uuid"]); t = sh["token"]
    H = dict(c.headers)
    # prepare new publishable revision
    l = eng(c, e)["draft"]["lines"][0]
    c.patch(f"/engagements/{e}/lines/{l['uuid']}", json={"expected_revision": rev(c, e), "unit_cost": "63.00", "reviewed": True})
    c.get(f"/engagements/{e}/agreement-preview")
    rv = rev(c, e)
    calls = [("POST", B + f"/public/proposals/{t}/accept", OK, {})] * 3 + [
        ("POST", B + f"/links/{sh['link_id']}/revoke", None, H),
        ("POST", B + f"/engagements/{e}/publish", {"expected_revision": rv, "idempotency_key": "tscheck-race"}, H),
        ("POST", B + f"/public/proposals/{t}/changes", {**OK, "comment": "tscheck race", "request_key": "tscheck-race"}, {})]
    rs = asyncio.run(_burst(calls))
    wos = wo_count(c, e)
    assert len(wos) <= 1
    g = eng(c, e)
    if wos:
        assert wos[0]["accepted_version_id"] == v["uuid"]
        assert not [d for d in g["decisions"] if "tscheck race" in str(d)], "change request also stored after accept"
        assert not [x for x in g["versions"] if x.get("version_no") == 2 and x.get("status") != "Void"], "v2 published after acceptance"


def test_publish_after_accept_409():
    c, D, e, v = published(); t = share(c, v["uuid"])["token"]
    wid = httpx.post(B + f"/public/proposals/{t}/accept", json=OK).json()["work_order_id"]
    l = eng(c, e)["draft"]["lines"][0]
    c.patch(f"/engagements/{e}/lines/{l['uuid']}", json={"expected_revision": rev(c, e), "unit_cost": "64.00", "reviewed": True})
    r = publish(c, e)
    assert r.status_code == 409 and "Engagement already accepted" in r.text, (r.status_code, r.text[:200])
    assert [w["uuid"] for w in wo_count(c, e)] == [wid]
