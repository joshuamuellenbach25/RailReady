from conftest import new_visit, add_file, manifest, wait_jobs, ROOT
import hashlib

def test_real_photo_candidates_review(fm):
    v = new_visit(fm, "image")
    ev = add_file(fm, v["uuid"], ROOT / "test_photos/tie_disintegrated.jpg", "photo", "image/jpeg")
    manifest(fm, v["uuid"], [ev])
    wait_jobs(fm, v["uuid"], 200)
    a = fm.get(f"/evidence/{ev['uuid']}/analysis").json()
    assert a["runs"], a
    run = a["runs"][-1]
    assert run["status"] == "Done", run
    s = str(run)
    assert "claude-sonnet-4-5" in s or "claude-sonnet-5-5" in s, run.get("model_id")
    assert run.get("prompt_version") and ev["sha256"] in s and run.get("raw_responses") is not None
    assert "Track clear" not in str(a)
    assert a["candidates"], "expected at least one candidate on a disintegrated tie"
    c = a["candidates"][0]
    for k in ("region", "visible_reason", "assessability", "uncertainty"):
        assert c.get(k) not in (None, ""), (k, c)
    # out of bounds rejected
    r = fm.post(f"/evidence/{ev['uuid']}/candidates", json={"category": c["category"], "region": [0.9, 0.9, 0.5, 0.5],
               "visible_reason": "tscheck", "assessability": "assessable", "uncertainty": "high"})
    assert r.status_code == 422 and "region" in r.text.lower(), r.text
    r = fm.post(f"/candidates/{c['uuid']}/decision", json={"action": "confirm", "expected_revision": c["revision"]})
    assert r.status_code == 200, r.text
    oid = r.json()["linked_observation_id"]
    obs = next(o for o in fm.get(f"/visits/{v['uuid']}/observations").json() if o["uuid"] == oid)
    assert obs["quantity"] is None and obs["specification"] is None
    m = fm.post(f"/evidence/{ev['uuid']}/candidates", json={"category": c["category"], "visible_reason": "tscheck dismiss",
               "assessability": "assessable", "uncertainty": "high"})
    assert m.status_code == 200, m.text
    m = m.json()
    r = fm.post(f"/candidates/{m['uuid']}/decision", json={"action": "dismiss", "expected_revision": m["revision"]})
    assert r.status_code == 200
    a2 = fm.get(f"/evidence/{ev['uuid']}/analysis").json()
    assert any(x["uuid"] == m["uuid"] and x["review_state"] == "Dismissed" for x in a2["candidates"])
