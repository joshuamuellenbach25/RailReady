"""JRN-86/87/93/97/98/103: per-photo scenes, idempotency, EXIF, failure+retry, unsupported."""
import os
from p2helpers import demo
from p4helpers import wait_scene, upload, variants, mdb, LABEL, UNSUP


def test_scenes_per_photo_exif_idempotent_failure_unsupported():
    c, D = demo()
    V = D["jobs"]["empty_draft"]["visit_id"]
    land, portrait, rot = variants()
    heic = b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00mif1heic" + os.urandom(1500)
    ups = {n: upload(c, V, d, m, f) for n, d, m, f in [
        ("land", land, "image/jpeg", "tscheck-land.jpg"), ("portrait", portrait, "image/jpeg", "tscheck-portrait.jpg"),
        ("exif6", rot, "image/jpeg", "tscheck-exif6.jpg"), ("heic", heic, "image/heic", "tscheck.heic")]}
    c.post(f"/visits/{V}/manifests", json={"members": [{"evidence_id": e, "sha256": h, "size": 0} for e, h in ups.values()]})
    res = {n: wait_scene(c, e) for n, (e, _) in ups.items()}
    js = {n: res[n]["status"] for n in res}
    for n in ("land", "portrait", "exif6"):
        assert res[n]["status"] == "Ready", js
        assert res[n]["label"] == LABEL
        m = res[n]["model"]
        assert m["id"] and m["revision"] and m["onnx_sha256"]
    assert len({res[n]["scene_id"] for n in ("land", "portrait", "exif6")}) == 3
    assert len({res[n]["source_sha256"] for n in ("land", "portrait", "exif6")}) == 3
    # EXIF / orientation (JRN-93)
    e6 = res["exif6"]
    assert e6["exif_transform"]["exif_orientation"] == 6
    assert e6["oriented_height"] > e6["oriented_width"]
    assert res["portrait"]["oriented_height"] > res["portrait"]["oriented_width"]
    assert res["land"]["oriented_width"] > res["land"]["oriented_height"]
    # unsupported (JRN-98), original retained
    assert res["heic"]["status"] == "Unsupported" and res["heic"]["error"] == UNSUP, res["heic"]
    assert c.get(f"/evidence/{ups['heic'][0]}/content").content == heic
    # idempotent re-trigger (JRN-87/103)
    le = ups["land"][0]
    db = mdb()
    n_img = db.image_analysis_runs.count_documents({"evidence_id": le})
    n_sc = db.scenes.count_documents({"evidence_id": le})
    for _ in range(5):
        assert c.get(f"/evidence/{le}/scene").status_code == 200
        c.get(f"/visits/{V}/inventory")
    r = c.post(f"/evidence/{le}/scene/retry", json={})
    assert r.status_code == 200 and r.json()["scene_id"] == res["land"]["scene_id"] and r.json()["scene_revision"] == res["land"]["scene_revision"]
    assert db.image_analysis_runs.count_documents({"evidence_id": le}) == n_img
    assert db.scenes.count_documents({"evidence_id": le}) == n_sc
    # fault + retry without reupload (JRN-97)
    assert c.post("/dev/fault", json={"visit_id": V, "stage": "depth", "target_id": le}).status_code in (200, 201)
    c.post(f"/evidence/{le}/scene/retry", json={"regenerate": True})
    f = wait_scene(c, le, want=("Failed",), t=60)
    assert f["status"] == "Failed" and f["error"], f
    assert c.get(f"/media/evidence/{le}/original").status_code == 200
    assert c.get(f"/visits/{V}/inventory").status_code == 200
    c.post(f"/evidence/{le}/scene/retry", json={})
    ok = wait_scene(c, le, want=("Ready",), t=90)
    assert ok["status"] == "Ready" and ok["scene_revision"] > f["scene_revision"] - 1, ok
