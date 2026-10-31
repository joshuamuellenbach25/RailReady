"""Phase 4 API journeys: depth scenes, anchors, inventory, scoped media, corrections (JRN-86..107 backend parts)."""
import asyncio, hashlib, io, os, sys, time, uuid
from datetime import datetime, timedelta, timezone
import jwt, requests
from PIL import Image

sys.path.insert(0, "/app/backend"); os.chdir("/app/backend")
from dotenv import load_dotenv; load_dotenv(".env")
import depth

API = os.environ.get("API", "http://localhost:8001/api")


def ok(c, m):
    print(("PASS " if c else "FAIL ") + m, flush=True)


def sess(tok):
    s = requests.Session(); s.headers["Authorization"] = "Bearer " + tok; return s


def wait_scene(s, eid, want=("Ready", "Failed", "Unsupported"), t=90):
    end = time.time() + t
    while time.time() < end:
        r = s.get(f"{API}/evidence/{eid}/scene").json()
        if r["status"] in want:
            return r
        time.sleep(1.5)
    return r


def upload(s, vid, data, mime, fn):
    eid = str(uuid.uuid4()); h = hashlib.sha256(data).hexdigest()
    s.post(f"{API}/visits/{vid}/evidence", json={"uuid": eid, "kind": "photo", "sha256": h, "size": len(data), "mime": mime, "filename": fn}).raise_for_status()
    s.put(f"{API}/evidence/{eid}/content", files={"file": (fn, data, mime)}).raise_for_status()
    s.post(f"{API}/evidence/{eid}/verify").raise_for_status()
    return eid, h


D = requests.post(f"{API}/demo/sessions").json(); dm = sess(D["token"])
D2 = requests.post(f"{API}/demo/sessions").json(); d2 = sess(D2["token"])
J = D["jobs"]; RV, EVV = J["ready_to_estimate"]["visit_id"], J["empty_draft"]["visit_id"]; PE = J["ready_to_estimate"]["evidence_id"]

# JRN-86 Ready + timing
t0 = time.time()
ls = dm.get(f"{API}/visits/{RV}/scenes").json()["scenes"]
sc = wait_scene(dm, PE)
ok(sc["status"] == "Ready" and sc["label"] == "AI-estimated depth. Geometry and scale unverified." and sc["model"]["onnx_sha256"].startswith("afb6a5c2"),
   f"JRN-86 demo photo scene Ready in {time.time()-t0:.1f}s inference_run={sc['inference_run']} timings={sc['timings']} bytes={sc['asset_bytes']} gaussians={sc['gaussians']}")
ok(sc["camera"]["fov_deg"] == 55.0 and sc["camera"]["fov_axis"] == "horizontal" and sc["projection"]["max_side"] == 384 and sc["projection"]["depth_mode"] == "relative_inverse", "projection/camera recorded")

# Asset access (Q-26 / JRN-100)
a = requests.get(API[:-4] + sc["asset_url"])
ok(a.status_code == 200 and a.content.startswith(b"ply\nformat binary_little_endian") and len(a.content) == sc["asset_bytes"], f"asset streams via scoped st ({len(a.content)} bytes)")
uid = D["user"]["uuid"]
exp = jwt.encode({"typ": "media", "uid": uid, "ws": D["workspace"]["uuid"], "ev": PE, "sid": sc["scene_id"], "exp": datetime.now(timezone.utc) - timedelta(seconds=5)},
                 os.environ["JWT_SECRET"], algorithm="HS256")
foreign_st = d2.get(f"{API}/visits/{D2['jobs']['ready_to_estimate']['visit_id']}/scenes").json()["scenes"][0]["thumbnail_url"].split("st=")[1]
probes = [requests.get(f"{API}/scenes/{sc['scene_id']}/asset"), requests.get(f"{API}/scenes/{sc['scene_id']}/asset?st={exp}"),
          requests.get(f"{API}/scenes/{sc['scene_id']}/asset?st={foreign_st}"), d2.get(f"{API}/scenes/{sc['scene_id']}/asset"),
          d2.get(f"{API}/evidence/{PE}/scene"), d2.get(f"{API}/visits/{RV}/scenes"), d2.get(f"{API}/visits/{RV}/inventory"),
          requests.get(f"{API}/media/evidence/{PE}/original"), requests.get(f"{API}/media/evidence/{PE}/original?st={foreign_st}"),
          d2.get(f"{API}/media/evidence/{PE}/thumbnail")]
codes = [p.status_code for p in probes]
ok(all(c in (401, 403, 404) for c in codes) and codes[1] == 401 and not any(p.content.startswith(b"ply") or p.content[:3] == b"\xff\xd8\xff" for p in probes), f"Q-26 10 probes no bytes {codes}")
ok(requests.get(API[:-4] + sc["original_url"]).status_code == 200, "original via scoped st")

# Inventory + anchors (REQ-131..133)
inv = dm.get(f"{API}/visits/{RV}/inventory?evidence_id={PE}").json()["items"]
loc = [i for i in inv if i["located"]]
ok(loc and all(i["anchor"]["location_basis"] == "single_photo_estimated_depth" and i["anchor"]["placement"] == "auto_box_center" for i in loc), f"inventory {len(inv)} items, {len(loc)} anchored")
it = loc[0]; x, y, w, h = it["region"]
ip = it["anchor"]["image_point"]
import photo_scene_processor as P
W, H = sc["sample_width"], sc["sample_height"]
pj = P.project(it["anchor"]["xyz"], 0.5 * W / __import__("math").tan(__import__("math").radians(27.5)), W, H)
ok(abs(ip[0] - (x + w / 2)) < 1e-3 and abs(ip[1] - (y + h / 2)) < 1e-3 and abs(pj[0] - ip[0]) * W <= 0.5 + 1e-6 and abs(pj[1] - ip[1]) * H <= 0.5 + 1e-6,
   f"anchor at box centre; reprojection error {abs(pj[0]-ip[0])*W:.2f}px / {abs(pj[1]-ip[1])*H:.2f}px (pixel-centre sampling)")
ok(any(i["review_state"] == "Confirmed" and i["provenance"]["saved_analysis"] for i in inv) and all(i["short_id"] for i in inv), "review states + saved-analysis provenance")
cr = dm.get(f"{API}/inventory-items/{it['item_id']}/crop")
ok(cr.status_code == 200 and cr.content[:3] == b"\xff\xd8\xff" and d2.get(f"{API}/inventory-items/{it['item_id']}/crop").status_code == 404, "crop scoped (own 200, foreign 404)")
before = it["review_state"]
mv = dm.put(f"{API}/anchors/{it['anchor']['anchor_id']}", json={"expected_version": 1, "image_point": [0.4, 0.6], "reason": "test move"})
st = dm.put(f"{API}/anchors/{it['anchor']['anchor_id']}", json={"expected_version": 1, "image_point": [0.3, 0.3]})
inv2 = {i["item_id"]: i for i in dm.get(f"{API}/visits/{RV}/inventory?evidence_id={PE}").json()["items"]}
ok(mv.status_code == 200 and mv.json()["version"] == 2 and mv.json()["placement"] == "manual" and st.status_code == 409 and
   inv2[it["item_id"]]["anchor"]["version"] == 2 and inv2[it["item_id"]]["review_state"] == before, "JRN-94 manual move v2, stale 409, review state unchanged")

# JRN-87 / JRN-103 zero new runs on reopen/retry
nruns = requests.get  # placeholder
import pymongo
mdb = pymongo.MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
c_img, c_sc = mdb.image_analysis_runs.count_documents({}), mdb.scenes.count_documents({"inference_run": True})
for _ in range(5):
    dm.get(f"{API}/evidence/{PE}/scene"); dm.get(f"{API}/visits/{RV}/inventory")
r = dm.post(f"{API}/evidence/{PE}/scene/retry", json={}).json()
ok(r["scene_revision"] == sc["scene_revision"] and r["status"] == "Ready" and mdb.image_analysis_runs.count_documents({}) == c_img and
   mdb.scenes.count_documents({"inference_run": True}) == c_sc, "JRN-87/103 reopen x5 + retry → same scene, zero new image/depth runs")

# JRN-86/93/98 uploads: landscape, portrait, EXIF-rotated, HEIC
land = open("test_photos/negative_coledale.jpg", "rb").read()
im = Image.open(io.BytesIO(land)); b = io.BytesIO(); im.rotate(90, expand=True).save(b, "JPEG", quality=90); portrait = b.getvalue()
ex = im.getexif(); ex[0x0112] = 6; b = io.BytesIO(); im.save(b, "JPEG", quality=90, exif=ex); rotated = b.getvalue()
heic = b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00mif1heic" + os.urandom(2000)
ups = {n: upload(dm, EVV, d, m, f) for n, d, m, f in [("land", land, "image/jpeg", "land.jpg"), ("portrait", portrait, "image/jpeg", "portrait.jpg"),
                                                         ("exif6", rotated, "image/jpeg", "exif6.jpg"), ("heic", heic, "image/heic", "photo.heic")]}
dm.post(f"{API}/visits/{EVV}/manifests", json={"members": [{"evidence_id": e, "sha256": h, "size": 0} for e, h in ups.values()]})
res = {n: wait_scene(dm, e) for n, (e, _) in ups.items()}
ok(res["land"]["status"] == res["portrait"]["status"] == res["exif6"]["status"] == "Ready" and len({res[n]["scene_id"] for n in ("land", "portrait", "exif6")}) == 3,
   f"JRN-86 three uploads Ready, distinct scene ids; verified→ready s: {[res[n]['timings']['verified_to_ready_s'] for n in ('land','portrait','exif6')]}")
e6 = res["exif6"]
ok(e6["exif_transform"]["exif_orientation"] == 6 and (e6["oriented_width"], e6["oriented_height"]) == (958, 1280) and res["portrait"]["oriented_height"] > res["portrait"]["oriented_width"],
   f"JRN-93 EXIF transform recorded {e6['exif_transform']['applied']} oriented {e6['oriented_width']}x{e6['oriented_height']}")
ok(res["heic"]["status"] == "Unsupported" and res["heic"]["error"] == "Unsupported photo format – view original or upload JPEG/PNG" and
   dm.get(f"{API}/evidence/{ups['heic'][0]}/content").content == heic, "JRN-98 HEIC Unsupported, original retained byte-for-byte")
ok(dm.get(f"{API}/evidence/{ups['land'][0]}/content").content == land, "REQ-123 original bytes unchanged")

# JRN-97 fault + retry, REQ-136 new revision, old anchors bound to old revision
le = ups["land"][0]
dm.post(f"{API}/dev/fault", json={"visit_id": EVV, "stage": "depth", "target_id": le})
dm.post(f"{API}/evidence/{le}/scene/retry", json={"regenerate": True})
f = wait_scene(dm, le, want=("Failed",), t=40)
ok(f["status"] == "Failed" and "Injected depth failure" in (f["error"] or "") and dm.get(f"{API}/visits/{EVV}/review").status_code == 200, f"JRN-97 fault → Failed rev {f['scene_revision']}; review still works")
time.sleep(1)
r = dm.post(f"{API}/evidence/{le}/scene/retry", json={}).json()
r = wait_scene(dm, le, want=("Ready",), t=60)
ok(r["status"] == "Ready" and r["scene_revision"] == res["land"]["scene_revision"] + 1, f"retry without reupload → Ready rev {r['scene_revision']}")

# JRN-105 whole number
E = J["ready_to_estimate"]["engagement_id"]
rv = dm.get(f"{API}/engagements/{E}").json()["draft"]["revision"]
bad = dm.post(f"{API}/engagements/{E}/lines", json={"expected_revision": rv, "category": "material", "description": "Crosstie", "quantity": "8.5", "unit": "each",
                                                   "unit_cost": "62.50", "markup_pct": "20", "taxable": True, "reason": "t"})
good = dm.post(f"{API}/engagements/{E}/lines", json={"expected_revision": rv, "category": "material", "description": "Crosstie", "quantity": "8", "unit": "each",
                                                    "unit_cost": "62.50", "markup_pct": "20", "taxable": True, "reason": "t"})
ok(bad.status_code == 422 and bad.json()["detail"]["message"] == "Whole number required" and good.status_code == 200, "JRN-105 8.5 rejected 'Whole number required', 8 accepted")

# JRN-106 revoke while page open → next media request denied
sid = dm.get(f"{API}/engagements/{E}").json()["scope_items"][0]["uuid"]
dm.post(f"{API}/scope-items/{sid}/package")
for l in dm.get(f"{API}/engagements/{E}").json()["draft"]["lines"]:
    if l["quantity_origin"] == "estimator edit" or l["description"] == "Crosstie":
        dm.patch(f"{API}/engagements/{E}/lines/{l['uuid']}", json={"expected_revision": dm.get(f"{API}/engagements/{E}").json()["draft"]["revision"], "included": False})
for l in dm.get(f"{API}/engagements/{E}").json()["draft"]["lines"]:
    dm.patch(f"{API}/engagements/{E}/lines/{l['uuid']}", json={"expected_revision": dm.get(f"{API}/engagements/{E}").json()["draft"]["revision"], "reviewed": True})
dm.get(f"{API}/engagements/{E}/agreement-preview")
v = dm.post(f"{API}/engagements/{E}/publish", json={"expected_revision": dm.get(f"{API}/engagements/{E}").json()["draft"]["revision"], "idempotency_key": str(uuid.uuid4())}).json()
sh = dm.post(f"{API}/versions/{v['uuid']}/share").json()
pub = requests.get(f"{API}/public/proposals/{sh['token']}").json()
m1 = requests.get(API + pub["photos"][0]["url"][4:])
dm.post(f"{API}/links/{sh['link_id']}/revoke")
m2 = requests.get(API + pub["photos"][0]["url"][4:])
ok(m1.status_code == 200 and m2.status_code == 404, f"JRN-106 media {m1.status_code} → after revoke {m2.status_code}")

# JRN-107 demo storage blip → 2 retries then 503 (in-process)
import routes_demo
calls = []
def boom(*a):
    calls.append(1); raise ConnectionError("blip")
try:
    asyncio.run(routes_demo._retry(boom)); raised = False
except routes_demo.DemoStorageError:
    raised = True
ok(raised and len(calls) == 3 and routes_demo.UNAVAILABLE == "Demo setup temporarily unavailable – try again", "JRN-107 3 attempts (2 retries) then DemoStorageError → 503 message")
sp = requests.get(f"{API}/openapi.json").json()["paths"]
ok(all(p in sp for p in ["/api/visits/{visit_id}/scenes", "/api/evidence/{evidence_id}/scene", "/api/evidence/{evidence_id}/scene/retry", "/api/scenes/{scene_id}/asset",
                          "/api/visits/{visit_id}/inventory", "/api/inventory-items/{item_id}/crop", "/api/anchors/{anchor_id}"]), "OpenAPI current")
