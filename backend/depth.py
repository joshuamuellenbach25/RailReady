"""Photo-derived depth scenes: Depth Anything V2 Small (ONNX, CPU) → relative inverse depth → perspective back-projection
→ coloured Gaussian samples (.ply, 3DGS layout). One verified session per process. Never fabricates depth: any failure is a
recorded Failed/Unsupported/Model-unavailable state, never a flat fallback."""
import hashlib
import io
import os
import threading
import time
from typing import Optional

import numpy as np
from PIL import Image, ImageOps

MODEL_DIR = "/app/models/depth-anything-v2-small"
MODEL = {"id": "onnx-community/depth-anything-v2-small", "revision": "4472b7362082ad9968fee890ca0f1e5aca36b93d",
         "onnx_sha256": "afb6a5c28f3b6bf1618c6e43f02073ef9dfdc70e937502d51603e57b0a1df10c",
         "preprocessor_sha256": "03576db3c13dd0471fdf5f5e1428befcb95de063fe699879150b293dc9e0a2c6",
         "license": "Apache-2.0 (see /app/models/depth-anything-v2-small/NOTICE.md)", "runtime": "onnxruntime CPU"}
PROJECTION = {"max_side": 384, "assumed_fov_deg": 55.0, "fov_axis": "horizontal", "depth_mode": "relative_inverse", "near": 2.0, "far": 6.0,
              "processor_revision": "photo-scene-v1", "normalization": "d = clip((depth-p2)/(p98-p2), 0, 1); z = 3/(0.5+d)",
              "coordinate_system": "right-handed, Y up, camera at origin looking down -Z (OpenGL)",
              "image_to_world": "display grid W x H (thumbnail max 384); f = 0.5*W/tan(27.5deg); col=floor(u*W), row=floor(v*H); x=(col+0.5-W/2)*z/f, y=-(row+0.5-H/2)*z/f, z=-z",
              "world_to_image": "u=(x*f/z + W/2)/W, v=(-y*f/z + H/2)/H with z=-P.z",
              "scale_note": "Relative units only. Depth is a monocular AI estimate; absolute scale, distances and hidden surfaces are unknown."}
SETTINGS_KEY = f"{MODEL['revision']}|ms{PROJECTION['max_side']}|fov{PROJECTION['assumed_fov_deg']}|n{PROJECTION['near']}|f{PROJECTION['far']}|v1"
CAMERA = {"position": [0.0, 0.0, 0.0], "target": [0.0, 0.0, -4.0], "up": [0.0, 1.0, 0.0], "fov_deg": 55.0, "fov_axis": "horizontal", "horizontal_fov": True}
LABEL = "AI-estimated depth. Geometry and scale unverified."
UNSUPPORTED = "Unsupported photo format. View original or upload JPEG/PNG"
SH_C0 = 0.28209479177387814
_OPS = {1: "none", 2: "mirror horizontal", 3: "rotate 180", 4: "mirror vertical", 5: "transpose", 6: "rotate 90 CW", 7: "transverse", 8: "rotate 90 CCW"}


class ModelUnavailable(Exception):
    pass


class UnsupportedPhoto(Exception):
    pass


_lock = threading.Lock()
_session = None
_mean = _std = None


def _sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def session():
    """Load + hash-verify once per process; reuse afterwards."""
    global _session, _mean, _std
    with _lock:
        if _session is not None:
            return _session
        mp, pp = os.path.join(MODEL_DIR, "model.onnx"), os.path.join(MODEL_DIR, "preprocessor_config.json")
        for p in (mp, pp):
            if not os.path.exists(p):
                raise ModelUnavailable(f"Model artifact missing: {p}")
        got_m, got_p = _sha(mp), _sha(pp)
        if got_m != MODEL["onnx_sha256"]:
            raise ModelUnavailable(f"model.onnx sha256 mismatch: expected {MODEL['onnx_sha256']}, got {got_m}")
        if got_p != MODEL["preprocessor_sha256"]:
            raise ModelUnavailable(f"preprocessor_config.json sha256 mismatch: expected {MODEL['preprocessor_sha256']}, got {got_p}")
        import json
        import onnxruntime as ort
        cfg = json.load(open(pp))
        _mean, _std = np.array(cfg["image_mean"], np.float32), np.array(cfg["image_std"], np.float32)
        so = ort.SessionOptions()
        so.intra_op_num_threads = 4
        _session = ort.InferenceSession(mp, sess_options=so, providers=["CPUExecutionProvider"])
        return _session


def orient(data: bytes):
    """EXIF-orient (original bytes untouched). Returns (RGB image, transform dict, captured_at|None)."""
    try:
        im = Image.open(io.BytesIO(data))
        im.load()
    except Exception as e:
        raise UnsupportedPhoto(f"{UNSUPPORTED} ({type(e).__name__})")
    exif = im.getexif()
    o = int(exif.get(0x0112, 1) or 1)
    cap = None
    try:
        cap = exif.get_ifd(0x8769).get(0x9003) or exif.get(0x0132)
    except Exception:
        pass
    raw_w, raw_h = im.size
    im = ImageOps.exif_transpose(im).convert("RGB")
    return im, {"exif_orientation": o, "applied": _OPS.get(o, "none"), "raw_width": raw_w, "raw_height": raw_h,
                "oriented_width": im.width, "oriented_height": im.height}, (str(cap) if cap else None)


def _infer(im: Image.Image) -> np.ndarray:
    s = session()
    m, mult = PROJECTION["inference_max_side"], PROJECTION["multiple_of"]
    sc = m / max(im.size)
    w, h = max(mult, round(im.width * sc / mult) * mult), max(mult, round(im.height * sc / mult) * mult)
    x = (np.asarray(im.resize((w, h), Image.BICUBIC), np.float32) / 255.0 - _mean) / _std
    x = x.transpose(2, 0, 1)[None].astype(np.float32)
    return s.run(None, {s.get_inputs()[0].name: x})[0][0]


def build(data: bytes, fault: Optional[str] = None) -> dict:
    """Full CPU pipeline for one photo. Returns ply bytes, depth grid (z) bytes and metadata."""
    t0 = time.time()
    im, transform, cap = orient(data)
    t1 = time.time()
    if fault:
        raise RuntimeError(fault)
    inv = _infer(im)
    t2 = time.time()
    ms = PROJECTION["max_side"]
    sc = ms / max(im.size)
    sw, sh = max(1, round(im.width * sc)), max(1, round(im.height * sc))
    rgb = np.asarray(im.resize((sw, sh), Image.LANCZOS), np.float32) / 255.0
    inv_s = np.asarray(Image.fromarray(inv.astype(np.float32), mode="F").resize((sw, sh), Image.BILINEAR), np.float32)
    lo, hi = np.percentile(inv_s, 2), np.percentile(inv_s, 98)
    if not np.isfinite(lo) or hi - lo < 1e-6:
        raise RuntimeError("Depth output degenerate (no relative depth variation). Not presented as depth")
    dn = np.clip((inv_s - lo) / (hi - lo), 0, 1)
    near, far = PROJECTION["near"], PROJECTION["far"]
    z = 1.0 / (1.0 / far + dn * (1.0 / near - 1.0 / far))
    t = np.tan(np.radians(PROJECTION["assumed_fov_deg"]) / 2)
    aspect = sw / sh
    u = (np.arange(sw) + 0.5) / sw
    v = (np.arange(sh) + 0.5) / sh
    U, V = np.meshgrid(u, v)
    X, Y = (2 * U - 1) * t * aspect * z, (1 - 2 * V) * t * z
    n = sw * sh
    sigma = z * 2 * t / sh * 0.6
    arr = np.zeros((n, 17), np.float32)
    arr[:, 0], arr[:, 1], arr[:, 2] = X.ravel(), Y.ravel(), -z.ravel()
    arr[:, 6:9] = ((rgb.reshape(-1, 3) - 0.5) / SH_C0)
    arr[:, 9] = np.log(0.97 / 0.03)
    arr[:, 10] = arr[:, 11] = np.log(sigma.ravel())
    arr[:, 12] = np.log(sigma.ravel() * 0.5)
    arr[:, 13] = 1.0
    props = ["x", "y", "z", "nx", "ny", "nz", "f_dc_0", "f_dc_1", "f_dc_2", "opacity", "scale_0", "scale_1", "scale_2", "rot_0", "rot_1", "rot_2", "rot_3"]
    header = "ply\nformat binary_little_endian 1.0\ncomment RailReady photo-derived depth (AI-estimated; geometry and scale unverified)\n" \
             f"element vertex {n}\n" + "".join(f"property float {p}\n" for p in props) + "end_header\n"
    ply = header.encode() + arr.astype("<f4").tobytes()
    buf = io.BytesIO()
    np.save(buf, z.astype(np.float32))
    t3 = time.time()
    return {"ply": ply, "depth_npy": buf.getvalue(), "transform": transform, "captured_at": cap, "sample_width": sw, "sample_height": sh,
            "gaussians": n, "timings": {"decode_orient_s": round(t1 - t0, 3), "inference_s": round(t2 - t1, 3), "backproject_ply_s": round(t3 - t2, 3)}}


def load_grid(npy: bytes) -> np.ndarray:
    return np.load(io.BytesIO(npy))


def unproject(grid: np.ndarray, u: float, v: float, aspect: float) -> list:
    """Image point (oriented, 0..1) → world xyz through this photo's estimated depth (median of a 5x5 window)."""
    h, w = grid.shape
    cx, cy = min(w - 1, max(0, int(u * w))), min(h - 1, max(0, int(v * h)))
    z = float(np.median(grid[max(0, cy - 2):cy + 3, max(0, cx - 2):cx + 3]))
    t = np.tan(np.radians(PROJECTION["assumed_fov_deg"]) / 2)
    return [round((2 * u - 1) * t * aspect * z, 5), round((1 - 2 * v) * t * z, 5), round(-z, 5)]


def project(xyz, aspect: float):
    x, y, zz = xyz
    if zz >= 0:
        return None
    t = np.tan(np.radians(PROJECTION["assumed_fov_deg"]) / 2)
    return [round(float((x / -zz / (t * aspect) + 1) / 2), 5), round(float((1 - y / -zz / t) / 2), 5)]


def oriented_jpeg(data: bytes, box=None, max_side=512, pad=0.15) -> bytes:
    im, _, _ = orient(data)
    if box:
        x, y, w, h = box
        px, py = w * pad, h * pad
        l, tt = max(0, x - px) * im.width, max(0, y - py) * im.height
        r, b = min(1, x + w + px) * im.width, min(1, y + h + py) * im.height
        im = im.crop((int(l), int(tt), max(int(l) + 1, int(r)), max(int(tt) + 1, int(b))))
    im.thumbnail((max_side, max_side))
    out = io.BytesIO()
    im.save(out, "JPEG", quality=85)
    return out.getvalue()
