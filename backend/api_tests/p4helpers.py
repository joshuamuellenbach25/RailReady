import hashlib, io, os, time, uuid
import httpx, pymongo
from dotenv import dotenv_values
from PIL import Image

B = "http://localhost:8001/api"
ROOT = "http://localhost:8001"
ENV = dotenv_values("/app/backend/.env")
LABEL = "AI-estimated depth. Geometry and scale unverified."
UNSUP = "Unsupported photo format – view original or upload JPEG/PNG"


def mdb():
    return pymongo.MongoClient(ENV["MONGO_URL"])[ENV["DB_NAME"]]


def wait_scene(c, eid, want=("Ready", "Failed", "Unsupported"), t=120):
    end = time.time() + t
    r = None
    while time.time() < end:
        r = c.get(f"/evidence/{eid}/scene").json()
        if r["status"] in want:
            return r
        time.sleep(2)
    return r


def upload(c, vid, data, mime, fn):
    eid = str(uuid.uuid4()); h = hashlib.sha256(data).hexdigest()
    r = c.post(f"/visits/{vid}/evidence", json={"uuid": eid, "kind": "photo", "sha256": h, "size": len(data), "mime": mime, "filename": fn})
    assert r.status_code == 200, r.text[:200]
    assert c.put(f"/evidence/{eid}/content", files={"file": (fn, data, mime)}).status_code == 200
    assert c.post(f"/evidence/{eid}/verify").status_code == 200
    return eid, h


def variants():
    land = open("/app/backend/test_photos/negative_coledale.jpg", "rb").read()
    im = Image.open(io.BytesIO(land))
    b = io.BytesIO(); im.rotate(90, expand=True).save(b, "JPEG", quality=90); portrait = b.getvalue()
    ex = im.getexif(); ex[0x0112] = 6; b = io.BytesIO(); im.save(b, "JPEG", quality=90, exif=ex); rot = b.getvalue()
    return land, portrait, rot
