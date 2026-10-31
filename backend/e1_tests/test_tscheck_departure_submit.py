from conftest import new_visit, add_note, field, est as _e

def test_departure_relevance_submit_stale(fm):
    v = new_visit(fm, "depart")
    vid = v["uuid"]
    d = fm.get(f"/visits/{vid}/departure").json()
    assert d["question"]["field"] and isinstance(d["question"]["prompt"], str)
    cur = fm.get(f"/visits/{vid}").json()
    r = fm.post(f"/visits/{vid}/fields/tie_specification", json={"expected_revision": cur["revision"], "action": "answer", "value": ""})
    assert r.status_code == 422
    assert field(fm, vid, "tie_specification")["state"] == "Missing required"
    r = fm.post(f"/visits/{vid}/fields/work_location", json={"expected_revision": cur["revision"], "action": "answer", "value": "yeah fine", "source": "departure_check"})
    assert r.status_code == 200, r.text
    f = field(fm, vid, "work_location")
    assert f["state"] == "Needs review" and f["review_reason"] == "Answer may not address the question", f
    # stale
    r = fm.patch(f"/visits/{vid}", json={"expected_revision": cur["revision"], "title": "tscheck-stale"})
    assert r.status_code == 409 and "recovery copy" in r.text
    cur = fm.get(f"/visits/{vid}").json()
    r = fm.post(f"/visits/{vid}/submit", json={"expected_revision": cur["revision"]})
    assert r.status_code == 200, r.text
    r = fm.patch(f"/visits/{vid}", json={"expected_revision": r.json()["revision"], "title": "x"})
    assert r.status_code == 423
