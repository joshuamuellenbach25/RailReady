"""Unit tests (no network): provisioning cache/bad cache/bad download/partial cleanup, all 8 EXIF region transforms, crop undo, anchors, real build."""
import hashlib, io, os, sys, tempfile, time
sys.path.insert(0, "/app/backend")
import numpy as np
from PIL import Image
import photo_scene_processor as P

R = []


def ok(c, m):
    R.append(c); print(("PASS " if c else "FAIL ") + m, flush=True)


class FakeResp(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): self.close()


good = os.urandom(300_000); gsha = hashlib.sha256(good).hexdigest()
d = tempfile.mkdtemp(prefix="prov-test-"); tgt = os.path.join(d, "model.onnx")
calls = []
fake = lambda url, timeout=0: (calls.append(url), FakeResp(good))[1]
r = P.provision_model(tgt, gsha, "http://x/m", urlopen=fake)
ok(r["source"] == "download" and P.sha256_file(tgt) == gsha and not [f for f in os.listdir(d) if f.endswith(".part")], "fresh download verified + os.replace, no .part left")
r = P.provision_model(tgt, gsha, "http://x/m", urlopen=lambda *a, **k: (_ for _ in ()).throw(AssertionError("no download expected")))
ok(r["source"] == "cache" and len(calls) == 1, "good cache → no download")
open(tgt, "wb").write(b"corrupt")
r = P.provision_model(tgt, gsha, "http://x/m", urlopen=fake)
ok(r["source"] == "download" and P.sha256_file(tgt) == gsha, "bad cache → re-download + verify")
open(tgt, "wb").write(b"corrupt")
try:
    P.provision_model(tgt, gsha, "http://x/m", urlopen=lambda *a, **k: FakeResp(b"evil" * 1000)); e = None
except P.ModelUnavailable as x:
    e = x
ok(e is not None and "checksum" in e.message and open(tgt, "rb").read() == b"corrupt" and not [f for f in os.listdir(d) if f.endswith(".part")],
   "bad download → ModelUnavailable, target not replaced, .part cleaned")


class Boom(FakeResp):
    def read(self, n=-1):
        raise ConnectionError("cut")
try:
    P.provision_model(tgt, gsha, "http://x/m", urlopen=lambda *a, **k: Boom(b"")); e = None
except P.ModelUnavailable as x:
    e = x
ok(e is not None and not [f for f in os.listdir(d) if f.endswith(".part")], "partial download → .part cleaned")
try:
    P.provision_model(tgt, gsha, "http://x/m", max_bytes=1000, urlopen=fake); e = None
except P.ModelUnavailable as x:
    e = x
ok(e is not None and "exceeded" in e.message and not [f for f in os.listdir(d) if f.endswith(".part")], "oversize download refused (cap) + cleaned")
try:
    P.DepthSession(tgt, P.MODEL["sha256"]); e = None
except P.ModelUnavailable as x:
    e = x
ok(e is not None and e.code == "model_unavailable" and "/" not in e.message, "session refuses mismatched model; message has no paths")

# all 8 EXIF orientations, numerically against PIL exif_transpose on a marked rectangle
RW, RH = 200, 120
box = [0.1, 0.2, 0.3, 0.25]
for o in range(1, 9):
    raw = Image.new("RGB", (RW, RH), "black")
    raw.paste((255, 0, 0), (int(box[0] * RW), int(box[1] * RH), int((box[0] + box[2]) * RW), int((box[1] + box[3]) * RH)))
    ex = raw.getexif(); ex[0x0112] = o
    b = io.BytesIO(); raw.save(b, "PNG", exif=ex)
    oriented, meta = P.decode(b.getvalue())
    a = np.asarray(oriented)[:, :, 0] > 128
    ys, xs = np.where(a)
    W, H = oriented.size
    truth = [xs.min() / W, ys.min() / H, (xs.max() + 1 - xs.min()) / W, (ys.max() + 1 - ys.min()) / H]
    got = P.raw_to_oriented_box(box, o)
    err = max(abs(g - t) for g, t in zip(got, truth))
    swap = (W, H) == ((RH, RW) if o >= 5 else (RW, RH))
    ok(err < 0.011 and meta["exif_orientation"] == o and swap, f"EXIF {o}: box {[round(v,3) for v in got]} vs pixels {[round(v,3) for v in truth]} err {err:.4f}, dims {W}x{H}")
ok(np.allclose(P.crop_box_to_full([0.5, 0.5, 0.5, 0.5], (100, 50, 200, 100), 400, 200), [0.5, 0.5, 0.25, 0.25]), "crop/letterbox undo u=(cx+a*cw)/W")
for bad in ([0.8, 0.1, 0.3, 0.1], [0.1, 0.1, 0, 0.1], [float("nan"), 0, 0.1, 0.1], [-0.1, 0, 0.2, 0.2]):
    try:
        P.validate_box(bad); r = False
    except ValueError:
        r = True
    ok(r, f"invalid box rejected {bad}")

# decode safety
for name, data in [("gif", (lambda b: (Image.new("RGB", (64, 64)).save(b, "GIF"), b.getvalue())[1])(io.BytesIO())),
                   ("rgba", (lambda b: (Image.new("RGBA", (64, 64)).save(b, "PNG"), b.getvalue())[1])(io.BytesIO())),
                   ("tiny", (lambda b: (Image.new("RGB", (20, 64)).save(b, "PNG"), b.getvalue())[1])(io.BytesIO())),
                   ("trunc", open("/app/backend/test_photos/negative_coledale.jpg", "rb").read()[:5000]), ("heic", b"\0\0\0\x18ftypheic" + b"\0" * 100)]:
    try:
        P.decode(data); c = None
    except P.UnsupportedImage as x:
        c = x.code
    ok(c == "unsupported", f"decode rejects {name}")

# real photo build + anchors
s = P.DepthSession(os.environ.get("RAILREADY_DEPTH_MODEL_PATH", "/app/models/depth-anything-v2-small/model.onnx"))
data = open("/app/backend/test_photos/tie_old_rotten.jpg", "rb").read()
t = time.time(); out = P.build(data, s); dt = time.time() - t
m = out["manifest"]; ply = out["artifacts"]["splat"][0]
hdr = ply[:ply.index(b"end_header\n") + 11].decode()
ok(m["splat"]["vertex_count"] == out["width"] * out["height"] and len(ply) == len(hdr) + 56 * m["splat"]["vertex_count"] and P.PLY_COMMENT in hdr and hdr.count("property float") == 14,
   f"real build {out['width']}x{out['height']} vertices {m['splat']['vertex_count']} ply {len(ply)} B in {dt:.2f}s timings {m['timings_s']}")
ok(2.0 - 1e-5 <= m["depth"]["z_min"] and m["depth"]["z_max"] <= 6.0 + 1e-5 and all(hashlib.sha256(b).hexdigest() == m["artifacts"][k]["sha256"] for k, (b, _, _) in out["artifacts"].items()),
   f"z in [2,6] ({m['depth']['z_min']:.3f}..{m['depth']['z_max']:.3f}); artifact hashes match manifest")
z = np.load(io.BytesIO(out["artifacts"]["display_z"][0]), allow_pickle=False)
a = P.anchor_from_box(z, out["focal"], [0.25, 0.25, 0.5, 0.5])
pu, pv = P.project(a["xyz"], out["focal"], out["width"], out["height"])
ok(a["placement_method"] == P.PLACEMENT and abs(pu - (a["col"] + 0.5) / out["width"]) < 1e-6 and abs(pv - (a["row"] + 0.5) / out["height"]) < 1e-6, f"anchor_from_box centre → pixel {a['col']},{a['row']} xyz {a['xyz']}")
try:
    P.build(data, s, fault="uninformative"); c = None
except P.DepthUninformative as x:
    c = x.code
ok(c == "depth_uninformative", "flat depth → depth_uninformative")
flat = io.BytesIO(); Image.new("RGB", (256, 192), (128, 128, 128)).save(flat, "PNG")
try:
    P.build(flat.getvalue(), s); c = "built"
except P.DepthUninformative as x:
    c = x.code
print("INFO uniform grey photo →", c)
print("RESULT", sum(R), "/", len(R))
