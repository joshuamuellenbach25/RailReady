"""JRN-100/106 media privacy + JRN-94 anchor move persistence."""
from datetime import datetime, timedelta, timezone
import httpx, jwt
from p2helpers import demo, ready, publish, share
from p4helpers import wait_scene, ENV, ROOT, B


def test_scene_media_privacy_and_anchor_move():
    c, D = demo()
    c2, D2 = demo()
    J = D["jobs"]["ready_to_estimate"]; V, E = J["visit_id"], J["evidence_id"]
    sc = wait_scene(c, E)
    assert sc["status"] == "Ready", sc
    a = httpx.get(ROOT + sc["asset_url"])
    assert a.status_code == 200 and a.content.startswith(b"ply")
    exp = jwt.encode({"typ": "media", "uid": D["user"]["uuid"], "ws": D["workspace"]["uuid"], "ev": E, "sid": sc["scene_id"],
                      "exp": datetime.now(timezone.utc) - timedelta(seconds=5)}, ENV["JWT_SECRET"], algorithm="HS256")
    V2 = D2["jobs"]["ready_to_estimate"]["visit_id"]
    foreign_st = c2.get(f"/visits/{V2}/scenes").json()["scenes"][0]["thumbnail_url"].split("st=")[1]
    inv = c.get(f"/visits/{V}/inventory?evidence_id={E}").json()["items"]
    it = next(i for i in inv if i["located"])
    sid = sc["scene_id"]
    probes = {
        "asset_noauth": (httpx.get(f"{B}/scenes/{sid}/asset"), 401),
        "asset_expired": (httpx.get(f"{B}/scenes/{sid}/asset?st={exp}"), 401),
        "asset_foreign_st": (httpx.get(f"{B}/scenes/{sid}/asset?st={foreign_st}"), 404),
        "asset_other_ws": (c2.get(f"/scenes/{sid}/asset"), 404),
        "orig_noauth": (httpx.get(f"{B}/media/evidence/{E}/original"), 401),
        "orig_other_ws": (c2.get(f"/media/evidence/{E}/original"), 404),
        "orig_expired": (httpx.get(f"{B}/media/evidence/{E}/original?st={exp}"), 401),
        "thumb_other_ws": (c2.get(f"/media/evidence/{E}/thumbnail"), 404),
        "crop_noauth": (httpx.get(f"{B}/inventory-items/{it['item_id']}/crop"), 401),
        "crop_other_ws": (c2.get(f"/inventory-items/{it['item_id']}/crop"), 404),
    }
    codes = {k: r.status_code for k, (r, _) in probes.items()}
    for k, (r, want) in probes.items():
        assert r.status_code == want, codes
        assert not (r.content.startswith(b"ply") or r.content[:3] == b"\xff\xd8\xff"), k
    assert c.get(f"/inventory-items/{it['item_id']}/crop").content[:3] == b"\xff\xd8\xff"
    # JRN-94 anchor move
    an = it["anchor"]; before = it["review_state"]
    mv = c.put(f"/anchors/{an['anchor_id']}", json={"expected_version": an["version"], "image_point": [0.4, 0.6], "reason": "tscheck move"})
    assert mv.status_code == 200, mv.text[:300]
    assert mv.json()["version"] == an["version"] + 1 and mv.json()["placement"] == "manual"
    inv2 = {i["item_id"]: i for i in c.get(f"/visits/{V}/inventory?evidence_id={E}").json()["items"]}
    a2 = inv2[it["item_id"]]["anchor"]
    assert a2["version"] == an["version"] + 1 and inv2[it["item_id"]]["review_state"] == before
    assert any(a2.get(k) for k in ("moved_by", "actor", "updated_by", "created_by")), a2


def test_revoked_link_denies_media():
    c, D, e, s = ready()
    r = publish(c, e)
    assert r.status_code == 200, r.text[:300]
    sh = share(c, r.json()["uuid"])
    pub = httpx.get(f"{B}/public/proposals/{sh['token']}").json()
    url = ROOT + pub["photos"][0]["url"]
    assert httpx.get(url).status_code == 200
    assert c.post(f"/links/{sh['link_id']}/revoke").status_code == 200
    m2 = httpx.get(url)
    assert m2.status_code in (401, 403, 404) and m2.content[:3] != b"\xff\xd8\xff"
