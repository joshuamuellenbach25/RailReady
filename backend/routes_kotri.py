"""Phase 9 Kotri dataset APIs. Admin-only; workspace-scoped (foreign ids → 404)."""
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response

import calibration as cal
import kotri
import storage
from core import audit, db, iso, new_id, require_role

router = APIRouter(prefix="/api/calibration/kotri", tags=["kotri"])
admin = require_role("admin")


def _view(r: dict) -> dict:
    return {k: r.get(k) for k in ("uuid", "status", "stage", "downloaded_bytes", "stored", "total", "archive", "metadata",
                                  "stats", "problems", "error", "created_at", "updated_at", "completed_at")} | {
        "source": kotri.SOURCE, "credit": kotri.CREDIT, "split_groups": kotri.SPLIT_GROUPS, "expected_splits": kotri.EXPECT_SPLITS}


@router.post("/import", status_code=202)
async def start(user=Depends(admin)):
    ws = user["workspace_id"]
    r = await db.dataset_releases.find_one({"workspace_id": ws, "source.sha256": kotri.SOURCE["sha256"]}, {"_id": 0})
    if r and r["status"] == "Complete":
        return {"release": _view(r), "already_complete": True}
    if r and r["status"] in ("Queued", "Running"):
        return {"release": _view(r), "resumed": True}
    rid = r["uuid"] if r else new_id()
    if not r:
        await db.dataset_releases.insert_one({"uuid": rid, "workspace_id": ws, "dataset": "kotri", "source": kotri.SOURCE,
                                              "status": "Queued", "created_at": iso(), "created_by": user["uuid"], "updated_at": iso()})
    else:
        await db.dataset_releases.update_one({"uuid": rid}, {"$set": {"status": "Queued", "error": None, "updated_at": iso()}})
    await cal.enqueue(ws, "kotri_import", rid, user["uuid"])
    await audit(user, ws, "kotri_import_started", "dataset_release", rid, {})
    return {"release": _view(await db.dataset_releases.find_one({"uuid": rid}, {"_id": 0})), "resumed": bool(r)}


async def _release(user) -> dict:
    r = await db.dataset_releases.find_one({"workspace_id": user["workspace_id"], "source.sha256": kotri.SOURCE["sha256"]}, {"_id": 0})
    if not r:
        raise HTTPException(404, "Not found")
    return r


@router.get("")
async def status(user=Depends(admin)):
    r = await _release(user)
    job = await db.cal_jobs.find_one({"target_id": r["uuid"]}, {"_id": 0, "status": 1, "attempts": 1, "error": 1, "updated_at": 1}, sort=[("created_at", -1)])
    return {"release": _view(r), "job": job}


@router.get("/images")
async def images(label: Optional[str] = None, split: Optional[Literal["fit", "calibration", "test"]] = None,
                 limit: int = Query(50, le=200), skip: int = 0, user=Depends(admin)):
    r = await _release(user)
    q = {"release_id": r["uuid"], **({"label": label} if label else {}), **({"split": split} if split else {})}
    return {"total": await db.kotri_images.count_documents(q),
            "items": await db.kotri_images.find(q, {"_id": 0}).sort("path", 1).skip(skip).limit(limit).to_list(limit)}


@router.get("/images/{folder}/{filename}/media")
async def media(folder: str, filename: str, user=Depends(admin)):
    r = await _release(user)
    im = await db.kotri_images.find_one({"release_id": r["uuid"], "path": f"{folder}/{filename}"})
    if not im:
        raise HTTPException(404, "Not found")
    return Response(storage.get_object(im["object_path"]), media_type="image/jpeg", headers={"Cache-Control": "private, max-age=300"})


import kotri_train  # noqa: E402  (registers kotri_train / kotri_smoke handlers)


async def _start_run(user, kind: str) -> dict:
    r = await _release(user)
    if r["status"] != "Complete":
        raise HTTPException(409, {"code": "import_incomplete", "message": "Kotri import is not complete yet", "retryable": True})
    rid = new_id()
    await db.model_runs.insert_one({"uuid": rid, "workspace_id": user["workspace_id"], "dataset": "kotri", "kind": kind, "release_id": r["uuid"],
                                    "status": "Queued", "domain": kotri_train.DOMAIN, "logs": [], "created_at": iso(), "created_by": user["uuid"], "updated_at": iso()})
    await cal.enqueue(user["workspace_id"], kind, rid, user["uuid"])
    await audit(user, user["workspace_id"], f"{kind}_started", "model_run", rid, {})
    return await db.model_runs.find_one({"uuid": rid}, {"_id": 0})


@router.post("/smoke", status_code=202)
async def smoke(user=Depends(admin)):
    """7 hosted calls (one fit image per class), labels/filenames withheld; counts against the global image-call budget."""
    b = await cal.budget()
    if b["remaining"] < 7:
        raise HTTPException(409, {"code": "budget", "message": cal.BUDGET_MSG})
    return await _start_run(user, "kotri_smoke")


@router.post("/train", status_code=202)
async def train(user=Depends(admin)):
    return await _start_run(user, "kotri_train")


@router.get("/runs/{run_id}")
async def get_run(run_id: str, user=Depends(admin)):
    r = await db.model_runs.find_one({"uuid": run_id, "workspace_id": user["workspace_id"], "dataset": "kotri"}, {"_id": 0})
    if not r:
        raise HTTPException(404, "Not found")
    return r
