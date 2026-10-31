"""Photo scene processor — single-photo depth to Gaussian scene (Phase 4b, REQ-163/164/167/170).
Pure functions: no DB, no auth, no storage. Wrapped by scenes.py (jobs/storage) and routes_photo_scene.py (auth/API).
Output is AI-estimated relative depth from ONE photo; it is never presented as measured geometry."""
import hashlib
import io
import json
import math
import os
import tempfile
import time
import urllib.request
import warnings
from typing import Callable, Optional

import numpy as np
from PIL import Image, ImageFile, ImageOps

PROCESSOR_REVISION = "photo-scene-v1"
SCHEMA_VERSION = 1
MAX_BYTES = 20 * 1024 * 1024
MAX_PIXELS = 32_000_000
MIN_SIDE = 32
FORMATS = {"JPEG", "PNG", "WEBP"}
MODEL_SIDE, MULTIPLE = 518, 14
MEAN = np.array([0.485, 0.456, 0.406], np.float32)
STD = np.array([0.229, 0.224, 0.225], np.float32)
DISPLAY_MAX = 384
FOV_H_DEG = 55.0
SH_C0 = 0.28209479177387814
OPACITY = 4.0
SCALE_XY_FACTOR = 0.72
SCALE_Z = math.log(0.002)
PLY_COMMENT = "AI-estimated relative depth; no measured geometry"
PLY_PROPS = ["x", "y", "z", "f_dc_0", "f_dc_1", "f_dc_2", "opacity", "scale_0", "scale_1", "scale_2", "rot_0", "rot_1", "rot_2", "rot_3"]
PLACEMENT = "bbox_center_estimated_depth"
LOCATION_BASIS = "single_photo_estimated_depth"
MODEL = {"id": "onnx-community/depth-anything-v2-small", "revision": "4472b7362082ad9968fee890ca0f1e5aca36b93d",
         "file": "onnx/model.onnx", "sha256": "afb6a5c28f3b6bf1618c6e43f02073ef9dfdc70e937502d51603e57b0a1df10c",
         "preprocessor_sha256": "03576db3c13dd0471fdf5f5e1428befcb95de063fe699879150b293dc9e0a2c6", "license": "Apache-2.0"}
MODEL_URL = f"https://huggingface.co/{MODEL['id']}/resolve/{MODEL['revision']}/{MODEL['file']}"
MODEL_MAX_BYTES = 512 * 1024 * 1024
SETTINGS = {"model_side": MODEL_SIDE, "multiple": MULTIPLE, "display_max": DISPLAY_MAX, "fov_horizontal_deg": FOV_H_DEG,
            "percentiles": [2, 98], "z_formula": "z = 3 / (0.5 + d)", "opacity": OPACITY, "scale_xy_factor": SCALE_XY_FACTOR, "scale_z": 0.002}

Image.MAX_IMAGE_PIXELS = MAX_PIXELS
ImageFile.LOAD_TRUNCATED_IMAGES = False


class ProcessorError(Exception):
    code, retryable = "failed", True

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message

    def as_dict(self):
        return {"code": self.code, "message": self.message, "retryable": self.retryable}


class UnsupportedImage(ProcessorError):
    code, retryable = "unsupported", False


class DepthUninformative(ProcessorError):
    code, retryable = "depth_uninformative", False


class ModelUnavailable(ProcessorError):
    code, retryable = "model_unavailable", True


class DepthModelError(ProcessorError):
    code, retryable = "depth_failed", True


def processing_key(source_sha256: str) -> str:
    return "|".join([source_sha256, PROCESSOR_REVISION, MODEL["sha256"], hashlib.sha256(json.dumps(SETTINGS, sort_keys=True).encode()).hexdigest()[:16]])


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


# ---------------- provisioning (REQ-167) ----------------
def provision_model(target_path: str, expected_sha256: str = MODEL["sha256"], url: str = MODEL_URL,
                    max_bytes: int = MODEL_MAX_BYTES, urlopen: Callable = urllib.request.urlopen) -> dict:
    """Good cache → no download. Otherwise download to a temp .part in the target dir, cap size, verify hash, os.replace.
    Any failure removes the .part and raises ModelUnavailable (an existing bad cache is never used)."""
    if os.path.exists(target_path) and sha256_file(target_path) == expected_sha256:
        return {"source": "cache", "path": target_path, "sha256": expected_sha256}
    d = os.path.dirname(os.path.abspath(target_path))
    os.makedirs(d, exist_ok=True)
    fd, part = tempfile.mkstemp(dir=d, prefix=os.path.basename(target_path) + ".", suffix=".part")
    try:
        h, n = hashlib.sha256(), 0
        with os.fdopen(fd, "wb") as out, urlopen(url, timeout=60) as r:
            for chunk in iter(lambda: r.read(1 << 20), b""):
                n += len(chunk)
                if n > max_bytes:
                    raise ModelUnavailable(f"Model download exceeded {max_bytes} bytes")
                h.update(chunk)
                out.write(chunk)
        if h.hexdigest() != expected_sha256:
            raise ModelUnavailable("Downloaded model checksum mismatch")
        os.replace(part, target_path)
        return {"source": "download", "path": target_path, "sha256": expected_sha256, "bytes": n}
    except ModelUnavailable:
        raise
    except Exception as e:
        raise ModelUnavailable(f"Model download failed ({type(e).__name__})")
    finally:
        if os.path.exists(part):
            os.remove(part)


class DepthSession:
    """One CPUExecutionProvider session per process."""

    def __init__(self, model_path: str, expected_sha256: str = MODEL["sha256"]):
        if not os.path.exists(model_path):
            raise ModelUnavailable("Depth model file not provisioned")
        if sha256_file(model_path) != expected_sha256:
            raise ModelUnavailable("Depth model checksum mismatch")
        import onnxruntime as ort
        so = ort.SessionOptions()
        so.intra_op_num_threads = min(4, os.cpu_count() or 1)
        self.session = ort.InferenceSession(model_path, sess_options=so, providers=["CPUExecutionProvider"])
        self.input = self.session.get_inputs()[0].name
        self.model_path = model_path

    def infer(self, x: np.ndarray) -> np.ndarray:
        try:
            out = self.session.run(None, {self.input: x})[0]
        except Exception as e:
            raise DepthModelError(f"Depth inference failed ({type(e).__name__})")
        out = np.squeeze(np.asarray(out, np.float32))
        if out.ndim != 2 or not np.all(np.isfinite(out)):
            raise DepthModelError("Depth output must be a finite 2D map")
        return out


# ---------------- decode / validate (REQ-163) ----------------
def decode(data: bytes):
    if len(data) > MAX_BYTES:
        raise UnsupportedImage("Photo larger than 20 MiB")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            im = Image.open(io.BytesIO(data))
            fmt = im.format
            if fmt not in FORMATS:
                raise UnsupportedImage("Unsupported photo format. View original or upload JPEG/PNG")
            if getattr(im, "n_frames", 1) != 1:
                raise UnsupportedImage("Multi-frame images are not supported")
            if im.width * im.height > MAX_PIXELS:
                raise UnsupportedImage("Photo larger than 32 megapixels")
            if min(im.size) < MIN_SIDE:
                raise UnsupportedImage("Photo smaller than 32 pixels on a side")
            im.load()
    except UnsupportedImage:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise UnsupportedImage("Photo exceeds the decompression safety limit")
    except Exception:
        raise UnsupportedImage("Unsupported photo format. View original or upload JPEG/PNG")
    if im.mode in ("RGBA", "LA", "PA", "La", "RGBa") or "transparency" in im.info:
        raise UnsupportedImage("Photos with transparency are not supported")
    o = int(im.getexif().get(0x0112, 1) or 1)
    o = o if 1 <= o <= 8 else 1
    raw_w, raw_h = im.size
    oriented = ImageOps.exif_transpose(im).convert("RGB")
    return oriented, {"format": fmt, "exif_orientation": o, "raw_width": raw_w, "raw_height": raw_h,
                      "oriented_width": oriented.width, "oriented_height": oriented.height}


def model_input(oriented: Image.Image) -> np.ndarray:
    scale = MODEL_SIDE / max(oriented.size)
    w = max(MULTIPLE, round(oriented.width * scale / MULTIPLE) * MULTIPLE)
    h = max(MULTIPLE, round(oriented.height * scale / MULTIPLE) * MULTIPLE)
    x = (np.asarray(oriented.resize((w, h), Image.BICUBIC), np.float32) / 255.0 - MEAN) / STD
    return x.transpose(2, 0, 1)[None].astype(np.float32)


def focal(width: int) -> float:
    return 0.5 * width / math.tan(math.radians(FOV_H_DEG / 2))


# ---------------- build (REQ-163/164) ----------------
def build(data: bytes, session: Optional[DepthSession], *, fault: Optional[str] = None, source_sha256: Optional[str] = None) -> dict:
    t0 = time.time()
    oriented, src = decode(data)
    t1 = time.time()
    if fault == "checksum":
        raise ModelUnavailable("Depth model checksum mismatch (fault injection)")
    if session is None:
        raise ModelUnavailable("Depth model not loaded")
    x = model_input(oriented)
    depth = session.infer(x)
    if fault == "uninformative":
        depth = np.full_like(depth, 1.0)
    if fault == "error":
        raise DepthModelError("Injected depth failure")
    t2 = time.time()
    display = oriented.copy()
    display.thumbnail((DISPLAY_MAX, DISPLAY_MAX), Image.LANCZOS)
    W, H = display.size
    dep = np.asarray(Image.fromarray(depth, mode="F").resize((W, H), Image.BICUBIC), np.float32)
    low, high = (float(v) for v in np.percentile(dep, [2, 98]))
    span = high - low
    if not math.isfinite(span) or span < 1e-6:
        raise DepthUninformative("Depth estimate has no usable variation for this photo")
    d = np.clip((dep - low) / span, 0, 1)
    z = (3.0 / (0.5 + d)).astype(np.float32)
    f = focal(W)
    cols, rows = np.meshgrid(np.arange(W, dtype=np.float32), np.arange(H, dtype=np.float32))
    X = (cols + 0.5 - W / 2) * z / f
    Y = -(rows + 0.5 - H / 2) * z / f
    rgb = np.asarray(display, np.float32).reshape(-1, 3)
    n = W * H
    arr = np.zeros((n, 14), np.float32)
    arr[:, 0], arr[:, 1], arr[:, 2] = X.ravel(), Y.ravel(), -z.ravel()
    arr[:, 3:6] = (rgb / 255.0 - 0.5) / SH_C0
    arr[:, 6] = OPACITY
    arr[:, 7] = arr[:, 8] = np.log(z.ravel() / f * SCALE_XY_FACTOR)
    arr[:, 9] = SCALE_Z
    arr[:, 10] = 1.0
    header = (f"ply\nformat binary_little_endian 1.0\ncomment {PLY_COMMENT}\nelement vertex {n}\n"
              + "".join(f"property float {p}\n" for p in PLY_PROPS) + "end_header\n")
    ply = header.encode("ascii") + arr.astype("<f4").tobytes()
    zb = io.BytesIO()
    np.save(zb, z, allow_pickle=False)
    png16 = io.BytesIO()
    Image.fromarray(np.round(d * 65535).astype(np.uint16)).save(png16, "PNG")
    opng = io.BytesIO()
    oriented.save(opng, "PNG")
    t3 = time.time()
    arts = {"splat": (ply, "application/octet-stream", "splat.ply"), "display_z": (zb.getvalue(), "application/octet-stream", "display_z.npy"),
            "depth_png": (png16.getvalue(), "image/png", "depth.png"), "oriented_photo": (opng.getvalue(), "image/png", "oriented.png")}
    manifest = {
        "schema_version": SCHEMA_VERSION, "mode": "photo_derived_depth", "processor_revision": PROCESSOR_REVISION,
        "label": "AI-estimated relative depth; no measured geometry", "units": "arbitrary_display_units", "metric": False,
        "hidden_surfaces": "not_reconstructed", "exif_orientation_applied": src["exif_orientation"],
        "dimensions": {"raw": {"width": src["raw_width"], "height": src["raw_height"]}, "oriented": {"width": src["oriented_width"], "height": src["oriented_height"]},
                       "sampled": {"width": W, "height": H}},
        "depth_range": {"z_min": float(z.min()), "z_max": float(z.max()), "low_p2": low, "high_p98": high},
        "focal_pixels": f, "coordinate_convention": "right-handed, +Y up, camera at origin looking down -Z (OpenGL); units arbitrary",
        "projection": {"type": "pinhole", "horizontal_fov_deg": FOV_H_DEG, "focal_pixels": f, "width": W, "height": H,
                       "image_to_world": "x=(col+0.5-W/2)*z/f, y=-(row+0.5-H/2)*z/f, z=-z", "world_to_image": "u=(x*f/z+W/2)/W, v=(-y*f/z+H/2)/H, z=-P.z"},
        "model": {k: MODEL[k] for k in ("id", "revision", "file", "sha256", "license")}, "settings": SETTINGS,
        "source": {"sha256": source_sha256 or hashlib.sha256(data).hexdigest(), "byte_length": len(data), **src},
        "model_input": {"width": int(x.shape[3]), "height": int(x.shape[2]), "resample": "BICUBIC", "mean": MEAN.tolist(), "std": STD.tolist(), "layout": "NCHW"},
        "display": {"width": W, "height": H, "resample": "LANCZOS"},
        "depth": {"output_width": int(depth.shape[1]), "output_height": int(depth.shape[0]), "resize": "BICUBIC", "low": low, "high": high, "span": span,
                  "mode": "relative_inverse_normalized", "z_min": float(z.min()), "z_max": float(z.max())},
        "camera": {"position": [0.0, 0.0, 0.0], "target": [0.0, 0.0, -4.0], "fov": FOV_H_DEG, "horizontal_fov": True, "fov_horizontal_deg": FOV_H_DEG, "focal_px": f, "width": W, "height": H,
                   "up": [0.0, 1.0, 0.0], "convention": "right-handed, +Y up, camera looks down -Z; pixel (col,row) centre: x=(col+0.5-W/2)*z/f, y=-(row+0.5-H/2)*z/f, z=-z"},
        "splat": {"format": "ply binary_little_endian", "vertex_count": n, "properties": PLY_PROPS, "comment": PLY_COMMENT},
        "anchor": {"placement_method": PLACEMENT, "location_basis": LOCATION_BASIS, "sampling": "col=floor(u*W), row=floor(v*H) on display_z"},
        "artifacts": {k: {"file": fn, "sha256": hashlib.sha256(b).hexdigest(), "byte_length": len(b), "content_type": ct} for k, (b, ct, fn) in arts.items()},
        "processing_key": processing_key(source_sha256 or hashlib.sha256(data).hexdigest()),
        "timings_s": {"decode": round(t1 - t0, 3), "inference": round(t2 - t1, 3), "build": round(t3 - t2, 3)},
        "processing_seconds": round(t3 - t0, 3),
    }
    return {"manifest": manifest, "artifacts": arts, "z": z, "focal": f, "width": W, "height": H}


def manifest_bytes(manifest: dict) -> bytes:
    return json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()


# ---------------- anchors (REQ-164/171) ----------------
def validate_box(box) -> list:
    if not isinstance(box, (list, tuple)) or len(box) != 4:
        raise ValueError("Box must be [x, y, w, h]")
    x, y, w, h = (float(v) for v in box)
    if not all(math.isfinite(v) for v in (x, y, w, h)) or w <= 0 or h <= 0 or x < 0 or y < 0 or x + w > 1 + 1e-9 or y + h > 1 + 1e-9:
        raise ValueError("Box outside the photo or empty")
    return [x, y, w, h]


def anchor_from_point(z: np.ndarray, f: float, u: float, v: float) -> dict:
    if not (math.isfinite(u) and math.isfinite(v) and 0 <= u <= 1 and 0 <= v <= 1):
        raise ValueError("Point must be within 0..1")
    H, W = z.shape
    col, row = min(W - 1, int(math.floor(u * W))), min(H - 1, int(math.floor(v * H)))
    zz = float(z[row, col])
    xyz = [(col + 0.5 - W / 2) * zz / f, -(row + 0.5 - H / 2) * zz / f, -zz]
    return {"u": u, "v": v, "col": col, "row": row, "xyz": [round(c, 6) for c in xyz], "location_basis": LOCATION_BASIS}


def anchor_from_box(z: np.ndarray, f: float, box) -> dict:
    x, y, w, h = validate_box(box)
    return {**anchor_from_point(z, f, x + w / 2, y + h / 2), "placement_method": PLACEMENT}


def project(xyz, f: float, W: int, H: int):
    x, y, zz = xyz
    if zz >= 0:
        return None
    z = -zz
    return [(x * f / z + W / 2) / W, (-y * f / z + H / 2) / H]


# ---------------- region frames (REQ-170) ----------------
_POINT = {1: lambda x, y: (x, y), 2: lambda x, y: (1 - x, y), 3: lambda x, y: (1 - x, 1 - y), 4: lambda x, y: (x, 1 - y),
          5: lambda x, y: (y, x), 6: lambda x, y: (1 - y, x), 7: lambda x, y: (1 - y, 1 - x), 8: lambda x, y: (y, 1 - x)}


def raw_to_oriented_box(box, orientation: int) -> list:
    """Normalized raw-pixel box → normalized EXIF-oriented box (4-corner transform + envelope; 5-8 swap W/H implicitly)."""
    x, y, w, h = validate_box(box)
    pts = [_POINT[orientation if orientation in _POINT else 1](px, py) for px, py in ((x, y), (x + w, y), (x, y + h), (x + w, y + h))]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return [min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)]


def crop_box_to_full(box, crop, full_w: int, full_h: int) -> list:
    """Box relative to an analysis crop/letterbox content area [cx,cy,cw,ch] (oriented pixels) → full-image normalized box."""
    a, b, w, h = validate_box(box)
    cx, cy, cw, ch = crop
    return validate_box([(cx + a * cw) / full_w, (cy + b * ch) / full_h, w * cw / full_w, h * ch / full_h])


def region_to_oriented(region, frame: Optional[dict], orientation: int):
    """frame None / {'kind':'oriented_full'} → as is; {'kind':'raw'} → EXIF transform; {'kind':'crop', crop, full_w, full_h} → undo crop."""
    kind = (frame or {}).get("kind", "oriented_full")
    if kind == "raw":
        return raw_to_oriented_box(region, orientation)
    if kind == "crop":
        return crop_box_to_full(region, frame["crop"], frame["full_w"], frame["full_h"])
    return validate_box(region)
