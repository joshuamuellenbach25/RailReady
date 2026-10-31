"""Client diagnostics breadcrumbs (capture step names only. No media, no credentials). Rate-limited; staff read their workspace."""
import time
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from core import db, iso, new_id, require_role, user_from_token
from routes_public import _hits

router = APIRouter(prefix="/api/diagnostics", tags=["diagnostics"])


class Crumb(BaseModel):
    step: str = Field(max_length=80)
    at: str = Field(max_length=40)
    detail: Optional[str] = Field(default=None, max_length=200)
    session: Optional[str] = Field(default=None, max_length=64)


class CrumbsIn(BaseModel):
    platform: Optional[str] = Field(default=None, max_length=20)
    os_version: Optional[str] = Field(default=None, max_length=40)
    app_version: Optional[str] = Field(default=None, max_length=40)
    sdk: Optional[str] = Field(default=None, max_length=20)
    expo_go: Optional[bool] = None
    crumbs: List[Crumb] = Field(max_length=200)


@router.post("/breadcrumbs", status_code=201)
async def post_crumbs(body: CrumbsIn, request: Request):
    k = "diag:" + (request.client.host if request.client else "?")
    q, t = _hits[k], time.time()
    while q and q[0] < t - 60:
        q.popleft()
    if len(q) >= 120:  # keyed by client host; behind the ingress all phones share one host, so keep this generous
        raise HTTPException(429, {"code": "rate_limited", "message": "Too many diagnostics uploads", "retryable": True})
    q.append(t)
    user = None
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        try:
            user = await user_from_token(auth[7:])
        except HTTPException:
            user = None
    doc = {"uuid": new_id(), "received_at": iso(), "user_id": user and user["uuid"], "workspace_id": user and user["workspace_id"],
           **body.model_dump(exclude={"crumbs"}), "crumbs": [c.model_dump() for c in body.crumbs],
           "last_step": body.crumbs[-1].step if body.crumbs else None}
    await db.diagnostics.insert_one(doc)
    return {"id": doc["uuid"], "count": len(body.crumbs), "last_step": doc["last_step"]}


@router.get("/breadcrumbs")
async def list_crumbs(limit: int = 20, user=Depends(require_role("admin", "estimator"))):
    q = {"$or": [{"workspace_id": user["workspace_id"]}, {"workspace_id": None}]}
    rows = await db.diagnostics.find(q, {"_id": 0}).sort("received_at", -1).to_list(min(limit, 100))
    return {"uploads": rows, "platform_counts": {p or "unknown": await db.diagnostics.count_documents({**q, "platform": p}) for p in ("ios", "android", "web")}}
