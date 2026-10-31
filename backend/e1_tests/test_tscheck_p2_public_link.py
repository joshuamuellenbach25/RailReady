from p2helpers import *
import json, re, time, uuid, datetime
from zoneinfo import ZoneInfo

FORBIDDEN = ["unit_cost", "markup", "margin_pct", "internal_cost", "internal_snapshot", "transcript", "candidate", "model_id", "storage_path", "Dismissed"]


def test_public_allowlist_media_404():
    c, D, e, v = published()
    t = share(c, v["uuid"])["token"]
    p = httpx.get(B + f"/public/proposals/{t}")
    assert p.status_code == 200
    body = p.text
    for w in FORBIDDEN:
        assert w not in body, w
    assert p.json()["expiry"]["timezone"] and p.json()["expiry"]["utc"]
    pr = httpx.get(B + f"/public/proposals/{t}/print").text
    pr_nostyle = re.sub(r"<style.*?</style>", "", pr, flags=re.S)
    for w in FORBIDDEN:
        assert w not in pr_nostyle, w
    url = p.json()["photos"][0]["url"]
    assert httpx.get("http://localhost:8001" + url).status_code == 200
    assert httpx.get(B + f"/public/proposals/{t}/media/{uuid.uuid4()}").status_code == 404
    # an unselected evidence of the same visit
    sel = set(eng(c, e)["draft"]["selected_photo_ids"])
    others = [x["uuid"] for x in c.get(f"/visits/{v['visit_id']}/evidence").json() if x["uuid"] not in sel] if isinstance(c.get(f"/visits/{v['visit_id']}/evidence").json(), list) else []
    for o in others:
        assert httpx.get(B + f"/public/proposals/{t}/media/{o}").status_code == 404


def test_revoke_denies_and_new_link_same_version():
    c, D, e, v = published()
    sh = share(c, v["uuid"]); t = sh["token"]
    url = httpx.get(B + f"/public/proposals/{t}").json()["photos"][0]["url"]
    assert c.post(f"/links/{sh['link_id']}/revoke").status_code == 200
    assert httpx.get(B + f"/public/proposals/{t}").status_code in (403, 404, 410)
    assert httpx.get("http://localhost:8001" + url).status_code in (403, 404, 410)
    a = httpx.post(B + f"/public/proposals/{t}/accept", json={"name": "tscheck", "email": "t@example.com", "agree": True})
    assert a.status_code in (403, 404, 410)
    assert eng(c, e)["work_order"] is None
    t2 = share(c, v["uuid"])["token"]
    p2 = httpx.get(B + f"/public/proposals/{t2}").json()
    assert p2["version_no"] == 1 and p2["snapshot_hash"] == v["snapshot_hash"]


def test_expiry_site_local_then_rejected():
    c, D, e, s = ready()
    tz = c.get("/auth/me").json().get("workspace", {}).get("timezone") or D["workspace"]["timezone"]
    loc = (datetime.datetime.now(ZoneInfo(tz)) + datetime.timedelta(minutes=1)).replace(second=0, microsecond=0) + datetime.timedelta(minutes=1)
    local = loc.strftime("%Y-%m-%dT%H:%M")
    r = c.patch(f"/engagements/{e}/draft", json={"expected_revision": rev(c, e), "expiry_local": local}); assert r.status_code == 200
    r = publish(c, e); assert r.status_code == 200, r.text[:300]
    t = share(c, r.json()["uuid"])["token"]
    ex = httpx.get(B + f"/public/proposals/{t}").json()["expiry"]
    assert ex["local"] == local
    assert datetime.datetime.fromisoformat(ex["utc"]) == loc.astimezone(datetime.timezone.utc)
    time.sleep(max(0, (loc - datetime.datetime.now(ZoneInfo(tz))).total_seconds()) + 3)
    a = httpx.post(B + f"/public/proposals/{t}/accept", json={"name": "tscheck", "email": "t@example.com", "agree": True})
    assert a.status_code >= 400 and "This proposal has expired" in a.text, a.text[:200]
