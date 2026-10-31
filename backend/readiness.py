"""Deterministic readiness labels per estimating field (server-side, shared by mobile + web)."""
from core import db

FIELDS = [
    {"key": "inspected_quantity", "label": "Ties inspected (count)", "type": "integer",
     "question": "How many ties did you inspect?"},
    {"key": "repair_quantity", "label": "Ties to replace (count)", "type": "integer",
     "question": "How many ties need replacement?"},
    {"key": "tie_specification", "label": "Tie specification", "type": "text",
     "question": "What tie specification is needed (size, material, grade)?"},
    {"key": "material_responsibility", "label": "Who supplies ties", "type": "enum",
     "options": ["Contractor", "Customer", "Unresolved"], "question": "Who supplies the replacement ties?"},
    {"key": "work_location", "label": "Work location / limits", "type": "text",
     "question": "Where exactly is the work (track, mile post, limits)?"},
]
FIELD_KEYS = [f["key"] for f in FIELDS]
LABELS = ["Provided", "Missing required", "Needs review", "Unknown with reason", "Not applicable", "Needs estimator input"]


async def proposals_by_field(visit_id: str) -> dict:
    out = {k: [] for k in FIELD_KEYS}
    flagged = set()
    async for c in db.text_checks.find({"visit_id": visit_id, "kind": "text_flags", "status": "Done", "result.contains_instructions": True}, {"target_id": 1}):
        flagged.add(c["target_id"])
    async for p in db.proposed_fields.find({"visit_id": visit_id, "active": True}, {"_id": 0}).sort("created_at", 1):
        p["untrusted"] = p.get("source_evidence_id") in flagged or (p.get("transcript_id") is not None and p["transcript_id"] in flagged)
        out.setdefault(p["field"], []).append(p)
    return out


def _distinct_values(props):
    return sorted({str(p["value"]).strip().lower() for p in props})


async def compute(visit: dict) -> dict:
    props = await proposals_by_field(visit["uuid"])
    answers = visit.get("answers", {})
    # audio items without a completed transcript never count as a source
    untranscribed = 0
    async for ev in db.evidence.find({"visit_id": visit["uuid"], "kind": "audio"}, {"uuid": 1}):
        if not await db.transcripts.find_one({"evidence_id": ev["uuid"]}):
            untranscribed += 1
    fields = []
    for f in FIELDS:
        k = f["key"]
        a = answers.get(k)
        p = props.get(k, [])
        distinct = _distinct_values(p)
        discrepancy = len(distinct) > 1
        review_reason = None
        if a:
            state = a["state"]
            if state == "Provided" and (a.get("relevance") or {}).get("low"):
                state, review_reason = "Needs review", "Answer may not address the question"
            if state == "Provided" and discrepancy and not a.get("resolves_discrepancy"):
                # a new conflicting source arrived after the answer
                newer = [x for x in p if x["created_at"] > a["at"]]
                if newer:
                    state = "Needs review"
        elif p:
            state = "Needs review"
        else:
            state = "Missing required"
        fields.append({
            "field": k, "label": f["label"], "type": f["type"], "options": f.get("options"),
            "question": f["question"], "state": state, "review_reason": review_reason, "answer": a, "proposals": p,
            "discrepancy": discrepancy, "distinct_values": distinct,
        })
    counts = {lbl: sum(1 for x in fields if x["state"] == lbl) for lbl in LABELS}
    return {"fields": fields, "counts": counts, "untranscribed_audio": untranscribed,
            "note": "Audio without a completed transcript is not counted as a source." if untranscribed else None}
