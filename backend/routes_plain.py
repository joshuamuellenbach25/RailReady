"""Phase 8 (REQ-258..270): plain-language view model shared by mobile and web.

Every string returned here is user-facing and must stay free of internal/technical terms
(model names, ids shown as text, confidence/probability/%, sync/upload/server/processing...).
Provenance (ids, model ids, scores) stays in the database and admin-only diagnostics; only
opaque references (evidence_id / target ids) are returned so the clients can act on a question.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core import audit, current_user, db, get_visit, iso
import routes_phase5
import rail_surface

router = APIRouter(prefix="/api", tags=["plain"])

SUGGESTION_TEXT = {
    "possible missing/displaced fastener": "Possible missing or loose fastening",
    "visible tie-surface deterioration": "Possible damaged tie",
    "other visible condition": "Something worth a closer look",
}
PHOTO_CHOICES = [  # U1: photo + result + Confirm / Correct / Dismiss
    {"id": "yes", "label": "Confirm"},
    {"id": "not_quite", "label": "Correct"},
    {"id": "no", "label": "Dismiss"},
]


def _value(p: dict, unit: str | None) -> str:
    return f"{p['value']}{' ' + unit if unit else ''}"


def field_question(f: dict) -> dict | None:
    label = f["label"]
    low = label[0].lower() + label[1:]
    base = {"id": f"field:{f['key']}", "kind": "answer", "target": {"type": "field", "key": f["key"]},
            "label": label, "options": f.get("options") or [], "unit": f.get("unit"), "input": f.get("type")}
    if f["status"] == "needs_estimator":
        return None  # waiting on the estimator, not on the foreman
    ps = f["proposals"]
    if f["group"] == "needs_review" and ps:
        if f["discrepancy"]:
            return {**base, "text": f"Your notes mention different values for {low}. Which one is right?",
                    "choices": [{"id": f"pick:{p['uuid']}", "label": _value(p, f.get('unit'))} for p in ps] + [{"id": "other", "label": "Something else"}],
                    "quotes": [{"text": p["excerpt"], "evidence_id": p.get("source_evidence_id"), "from": "voice note" if p.get("source_kind") == "audio" else "note"} for p in ps]}
        p = ps[0]
        return {**base, "text": f"{label.rstrip('?')}: {_value(p, f.get('unit'))} - is that right?",
                "choices": [{"id": f"pick:{p['uuid']}", "label": "Yes"}, {"id": "other", "label": "Not quite"}, {"id": "ask", "label": "Ask the estimator"}],
                "quotes": [{"text": p["excerpt"], "evidence_id": p.get("source_evidence_id"), "from": "voice note" if p.get("source_kind") == "audio" else "note"}],
                "careful": bool(p.get("untrusted"))}
    if f["group"] == "missing":
        return {**base, "kind": "missing", "text": label if label.endswith("?") else f"What is the {low}?",
                "hint": "Not mentioned in your photos, voice notes or notes yet. You can type it, record a voice note or take a photo.",
                "choices": [{"id": "other", "label": "Answer"}, {"id": "ask", "label": "Ask the estimator"}]
                + ([{"id": "later", "label": "Don't know yet"}] if f.get("allowed_non_answers") else [])}
    return None


async def build(visit_id: str, user: dict) -> dict:
    checklist = await routes_phase5.visit_checklist(visit_id, user)
    questions = [q for q in (field_question(f) for f in checklist["fields"]) if q]
    if checklist.get("state") == "needs_repair":  # C5: say so plainly instead of hiding the checklist
        questions.append({"id": "checklist:repair", "kind": "missing", "text": checklist["message"], "target": {"type": "checklist_repair"},
                          "choices": [], "hint": None})

    ev_by_id = {e["uuid"]: e async for e in db.evidence.find({"visit_id": visit_id}, {"_id": 0})}
    async for c in db.visual_candidates.find({"visit_id": visit_id, "review_state": {"$in": ["Pending", "Closer photo requested"]}}, {"_id": 0}).sort("created_at", 1):
        what = SUGGESTION_TEXT.get(c.get("category"), "Something worth a closer look")
        text = None
        if c.get("pipeline") == rail_surface.PIPELINE:  # B4/C2: rail-surface items, plain words; image-level vs localized stay distinct
            # C4: uncertain items are shown by default (needs_review as well as suggested); unclassified/fallbacks are not questions
            if c.get("identity_status") not in ("suggested", "needs_review") or not (text := rail_surface.plain_text(c)):
                continue
        elif c.get("pipeline") == "two_stage_v1":  # Phase 7: ask about candidates with a visible concern, in plain words (no hidden filter)
            con = c.get("concerns") or {}
            if (con.get("visible_tie_surface_damage") or {}).get("choice") == "present" and con["visible_tie_surface_damage"]["status"] in ("suggested", "needs_review"):
                what = "Possible damaged tie"
            elif (con.get("missing_or_displaced_fastener") or {}).get("choice") == "present" and con["missing_or_displaced_fastener"]["status"] in ("suggested", "needs_review"):
                what = "Possible missing or loose fastening"
            else:
                continue
        ref = {"evidence_id": c["evidence_id"], "kind": "photo"}
        if c["review_state"] == "Pending":
            questions.append({"id": f"photo:{c['uuid']}", "kind": "photo_suggestion", "text": text or f"{what} - does this look right?",
                              "detail": None if c.get("pipeline") in ("two_stage_v1", rail_surface.PIPELINE) else (c.get("visible_reason") or None),
                              "where": ("spot" if c.get("localized") else "whole_photo"), "moment_s": c.get("timestamp_s"), "moments_s": c.get("timestamps_s"), "evidence": ref, "target": {"type": "candidate", "id": c["uuid"], "revision": c["revision"]},
                              "choices": PHOTO_CHOICES + [{"id": "closer", "label": "I'll take a closer photo"}]})
        else:
            questions.append({"id": f"request:{c['uuid']}", "kind": "evidence_request", "text": "Please take a closer photo of this spot.",
                              "evidence": ref, "target": {"type": "candidate", "id": c["uuid"]}, "choices": [{"id": "take_photo", "label": "Take photo"}]})

    for eid, e in ev_by_id.items():
        if e.get("kind") != "audio":
            continue
        t = await db.transcripts.find_one({"evidence_id": eid}, {"_id": 0}, sort=[("version", -1)])
        if not t or t.get("kind") == "corrected" or e.get("transcript_ok_version") == t["version"]:
            continue
        questions.append({"id": f"voice:{eid}", "kind": "voice_check", "text": "Here's what we heard in your voice note. Is it right?",
                          "heard": t["text"], "evidence": {"evidence_id": eid, "kind": "audio"}, "target": {"type": "transcript", "base_version": t["version"]},
                          "choices": [{"id": "yes", "label": "Yes"}, {"id": "edit", "label": "Fix the words"}]})

    order = {"photo_suggestion": 0, "voice_check": 1, "answer": 2, "missing": 3, "evidence_request": 4}
    questions.sort(key=lambda q: order[q["kind"]])
    n = len(questions)
    return {"visit_id": visit_id, "revision": checklist["revision"], "count": n,
            "summary": "Nothing left to check - you're all set." if not n else f"{n} thing{'s' if n != 1 else ''} to check",
            "questions": questions}


@router.get("/visits/{visit_id}/review-questions")
async def review_questions(visit_id: str, user=Depends(current_user)):
    return await build(visit_id, user)


class VoiceOkIn(BaseModel):
    base_version: int


@router.post("/evidence/{evidence_id}/transcript-ok")
async def transcript_ok(evidence_id: str, body: VoiceOkIn, user=Depends(current_user)):
    e = await db.evidence.find_one({"uuid": evidence_id}, {"_id": 0})
    if not e:
        raise HTTPException(404, "Not found")
    v = await get_visit(user, e["visit_id"])  # scoped: foreign visits 404
    t = await db.transcripts.find_one({"evidence_id": evidence_id}, sort=[("version", -1)])
    if not t or t["version"] != body.base_version:
        raise HTTPException(409, {"code": "stale_version", "message": "This voice note changed - showing the latest words.", "retryable": True})
    await db.evidence.update_one({"uuid": evidence_id}, {"$set": {"transcript_ok_version": t["version"], "updated_at": iso()}})
    await audit(user, v["workspace_id"], "transcript_confirmed", "evidence", evidence_id, {"version": t["version"]})
    return {"ok": True}
