from conftest import client, login, new_visit, add_note
import uuid

def test_wrong_password():
    r = client().post("/auth/login", json={"email": "estimator@ridgeline.example", "password": "wrong-" + uuid.uuid4().hex[:4]})
    assert r.status_code == 401 and "Invalid email or password" in r.text

def test_sites_scoped(fm):
    ids = {s["uuid"] for s in fm.get("/sites").json()}
    assert {"s-cascade", "s-pinecrest"} <= ids and "s-iso" not in ids

def test_foreign_ids_404_no_write(fm):
    iso = login("foreman@isolation.example")
    v = new_visit(fm, "auth")
    ev = add_note(fm, v["uuid"], "tscheck-auth note")
    assert fm.get("/visits/v-seed-iso").status_code == 404
    assert iso.get(f"/visits/{v['uuid']}").status_code == 404
    assert iso.get(f"/evidence/{ev['uuid']}/content").status_code == 404
    r = iso.patch(f"/visits/{v['uuid']}", json={"expected_revision": v["revision"], "title": "hacked"})
    assert r.status_code == 404
    r = iso.post(f"/visits/{v['uuid']}/observations", json={"uuid": str(uuid.uuid4()), "kind": "location", "text": "x"})
    assert r.status_code == 404
    assert fm.get(f"/visits/{v['uuid']}").json()["title"].startswith("tscheck-auth")
    assert len(fm.get(f"/visits/{v['uuid']}/observations").json()) == 0
