from conftest import new_visit, add_file, add_note, manifest, ROOT
import hashlib

PHOTO = ROOT / "test_photos/tie_old_rotten.jpg"

def test_verified_receipt_idempotent(fm):
    v = new_visit(fm, "sync", perm="Denied")
    ev = add_file(fm, v["uuid"], PHOTO, "photo", "image/jpeg")
    again = fm.get(f"/visits/{v['uuid']}/evidence").json()
    assert [e["upload_state"] for e in again] == ["Verified"]
    m1 = manifest(fm, v["uuid"], [ev]); m2 = manifest(fm, v["uuid"], [ev])
    assert m1["state"] == "Received complete" and m1["receipt_id"]
    assert m1["uuid"] == m2["uuid"] and m1["receipt_id"] == m2["receipt_id"]
    assert len(fm.get(f"/visits/{v['uuid']}/evidence").json()) == 1

def test_partial_hash_mismatch_blocks_submit(fm):
    v = new_visit(fm, "partial", perm="Denied")
    ok = add_note(fm, v["uuid"], "tscheck partial ok")
    b = PHOTO.read_bytes()
    bad = add_file(fm, v["uuid"], PHOTO, "photo", "image/jpeg", upload=False, verify=False)
    r = fm.put(f"/evidence/{bad['uuid']}/content", files={"file": ("x.jpg", b[:-10] + b"corrupted!", "image/jpeg")})
    r2 = fm.post(f"/evidence/{bad['uuid']}/verify")
    assert r2.status_code != 200 or r2.json()["upload_state"] != "Verified", r2.text
    m = manifest(fm, v["uuid"], [ok, bad])
    assert m["state"] == "Receiving partial" and not m.get("receipt_id"), m
    cur = fm.get(f"/visits/{v['uuid']}").json()
    r = fm.post(f"/visits/{v['uuid']}/submit", json={"expected_revision": cur["revision"]})
    assert r.status_code == 409 and r.json()["detail"]["missing"] >= 1, r.text
