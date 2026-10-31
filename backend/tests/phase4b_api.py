"""Phase 4b API journeys (V01–V15 backend parts): photo-scene routes, jobs, signed assets, anchors, saved view, faults, lazy regeneration."""
import hashlib, io, os, sys, time, uuid
sys.path.insert(0, "/app/backend"); os.chdir("/app/backend")
from dotenv import load_dotenv; load_dotenv(".env")
import numpy as np, pymongo, requests
import photo_scene_processor as P

API = os.environ.get("API", "http://localhost:8001/api")
BASE = API[:-4]
mdb = pymongo.MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def ok(c, m):
    print(("PASS " if c else "FAIL ") + m, flush=True)


def sess(tok):
    s = requests.Session(); s.headers["Authorization"] = "Bearer " + tok; return s


def poll(s, job_id, t=90):
    end = time.time() + t
    while time.time() < end:
        j = s.get(f"{API}/photo-scene-jobs/{job_id}").json()
        if j["status"] not in ("queued", "processing"):
            return j
        time.sleep(1.2)
    return j


def scene_for(s, eid):
    r = s.post(f"{API}/evidence/{eid}/photo-scene")
    if r.status_code == 200:
        return r.status_code, r.json(), None
    j = poll(s, r.json()["job_id"])
    return r.status_code, j, r.json()


def upload(s, vid, data, mime, fn):
    eid = str(uuid.uuid4()); h = hashlib.sha256(data).hexdigest()
    s.post(f"{API}/visits/{vid}/evidence", json={"uuid": eid, "kind": "photo", "sha256": h, "size": len(data), "mime": mime, "filename": fn}).raise_for_status()
    s.put(f"{API}/evidence/{eid}/content", files={"file": (fn, data, mime)}).raise_for_status()
    s.post(f"{API}/evidence/{eid}/verify").raise_for_status()
    return eid


D = requests.post(f"{API}/demo/sessions").json(); dm = sess(D["token"])
D2 = requests.post(f"{API}/demo/sessions").json(); d2 = sess(D2["token"])
J = D["jobs"]; RV, EVV, PE = J["ready_to_estimate"]["visit_id"], J["empty_draft"]["visit_id"], J["ready_to_estimate"]["evidence_id"]

# V01 create → 202 job → ready; repeat → 200 same scene
t = time.time()
code, j, first = scene_for(dm, PE)
ok(code == 202 and j["status"] == "ready" and j["scene_id"] and j["started_at"] and j["completed_at"], f"V01 202 → job ready in {time.time()-t:.1f}s")
SID = j["scene_id"]
r = dm.post(f"{API}/evidence/{PE}/photo-scene")
ok(r.status_code == 200 and r.json()["scene_id"] == SID, "V01 repeat → 200 same scene (no new generation)")

# V02 scene payload + manifest + signed assets
sc = dm.get(f"{API}/photo-scenes/{SID}").json()
m = sc["manifest"]
ok(sc["status"] == "ready" and m["schema_version"] == 1 and m["processor_revision"] == "photo-scene-v1" and m["model"]["sha256"] == P.MODEL["sha256"]
   and sc["scene_hash"] and set(sc["assets"]) >= {"splat", "oriented_photo", "original"}, f"V02 scene ready, manifest v1, vertices {m['splat']['vertex_count']}")
sp = requests.get(BASE + sc["assets"]["splat"]["url"])
ok(sp.status_code == 200 and hashlib.sha256(sp.content).hexdigest() == sc["assets"]["splat"]["sha256"] == m["artifacts"]["splat"]["sha256"]
   and len(sp.content) == sc["assets"]["splat"]["byte_length"] and P.PLY_COMMENT.encode() in sp.content[:300], f"V02 splat via signed url sha ok ({len(sp.content)} B)")
op = requests.get(BASE + sc["assets"]["oriented_photo"]["url"]); og = requests.get(BASE + sc["assets"]["original"]["url"])
ok(op.status_code == 200 and op.content[:4] == b"\x89PNG" and og.status_code == 200 and hashlib.sha256(og.content).hexdigest() == sc["assets"]["original"]["sha256"], "oriented photo + original via signed urls")
pre = requests.options(BASE + sc["assets"]["splat"]["url"], headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"})
ok(pre.headers.get("access-control-allow-origin") in ("*", "http://localhost:3000"), "CORS for site origin on signed asset")
sc2 = dm.get(f"{API}/photo-scenes/{SID}").json()
ok(sc2["assets"]["splat"]["url"] != sc["assets"]["splat"]["url"] and sc2["assets"]["splat"]["sha256"] == sc["assets"]["splat"]["sha256"], "expiry refresh → new url, same artifact")
dg = dm.get(f"{API}/photo-scenes/{SID}/assets/depth_grid")
z = np.load(io.BytesIO(dg.content), allow_pickle=False)
ok(dg.status_code == 200 and z.shape == (m["display"]["height"], m["display"]["width"]), "depth grid via authenticated route")

# V03/V04 anchors: auto at box centre, manual move, stale 409
an = dm.get(f"{API}/photo-scenes/{SID}/anchors").json()
a0 = an["anchors"][0]
inv = {i["item_id"]: i for i in dm.get(f"{API}/visits/{RV}/inventory").json()["items"]}
x, y, w, h = inv[a0["finding_id"]]["region"]
exp = P.anchor_from_box(z, m["camera"]["focal_px"], [x, y, w, h])
ok(a0["placement_method"] == "bbox_center_estimated_depth" and a0["location_basis"] == "single_photo_estimated_depth" and np.allclose(a0["xyz"], exp["xyz"], atol=1e-5),
   f"V03 {len(an['anchors'])} anchors, {len(an['unplaced'])} unplaced; xyz = reference anchor_from_box")
mv = dm.put(f"{API}/photo-scenes/{SID}/anchors/{a0['finding_id']}", json={"u": 0.3, "v": 0.7, "expected_version": a0["version"]})
st = dm.put(f"{API}/photo-scenes/{SID}/anchors/{a0['finding_id']}", json={"u": 0.2, "v": 0.2, "expected_version": a0["version"]})
ok(mv.status_code == 200 and mv.json()["version"] == a0["version"] + 1 and np.allclose(mv.json()["xyz"], P.anchor_from_point(z, m["camera"]["focal_px"], 0.3, 0.7)["xyz"], atol=1e-5)
   and st.status_code == 409 and st.json()["detail"]["code"] == "stale_version", "V04 manual move server-computed xyz; stale 409")
dm.get(f"{API}/photo-scenes/{SID}/anchors")
a1 = next(a for a in dm.get(f"{API}/photo-scenes/{SID}/anchors").json()["anchors"] if a["finding_id"] == a0["finding_id"])
ok(a1["placement"] == "manual" and a1["version"] == mv.json()["version"], "REQ-172 manual placement preserved on auto refresh")
# region change → manual stale flag only; auto anchor of another finding updated
cid = a0["finding_id"]
mdb.visual_candidates.update_one({"uuid": cid}, {"$set": {"region": [0.1, 0.1, 0.2, 0.2]}})
an2 = {a["finding_id"]: a for a in dm.get(f"{API}/photo-scenes/{SID}/anchors").json()["anchors"]}
ok(an2[cid]["stale"] and an2[cid]["placement"] == "manual" and an2[cid]["version"] == a1["version"], "REQ-173 region change → manual anchor marked stale, not moved")
other = [a for a in an["anchors"] if a["finding_id"] != cid]
if other:
    oid = other[0]["finding_id"]
    mdb.visual_candidates.update_one({"uuid": oid}, {"$set": {"region": [0.6, 0.6, 0.2, 0.2]}})
    a2 = {a["finding_id"]: a for a in dm.get(f"{API}/photo-scenes/{SID}/anchors").json()["anchors"]}[oid]
    ok(a2["placement"] == "auto" or a2["placement"] == "auto_box_center", f"auto anchor refreshed on region change → v{a2['version']} u,v {a2['u']:.2f},{a2['v']:.2f}")
    ok(a2["version"] == other[0]["version"] + 1 and abs(a2["u"] - 0.7) < 1e-6, "auto refresh = new version at new box centre")
ok(mdb.anchors.count_documents({"evidence_id": PE, "current": True}) == len(an["anchors"]), "one current anchor per (revision, evidence, finding)")

# V05 saved view
pv = dm.put(f"{API}/photo-scenes/{SID}/view", json={"camera": {"position": [0.1, 0.2, 0.5], "target": [0, 0, -3], "fov_deg": 50}, "selected_finding_id": cid})
gv = dm.get(f"{API}/photo-scenes/{SID}/view").json()
bad = dm.put(f"{API}/photo-scenes/{SID}/view", json={"camera": {"position": [0, 0], "target": [0, 0, -1], "fov_deg": 50}})
ok(pv.status_code == 200 and gv["saved"] and gv["camera"]["fov_deg"] == 50 and gv["selected_finding_id"] == cid and gv["revision"] == sc["revision"] and bad.status_code == 422, "V05 saved view round-trip + validation")

# V10 access: 10 probes
import jwt as J2
from datetime import datetime, timedelta, timezone
expired = J2.encode({"typ": "scene_asset", "uid": D["user"]["uuid"], "ws": D["workspace"]["uuid"], "sid": SID, "ev": PE, "k": "splat",
                     "exp": datetime.now(timezone.utc) - timedelta(seconds=1)}, os.environ["JWT_SECRET"], algorithm="HS256")
wrongkind = sc["assets"]["splat"]["url"].split("st=")[1]
probes = [d2.get(f"{API}/photo-scenes/{SID}"), d2.get(f"{API}/photo-scenes/{SID}/anchors"), d2.get(f"{API}/photo-scenes/{SID}/view"),
          d2.get(f"{API}/photo-scenes/{SID}/assets/depth_grid"), d2.get(f"{API}/photo-scenes/{SID}/assets/manifest"),
          requests.get(f"{API}/photo-scenes/{SID}/assets/splat?st={expired}"), requests.get(f"{API}/photo-scenes/{SID}/assets/original?st={wrongkind}"),
          requests.get(f"{API}/photo-scenes/{SID}/assets/oriented_photo"), d2.post(f"{API}/evidence/{PE}/photo-scene"),
          d2.put(f"{API}/photo-scenes/{SID}/anchors/{cid}", json={"u": 0.5, "v": 0.5, "expected_version": 9})]
codes = [p.status_code for p in probes]
ok(all(c in (401, 404) for c in codes) and codes[5] == 401 and all("Traceback" not in p.text and "/app/" not in p.text for p in probes), f"V10 probes {codes}")
ok(d2.get(f"{API}/photo-scene-jobs/{j['job_id']}").status_code == 404, "job scoped")

# V09 faults: storage, uninformative, checksum (on fresh uploads in the empty draft visit)
land = open("test_photos/negative_coledale.jpg", "rb").read()
from PIL import Image
im = Image.open(io.BytesIO(land))
variants = {}
for k, angle in (("storage", 0), ("uninformative", 180), ("checksum", 90)):
    b = io.BytesIO(); (im.rotate(angle, expand=True) if angle else im).save(b, "JPEG", quality=88 - len(variants)); variants[k] = b.getvalue()
ids = {k: upload(dm, EVV, v, "image/jpeg", f"{k}.jpg") for k, v in variants.items()}
for k, eid in ids.items():
    dm.post(f"{API}/dev/fault", json={"visit_id": EVV, "stage": "depth", "target_id": eid, "mode": k})
res = {}
for k, eid in ids.items():
    code, jj, _ = scene_for(dm, eid)
    res[k] = jj
ok(res["storage"]["status"] == "failed" and res["storage"]["error"]["code"] == "storage_unavailable" and res["storage"]["error"]["retryable"], f"V09 storage fault → failed/storage_unavailable/retryable")
ok(res["uninformative"]["status"] == "depth_uninformative" and res["uninformative"]["error"]["retryable"] is False, "V09 flat depth → depth_uninformative")
ok(res["checksum"]["status"] == "failed" and res["checksum"]["error"]["code"] == "model_unavailable", "V09 checksum → model_unavailable")
sid_fail = res["storage"]["scene_id"]
ok(dm.get(f"{API}/photo-scenes/{sid_fail}").json()["assets"].get("splat") is None and mdb.scenes.find_one({"uuid": sid_fail})["status"] != "Ready", "no Ready / no splat after storage failure")
ok(not os.listdir("/tmp/railready-scene-staging"), "staging dirs cleaned")
code, jj, _ = scene_for(dm, ids["storage"])
ok(jj["status"] == "ready", "retry after storage fault → ready (no reupload)")

# REQ-169 lazy regeneration of an older-key scene; old anchors stay on old revision
mdb.scenes.update_one({"uuid": jj["scene_id"]}, {"$set": {"scene_key": "legacy|photo-scene-v0"}})
old = mdb.scenes.find_one({"uuid": jj["scene_id"]})
dm.get(f"{API}/evidence/{ids['storage']}/scene")  # open (alias) → lazy regenerate
time.sleep(1)
code, jn, _ = scene_for(dm, ids["storage"])
newsc = dm.get(f"{API}/photo-scenes/{jn['scene_id']}").json()
oldsc = dm.get(f"{API}/photo-scenes/{old['uuid']}").json()
ok(newsc["revision"] == old["revision"] + 1 and newsc["is_current"] and not oldsc["is_current"] and oldsc["status"] == "ready", f"REQ-169 lazy regen r{old['revision']} → r{newsc['revision']}, old kept")

# alias routes still work
ok(dm.get(f"{API}/evidence/{PE}/scene").json()["status"] == "Ready" and dm.get(f"{API}/visits/{RV}/scenes").status_code == 200, "Phase 4 alias routes intact")
spec = requests.get(f"{API}/openapi.json").json()["paths"]
ok(all(p in spec for p in ["/api/evidence/{evidence_id}/photo-scene", "/api/photo-scene-jobs/{job_id}", "/api/photo-scenes/{scene_id}",
                            "/api/photo-scenes/{scene_id}/anchors", "/api/photo-scenes/{scene_id}/anchors/{finding_id}", "/api/photo-scenes/{scene_id}/view",
                            "/api/photo-scenes/{scene_id}/assets/{name}"]), "OpenAPI current")
