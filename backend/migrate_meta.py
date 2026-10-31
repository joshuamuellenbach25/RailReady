"""Idempotent no-metacommentary migration across ALL workspaces (demo included).
- Display fields of app-generated records are cleaned in place (ids, relations, workspace ids unchanged); one audit entry
  per changed document (action display_copy_migrated, before/after).
- Issued proposal versions / agreements are NOT modified: a versioned correction record is written in
  document_corrections (original version, its hashes and signatures untouched).
- Never touches user-authored or evidential content: evidence, transcripts, observations, decisions, audit, runs.
Run: python3 /app/backend/migrate_meta.py  (safe to re-run: second run changes 0)."""
import asyncio, json, sys
sys.path.insert(0, "/app/backend")
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
from core import db, iso, new_id, sha256_hex
from meta_rules import BANNED, clean_text

KEYS = {"name", "label", "address", "title", "description", "assumption", "legal_identity", "tax_treatment_text", "payment_terms",
        "schedule_wording", "assumptions", "exclusions", "validity", "acceptance_wording", "escalation_text", "display_name", "customer_name"}
SKIP = {"evidence", "transcripts", "observations", "decisions", "candidate_decisions", "audit_log", "audit", "image_analysis_runs", "jobs",
        "share_links", "proposal_versions", "document_corrections", "kotri_images", "dataset_files", "cal_images", "breadcrumbs", "users"}


def walk(v, key=None):
    """Returns (new_value, changed). Only strings under display KEYS are rewritten."""
    if isinstance(v, dict):
        ch, out = False, {}
        for k, x in v.items():
            nx, c = walk(x, k)
            out[k], ch = nx, ch or c
        return out, ch
    if isinstance(v, list):
        res = [walk(x, key) for x in v]
        return [r[0] for r in res], any(r[1] for r in res)
    if isinstance(v, str) and key == "document_text" and BANNED.search(v):  # generated agreement text: drop label lines only
        nv = "\n".join(clean_text(l) for l in v.split("\n") if clean_text(l) or not l.strip() or not BANNED.search(l))
        return nv, nv != v
    if isinstance(v, str) and key in KEYS and BANNED.search(v):
        nv = clean_text(v)
        return (nv if nv else None), nv != v
    return v, False


async def main():
    counts, corrections = {}, 0
    for coll in sorted(await db.list_collection_names()):
        if coll in SKIP or coll.startswith("system."):
            continue
        n = 0
        async for d in db[coll].find({}):
            body = {k: x for k, x in d.items() if k != "_id"}
            new, changed = walk(body)
            if not changed:
                continue
            diff = {k: new[k] for k in new if new[k] != body.get(k)}
            await db[coll].update_one({"_id": d["_id"]}, {"$set": diff})
            await db.audit_log.insert_one({"uuid": new_id(), "workspace_id": d.get("workspace_id"), "actor_id": "system:migrate_meta", "action": "display_copy_migrated",
                                           "object_type": coll, "object_id": d.get("uuid"), "detail": {"before": {k: body.get(k) for k in diff}, "after": diff}, "at": iso()})
            n += 1
        if n:
            counts[coll] = n
    # issued documents: versioned correction, original untouched
    async for v in db.proposal_versions.find({}):
        snap = v.get("snapshot") or {}
        new, changed = walk(snap)
        doc_txt = (v.get("agreement") or {}).get("text") or ""
        new_txt = "\n".join(l for l in doc_txt.split("\n") if not BANNED.search(l)) if BANNED.search(doc_txt) else doc_txt
        if not changed and new_txt == doc_txt:
            continue
        if await db.document_corrections.find_one({"version_id": v["uuid"], "kind": "display_copy"}):
            continue
        await db.document_corrections.insert_one({
            "uuid": new_id(), "workspace_id": v["workspace_id"], "version_id": v["uuid"], "engagement_id": v.get("engagement_id"), "kind": "display_copy",
            "correction_no": 1, "original_snapshot_hash": v.get("snapshot_hash"), "original_document_hash": v.get("document_hash"),
            "corrected_snapshot": new, "corrected_agreement_text": new_txt if new_txt != doc_txt else None,
            "corrected_hash": sha256_hex(json.dumps(new, sort_keys=True, default=str).encode() + new_txt.encode()),
            "reason": "Removed development/demo labels from display copy. Terms, prices and signatures unchanged.", "created_by": "system:migrate_meta", "at": iso()})
        await db.audit_log.insert_one({"uuid": new_id(), "workspace_id": v["workspace_id"], "actor_id": "system:migrate_meta", "action": "document_correction_issued",
                                       "object_type": "proposal_version", "object_id": v["uuid"], "at": iso()})
        corrections += 1
    counts["document_corrections (issued versions, originals untouched)"] = corrections
    print(json.dumps(counts, indent=1))

asyncio.run(main())
