from conftest import new_visit, add_note, manifest, wait_jobs
import uuid

def test_forced_failure_and_retry(fm):
    v = new_visit(fm, "fault")
    fm.post("/dev/fault", json={"visit_id": v["uuid"], "stage": "extraction"}).raise_for_status()
    ev = add_note(fm, v["uuid"], "inspected four ties")
    manifest(fm, v["uuid"], [ev])
    p = wait_jobs(fm, v["uuid"])
    j = p["by_evidence"][ev["uuid"]]["extraction"]
    assert j["status"] == "Failed" and j["error_stage"], j
    r = fm.post(f"/jobs/{j['uuid']}/retry")
    assert r.status_code == 200, r.text
    p = wait_jobs(fm, v["uuid"])
    assert p["by_evidence"][ev["uuid"]]["extraction"]["status"] == "Done"
    assert len(fm.get(f"/visits/{v['uuid']}/evidence").json()) == 1

def test_denied_permission_blocks(fm):
    v = new_visit(fm, "denied", perm="Denied")
    ev = add_note(fm, v["uuid"], "inspected four ties")
    manifest(fm, v["uuid"], [ev])
    p = fm.get(f"/visits/{v['uuid']}/processing").json()
    assert p["blocker"]
    assert all(s["status"] == "Blocked" for s in p["by_evidence"][ev["uuid"]].values()), p
    assert fm.get(f"/visits/{v['uuid']}/proposals").json()["runs"] == []
    tc = fm.get(f"/evidence/{ev['uuid']}/text-checks").json()["checks"]
    assert all(c["status"] == "Not run" for c in tc)
    cur = fm.get(f"/visits/{v['uuid']}").json()
    r = fm.post(f"/visits/{v['uuid']}/fields/inspected_quantity", json={"expected_revision": cur["revision"], "action": "answer", "value": "4"})
    assert r.status_code == 200, r.text
