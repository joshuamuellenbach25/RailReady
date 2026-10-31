from conftest import new_visit
import uuid

def test_observations_and_not_inspected(fm):
    v = new_visit(fm, "capture")
    vid = v["uuid"]
    r = fm.post(f"/visits/{vid}/observations", json={"uuid": str(uuid.uuid4()), "kind": "measurement", "label": "gauge", "value": "56.5", "unit": "in"})
    assert r.status_code == 200, r.text
    r = fm.post(f"/visits/{vid}/observations", json={"uuid": str(uuid.uuid4()), "kind": "not_inspected", "area": "Spur 2", "reason": "Cars spotted"})
    assert r.status_code == 200, r.text
    r = fm.post(f"/visits/{vid}/observations", json={"uuid": str(uuid.uuid4()), "kind": "not_inspected", "area": "Spur 3", "reason": "x", "quantity": 4})
    assert r.status_code == 422
    r = fm.post(f"/visits/{vid}/observations", json={"uuid": str(uuid.uuid4()), "kind": "not_inspected", "area": "Spur 3"})
    assert r.status_code == 422
    # idempotent uuid
    u = str(uuid.uuid4())
    a = fm.post(f"/visits/{vid}/observations", json={"uuid": u, "kind": "location", "text": "dup"}).json()
    b = fm.post(f"/visits/{vid}/observations", json={"uuid": u, "kind": "location", "text": "dup"}).json()
    assert a["uuid"] == b["uuid"]
    assert len(fm.get(f"/visits/{vid}/observations").json()) == 3

def test_bundle_prepare(fm):
    r = fm.get("/sites/s-pinecrest/bundle")
    assert r.status_code == 200 and r.json()
