"""Phase 9 (REQ-271..273): Kotri Railway Track Surface Faults Dataset v2 import + group splits.

Separate from Pueblo (calibration.SOURCE untouched). Admin-only. Staging under /tmp, originals byte-identical in
private object storage (re-read + sha256 verified). Durable/resumable via the calibration leased job queue
(kind "kotri_import"); idempotent by (release, path, sha256). Derived splits are project-generated.
"""
import asyncio
import io
import json
import os
import re
import stat
import zipfile
from collections import Counter, defaultdict

import requests
from PIL import Image

import calibration as cal
import storage
from core import APP_NAME, db, iso

SOURCE = {
    "kind": "mendeley_fixed", "dataset_id": "8hxtgyyxrw", "version": 2, "doi": "10.17632/8hxtgyyxrw.2",
    "url": "https://data.mendeley.com/public-api/zip/8hxtgyyxrw/download/2",
    "metadata_url": "https://data.mendeley.com/public-api/datasets/8hxtgyyxrw",
    "size": 317983414, "sha256": "e363aa06aee735b3643f1f0e43e5e0c95141f22c711e20242cd71b21ea62f450",
    "images": 5153, "image_bytes": 316715216, "distinct": 5151, "prefix": "Railway Track Surface Faults Dataset/",
}
FOLDERS = {"Cracks": ("crack", 40), "Flakings": ("flaking", 2829), "Grooves": ("groove", 8), "Joints": ("joint", 11),
           "Shellings": ("shelling", 130), "Spallings": ("spalling", 291), "Squats": ("squat", 1844)}
CLASSES = [v[0] for v in FOLDERS.values()]
SPLIT_GROUPS = {"fit": ["MOV_20201221091849", "MOV_20201221130147", "MOV_20201222164809", "MOV_20201228114152"],
                "calibration": ["MOV_20201223130541"], "test": ["MOV_20201227192101"]}
EXPECT_SPLITS = {
    "fit": {"total": 2745, "crack": 40, "flaking": 1878, "groove": 8, "joint": 11, "shelling": 87, "spalling": 89, "squat": 632},
    "calibration": {"total": 1908, "flaking": 933, "shelling": 43, "spalling": 154, "squat": 778},
    "test": {"total": 498, "flaking": 18, "spalling": 48, "squat": 432},
}
CREDIT = {
    "authors": "Asfar Arain, Sanaullah Mehran, Muhammad Zakir Shaikh, Dileep Kumar, Tanweer Hussain, Bhawani Shankar Chowdhry",
    "title": "Railway Track Surface Faults Dataset", "publisher": "Mendeley Data", "version": 2, "year": 2022,
    "doi": "10.17632/8hxtgyyxrw.2", "license": "CC BY 4.0", "endorsement": "No endorsement implied.",
    "location": "Kotri Junction, Pakistan", "capture": "Frames from inspection-vehicle videos (two EKEN-H9R cameras at railheads)",
    "not_in_source": ["videos", "healthy class", "bounding boxes", "masks", "severity", "cost labels"],
    "notes": ["Joints label is a rail joint, not a broken rail."],
}
GROUP_RE = re.compile(r"(MOV_\d{14})")
FRAME_RE = re.compile(r"_(\d+)\.[A-Za-z]+$")


def obj_path(ws: str, rid: str, rel: str) -> str:
    return f"{APP_NAME}/datasets/kotri/{ws}/{rid}/{rel}"


def check_members(z: zipfile.ZipFile, meta_by_name: dict) -> dict:
    problems, items = [], []
    for i in z.infolist():
        n = i.filename
        if i.is_dir():
            continue
        bad = cal._bad_name(n)
        if bad:
            problems.append(f"{bad}: {n}")
            continue
        if stat.S_ISLNK(i.external_attr >> 16):
            problems.append(f"symlink: {n}")
            continue
        if not n.startswith(SOURCE["prefix"]):
            problems.append(f"unexpected path: {n}")
            continue
        parts = n[len(SOURCE["prefix"]):].split("/")
        if len(parts) != 2 or parts[0] not in FOLDERS:
            problems.append(f"unexpected path: {n}")
            continue
        if parts[1] not in meta_by_name:
            problems.append(f"not in metadata: {n}")
        items.append((n, parts[0], parts[1], i.file_size))
    counts = Counter(f for _, f, _, _ in items)
    for f, (_, want) in FOLDERS.items():
        if counts.get(f, 0) != want:
            problems.append(f"{f}: {counts.get(f, 0)} images != {want}")
    if len(items) != SOURCE["images"]:
        problems.append(f"image count {len(items)} != {SOURCE['images']}")
    if sum(s for *_, s in items) != SOURCE["image_bytes"]:
        problems.append(f"image bytes {sum(s for *_, s in items)} != {SOURCE['image_bytes']}")
    return {"ok": not problems, "problems": problems[:50], "items": items}


def _store(zip_path: str, name: str, folder: str, fname: str, ws: str, rid: str, meta: list) -> dict:
    with zipfile.ZipFile(zip_path) as z:
        data = z.read(name)
    h = cal.sha(data)
    m = next((x for x in meta if x["sha256"] == h), None)
    rel = f"{folder}/{fname}"
    g = GROUP_RE.search(fname)
    fr = FRAME_RE.search(fname)
    rec = {"release_id": rid, "workspace_id": ws, "dataset_id": SOURCE["dataset_id"], "version": SOURCE["version"],
           "source_file_id": m["id"] if m else None, "filename": fname, "folder": folder, "path": rel,
           "label": FOLDERS[folder][0], "label_type": "image_class", "source_bbox": None, "source_mask": None, "source_severity": None,
           "bytes": len(data), "sha256": h, "doi": SOURCE["doi"], "license": CREDIT["license"],
           "capture_group": g.group(1) if g else None, "capture_group_basis": "provisional: MOV_ + 14 digits parsed from filename",
           "frame_index": int(fr.group(1)) if fr else None, "object_path": obj_path(ws, rid, rel), "created_at": iso()}
    err = []
    if not m:
        err.append("sha256 does not match source metadata for this filename")
    elif m["size"] != len(data):
        err.append(f"size {len(data)} != metadata {m['size']}")
    try:
        im = Image.open(io.BytesIO(data))
        im.load()
        rec["width"], rec["height"] = im.size
        if im.format != "JPEG":
            err.append(f"format {im.format} != JPEG")
        if im.size != (1280, 720):
            err.append(f"decoded size {im.size} != (1280, 720)")
    except Exception as e:
        err.append(f"decode failed: {e}"[:200])
    for attempt in range(4):
        try:
            storage.put_object(rec["object_path"], data, "image/jpeg")
            back = storage.get_object(rec["object_path"])
            break
        except Exception:
            if attempt == 3:
                raise
            import time
            time.sleep(2 * (attempt + 1))
    if cal.sha(back) != h:
        err.append("stored copy sha256 mismatch on re-verify")
    rec["verified"] = not err
    rec["error"] = "; ".join(err) or None
    return rec


async def _set(rid, **f):
    await db.dataset_releases.update_one({"uuid": rid}, {"$set": {"updated_at": iso(), **f}})


async def run_import(job):
    rid = job["target_id"]
    rel = await db.dataset_releases.find_one({"uuid": rid})
    ws = rel["workspace_id"]
    d = cal.stage_dir(rid)
    zip_path = os.path.join(d, "kotri.zip")
    loop = asyncio.get_running_loop()

    # metadata first (version must be 2)
    meta_raw = await cal.run_blocking(lambda: requests.get(SOURCE["metadata_url"], timeout=60).content)
    meta = json.loads(meta_raw)
    if meta.get("version") != SOURCE["version"]:
        raise RuntimeError(f"metadata version {meta.get('version')} != {SOURCE['version']}")
    files = meta["files"]
    if len(files) != SOURCE["images"]:
        raise RuntimeError(f"metadata lists {len(files)} files != {SOURCE['images']}")
    by_name = defaultdict(list)
    for f in files:
        by_name[f["filename"]].append({"id": f["id"], "sha256": f["content_details"]["sha256_hash"], "size": f["content_details"]["size"]})
    await _set(rid, status="Running", stage="download", metadata={"version": meta["version"], "files": len(files), "sha256": cal.sha(meta_raw)})

    if not os.path.exists(zip_path):
        part = zip_path + ".part"

        def prog(n):
            if n % (16 << 20) < (1 << 20):
                asyncio.run_coroutine_threadsafe(_set(rid, downloaded_bytes=n), loop)
                asyncio.run_coroutine_threadsafe(cal.heartbeat(job), loop)
        await cal.run_blocking(cal._download, SOURCE["url"], part, SOURCE["size"], prog)
        size = os.path.getsize(part)
        if size != SOURCE["size"]:
            os.remove(part)
            raise RuntimeError(f"archive size {size} != {SOURCE['size']}")
        h = await cal.run_blocking(cal._file_sha, part)
        if h != SOURCE["sha256"]:
            os.remove(part)
            raise RuntimeError(f"archive sha256 {h} != {SOURCE['sha256']}")
        os.replace(part, zip_path)
    await _set(rid, stage="verify", downloaded_bytes=SOURCE["size"], archive={"size": SOURCE["size"], "sha256": SOURCE["sha256"], "verified": True})
    await cal.heartbeat(job)

    chk = await cal.run_blocking(lambda: check_members(zipfile.ZipFile(zip_path), by_name))
    if not chk["ok"]:
        await _set(rid, status="Failed", stage="verify", problems=chk["problems"])
        return "Failed"

    done = {r["path"] async for r in db.kotri_images.find({"release_id": rid, "verified": True}, {"path": 1})}
    todo = [it for it in chk["items"] if f"{it[1]}/{it[2]}" not in done]
    await _set(rid, stage="store", stored=len(done), total=len(chk["items"]))
    for i in range(0, len(todo), 32):
        batch = todo[i:i + 32]
        recs = await asyncio.gather(*[loop.run_in_executor(cal.STORE_POOL, _store, zip_path, n, f, fn, ws, rid, by_name[fn])
                                      for n, f, fn, _ in batch])
        for r in recs:
            await db.kotri_images.update_one({"release_id": rid, "path": r["path"]}, {"$set": r}, upsert=True)
        await cal.heartbeat(job)
        await _set(rid, stored=await db.kotri_images.count_documents({"release_id": rid, "verified": True}))

    stats = await finalize(rid)
    ok = stats["matches_contract"]
    await _set(rid, status="Complete" if ok else "Failed", stage="done", stats=stats, completed_at=iso())
    return "Done" if ok else "Failed"


async def finalize(rid: str) -> dict:
    imgs = await db.kotri_images.find({"release_id": rid}, {"_id": 0, "path": 1, "sha256": 1, "label": 1, "capture_group": 1,
                                                             "verified": 1, "bytes": 1, "frame_index": 1}).to_list(10000)
    by_hash = defaultdict(list)
    for im in imgs:
        by_hash[im["sha256"]].append(im)
    dup_groups = [sorted(v, key=lambda x: x["path"]) for v in by_hash.values() if len(v) > 1]
    group_split = {g: s for s, gs in SPLIT_GROUPS.items() for g in gs}
    split_counts = {s: Counter() for s in SPLIT_GROUPS}
    cross = []
    for h, v in by_hash.items():
        splits = {group_split.get(x["capture_group"]) for x in v}
        if len(splits) > 1:
            cross.append(h)
        for k, x in enumerate(sorted(v, key=lambda x: x["path"])):
            s = group_split.get(x["capture_group"])
            await db.kotri_images.update_one({"release_id": rid, "path": x["path"]}, {"$set": {
                "split": s, "split_basis": "project-generated: by capture group (REQ-273)",
                "duplicate_of": None if k == 0 else v[0]["path"], "representative": k == 0}})
            if s and k == 0:
                split_counts[s][x["label"]] += 1
    splits = {s: {"total": sum(c.values()), **dict(c)} for s, c in split_counts.items()}
    classes = Counter(im["label"] for im in imgs)
    stats = {
        "images": len(imgs), "verified": sum(1 for i in imgs if i["verified"]), "bytes": sum(i["bytes"] for i in imgs),
        "distinct_hashes": len(by_hash), "duplicate_groups": [[x["path"] for x in g] for g in dup_groups],
        "classes": dict(classes), "splits": splits, "cross_split_hashes": len(cross),
        "unassigned": sum(1 for i in imgs if group_split.get(i["capture_group"]) is None),
        "healthy_false_positive_rate": None, "healthy_note": "No healthy class in source. Unmeasured.",
    }
    stats["matches_contract"] = (stats["images"] == SOURCE["images"] and stats["verified"] == SOURCE["images"]
                                 and stats["bytes"] == SOURCE["image_bytes"] and stats["distinct_hashes"] == SOURCE["distinct"]
                                 and all(classes.get(c) == n for c, n in FOLDERS.values()) and not cross and not stats["unassigned"]
                                 and all({k: v for k, v in splits[s].items() if v} == {k: v for k, v in EXPECT_SPLITS[s].items() if v} for s in SPLIT_GROUPS))
    return stats


cal.HANDLERS["kotri_import"] = run_import
