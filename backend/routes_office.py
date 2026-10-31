"""Phase 3 office read models for the web app: jobs board and contracts (contracts map 1:1 onto proposal versions)."""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse

from core import clean, clean_all, db
import agreement
from routes_estimate import contract_status, get_version, staff, version_status

router = APIRouter(prefix="/api", tags=["office"])


def link_state(links):
    return "Revoked" if links and all(l["revoked"] for l in links) else None


async def _contract_status(v, eng):
    st = contract_status(version_status(v, eng))
    if st == "Issued" and link_state(await db.share_links.find({"version_id": v["uuid"]}).to_list(50)):
        return "Revoked"
    return st


@router.get("/office/jobs")
async def jobs(user=Depends(staff)):
    ws = user["workspace_id"]
    out = []
    for v in await db.visits.find({"workspace_id": ws}).sort("updated_at", -1).to_list(300):
        site = await db.sites.find_one({"uuid": v["site_id"]}) or {}
        cust = await db.customers.find_one({"uuid": v["customer_id"]}) or {}
        eng = await db.engagements.find_one({"visit_id": v["uuid"]})
        row = {"visit_id": v["uuid"], "visit_title": v.get("title"), "visit_status": v["status"], "visit_revision": v["revision"],
               "customer_id": v["customer_id"], "customer_name": cust.get("name"), "site_id": v["site_id"], "site_name": site.get("name"),
               "findings_count": await db.observations.count_documents({"visit_id": v["uuid"], "kind": "finding"}),
               "candidate_count": await db.visual_candidates.count_documents({"visit_id": v["uuid"]}),
               "pending_candidate_count": await db.visual_candidates.count_documents({"visit_id": v["uuid"], "review_state": "Pending"}),
               "engagement_id": None, "proposal_number": None, "estimate_status": "Not started", "latest_version_id": None,
               "latest_version_no": None, "latest_version_status": None, "contract_id": None, "contract_status": None,
               "work_order_id": None, "work_order_number": None, "work_order_access_status": None, "updated_at": v.get("updated_at")}
        if eng:
            d = await db.estimate_drafts.find_one({"uuid": eng["draft_id"]})
            row.update({"engagement_id": eng["uuid"], "proposal_number": eng["proposal_number"],
                        "estimate_status": "Accepted" if eng.get("accepted_version_id") else ("Draft" if d and d["lines"] else "Empty draft")})
            lv = await db.proposal_versions.find_one({"engagement_id": eng["uuid"], "status": {"$ne": "Void"}}, sort=[("version_no", -1)])
            if lv:
                vs = version_status(lv, eng)
                row.update({"latest_version_id": lv["uuid"], "latest_version_no": lv["version_no"], "latest_version_status": vs,
                            "contract_id": lv["uuid"], "contract_status": await _contract_status(lv, eng)})
                if row["estimate_status"] != "Accepted":
                    row["estimate_status"] = "Published"
            else:
                row["contract_status"] = "Draft"
            w = await db.work_orders.find_one({"engagement_id": eng["uuid"]})
            if w:
                row.update({"work_order_id": w["uuid"], "work_order_number": w.get("number"), "work_order_access_status": w.get("access_status")})
        out.append(row)
    return {"jobs": out}


def _contract_summary(v, eng, st):
    a = v["snapshot"]["agreement"]
    return {"contract_id": v["uuid"], "version_id": v["uuid"], "version_no": v["version_no"], "engagement_id": eng["uuid"],
            "visit_id": v["visit_id"], "proposal_number": v["snapshot"]["proposal_number"], "customer_site": v["snapshot"]["customer_site"],
            "status": st, "template_version": a["template_version"], "template_hash": a["template_hash"], "document_hash": a["document_hash"],
            "label": a["label"], "issued_at": v.get("published_at"), "expiry": v["snapshot"]["expiry"]}


@router.get("/contracts")
async def list_contracts(user=Depends(staff)):
    out = []
    for v in await db.proposal_versions.find({"workspace_id": user["workspace_id"], "status": {"$ne": "Void"}},
                                             {"internal_snapshot": 0}).sort("published_at", -1).to_list(300):
        eng = await db.engagements.find_one({"uuid": v["engagement_id"]})
        out.append(_contract_summary(v, eng, await _contract_status(v, eng)))
    drafts = []
    async for eng in db.engagements.find({"workspace_id": user["workspace_id"], "latest_version_id": None}):
        drafts.append({"contract_id": None, "engagement_id": eng["uuid"], "visit_id": eng["visit_id"], "proposal_number": eng["proposal_number"],
                       "status": "Draft", "preview_path": f"/api/engagements/{eng['uuid']}/agreement-preview"})
    return {"contracts": out, "drafts": drafts}


@router.get("/contracts/{cid}")
async def get_contract(cid: str, user=Depends(staff)):
    v, eng = await get_version(user, cid)
    if v.get("status") == "Void":
        raise HTTPException(404, "Not found")
    a = v["snapshot"]["agreement"]
    acc = [clean(d) for d in await db.decisions.find({"version_id": cid, "type": "accept"}).to_list(5)]
    chg = [clean(d) for d in await db.decisions.find({"version_id": cid, "type": "changes"}).to_list(20)]
    links = clean_all(await db.share_links.find({"version_id": cid}, {"token_hash": 0}).to_list(20))
    return {**_contract_summary(v, eng, await _contract_status(v, eng)),
            "document": {"label": a["label"], "document_text": a["document_text"], "document_hash": a["document_hash"],
                         "template_version": a["template_version"], "template_hash": a["template_hash"], "variables": a["variables"]},
            "snapshot_hash": v["snapshot_hash"], "acceptance_evidence": acc[0] if acc else None, "change_requests": chg, "links": links,
            "print_path": f"/api/contracts/{cid}/print"}


@router.get("/contracts/{cid}/print", response_class=HTMLResponse)
async def print_contract(cid: str, request: Request, user=Depends(staff)):
    v, _ = await get_version(user, cid)
    tok = request.query_params.get("auth", "")
    return agreement.print_html(v["snapshot"], v, lambda eid: f"/api/proposals/{cid}/media/{eid}?auth={tok}")
