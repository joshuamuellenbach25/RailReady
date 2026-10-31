"""Phase 6 calibration APIs. Staff-only (admin/estimator), workspace-scoped; foreign ids → 404, foreman → 403, unauth → 401."""
import hashlib
import json
import os
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

import calibration as cal
import storage
from core import audit, db, iso, new_id, require_role

router = APIRouter(prefix="/api/calibration", tags=["calibration"])
staff = require_role("admin", "estimator")


def err(status, code, message, retryable=False):
    raise HTTPException(status, {"code": code, "message": message, "retryable": retryable})


async def _scoped(coll: str, user: dict, item_id: str, proj=None) -> dict:
    d = await db[coll].find_one({"uuid": item_id, "workspace_id": user["workspace_id"]}, proj or {"_id": 0})
    if not d:
        err(404, "not_found", "Not found")
    d.pop("_id", None)
    return d


async def _job(target_id):
    j = await db.cal_jobs.find_one({"target_id": target_id}, {"_id": 0}, sort=[("created_at", -1)])
    return j and {k: j.get(k) for k in ("uuid", "kind", "status", "attempts", "error", "updated_at")}


def _release_view(r: dict) -> dict:
    r = {k: v for k, v in r.items() if k != "_id"}
    r["attribution"], r["license"], r["source_contract"] = cal.ATTRIBUTION, cal.LICENSE, cal.SOURCE
    r["expected"] = cal.EXPECT
    r["sf_validation"] = cal.SF_VALIDATION
    return r


# ---------------- datasets
class ImportIn(BaseModel):
    source: Literal["kaggle_fixed"] = "kaggle_fixed"


@router.post("/datasets/import", status_code=202)
async def start_import(request: Request, user: dict = Depends(staff)):
    """JSON {source:"kaggle_fixed"} (fixed contract URL only) or multipart ZIP upload (field 'file') with the same verification."""
    ws = user["workspace_id"]
    ctype = request.headers.get("content-type", "")
    upload = ctype.startswith("multipart/form-data")
    if not upload:
        body = await request.body()
        ImportIn(**(json.loads(body) if body else {}))  # only the fixed source is accepted; no arbitrary URLs
    existing = await db.dataset_releases.find_one({"workspace_id": ws, "source.sha256": cal.SOURCE["sha256"]}, {"_id": 0})
    if existing and existing["status"] == "Complete" and not upload:
        return {"release": _release_view(existing), "job": await _job(existing["uuid"]), "resumed": False, "already_complete": True}
    rid = existing["uuid"] if existing else new_id()
    if not existing:
        await db.dataset_releases.insert_one({
            "uuid": rid, "workspace_id": ws, "version": 1, "name": "Pueblo Rail Components v1",
            "source": {"kind": "upload" if upload else "kaggle_fixed", **{k: cal.SOURCE[k] for k in ("dataset", "url", "size", "sha256")}},
            "status": "Queued", "progress": {}, "created_by": user["uuid"], "created_at": iso(), "updated_at": iso()})
    if upload:
        form = await request.form()
        f = form.get("file")
        if f is None:
            err(422, "file_required", "Multipart field 'file' (ZIP) is required")
        d = cal.stage_dir(rid)
        dst = os.path.join(d, "archive.zip")
        tmp = dst + ".upload"
        h, n = hashlib.sha256(), 0
        with open(tmp, "wb") as out:
            while chunk := await f.read(1 << 20):
                out.write(chunk); h.update(chunk); n += len(chunk)
                if n > cal.SOURCE["size"] + (1 << 20):
                    out.close(); os.remove(tmp)
                    err(413, "too_large", "Upload larger than the contract archive")
        if n != cal.SOURCE["size"] or h.hexdigest() != cal.SOURCE["sha256"]:
            os.remove(tmp)
            err(422, "archive_mismatch", f"Uploaded ZIP size {n} / sha256 {h.hexdigest()} does not match contract "
                                         f"{cal.SOURCE['size']} / {cal.SOURCE['sha256']}")
        os.replace(tmp, dst)
        await db.dataset_releases.update_one({"uuid": rid}, {"$set": {"source.kind": "upload", "status": "Queued", "blocker": None}})
    else:
        await db.dataset_releases.update_one({"uuid": rid, "status": {"$in": ["Blocked", "Failed", "Partial"]}},
                                             {"$set": {"status": "Queued", "blocker": None}})
    active = await db.cal_jobs.find_one({"target_id": rid, "status": {"$in": ["Queued", "Running"]}})
    if not active:
        await cal.enqueue(ws, "import", rid, user["uuid"])
    await audit(user, ws, "calibration.import", "dataset_release", rid, {"upload": upload})
    r = await db.dataset_releases.find_one({"uuid": rid}, {"_id": 0})
    return {"release": _release_view(r), "job": await _job(rid), "resumed": bool(existing)}


@router.get("/datasets")
async def list_datasets(user: dict = Depends(staff)):
    rows = await db.dataset_releases.find({"workspace_id": user["workspace_id"]}, {"_id": 0}).to_list(20)
    return {"datasets": [_release_view(r) for r in rows]}


@router.get("/datasets/{release_id}")
async def get_dataset(release_id: str, user: dict = Depends(staff)):
    r = await _scoped("dataset_releases", user, release_id)
    v = _release_view(r)
    v["job"] = await _job(release_id)
    v["partitions"] = await db.data_partitions.find({"release_id": release_id}, {"_id": 0, "members": 0, "groups": 0}).to_list(20)
    return v


@router.get("/datasets/{release_id}/images")
async def list_images(release_id: str, split: Optional[Literal["train", "val"]] = None, category_id: Optional[int] = None,
                      condition: Optional[Literal["Good", "Bad"]] = None, page: int = Query(1, ge=1), page_size: int = Query(24, ge=1, le=100),
                      user: dict = Depends(staff)):
    await _scoped("dataset_releases", user, release_id, {"uuid": 1})
    q = {"release_id": release_id}
    if split:
        q["split"] = split
    if category_id is not None or condition:
        aq = {"release_id": release_id}
        if category_id is not None:
            aq["category_id"] = category_id
        if condition:
            aq["attributes.Condition"] = condition
        q["uuid"] = {"$in": await db.dataset_annotations.distinct("image_key", aq)}
    total = await db.dataset_images.count_documents(q)
    rows = await db.dataset_images.find(q, {"_id": 0}).sort([("split", -1), ("file_name", 1)]).skip((page - 1) * page_size).limit(page_size).to_list(page_size)
    for r in rows:
        r["media_url"] = f"/api/calibration/datasets/{release_id}/images/{r['uuid']}/media"
        r["annotation_count"] = await db.dataset_annotations.count_documents({"image_key": r["uuid"]})
    return {"total": total, "page": page, "page_size": page_size, "images": rows, "attribution": cal.ATTRIBUTION, "license": cal.LICENSE}


@router.get("/datasets/{release_id}/images/{image_key}")
async def get_image(release_id: str, image_key: str, user: dict = Depends(staff)):
    await _scoped("dataset_releases", user, release_id, {"uuid": 1})
    im = await db.dataset_images.find_one({"uuid": image_key, "release_id": release_id}, {"_id": 0})
    if not im:
        err(404, "not_found", "Not found")
    im["annotations"] = await db.dataset_annotations.find({"image_key": image_key}, {"_id": 0}).to_list(500)
    im["media_url"] = f"/api/calibration/datasets/{release_id}/images/{image_key}/media"
    return im


@router.get("/datasets/{release_id}/images/{image_key}/media")
async def image_media(release_id: str, image_key: str, user: dict = Depends(staff)):
    await _scoped("dataset_releases", user, release_id, {"uuid": 1})
    im = await db.dataset_images.find_one({"uuid": image_key, "release_id": release_id})
    if not im or not im.get("object_path"):
        err(404, "not_found", "Not found")
    data = storage.get_object(im["object_path"])
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600", "X-Content-SHA256": im["sha256"]})


# ---------------- partitions
class PartitionIn(BaseModel):
    release_id: str
    seed: int = 20261024
    calibration_fraction: float = Field(0.25, gt=0.05, lt=0.5)


@router.post("/partitions", status_code=202)
async def create_partition(body: PartitionIn, user: dict = Depends(staff)):
    r = await _scoped("dataset_releases", user, body.release_id, {"uuid": 1, "status": 1})
    if r["status"] != "Complete":
        err(409, "release_incomplete", "Dataset release is not Complete")
    last = await db.data_partitions.find_one({"release_id": body.release_id}, sort=[("version", -1)])
    p = {"uuid": new_id(), "workspace_id": user["workspace_id"], "release_id": body.release_id, "version": (last["version"] + 1) if last else 1,
         "status": "Queued", "config": body.model_dump(exclude={"release_id"}), "immutable": True,
         "test_policy": "source val (500) locked as final test; unused for prompts, training, calibration fitting or thresholds",
         "augmentation_policy": "fit partition only (seed + transforms recorded per training run)",
         "created_by": user["uuid"], "created_at": iso()}
    await db.data_partitions.insert_one(dict(p))
    p.pop("_id", None)
    await cal.enqueue(user["workspace_id"], "partition", p["uuid"], user["uuid"])
    return {"partition": p, "job": await _job(p["uuid"])}


@router.get("/partitions/{partition_id}")
async def get_partition(partition_id: str, include_members: bool = False, user: dict = Depends(staff)):
    p = await _scoped("data_partitions", user, partition_id, {"_id": 0} if include_members else {"_id": 0, "members": 0})
    p["job"] = await _job(partition_id)
    return p


# ---------------- runs
class RunIn(BaseModel):
    kind: Literal["baseline", "training", "evaluation"]
    release_id: Optional[str] = None
    partition_id: Optional[str] = None
    profile_id: Optional[str] = None
    model: Literal["local_crop_logreg", "hosted_vision"] = "local_crop_logreg"
    max_images: int = Field(48, ge=1, le=48)
    seed: int = 7


@router.post("/runs", status_code=202)
async def create_run(body: RunIn, user: dict = Depends(staff)):
    ws = user["workspace_id"]
    run = {"uuid": new_id(), "workspace_id": ws, "kind": body.kind, "status": "Queued", "logs": [], "created_by": user["uuid"], "created_at": iso()}
    if body.kind == "evaluation":
        if not body.profile_id:
            err(422, "profile_required", "evaluation needs profile_id")
        prof = await _scoped("calibration_profiles", user, body.profile_id)
        tr = await db.model_runs.find_one({"uuid": prof["model_run_id"]})
        run |= {"profile_id": prof["uuid"], "release_id": tr["release_id"], "partition_id": tr["partition_id"], "model_run_id": tr["uuid"],
                "config": {"test": "source val (locked)", "threshold": 0.5}}
    else:
        if not body.partition_id:
            err(422, "partition_required", "partition_id is required")
        p = await _scoped("data_partitions", user, body.partition_id, {"_id": 0, "members": 0})
        if p["status"] != "Complete":
            err(409, "partition_incomplete", "Partition is not Complete")
        run |= {"release_id": p["release_id"], "partition_id": p["uuid"]}
        if body.kind == "training" and body.model == "hosted_vision":
            run |= {"status": "Unsupported", "blocker": cal.HOSTED_TRAINING_BLOCKER, "config": {"model": "claude-sonnet-5-5 (hosted)"}}
            await db.model_runs.insert_one(dict(run))
            run.pop("_id", None)
            return {"run": run, "job": None}
        if body.kind == "training":
            run["config"] = {"model": "local_crop_logreg", "task": "supplied_box_condition_classification", "classes": {str(k): v for k, v in cal.TARGET_CLASSES.items()},
                             "features": "48x48 context crop (bbox +25%): 6x6x9 gradient-orientation histogram, RGB histograms/stats, class one-hot, box geometry",
                             "l2": 1e-3, "iters": 600, "lr": 0.05, "seed": body.seed, "class_balanced": True,
                             "augmentation": {"seed": 1337, "applies_to": "fit only", "copies_bad": 2, "copies_good": 0,
                                              "transforms": ["horizontal flip p=0.5", "brightness ×U(0.8,1.2)"]},
                             "abstain_rule": "bbox min side < 6 px", "occluded": "included as labelled"}
        else:
            b = await cal.budget()
            if b["remaining"] <= 0:
                err(409, "budget_reached", cal.BUDGET_MSG)
            run["config"] = {"model": "claude-sonnet-5-5 via existing ai_image adapter", "prompt_version": __import__("ai_image").PROMPT_VERSION,
                             "max_images": min(body.max_images, b["remaining"]), "seed": body.seed,
                             "inputs": "re-encoded pixels only; labels, filenames and overlays withheld", "pool": "source train (fit+calibration); never val"}
        run["config_sha256"] = hashlib.sha256(json.dumps(run["config"], sort_keys=True, default=str).encode()).hexdigest()
    await db.model_runs.insert_one(dict(run))
    run.pop("_id", None)
    await cal.enqueue(ws, body.kind, run["uuid"], user["uuid"])
    await audit(user, ws, f"calibration.run.{body.kind}", "model_run", run["uuid"])
    return {"run": run, "job": await _job(run["uuid"])}


@router.get("/runs")
async def list_runs(user: dict = Depends(staff)):
    rows = await db.model_runs.find({"workspace_id": user["workspace_id"]}, {"_id": 0, "logs": 0, "selection": 0}).sort("created_at", -1).to_list(50)
    return {"runs": rows, "budget": await cal.budget()}


@router.get("/runs/{run_id}")
async def get_run(run_id: str, include_items: bool = False, user: dict = Depends(staff)):
    r = await _scoped("model_runs", user, run_id)
    r["job"] = await _job(run_id)
    if r["kind"] == "baseline":
        r["budget"] = await cal.budget()
        if include_items:
            r["items"] = await db.cal_run_items.find({"run_id": run_id}, {"_id": 0}).to_list(100)
    return r


@router.get("/budget")
async def get_budget(user: dict = Depends(staff)):
    return await cal.budget()


# ---------------- profiles
class ProfileIn(BaseModel):
    training_run_id: str


@router.post("/profiles", status_code=201)
async def create_profile(body: ProfileIn, user: dict = Depends(staff)):
    tr = await _scoped("model_runs", user, body.training_run_id)
    if tr["kind"] != "training" or tr["status"] != "Done":
        err(409, "training_not_done", "A completed local training run is required")
    return await cal.fit_profile(user["workspace_id"], tr, user)


@router.post("/profiles/{profile_id}/activate")
async def activate(profile_id: str, user: dict = Depends(staff)):
    p = await _scoped("calibration_profiles", user, profile_id, {"uuid": 1})
    ws = user["workspace_id"]
    await db.calibration_profiles.update_many({"workspace_id": ws, "status": "Active"}, {"$set": {"status": "Superseded", "superseded_at": iso()}})
    await db.calibration_profiles.update_one({"uuid": p["uuid"]}, {"$set": {
        "status": "Active", "activated_by": user["uuid"], "activated_by_role": user["role"], "activated_at": iso(),
        "applies_to": "new runs only, within declared task/class/domain; historical runs keep their recorded versions"}})
    await audit(user, ws, "calibration.profile.activate", "calibration_profile", p["uuid"])
    return await db.calibration_profiles.find_one({"uuid": p["uuid"]}, {"_id": 0, "calibration_memberships": 0})


@router.get("/profiles")
async def list_profiles(user: dict = Depends(staff)):
    rows = await db.calibration_profiles.find({"workspace_id": user["workspace_id"]}, {"_id": 0, "calibration_memberships": 0}).sort("version", -1).to_list(50)
    return {"profiles": rows, "label": cal.PROFILE_LABEL, "sf_validation": cal.SF_VALIDATION}
