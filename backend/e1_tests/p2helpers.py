import httpx, uuid
B = "http://localhost:8001/api"


def demo():
    import time
    for _ in range(40):
        r = httpx.post(B + "/demo/sessions", timeout=60)
        if r.status_code != 429:
            break
        time.sleep(10)  # demo-session creation is rate limited per IP
    assert r.status_code in (200, 201), r.text[:200]
    D = r.json()
    c = httpx.Client(base_url=B, headers={"Authorization": "Bearer " + D["token"]}, timeout=120)
    return c, D


def eng(c, e):
    return c.get(f"/engagements/{e}").json()


def rev(c, e):
    return eng(c, e)["draft"]["revision"]


def review_all(c, e):
    for l in eng(c, e)["draft"]["lines"]:
        if not l.get("reviewed"):
            r = c.patch(f"/engagements/{e}/lines/{l['uuid']}", json={"expected_revision": rev(c, e), "reviewed": True})
            assert r.status_code == 200, r.text[:300]


def ready(c=None, D=None, package=True):
    if c is None:
        c, D = demo()
    j = D["jobs"]["ready_to_estimate"]
    if package:
        r = c.post(f"/scope-items/{j['scope_item_id']}/package")
        assert r.status_code == 200, r.text[:300]
        review_all(c, j["engagement_id"])
    return c, D, j["engagement_id"], j["scope_item_id"]


def publish(c, e, key=None):
    c.get(f"/engagements/{e}/agreement-preview")
    r = c.post(f"/engagements/{e}/publish", json={"expected_revision": rev(c, e), "idempotency_key": key or uuid.uuid4().hex})
    return r


def published(key=None):
    c, D, e, s = ready()
    r = publish(c, e, key)
    assert r.status_code == 200, r.text[:500]
    return c, D, e, r.json()


def share(c, vid):
    r = c.post(f"/versions/{vid}/share")
    assert r.status_code == 200, r.text[:300]
    return r.json()
