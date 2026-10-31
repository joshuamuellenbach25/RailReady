import os
import hashlib, time, uuid, pathlib
import httpx, pytest

BASE = "http://localhost:8001/api"
PW = os.environ["SEED_PASSWORD"]
ROOT = pathlib.Path(__file__).resolve().parent.parent


def client():
    return httpx.Client(base_url=BASE, timeout=180)


def login(email):
    c = client()
    r = c.post("/auth/login", json={"email": email, "password": PW})
    assert r.status_code == 200, r.text
    c.headers["Authorization"] = "Bearer " + r.json()["token"]
    return c


@pytest.fixture
def fm():
    return login("foreman@ridgeline.example")


@pytest.fixture
def est():
    return login("estimator@ridgeline.example")


def new_visit(c, slug, site="s-pinecrest", perm="Granted"):
    r = c.post("/visits", json={"uuid": str(uuid.uuid4()), "site_id": site,
                                "title": f"tscheck-{slug}-{uuid.uuid4().hex[:6]}", "processing_permission": perm})
    assert r.status_code == 200, r.text
    return r.json()


def add_note(c, vid, text):
    b = text.encode()
    r = c.post(f"/visits/{vid}/evidence", json={"uuid": str(uuid.uuid4()), "kind": "note",
               "sha256": hashlib.sha256(b).hexdigest(), "size": len(b), "mime": "text/plain", "text": text})
    assert r.status_code == 200, r.text
    return r.json()


def add_file(c, vid, path, kind, mime, upload=True, verify=True):
    b = pathlib.Path(path).read_bytes()
    r = c.post(f"/visits/{vid}/evidence", json={"uuid": str(uuid.uuid4()), "kind": kind,
               "sha256": hashlib.sha256(b).hexdigest(), "size": len(b), "mime": mime, "filename": pathlib.Path(path).name})
    assert r.status_code == 200, r.text
    ev = r.json()
    if upload:
        r = c.put(f"/evidence/{ev['uuid']}/content", files={"file": (pathlib.Path(path).name, b, mime)})
        assert r.status_code == 200, r.text
    if verify:
        r = c.post(f"/evidence/{ev['uuid']}/verify")
        assert r.status_code == 200, r.text
    return ev


def manifest(c, vid, evs):
    r = c.post(f"/visits/{vid}/manifests", json={"members": [
        {"evidence_id": e["uuid"], "sha256": e["sha256"], "size": e["size"]} for e in evs]})
    assert r.status_code == 200, r.text
    return r.json()


def wait_jobs(c, vid, timeout=150):
    end = time.time() + timeout
    while time.time() < end:
        p = c.get(f"/visits/{vid}/processing").json()
        sts = [s["status"] for t in p["by_evidence"].values() for s in t.values()]
        if sts and all(s in ("Done", "Failed", "Blocked") for s in sts):
            return p
        time.sleep(3)
    return p


def field(c, vid, name):
    return next(f for f in c.get(f"/visits/{vid}/proposals").json()["fields"] if f["field"] == name)
