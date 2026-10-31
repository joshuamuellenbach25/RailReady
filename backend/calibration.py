"""Phase 6: Pueblo Rail Components dataset import, partitions, baseline/training/evaluation runs, Platt calibration.

Staff-only research/calibration (CC BY-NC-SA 4.0). Dataset images NEVER create visits, findings, decisions or quantities.
Staging lives in /tmp (not /app). Originals are stored byte-identical in private object storage, re-verified by sha256.
"""
import asyncio
import base64
import hashlib
import io
import json
import logging
import os
import re
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import numpy as np
import requests
from PIL import Image

import storage
from core import APP_NAME, db, iso, new_id

log = logging.getLogger("calibration")

STAGE_ROOT = "/tmp/railready_cal"
SOURCE = {
    "kind": "kaggle_fixed", "dataset": "elvin1233/rail-components", "version": 1,
    "url": "https://www.kaggle.com/api/v1/datasets/download/elvin1233/rail-components",
    "size": 500370877, "sha256": "af60904318e2a6e5f8f136fd2064ac7a00d04cb231a41c831e513c2cac209a83",
    "members": 2102, "uncompressed": 519538936, "prefix": "Rail Components Dataset/",
}
JSON_SHA = {"train": "1e063d8d8dbafa2f64814bfdc254460a6571df2762f2c59923d554659ba29475",
            "val": "5bccc1ab170092b59481d11bc77e6decbb5ead6f55e6aa6ae4272459da5db53d"}
EXPECT = {"images": 2100, "train_images": 1600, "val_images": 500, "annotations": 43545, "train_annotations": 33406,
          "val_annotations": 10139, "whole_image_annotations": 2100, "physical_annotations": 41445}
CONTRACT_STATS = {1: ("clip", 4306, 204), 2: ("spike_and_bolt", 10882, 497), 3: ("tie", 3709, 409), 4: ("hole", 5204, 649),
                  5: ("rail", 2168, 0), 6: ("anchor", 1711, 14), 7: ("clip_base", 3748, 208), 8: ("joint_bar", 169, 5),
                  9: ("joint_gap", 73, 21), 10: ("baseplate", 6820, 648), 11: ("image", 1662, 438)}
ATTRIBUTION = {
    "authors": "Youzhi Tang, Yu Qian", "citation": "Automation in Construction 190 (2026) 107074",
    "doi": "10.1016/j.autcon.2026.107074", "region": "Pueblo, Colorado", "region_source": "rip.trb.org/View/2572335",
    "source": "Kaggle elvin1233/rail-components v1",
}
LICENSE = {"id": "CC BY-NC-SA 4.0", "use": "private research/calibration only; commercial/public permission UNKNOWN"}
RAIL_NOTE = "No Bad rail labels. Broken-rail sensitivity unsupported"
PROFILE_LABEL = "Pueblo source-domain calibration. Not field-validated elsewhere"
SF_VALIDATION = {"status": "UNKNOWN", "reason": "No separately sourced, reviewed SF images have been evaluated."}
BUDGET_MSG = "Image-call budget reached – admin approval needed"
HOSTED_TRAINING_BLOCKER = ("Weight training of the hosted vision model (Claude Sonnet 5.5 via Emergent Universal Key) is "
                           "unsupported: no fine-tuning endpoint is available. Prompting/exemplars are not training.")
TARGET_CLASSES = {1: "clip", 2: "spike_and_bolt", 3: "tie"}
WHOLE_IMAGE_CAT = 11
OWNER = f"cal-{os.getpid()}-{new_id()[:8]}"
LEASE_S = 600
POOL = ThreadPoolExecutor(max_workers=8)
STORE_POOL = ThreadPoolExecutor(max_workers=4)  # gentle on object storage


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def stage_dir(release_id: str) -> str:
    d = os.path.join(STAGE_ROOT, release_id)
    os.makedirs(d, exist_ok=True)
    return d


def obj_path(ws: str, release_id: str, rel: str) -> str:
    return f"{APP_NAME}/calibration/{ws}/{release_id}/{rel}"


# ---------------------------------------------------------------- jobs (durable, leased, resumable)
async def enqueue(ws: str, kind: str, target_id: str, user_id: str) -> dict:
    job = {"uuid": new_id(), "workspace_id": ws, "kind": kind, "target_id": target_id, "status": "Queued", "attempts": 0,
           "lease_owner": None, "lease_until": None, "error": None, "created_by": user_id, "created_at": iso(), "updated_at": iso()}
    await db.cal_jobs.insert_one(dict(job))
    return job


async def heartbeat(job: dict, **fields):
    await db.cal_jobs.update_one({"uuid": job["uuid"]}, {"$set": {
        "lease_until": time.time() + LEASE_S, "updated_at": iso(), **fields}})


async def _claim():
    return await db.cal_jobs.find_one_and_update(
        {"$or": [{"status": "Queued"}, {"status": "Running", "lease_until": {"$lt": time.time()}}]},
        {"$set": {"status": "Running", "lease_owner": OWNER, "lease_until": time.time() + LEASE_S, "updated_at": iso()},
         "$inc": {"claims": 1}}, sort=[("created_at", 1)], return_document=True)


async def worker():
    await db.cal_jobs.update_many({"status": "Running", "lease_owner": {"$ne": OWNER}},
                                  {"$set": {"status": "Queued", "lease_owner": None}})  # resume after restart
    while True:
        try:
            job = await _claim()
            if not job:
                await asyncio.sleep(2)
                continue
            handler = HANDLERS[job["kind"]]
            try:
                status = await handler(job) or "Done"
                await db.cal_jobs.update_one({"uuid": job["uuid"]}, {"$set": {"status": status, "lease_owner": None, "updated_at": iso()}})
            except Exception as e:  # bounded retries (failures only; restarts/resumes don't count), then fail with the exact error
                log.exception("calibration job %s failed", job["uuid"])
                st = "Queued" if job.get("attempts", 0) + 1 < 3 else "Failed"
                await db.cal_jobs.update_one({"uuid": job["uuid"]}, {"$set": {"status": st, "error": f"{type(e).__name__}: {e}"[:600],
                                                                              "lease_owner": None, "updated_at": iso()}, "$inc": {"attempts": 1}})
                if st == "Failed":
                    await _mark_target_failed(job, f"{type(e).__name__}: {e}"[:600])
                await asyncio.sleep(3)
        except Exception:
            log.exception("calibration worker loop")
            await asyncio.sleep(5)


async def _mark_target_failed(job, err):
    coll = {"import": "dataset_releases", "kotri_import": "dataset_releases", "partition": "data_partitions"}.get(job["kind"], "model_runs")
    await db[coll].update_one({"uuid": job["target_id"]}, {"$set": {"status": "Failed", "error": err, "updated_at": iso()}})


def start_worker():
    asyncio.get_running_loop().create_task(worker())


async def run_blocking(fn, *a):
    return await asyncio.get_running_loop().run_in_executor(POOL, fn, *a)


# ---------------------------------------------------------------- import
def _download(url: str, part: str, expect_size: int, progress_cb) -> None:
    for attempt in range(5):  # bounded retries, HTTP Range resume
        have = os.path.getsize(part) if os.path.exists(part) else 0
        if have >= expect_size:
            return
        try:
            with requests.get(url, headers={"Range": f"bytes={have}-"} if have else {}, stream=True, timeout=60) as r:
                if r.status_code == 200 and have:
                    have = 0  # server ignored Range: restart cleanly
                    open(part, "wb").close()
                r.raise_for_status()
                with open(part, "ab") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
                        have += len(chunk)
                        progress_cb(have)
            return
        except Exception as e:
            log.warning("download attempt %d failed: %s", attempt + 1, e)
            time.sleep(min(30, 2 ** attempt))
    raise RuntimeError("download failed after 5 attempts")


def _file_sha(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _bad_name(n: str) -> Optional[str]:
    if n.startswith("/") or n.startswith("\\") or re.match(r"^[A-Za-z]:", n):
        return "absolute path"
    if "\\" in n or any(p == ".." for p in n.split("/")):
        return "path traversal"
    return None


def verify_members(zip_path: str) -> dict:
    """Member list must exactly match the contract (derived from the hashed JSONs)."""
    z = zipfile.ZipFile(zip_path)
    infos = z.infolist()
    names = [i.filename for i in infos]
    problems = []
    seen = set()
    for i in infos:
        bad = _bad_name(i.filename)
        if bad:
            problems.append(f"{bad}: {i.filename}")
        if i.filename in seen:
            problems.append(f"duplicate name: {i.filename}")
        seen.add(i.filename)
        if i.compress_size and i.file_size / max(1, i.compress_size) > 100 and i.file_size > 10_000_000:
            problems.append(f"excessive decompression ratio: {i.filename}")
    jsons = {}
    for s in ("train", "val"):
        p = f"{SOURCE['prefix']}annotations/{s}.json"
        if p not in seen:
            problems.append(f"missing member: {p}")
            continue
        b = z.read(p)
        if sha(b) != JSON_SHA[s]:
            problems.append(f"{s}.json sha256 {sha(b)} != {JSON_SHA[s]}")
        jsons[s] = json.loads(b)
    expected = {f"{SOURCE['prefix']}annotations/{s}.json" for s in ("train", "val")}
    for s, j in jsons.items():
        expected |= {f"{SOURCE['prefix']}{s}/{im['file_name']}" for im in j["images"]}
    unexpected = sorted(seen - expected)
    missing = sorted(expected - seen)
    problems += [f"unexpected path: {n}" for n in unexpected[:20]] + [f"missing member: {n}" for n in missing[:20]]
    if len(names) != SOURCE["members"]:
        problems.append(f"member count {len(names)} != {SOURCE['members']}")
    total = sum(i.file_size for i in infos)
    if total != SOURCE["uncompressed"]:
        problems.append(f"uncompressed bytes {total} != {SOURCE['uncompressed']}")
    return {"ok": not problems, "problems": problems, "rejected": [p for p in problems if p.split(":")[0] in
                                                                     ("absolute path", "path traversal", "duplicate name", "unexpected path", "excessive decompression ratio")]}


def _store_member(zip_path: str, name: str, ws: str, rid: str) -> dict:
    with zipfile.ZipFile(zip_path) as z:
        data = z.read(name)
    rel = name[len(SOURCE["prefix"]):]
    h = sha(data)
    rec = {"path": rel, "sha256": h, "size": len(data), "object_path": obj_path(ws, rid, rel)}
    if rel.endswith(".jpg"):
        try:
            im = Image.open(io.BytesIO(data))
            im.load()
            rec["width"], rec["height"] = im.size
            rec["decoded"] = im.size == (512, 512)
            if not rec["decoded"]:
                rec["error"] = f"decoded size {im.size} != (512, 512)"
        except Exception as e:
            rec["decoded"], rec["error"] = False, f"decode failed: {e}"[:200]
    for attempt in range(4):  # transient storage errors: bounded retry with backoff
        try:
            storage.put_object(rec["object_path"], data, "image/jpeg" if rel.endswith(".jpg") else "application/json")
            back = storage.get_object(rec["object_path"])
            break
        except Exception:
            if attempt == 3:
                raise
            time.sleep(2 * (attempt + 1))
    rec["verified"] = sha(back) == h and len(back) == len(data)
    if not rec["verified"]:
        rec["error"] = "stored copy sha256 mismatch on re-verify"
    return rec


async def _set_release(rid: str, **fields):
    await db.dataset_releases.update_one({"uuid": rid}, {"$set": {"updated_at": iso(), **fields}})


async def run_import(job):
    rid = job["target_id"]
    rel = await db.dataset_releases.find_one({"uuid": rid})
    ws = rel["workspace_id"]
    d = stage_dir(rid)
    zip_path = os.path.join(d, "archive.zip")
    loop = asyncio.get_running_loop()

    # 1) download (fixed source) or uploaded archive already staged
    if not os.path.exists(zip_path):
        if rel["source"]["kind"] != "kaggle_fixed":
            await _set_release(rid, status="Blocked", blocker="Uploaded archive missing from staging; upload again.")
            return "Failed"
        part = zip_path + ".part"
        early = os.path.join(STAGE_ROOT, "staging", "archive.zip.part")  # same fixed URL, started early; still fully verified below
        if not os.path.exists(part) and os.path.exists(early):
            os.replace(early, part)
        await _set_release(rid, status="Downloading")
        last = [0.0]

        def cb(n):
            if time.time() - last[0] > 2:
                last[0] = time.time()
                asyncio.run_coroutine_threadsafe(_set_release(rid, **{"progress.downloaded_bytes": n}), loop)
        await run_blocking(_download, SOURCE["url"], part, SOURCE["size"], cb)
        os.replace(part, zip_path)
    await heartbeat(job)

    # 2) archive verification (size + sha + member list)
    await _set_release(rid, status="Verifying", **{"progress.downloaded_bytes": os.path.getsize(zip_path)})
    size = os.path.getsize(zip_path)
    digest = await run_blocking(_file_sha, zip_path)
    if size != SOURCE["size"] or digest != SOURCE["sha256"]:
        await _set_release(rid, status="Blocked", archive_observed={"size": size, "sha256": digest},
                           blocker=f"Archive differs from contract: size {size} (expected {SOURCE['size']}), sha256 {digest} "
                                   f"(expected {SOURCE['sha256']}). Upload the exact ZIP via POST /api/calibration/datasets/import (multipart).",
                           upload_option=True)
        return "Failed"
    mv = await run_blocking(verify_members, zip_path)
    if not mv["ok"]:
        await _set_release(rid, status="Blocked", blocker="Member list differs from contract: " + "; ".join(mv["problems"][:10]),
                           rejected_members=mv["rejected"], upload_option=True)
        return "Failed"
    await _set_release(rid, archive_observed={"size": size, "sha256": digest}, **{"progress.archive_verified": True})

    # 3) store every member byte-identical + re-verify (resume by key; skip verified)
    with zipfile.ZipFile(zip_path) as z:
        members = [n for n in z.namelist()]
    for pass_no in range(3):  # retry passes for files that failed transiently
        done = {f["path"] async for f in db.dataset_files.find({"release_id": rid, "verified": True}, {"path": 1})}
        todo = [n for n in members if n[len(SOURCE["prefix"]):] not in done]
        if not todo:
            break
        if pass_no:
            await asyncio.sleep(10 * pass_no)
        await _set_release(rid, status="Storing", **{"progress.files_total": len(members), "progress.files_verified": len(done), "progress.store_pass": pass_no + 1})
        for i in range(0, len(todo), 16):
            batch = todo[i:i + 16]
            recs = await asyncio.gather(*[loop.run_in_executor(STORE_POOL, _store_member, zip_path, n, ws, rid) for n in batch], return_exceptions=True)
            for n, r in zip(batch, recs):
                if isinstance(r, Exception):
                    r = {"path": n[len(SOURCE["prefix"]):], "verified": False, "error": f"{type(r).__name__}: {r}"[:200]}
                await db.dataset_files.update_one({"release_id": rid, "path": r["path"]},
                                                  {"$set": {**r, "release_id": rid, "workspace_id": ws, "updated_at": iso()}}, upsert=True)
            nver = await db.dataset_files.count_documents({"release_id": rid, "verified": True})
            await _set_release(rid, **{"progress.files_verified": nver})
            await heartbeat(job)

    # 4) index images + annotations from the verified JSONs (idempotent upserts by key)
    await _set_release(rid, status="Indexing")
    with zipfile.ZipFile(zip_path) as z:
        jsons = {s: json.loads(z.read(f"{SOURCE['prefix']}annotations/{s}.json")) for s in ("train", "val")}
    files = {f["path"]: f async for f in db.dataset_files.find({"release_id": rid})}
    cats = {c["id"]: c["name"] for c in jsons["train"]["categories"]}
    orphans = 0
    for s, j in jsons.items():
        img_ops, idmap = [], {}
        from pymongo import UpdateOne
        for im in j["images"]:
            f = files.get(f"{s}/{im['file_name']}", {})
            key = f"{rid}:{s}:{im['file_name']}"
            idmap[im["id"]] = key
            img_ops.append(UpdateOne({"uuid": key}, {"$set": {
                "uuid": key, "release_id": rid, "workspace_id": ws, "split": s, "file_name": im["file_name"], "coco_id": im["id"],
                "width": im["width"], "height": im["height"], "sha256": f.get("sha256"), "object_path": f.get("object_path"),
                "decoded": bool(f.get("decoded")), "verified": bool(f.get("verified")), "error": f.get("error"),
                "test_locked": s == "val"}}, upsert=True))
        await db.dataset_images.bulk_write(img_ops, ordered=False)
        for k in range(0, len(j["annotations"]), 2000):
            ops = []
            for a in j["annotations"][k:k + 2000]:
                parent = idmap.get(a["image_id"])
                orphans += parent is None
                attrs = a.get("attributes") or {}
                ops.append(UpdateOne({"release_id": rid, "split": s, "ann_id": a["id"]}, {"$set": {
                    "release_id": rid, "workspace_id": ws, "split": s, "ann_id": a["id"], "image_key": parent,
                    "coco_image_id": a["image_id"], "category_id": a["category_id"], "category_name": cats.get(a["category_id"]),
                    "attributes": attrs, "bbox": a["bbox"], "segmentation": a.get("segmentation"), "area": a.get("area"),
                    "iscrowd": a.get("iscrowd"),  # source fields unmodified (REQ-239)
                    "physical": a["category_id"] != WHOLE_IMAGE_CAT and not (a["category_id"] == 10 and attrs.get("Type") == "virtual"),
                    "virtual_baseplate": a["category_id"] == 10 and attrs.get("Type") == "virtual"}}, upsert=True))
            await db.dataset_annotations.bulk_write(ops, ordered=False)
            await heartbeat(job)

    # 5) completeness
    stats = await compute_stats(rid)
    counts = {
        "images": await db.dataset_images.count_documents({"release_id": rid}),
        "images_verified_512": await db.dataset_images.count_documents({"release_id": rid, "verified": True, "decoded": True}),
        "train_images": await db.dataset_images.count_documents({"release_id": rid, "split": "train"}),
        "val_images": await db.dataset_images.count_documents({"release_id": rid, "split": "val"}),
        "json_verified": await db.dataset_files.count_documents({"release_id": rid, "path": {"$regex": "^annotations/"}, "verified": True}),
        "annotations": await db.dataset_annotations.count_documents({"release_id": rid}),
        "train_annotations": await db.dataset_annotations.count_documents({"release_id": rid, "split": "train"}),
        "val_annotations": await db.dataset_annotations.count_documents({"release_id": rid, "split": "val"}),
        "whole_image_annotations": await db.dataset_annotations.count_documents({"release_id": rid, "category_id": WHOLE_IMAGE_CAT}),
        "physical_annotations_incl_virtual_baseplates": await db.dataset_annotations.count_documents({"release_id": rid, "category_id": {"$ne": WHOLE_IMAGE_CAT}}),
        "virtual_baseplates": await db.dataset_annotations.count_documents({"release_id": rid, "virtual_baseplate": True}),
        "orphan_annotations": orphans,
        "files_verified": await db.dataset_files.count_documents({"release_id": rid, "verified": True}),
    }
    failed = [f["path"] + ": " + (f.get("error") or "unverified") async for f in db.dataset_files.find(
        {"release_id": rid, "$or": [{"verified": False}, {"decoded": False}]}, {"path": 1, "error": 1})]
    complete = (counts["images_verified_512"] == EXPECT["images"] and counts["json_verified"] == 2 and counts["annotations"] == EXPECT["annotations"]
                and counts["whole_image_annotations"] == EXPECT["whole_image_annotations"]
                and counts["physical_annotations_incl_virtual_baseplates"] == EXPECT["physical_annotations"] and orphans == 0
                and stats["matches_contract"])
    receipt = None
    if complete:
        manifest = sorted((f["path"], f["sha256"]) for f in files.values())
        receipt = {"archive_sha256": digest, "files": len(manifest), "manifest_sha256": sha(json.dumps(manifest).encode()), "completed_at": iso()}
    await _set_release(rid, status="Complete" if complete else "Partial", counts=counts, stats=stats, failed_files=failed[:50],
                       receipt=receipt, blocker=None if complete else "Incomplete: " + ("; ".join(failed[:5]) or "counts differ from contract"))
    return "Done" if complete else "Failed"


async def compute_stats(rid: str) -> dict:
    rows = await db.dataset_annotations.aggregate([
        {"$match": {"release_id": rid}},
        {"$group": {"_id": {"c": "$category_id", "cond": "$attributes.Condition", "t": "$attributes.Type", "s": "$split"}, "n": {"$sum": 1}}},
    ]).to_list(1000)
    cats = {}
    for r in rows:
        k = r["_id"]
        name = CONTRACT_STATS.get(k["c"], (str(k["c"]),))[0]
        c = cats.setdefault(k["c"], {"category_id": k["c"], "name": name, "Good": 0, "Bad": 0, "by_type": {}, "by_split": {}})
        cond = k.get("cond") or "None"
        c[cond] = c.get(cond, 0) + r["n"]
        if k.get("t"):
            c["by_type"].setdefault(k["t"], {"Good": 0, "Bad": 0})[cond] = c["by_type"].setdefault(k["t"], {}).get(cond, 0) + r["n"]
        c["by_split"].setdefault(k["s"], {"Good": 0, "Bad": 0})[cond] = c["by_split"].setdefault(k["s"], {}).get(cond, 0) + r["n"]
    out = sorted(cats.values(), key=lambda c: c["category_id"])
    for c in out:
        exp = CONTRACT_STATS.get(c["category_id"])
        c["contract"] = {"Good": exp[1], "Bad": exp[2]} if exp else None
        c["matches_contract"] = bool(exp) and c["Good"] == exp[1] and c["Bad"] == exp[2]
        c["excluded_from_physical_metrics"] = c["category_id"] == WHOLE_IMAGE_CAT
        if c["name"] == "rail":
            c["note"] = RAIL_NOTE
        if c["category_id"] == 10:
            c["note"] = "Virtual baseplates (Type 'virtual') are excluded from physical-component counts and metrics."
    return {"categories": out, "matches_contract": len(out) == 11 and all(c["matches_contract"] for c in out), "rail_note": RAIL_NOTE}


# ---------------------------------------------------------------- partitions (grouping, quarantine)
def _dhash(data: bytes) -> int:
    im = Image.open(io.BytesIO(data)).convert("L").resize((9, 8), Image.BILINEAR)
    a = np.asarray(im, dtype=np.int16)
    bits = (a[:, 1:] > a[:, :-1]).flatten()
    return int("".join("1" if b else "0" for b in bits), 2)


def _ham(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    x = np.bitwise_xor(a[:, None], b[None, :])
    return np.unpackbits(x.view(np.uint8).reshape(x.shape + (8,)), axis=-1).sum(-1)


class ImageSource:
    """Read dataset bytes from the staged archive (verified against stored sha256) or private object storage."""

    def __init__(self, rid: str):
        p = os.path.join(STAGE_ROOT, rid, "archive.zip")
        self.z = zipfile.ZipFile(p) if os.path.exists(p) else None

    def read(self, img: dict) -> bytes:
        data = None
        if self.z:
            try:
                data = self.z.read(f"{SOURCE['prefix']}{img['split']}/{img['file_name']}")
            except KeyError:
                data = None
        if data is None or sha(data) != img["sha256"]:
            data = storage.get_object(img["object_path"])
        if sha(data) != img["sha256"]:
            raise RuntimeError(f"sha256 mismatch for {img['split']}/{img['file_name']}")
        return data


def build_groups(images: list[dict], rid: str, near: int = 8, seq: int = 16) -> dict:
    src = ImageSource(rid)
    hashes = {im["uuid"]: _dhash(src.read(im)) for im in images}
    train = [im for im in images if im["split"] == "train"]
    val = [im for im in images if im["split"] == "val"]
    th = np.array([hashes[i["uuid"]] for i in train], dtype=np.uint64)
    vh = np.array([hashes[i["uuid"]] for i in val], dtype=np.uint64)
    parent = list(range(len(train)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    d = _ham(th, th)
    links = {"near_duplicate": 0, "sequence": 0}
    idx = {int(re.sub(r"\D", "", im["file_name"]) or -1): n for n, im in enumerate(train)}
    for i in range(len(train)):
        for j in np.nonzero(d[i, i + 1:] <= near)[0] + i + 1:
            if find(i) != find(int(j)):
                parent[find(i)] = find(int(j))
                links["near_duplicate"] += 1
    for num, i in idx.items():
        j = idx.get(num + 1)
        if j is not None and d[i, j] <= seq and find(i) != find(j):
            parent[find(i)] = find(j)
            links["sequence"] += 1
    groups = {}
    for n, im in enumerate(train):
        groups.setdefault(find(n), []).append(im["uuid"])
    dv = _ham(th, vh) if len(vh) else np.zeros((len(th), 0))
    overlap_train = {train[i]["uuid"] for i in np.nonzero((dv <= near).any(1))[0]} if dv.size else set()
    out = []
    for g in groups.values():
        gid = "g-" + sha(",".join(sorted(g)).encode())[:12]
        out.append({"group_id": gid, "members": sorted(g), "quarantined": bool(set(g) & overlap_train)})
    return {"groups": out, "links": links, "hashes": {k: f"{v:016x}" for k, v in hashes.items()},
            "method": {"kind": "provisional", "perceptual_hash": "dHash 9x8 grayscale (64-bit)", "near_duplicate_hamming_max": near,
                       "sequence_rule": f"consecutive numeric filenames with dHash hamming ≤ {seq}",
                       "test_overlap_rule": f"train group quarantined if any member within hamming ≤ {near} of any val image"}}


async def run_partition(job):
    pid = job["target_id"]
    p = await db.data_partitions.find_one({"uuid": pid})
    rid = p["release_id"]
    images = await db.dataset_images.find({"release_id": rid}, {"_id": 0}).to_list(5000)
    await db.data_partitions.update_one({"uuid": pid}, {"$set": {"status": "Running"}})
    g = await run_blocking(build_groups, images, rid)
    rng = np.random.default_rng(p["config"]["seed"])
    usable = [x for x in g["groups"] if not x["quarantined"]]
    order = rng.permutation(len(usable))
    n_imgs = sum(len(x["members"]) for x in usable)
    target_cal = p["config"]["calibration_fraction"] * n_imgs
    fit, cal, acc = [], [], 0
    for i in order:  # assign whole groups → no group spans fit/calibration
        grp = usable[i]
        if acc < target_cal:
            cal += grp["members"]
            acc += len(grp["members"])
        else:
            fit += grp["members"]
    quarantined = [m for x in g["groups"] if x["quarantined"] for m in x["members"]]
    test = sorted(im["uuid"] for im in images if im["split"] == "val")
    members = {"fit": sorted(fit), "calibration": sorted(cal), "test_locked": test, "quarantined": sorted(quarantined)}
    msha = sha(json.dumps(members, sort_keys=True).encode())
    await db.data_partitions.update_one({"uuid": pid}, {"$set": {
        "status": "Complete", "members": members, "membership_sha256": msha, "grouping": g["method"], "links": g["links"],
        "groups": [{"group_id": x["group_id"], "size": len(x["members"]), "quarantined": x["quarantined"]} for x in g["groups"]],
        "counts": {k: len(v) for k, v in members.items()} | {"groups": len(g["groups"]), "quarantined_groups": sum(x["quarantined"] for x in g["groups"])},
        "val_in_fit_or_calibration": len(set(test) & (set(fit) | set(cal))), "completed_at": iso()}})
    await db.dataset_images.bulk_write([__import__("pymongo").UpdateOne({"uuid": k}, {"$set": {"dhash": v}}) for k, v in g["hashes"].items()])
    return "Done"


# ---------------------------------------------------------------- local supplied-box classifier (numpy)
def crop_features(img: Image.Image, bbox, cat: int, flip=False, bright=1.0) -> Optional[np.ndarray]:
    x, y, w, h = bbox
    if min(w, h) < 6:
        return None  # abstain: too small to assess
    cx, cy, pw, ph = x + w / 2, y + h / 2, w * 1.25, h * 1.25  # 25% context
    box = (max(0, cx - pw / 2), max(0, cy - ph / 2), min(img.width, cx + pw / 2), min(img.height, cy + ph / 2))
    c = img.crop(box).resize((48, 48), Image.BILINEAR)
    a = np.asarray(c, dtype=np.float32) / 255.0
    if flip:
        a = a[:, ::-1]
    a = np.clip(a * bright, 0, 1)
    g = a.mean(-1)
    gx = np.zeros_like(g); gy = np.zeros_like(g)
    gx[:, 1:-1] = g[:, 2:] - g[:, :-2]
    gy[1:-1] = g[2:] - g[:-2]
    mag = np.hypot(gx, gy)
    ang = (np.arctan2(gy, gx) % np.pi) / np.pi * 9
    b = np.minimum(ang.astype(int), 8)
    hog = np.zeros((6, 6, 9), np.float32)
    for i in range(6):
        for j in range(6):
            hog[i, j] = np.bincount(b[i * 8:(i + 1) * 8, j * 8:(j + 1) * 8].ravel(), weights=mag[i * 8:(i + 1) * 8, j * 8:(j + 1) * 8].ravel(), minlength=9)
    hog = hog.ravel()
    hog /= np.linalg.norm(hog) + 1e-6
    col = np.concatenate([np.histogram(a[..., k], bins=8, range=(0, 1))[0] / 2304.0 for k in range(3)])
    stats = np.concatenate([a.reshape(-1, 3).mean(0), a.reshape(-1, 3).std(0), [g.std(), mag.mean()]])
    onehot = np.array([cat == 1, cat == 2, cat == 3], np.float32)
    geom = np.array([np.log1p(w * h) / 12, np.log((w + 1) / (h + 1))], np.float32)
    return np.concatenate([hog, col, stats, onehot, geom]).astype(np.float32)


def extract(rid: str, images: list[dict], anns_by_img: dict, augment: Optional[dict] = None):
    src = ImageSource(rid)
    X, y, meta, abstained = [], [], [], []
    rng = np.random.default_rng(augment["seed"]) if augment else None
    for im in images:
        pil = Image.open(io.BytesIO(src.read(im))).convert("RGB")
        for a in anns_by_img.get(im["uuid"], []):
            lab = 1 if a["attributes"].get("Condition") == "Bad" else 0
            f = crop_features(pil, a["bbox"], a["category_id"])
            key = {"ann_id": a["ann_id"], "split": a["split"], "image_key": im["uuid"], "category_id": a["category_id"]}
            if f is None:
                abstained.append(key)
                continue
            X.append(f); y.append(lab); meta.append(key)
            if augment:
                for _ in range(augment["copies_bad"] if lab else augment["copies_good"]):
                    t = {"flip": bool(rng.random() < 0.5), "brightness": float(rng.uniform(0.8, 1.2))}
                    X.append(crop_features(pil, a["bbox"], a["category_id"], t["flip"], t["brightness"])); y.append(lab)
                    meta.append({**key, "augmented": t})
    return (np.array(X, np.float32) if X else np.zeros((0, 1), np.float32)), np.array(y, np.int8), meta, abstained


def train_logreg(X, y, l2=1e-3, iters=600, lr=0.05, seed=7):
    mu, sd = X.mean(0), X.std(0) + 1e-6
    Z = (X - mu) / sd
    rng = np.random.default_rng(seed)
    w = rng.normal(0, 0.01, Z.shape[1]).astype(np.float64); b = 0.0
    pos = y.mean()
    sw = np.where(y == 1, 0.5 / max(pos, 1e-6), 0.5 / max(1 - pos, 1e-6))  # class-balanced
    m = v = np.zeros_like(w); mb = vb = 0.0
    losses = []
    for t in range(1, iters + 1):
        s = Z @ w + b
        p = 1 / (1 + np.exp(-s))
        gr = (sw * (p - y))
        gw = Z.T @ gr / len(y) + l2 * w
        gb = gr.mean()
        m = 0.9 * m + 0.1 * gw; v = 0.999 * v + 0.001 * gw ** 2
        mb = 0.9 * mb + 0.1 * gb; vb = 0.999 * vb + 0.001 * gb ** 2
        w -= lr * (m / (1 - 0.9 ** t)) / (np.sqrt(v / (1 - 0.999 ** t)) + 1e-8)
        b -= lr * (mb / (1 - 0.9 ** t)) / (np.sqrt(vb / (1 - 0.999 ** t)) + 1e-8)
        if t % 50 == 0:
            eps = 1e-7
            losses.append({"iter": t, "weighted_log_loss": float(-(sw * (y * np.log(p + eps) + (1 - y) * np.log(1 - p + eps))).mean())})
    return {"w": w, "b": b, "mu": mu, "sd": sd}, losses


def score(model, X):
    return ((X - model["mu"]) / model["sd"]) @ model["w"] + model["b"]


def platt(s, y, iters=100):
    """Newton-Raphson Platt scaling with Platt's target smoothing. Returns a, b for p = 1/(1+exp(-(a*s+b)))."""
    n1, n0 = y.sum(), len(y) - y.sum()
    t = np.where(y == 1, (n1 + 1) / (n1 + 2), 1 / (n0 + 2))
    a, b = 1.0, 0.0
    for _ in range(iters):
        p = 1 / (1 + np.exp(-(a * s + b)))
        g = np.array([((p - t) * s).sum(), (p - t).sum()])
        wv = p * (1 - p) + 1e-9
        H = np.array([[(wv * s * s).sum(), (wv * s).sum()], [(wv * s).sum(), wv.sum()]]) + 1e-9 * np.eye(2)
        step = np.linalg.solve(H, g)
        a, b = a - step[0], b - step[1]
        if np.abs(step).max() < 1e-8:
            break
    return float(a), float(b)


def metrics(y, p, thr=0.5, bins=10) -> dict:
    y = np.asarray(y); p = np.asarray(p)
    pred = p >= thr
    tp = int((pred & (y == 1)).sum()); fp = int((pred & (y == 0)).sum()); fn = int((~pred & (y == 1)).sum()); tn = int((~pred & (y == 0)).sum())
    rel, ece = [], 0.0
    for k in range(bins):
        lo, hi = k / bins, (k + 1) / bins
        mk = (p >= lo) & ((p < hi) if k < bins - 1 else (p <= hi))
        n = int(mk.sum())
        if n:
            conf, acc = float(p[mk].mean()), float(y[mk].mean())
            ece += n / len(y) * abs(conf - acc)
            rel.append({"bin": [lo, hi], "n": n, "mean_predicted": round(conf, 4), "observed_bad_rate": round(acc, 4)})
        else:
            rel.append({"bin": [lo, hi], "n": 0, "mean_predicted": None, "observed_bad_rate": None})
    return {"n": int(len(y)), "n_bad": int(y.sum()), "n_good": int(len(y) - y.sum()), "threshold": thr,
            "confusion": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
            "precision": {"value": round(tp / (tp + fp), 4) if tp + fp else None, "denominator": tp + fp},
            "recall": {"value": round(tp / (tp + fn), 4) if tp + fn else None, "denominator": tp + fn},
            "false_alerts": fp, "misses": fn, "brier": round(float(((p - y) ** 2).mean()), 5) if len(y) else None,
            "ece": round(float(ece), 5) if len(y) else None, "reliability_bins": rel}


async def _anns_by_image(rid, image_keys, cats=(1, 2, 3)):
    out = {}
    async for a in db.dataset_annotations.find({"release_id": rid, "image_key": {"$in": list(image_keys)}, "category_id": {"$in": list(cats)}},
                                               {"_id": 0, "segmentation": 0}):
        out.setdefault(a["image_key"], []).append(a)
    return out


async def _log(run_id, msg):
    await db.model_runs.update_one({"uuid": run_id}, {"$push": {"logs": {"at": iso(), "msg": msg}}, "$set": {"updated_at": iso()}})


async def run_training(job):
    run = await db.model_runs.find_one({"uuid": job["target_id"]})
    rid, part = run["release_id"], await db.data_partitions.find_one({"uuid": run["partition_id"]})
    await db.model_runs.update_one({"uuid": run["uuid"]}, {"$set": {"status": "Running", "job_id": job["uuid"], "started_at": iso()}})
    fit_keys, cal_keys = part["members"]["fit"], part["members"]["calibration"]
    assert not set(part["members"]["test_locked"]) & (set(fit_keys) | set(cal_keys)), "val leakage"
    imgs = {i["uuid"]: i async for i in db.dataset_images.find({"release_id": rid, "split": "train"}, {"_id": 0})}
    cfg = run["config"]
    anns = await _anns_by_image(rid, fit_keys)
    await _log(run["uuid"], f"extracting fit features: {len(fit_keys)} images (augmentation fit-only, seed {cfg['augmentation']['seed']})")
    Xf, yf, mf, abf = await run_blocking(extract, rid, [imgs[k] for k in fit_keys], anns, cfg["augmentation"])
    await heartbeat(job)
    await _log(run["uuid"], f"fit crops: {len(yf)} (incl. augmented), Bad {int(yf.sum())}, abstained {len(abf)}")
    model, losses = await run_blocking(train_logreg, Xf.astype(np.float64), yf.astype(np.float64), cfg["l2"], cfg["iters"], cfg["lr"], cfg["seed"])
    await heartbeat(job)
    canns = await _anns_by_image(rid, cal_keys)
    Xc, yc, mc, abc = await run_blocking(extract, rid, [imgs[k] for k in cal_keys], canns, None)
    sc = score(model, Xc.astype(np.float64)) if len(yc) else np.zeros(0)
    d = stage_dir(rid)
    ck = os.path.join(d, f"checkpoint-{run['uuid']}.npz")
    np.savez(ck, w=model["w"], b=np.array([model["b"]]), mu=model["mu"], sd=model["sd"])
    blob = open(ck, "rb").read()
    ck_sha = sha(blob)
    opath = f"{APP_NAME}/calibration/{run['workspace_id']}/models/{run['uuid']}.npz"
    await run_blocking(storage.put_object, opath, blob, "application/octet-stream")
    from pymongo import InsertOne
    await db.cal_scores.delete_many({"run_id": run["uuid"]})
    if len(yc):
        await db.cal_scores.bulk_write([InsertOne({"run_id": run["uuid"], "partition": "calibration", **m, "score": float(s), "label_bad": int(l)})
                                        for m, s, l in zip(mc, sc, yc)])
    fit_data = sorted({m["ann_id"] for m in mf})
    await db.model_runs.update_one({"uuid": run["uuid"]}, {"$set": {
        "status": "Done", "finished_at": iso(),
        "checkpoint": {"object_path": opath, "local_path": ck, "sha256": ck_sha, "bytes": len(blob), "format": "numpy npz (w, b, mu, sd)"},
        "data_sha256": sha(json.dumps({"fit_annotations": fit_data, "partition_membership_sha256": part["membership_sha256"]}).encode()),
        "training_summary": {"fit_crops": int(len(yf)), "fit_bad": int(yf.sum()), "fit_abstained": len(abf),
                             "calibration_crops_scored": int(len(yc)), "calibration_abstained": len(abc), "loss_curve": losses,
                             "fit_split_metrics_uncalibrated_not_a_test": metrics(yf, 1 / (1 + np.exp(-score(model, Xf.astype(np.float64)))))
                             | {"note": "training-set fit, not a test"}}}})
    await _log(run["uuid"], f"done; checkpoint sha256 {ck_sha}")
    return "Done"


def load_checkpoint(path_or_bytes) -> dict:
    z = np.load(io.BytesIO(path_or_bytes) if isinstance(path_or_bytes, bytes) else path_or_bytes)
    return {"w": z["w"], "b": float(z["b"][0]), "mu": z["mu"], "sd": z["sd"]}


async def _checkpoint(train_run) -> dict:
    ck = train_run["checkpoint"]
    blob = await run_blocking(storage.get_object, ck["object_path"])
    if sha(blob) != ck["sha256"]:
        raise RuntimeError("checkpoint sha256 mismatch")
    return load_checkpoint(blob)


async def run_evaluation(job):
    run = await db.model_runs.find_one({"uuid": job["target_id"]})
    prof = await db.calibration_profiles.find_one({"uuid": run["profile_id"]})
    train_run = await db.model_runs.find_one({"uuid": prof["model_run_id"]})
    rid = run["release_id"]
    await db.model_runs.update_one({"uuid": run["uuid"]}, {"$set": {"status": "Running", "job_id": job["uuid"], "started_at": iso()}})
    model = await _checkpoint(train_run)
    imgs = [i async for i in db.dataset_images.find({"release_id": rid, "split": "val"}, {"_id": 0})]  # locked final test (500)
    anns = await _anns_by_image(rid, [i["uuid"] for i in imgs])
    X, y, meta, ab = await run_blocking(extract, rid, imgs, anns, None)
    s = score(model, X.astype(np.float64))
    cats = np.array([m["category_id"] for m in meta])
    p = np.full(len(y), np.nan)
    per_class, nulls = {}, {}
    for cid, name in TARGET_CLASSES.items():
        c = prof["classes"].get(name)
        mk = cats == cid
        if c and c.get("a") is not None:
            p[mk] = 1 / (1 + np.exp(-(c["a"] * s[mk] + c["b"])))
            total = sum(1 for a in sum(anns.values(), []) if a["category_id"] == cid)
            per_class[name] = metrics(y[mk], p[mk]) | {"abstained": sum(1 for a in ab if a["category_id"] == cid), "total_annotations": total,
                                                         "assessable_coverage": round(int(mk.sum()) / total, 4) if total else None}
        else:
            nulls[name] = (c or {}).get("reason", "no calibration for class")
    ok = ~np.isnan(p)
    overall = metrics(y[ok], p[ok]) if ok.any() else None
    if overall:
        overall |= {"abstained": len(ab), "assessable_coverage": round(int(ok.sum()) / (len(y) + len(ab)), 4)}
    await db.model_runs.update_one({"uuid": run["uuid"]}, {"$set": {
        "status": "Done", "finished_at": iso(),
        "evaluation": {"label": "classification given supplied boxes", "not": "end-to-end detection",
                       "test_set": "source val (500 images, locked; unused for prompts, training, calibration or thresholds)",
                       "score_semantics": "source_bad_condition_probability", "threshold_rule": "0.5 on calibrated probability, fixed before evaluation",
                       "overall": overall, "per_class": per_class, "classes_without_calibration": nulls,
                       "profile_id": prof["uuid"], "profile_version": prof["version"], "model_run_id": train_run["uuid"],
                       "checkpoint_sha256": train_run["checkpoint"]["sha256"],
                       "excluded": "category 11 'image' and virtual baseplates excluded; only clip/spike_and_bolt/tie evaluated",
                       "sf_validation": SF_VALIDATION, "domain_label": PROFILE_LABEL}}})
    return "Done"


# ---------------------------------------------------------------- hosted baseline (existing Claude adapter)
async def reserve_call(n=1) -> bool:
    await db.cal_budget.update_one({"_id": "hosted_image_calls"}, {"$setOnInsert": {
        "cap": 150, "used": 85, "seeded_from": "eval/tie_fastener/REPORT.md (85 of 150 used before Phase 6)", "history": []}}, upsert=True)
    # One-time budget increase: cap 150 → 300 (2026-10-24); 'used' unchanged.
    await db.cal_budget.update_one({"_id": "hosted_image_calls", "cap": 150}, {"$set": {"cap": 300}, "$push": {"history": {
        "change": "cap 150 → 300", "approved_by": "admin", "approved_on": "2026-10-24", "recorded_at": iso()}}})
    r = await db.cal_budget.find_one_and_update({"_id": "hosted_image_calls", "$expr": {"$lte": [{"$add": ["$used", n]}, "$cap"]}},
                                                {"$inc": {"used": n}})
    return r is not None


async def budget() -> dict:
    await reserve_call(0)
    b = await db.cal_budget.find_one({"_id": "hosted_image_calls"}, {"_id": 0, "history": 0})
    return b | {"remaining": b["cap"] - b["used"], "message": BUDGET_MSG if b["used"] >= b["cap"] else None}


def _select_baseline(imgs, anns, n, seed):
    rng = np.random.default_rng(seed)
    buckets = {"bad_tie": [], "bad_spike_and_bolt": [], "bad_clip": [], "all_good": []}
    for im in imgs:
        a = anns.get(im["uuid"], [])
        bad = {x["category_id"] for x in a if x["attributes"].get("Condition") == "Bad"}
        if 3 in bad: buckets["bad_tie"].append(im)
        elif 2 in bad: buckets["bad_spike_and_bolt"].append(im)
        elif 1 in bad: buckets["bad_clip"].append(im)
        elif a: buckets["all_good"].append(im)
    quota = {"bad_tie": n // 6 + (n % 6 > 0), "bad_spike_and_bolt": n // 6, "bad_clip": n // 6}
    quota["all_good"] = n - sum(quota.values())
    out = []
    for k, q in quota.items():
        b = buckets[k]
        for i in rng.permutation(len(b))[:q]:
            out.append((k, b[i]))
    return out


async def run_baseline(job):
    import ai_image
    run = await db.model_runs.find_one({"uuid": job["target_id"]})
    rid = run["release_id"]
    part = await db.data_partitions.find_one({"uuid": run["partition_id"]})
    await db.model_runs.update_one({"uuid": run["uuid"]}, {"$set": {"status": "Running", "job_id": job["uuid"], "started_at": iso()}})
    pool_keys = part["members"]["fit"] + part["members"]["calibration"]  # source train only; never val
    imgs = [i async for i in db.dataset_images.find({"uuid": {"$in": pool_keys}}, {"_id": 0})]
    anns = await _anns_by_image(rid, pool_keys)
    sel = run.get("selection") or [{"bucket": k, "image_key": im["uuid"]} for k, im in _select_baseline(imgs, anns, run["config"]["max_images"], run["config"]["seed"])]
    await db.model_runs.update_one({"uuid": run["uuid"]}, {"$set": {"selection": sel}})
    by = {i["uuid"]: i for i in imgs}
    src = ImageSource(rid)
    for k, s in enumerate(sel):
        if await db.cal_run_items.find_one({"run_id": run["uuid"], "image_key": s["image_key"], "raw_saved": True}):
            continue  # resume: never re-call for an item whose raw response is saved
        if not await reserve_call(1):
            await db.model_runs.update_one({"uuid": run["uuid"]}, {"$set": {"status": "Blocked", "blocker": BUDGET_MSG}})
            return "Done"
        im = by[s["image_key"]]
        data = await run_blocking(src.read, im)
        b64, _ = ai_image._prepare_image(data)  # re-encoded pixels only: no filename, labels or overlays
        item = {"run_id": run["uuid"], "image_key": s["image_key"], "bucket": s["bucket"], "input_sha256": sha(base64.b64decode(b64)),
                "source_sha256": im["sha256"], "at": iso()}
        try:
            raw = await ai_image.PROVIDER.call(b64, [ai_image.USER], f"cal-{run['uuid'][:8]}-{k}-{new_id()[:6]}")
            await db.cal_run_items.update_one({"run_id": run["uuid"], "image_key": s["image_key"]},
                                              {"$set": {**item, "raw_response": raw, "raw_saved": True, "calls": 1}}, upsert=True)  # raw first
        except Exception as e:
            await db.cal_run_items.update_one({"run_id": run["uuid"], "image_key": s["image_key"]},
                                              {"$set": {**item, "raw_saved": True, "calls": 1, "status": "Failed", "error": f"{type(e).__name__}: {e}"[:300]}}, upsert=True)
            continue
        try:
            parsed = ai_image.validate_output(ai_image._extract_json(raw))
            st = "Abstained" if parsed["image_assessability"] == "cannot_assess" else "Done"
            upd = {"status": st, "parsed": parsed}
        except Exception as e:
            upd = {"status": "Failed", "error": f"parse/validation: {e}"[:300]}
        await db.cal_run_items.update_one({"run_id": run["uuid"], "image_key": s["image_key"]}, {"$set": upd})
        await heartbeat(job)
    await _score_baseline(run, anns)
    return "Done"


async def _score_baseline(run, anns):
    items = await db.cal_run_items.find({"run_id": run["uuid"]}, {"_id": 0}).to_list(100)
    rows = {"tie": ([], [], "visible tie-surface deterioration", (3,)), "fastener": ([], [], "possible missing/displaced fastener", (1, 2))}
    status = {}
    for it in items:
        status[it.get("status", "Unknown")] = status.get(it.get("status", "Unknown"), 0) + 1
        if it.get("status") != "Done":
            continue
        a = anns.get(it["image_key"], [])
        cats_pred = {c["category"] for c in it["parsed"]["candidates"]}
        for name, (yy, pp, label, cids) in rows.items():
            yy.append(int(any(x["attributes"].get("Condition") == "Bad" and x["category_id"] in cids for x in a)))
            pp.append(1.0 if label in cats_pred else 0.0)
    result = {"label": "image-level qualitative candidates vs source Bad labels (not supplied-box classification)",
              "items": len(items), "status_counts": status,
              "per_category": {k: (metrics(np.array(v[0]), np.array(v[1])) | {"model_category": v[2]}) if v[0] else None for k, v in rows.items()},
              "calibrated_probability": None,
              "calibrated_probability_reason": "Hosted model returns qualitative uncertainty text, no numeric score. Platt scaling not applicable.",
              "budget_after": await budget()}
    for k in result["per_category"].values():
        if k:
            k.pop("reliability_bins", None); k.pop("brier", None); k.pop("ece", None)  # binary outputs: no probability metrics
    await db.model_runs.update_one({"uuid": run["uuid"]}, {"$set": {"status": "Done", "finished_at": iso(), "baseline": result}})


# ---------------------------------------------------------------- profiles
async def fit_profile(ws: str, train_run: dict, user: dict, min_bad=20, min_good=20) -> dict:
    rows = await db.cal_scores.find({"run_id": train_run["uuid"], "partition": "calibration"}, {"_id": 0}).to_list(100000)
    part = await db.data_partitions.find_one({"uuid": train_run["partition_id"]})
    cal_set = set(part["members"]["calibration"])
    assert all(r["image_key"] in cal_set and r["split"] == "train" for r in rows), "non-calibration records"
    classes = {}
    for cid, name in TARGET_CLASSES.items():
        r = [x for x in rows if x["category_id"] == cid]
        s = np.array([x["score"] for x in r]); y = np.array([x["label_bad"] for x in r])
        nb, ng = int(y.sum()), int(len(y) - y.sum())
        if nb < min_bad or ng < min_good:
            classes[name] = {"a": None, "b": None, "n": len(r), "n_bad": nb, "n_good": ng, "calibrated_probability": None,
                             "reason": f"insufficient class support (Bad {nb} < {min_bad} or Good {ng} < {min_good})"}
            continue
        a, b = platt(s, y)
        p = 1 / (1 + np.exp(-(a * s + b)))
        classes[name] = {"a": a, "b": b, "n": len(r), "n_bad": nb, "n_good": ng, "calibration_partition_brier_in_sample": round(float(((p - y) ** 2).mean()), 5)}
    for name in ("hole", "rail", "anchor", "clip_base", "joint_bar", "joint_gap", "baseplate"):
        classes[name] = {"a": None, "b": None, "calibrated_probability": None,
                         "reason": RAIL_NOTE if name == "rail" else "class not in model's declared task (clip, spike_and_bolt, tie only)"}
    last = await db.calibration_profiles.find_one({"workspace_id": ws}, sort=[("version", -1)])
    prof = {"uuid": new_id(), "workspace_id": ws, "version": (last["version"] + 1) if last else 1, "status": "Draft",
            "method": "Platt scaling on logit scores (Newton, Platt target smoothing)", "score_semantics": "source_bad_condition_probability",
            "task": "supplied_box_condition_classification", "classes": classes,
            "binding": {"model_run_id": train_run["uuid"], "checkpoint_sha256": train_run["checkpoint"]["sha256"], "model": train_run["config"]["model"]},
            "model_run_id": train_run["uuid"], "partition_id": train_run["partition_id"], "membership_sha256": part["membership_sha256"],
            "calibration_records": len(rows), "calibration_memberships": sorted(cal_set),
            "domain": {"dataset": "Pueblo Rail Components v1 (source domain)", "region": ATTRIBUTION["region"], "image_size": "512x512",
                       "input": "supplied bounding boxes"},
            "candidate_correctness_probability": {"value": None, "reason": "No reviewed localized-candidate matches (IoU 0.50, one-to-one, class-compatible) available to fit."},
            "label": PROFILE_LABEL, "sf_validation": SF_VALIDATION, "created_by": user["uuid"], "created_at": iso()}
    await db.calibration_profiles.insert_one(dict(prof))
    prof.pop("_id", None)
    return prof


async def live_candidate_calibration(ws: str) -> dict:
    """Applied to NEW live candidates (CAL10): the active profile's task is supplied-box classification, so localized
    hosted-model candidates are outside its declared task → calibrated_probability stays null with the reason."""
    p = await db.calibration_profiles.find_one({"workspace_id": ws, "status": "Active"}, {"uuid": 1, "version": 1})
    if not p:
        return {"calibrated_probability": None, "reason": "No active calibration profile", "profile_id": None}
    return {"calibrated_probability": None, "profile_id": p["uuid"], "profile_version": p["version"], "label": PROFILE_LABEL,
            "reason": "Out of declared task: profile calibrates source_bad_condition_probability for supplied boxes in the Pueblo source "
                      "domain; live localized candidates need candidate_correctness_probability, which is not fitted."}


HANDLERS = {"import": run_import, "partition": run_partition, "training": run_training, "evaluation": run_evaluation, "baseline": run_baseline}
