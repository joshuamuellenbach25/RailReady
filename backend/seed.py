"""Idempotent seed: two workspaces, users, customers/sites/tracks, crews, sample catalog, demo visits.
Seeded notes are real text; their extraction runs through the real local LLM job pipeline (no canned outputs)."""
import os

from core import db, hash_password, iso, sha256_hex, verify_password
import jobs

PW = os.environ["SEED_PASSWORD"]
SYS = "seed"


def base(uuid, **kw):
    return {"uuid": uuid, "created_at": iso(), "created_by": SYS, "updated_at": iso(), "updated_by": SYS, "revision": 1, **kw}


async def upsert(coll, doc):
    await db[coll].update_one({"uuid": doc["uuid"]}, {"$setOnInsert": doc}, upsert=True)


WS1, WS2 = "ws-ridgeline", "ws-isolation"
F1, E1, A1, F2 = "u-foreman-ridgeline", "u-estimator-ridgeline", "u-admin-ridgeline", "u-foreman-isolation"
USERS = [
    (F1, WS1, "foreman@ridgeline.example", "Dale Ortiz", "foreman"),
    (E1, WS1, "estimator@ridgeline.example", "Priya Nair", "estimator"),
    (A1, WS1, "admin@ridgeline.example", "Ridgeline Admin", "admin"),
    (F2, WS2, "foreman@isolation.example", "Iso Foreman", "foreman"),
]


async def seed():
    await upsert("workspaces", base(WS1, name="Ridgeline Rail Services", workspace_id=WS1, timezone="America/Los_Angeles",
                                    escalation_text="Urgent safety concern: stop work, call Ridgeline dispatch (555-0100) and the railroad's posted emergency number. Saving does not notify anyone."))
    await upsert("workspaces", base(WS2, name="Isolation Test Co", workspace_id=WS2, timezone="America/Denver",
                                    escalation_text="Call your supervisor. Saving does not notify anyone."))
    for uid, ws, email, name, role in USERS:
        ex = await db.users.find_one({"email": email})
        if not ex:
            await db.users.insert_one(base(uid, workspace_id=ws, email=email, name=name, role=role, password_hash=hash_password(PW)))
        elif not verify_password(PW, ex["password_hash"]):
            await db.users.update_one({"email": email}, {"$set": {"password_hash": hash_password(PW)}})

    await upsert("customers", base("c-cascade", workspace_id=WS1, name="Cascade Grain Co-op"))
    await upsert("customers", base("c-pinecrest", workspace_id=WS1, name="Pinecrest Lumber"))
    await upsert("customers", base("c-iso", workspace_id=WS2, name="Isolation Customer"))
    await upsert("sites", base("s-cascade", workspace_id=WS1, customer_id="c-cascade", name="Cascade Elevator Spur",
                               address="1200 Elevator Rd, Quincy WA", assigned_foreman_ids=[F1],
                               access_notes="Gate code at dispatch. Loaded cars may be spotted on Spur 2.",
                               prior_findings=[{"id": "pf-1", "status": "Outstanding", "recorded_at": "2026-04-12",
                                                "text": "Spur 2 near switch: several ties with plate cutting noted at last survey (not yet repaired)."}]))
    await upsert("sites", base("s-pinecrest", workspace_id=WS1, customer_id="c-pinecrest", name="Pinecrest Mill Siding",
                               address="88 Mill Ln, Sweet Home OR", assigned_foreman_ids=[F1],
                               access_notes="Mill shift change 14:00; avoid log loader lane.", prior_findings=[]))
    await upsert("sites", base("s-iso", workspace_id=WS2, customer_id="c-iso", name="Isolation Yard", address=None,
                               assigned_foreman_ids=[F2], prior_findings=[]))
    for t, s, n in [("t-c1", "s-cascade", "Spur 1"), ("t-c2", "s-cascade", "Spur 2"), ("t-p1", "s-pinecrest", "Siding A"), ("t-i1", "s-iso", "Yard 1")]:
        await upsert("tracks", base(t, workspace_id=WS1 if s != "s-iso" else WS2, site_id=s, name=n))
    await db.workspaces.update_one({"uuid": WS1}, {"$set": {
        "legal_identity": "Ridgeline Rail Services LLC, 400 Industrial Way, Spokane WA. Contractor license: Not set",
        "tax_rate": "0", "taxable_flags": {"material": True, "labor": False, "handling": False, "equipment": False, "mobilization": False, "general_repair": False, "other": False},
        "tax_treatment_text": "0% sales tax applied; tie material is configured taxable, services non-taxable. Confirm with your tax advisor.",
        "default_terms": {"payment_terms": "Net 30 from completion.", "schedule_wording": "Work scheduled within 30 days of acceptance, subject to track access.",
                          "assumptions": "Track time and access provided by customer; quantities per confirmed survey.",
                          "exclusions": "Rail, surfacing, ballast and areas marked Not inspected are excluded.",
                          "validity": "Proposal valid for 30 days.", "acceptance_wording": "By accepting, the customer agrees to this agreement and proposal version."}}})
    # The automated-test workspace needs its own estimate settings (open_engagement requires them). Only filled when absent.
    await db.workspaces.update_one({"uuid": WS2, "tax_rate": {"$exists": False}}, {"$set": {
        "legal_identity": "Isolation Test Co (TEST ONLY workspace). Contractor license: Not set",
        "tax_rate": "0", "taxable_flags": {"material": True, "labor": False, "handling": False, "equipment": False, "mobilization": False, "general_repair": False, "other": False},
        "tax_treatment_text": "TEST ONLY: 0% sales tax.",
        "default_terms": {"payment_terms": "TEST ONLY: Net 30 from completion.", "schedule_wording": "TEST ONLY: scheduled within 30 days of acceptance.",
                          "assumptions": "TEST ONLY: quantities per confirmed survey.", "exclusions": "TEST ONLY: areas marked Not inspected are excluded.",
                          "validity": "Proposal valid for 30 days.", "acceptance_wording": "By accepting, the customer agrees to this agreement and proposal version."}}})
    await upsert("packages", base("pkg-tie-v1", workspace_id=WS1, name="Tie replacement package", version=1, rates_version="rates-2026-sample-1",
                                  rates={"crosstie": {"unit_cost": "62.50", "markup_pct": "20", "assumption": "Crosstie 7x9x8'6\" hardwood grade 5 price"},
                                         "switch_tie": {"unit_cost": "185.00", "markup_pct": "20", "assumption": "Switch tie sized-set price (not substitutable)"},
                                         "labor": {"unit_cost": "68.00", "markup_pct": "15", "allowance_per_tie": "1.5", "assumption": "Configured allowance – Needs review"},
                                         "handling": {"unit_cost": "6.00", "markup_pct": "10", "assumption": "Per tie handled"},
                                         "equipment": {"unit_cost": "950.00", "markup_pct": "10", "ties_per_day": "40", "assumption": "Configured allowance – Needs review"},
                                         "mobilization": {"unit_cost": "1200.00", "markup_pct": "10", "assumption": "Configured allowance – Needs review"}}))
    for cid, n in [("crew-1", "Crew North"), ("crew-2", "Crew South")]:
        await upsert("crews", base(cid, workspace_id=WS1, name=n))
    catalog = [
        ("cat-crosstie", "Crosstie 7x9x8'6\" hardwood, grade 5", "each", "illustrative"),
        ("cat-switchtie", "Switch tie 7x9 hardwood, sized set", "each", "illustrative"),
        ("cat-labor", "Tie replacement labor", "tie", "illustrative"),
        ("cat-handling", "Material handling", "tie", "illustrative"),
        ("cat-equipment", "Tie inserter + hi-rail equipment", "day", "illustrative"),
        ("cat-mob", "Mobilization", "lump", "illustrative"),
    ]
    for cid, n, unit, lbl in catalog:
        await upsert("catalog_items", base(cid, workspace_id=WS1, name=n, unit=unit, label=lbl, tax_rate="0", phase="2 (not used in Phase 1)"))

    # ---- demo visits ----
    notes = {
        "v-seed-pinecrest": [
            ("n-seed-1", "Siding A west end. Inspected twelve ties, replace eight, customer supplies ties."),
            ("n-seed-2", "Walked it again with the mill super: replace ten ties, not eight. Customer still supplying."),
        ],
        "v-seed-cascade": [
            ("n-seed-3", "Spur 1 from the gate to the scale. Counted 40 ties, about 6 need changing. Did not get to spur 2."),
        ],
    }
    visits = [
        base("v-seed-pinecrest", workspace_id=WS1, site_id="s-pinecrest", customer_id="c-pinecrest", track_id="t-p1",
             foreman_id=F1, title="Pinecrest siding survey (seeded: competing count + customer-supplied ties)",
             processing_permission="Granted", status="Submitted", submitted_at=iso(), submitted_by=F1, answers={},
             coverage_note="Siding A full length", urgent_concern=None),
        base("v-seed-cascade", workspace_id=WS1, site_id="s-cascade", customer_id="c-cascade", track_id="t-c1",
             foreman_id=F1, title="Cascade spur check (seeded: missing specification, Not inspected area)",
             processing_permission="Granted", status="Submitted", submitted_at=iso(), submitted_by=F1, answers={},
             coverage_note="Spur 1 only", urgent_concern=None),
        base("v-seed-iso", workspace_id=WS2, site_id="s-iso", customer_id="c-iso", track_id="t-i1", foreman_id=F2,
             title="Isolation workspace visit", processing_permission="Unknown", status="Draft", answers={}),
    ]
    for v in visits:
        if await db.visits.find_one({"uuid": v["uuid"]}):
            continue
        await db.visits.insert_one(v)
        members = []
        for nid, text in notes.get(v["uuid"], []):
            data = text.encode()
            ev = base(nid, workspace_id=v["workspace_id"], visit_id=v["uuid"], kind="note", text=text, sha256=sha256_hex(data),
                      size=len(data), mime="text/plain", filename=None, upload_state="Verified", server_sha256=sha256_hex(data),
                      server_size=len(data), storage_path=None, verified_at=iso(), receipt_id=f"r-{v['uuid']}")
            await db.evidence.insert_one(ev)
            members.append({"evidence_id": nid, "sha256": ev["sha256"], "size": ev["size"]})
        if members:
            mid = f"m-{v['uuid']}"
            await db.manifests.insert_one(base(mid, workspace_id=WS1, visit_id=v["uuid"], manifest_hash=sha256_hex(str(members).encode()),
                                               members=members, state="Received complete", receipt_id=f"r-{v['uuid']}", missing=[]))
            await db.receipts.insert_one(base(f"r-{v['uuid']}", workspace_id=WS1, visit_id=v["uuid"], manifest_id=mid,
                                              member_count=len(members), issued_at=iso(), issued_by="server"))
            for nid, _ in notes[v["uuid"]]:
                await jobs.enqueue(v, "extraction", nid, "note")
    for vid, ns in notes.items():
        v = await db.visits.find_one({"uuid": vid})
        for nid, _ in ns:
            await jobs.enqueue(v, "text_checks", nid, "note")
    await seed_ready_visit("v-seed-ready", "")
    await seed_ready_visit("v-seed-ready-demo", "-demo")
    if not await db.observations.find_one({"uuid": "o-seed-ni"}):
        await db.observations.insert_one(base("o-seed-ni", workspace_id=WS1, visit_id="v-seed-cascade", kind="not_inspected",
                                              area="Spur 2 (switch to bumper)", reason="Loaded grain cars spotted on track; no safe access.",
                                              quantity=None, value=None, human_reviewed=True, source_candidate_id=None, specification=None))


async def seed_ready_visit(vid: str, sfx: str):
    """Ready-to-estimate submitted visit with a real verified photo (Wikimedia CC BY-SA 2.5, see test_photos/SOURCES.md)."""
    import asyncio
    import storage
    pid = f"e-seed-ready-photo{sfx}"
    if await db.visits.find_one({"uuid": vid}):
        return
    data = open(os.path.join(os.path.dirname(__file__), "test_photos", "tie_old_rotten.jpg"), "rb").read()
    path = f"railready/{WS1}/{vid}/{pid}.jpg"
    await asyncio.to_thread(storage.put_object, path, data, "image/jpeg")
    back = await asyncio.to_thread(storage.get_object, path)
    h = sha256_hex(back)
    ans = lambda val: {"state": "Provided", "value": val, "by": E1, "by_role": "estimator", "at": iso(), "source": "seed"}
    await db.visits.insert_one(base(vid, workspace_id=WS1, site_id="s-cascade", customer_id="c-cascade", track_id="t-c1", foreman_id=F1,
                                    title="Cascade Spur 1 survey (seeded: ready to estimate)", processing_permission="Granted", status="Submitted",
                                    submitted_at=iso(), submitted_by=F1, coverage_note="Spur 1 gate to scale", urgent_concern=None,
                                    answers={"inspected_quantity": ans(12), "repair_quantity": ans(8), "tie_specification": ans("Crosstie 7x9x8'6\" hardwood grade 5"),
                                             "material_responsibility": ans("Contractor"), "work_location": ans("Spur 1, gate to scale house")}))
    await db.evidence.insert_one(base(pid, workspace_id=WS1, visit_id=vid, kind="photo", sha256=h, size=len(back), mime="image/jpeg",
                                      filename="tie_old_rotten.jpg", caption="Weathered tie, Spur 1 (CC BY-SA 2.5, Per Erik Strandberg)",
                                      upload_state="Verified", storage_path=path, server_sha256=h, server_size=len(back), verified_at=iso(), receipt_id=f"r-{vid}"))
    members = [{"evidence_id": pid, "sha256": h, "size": len(back)}]
    await db.manifests.insert_one(base(f"m-{vid}", workspace_id=WS1, visit_id=vid, manifest_hash=sha256_hex(str(members).encode()), members=members,
                                       state="Received complete", receipt_id=f"r-{vid}", missing=[]))
    await db.receipts.insert_one(base(f"r-{vid}", workspace_id=WS1, visit_id=vid, manifest_id=f"m-{vid}", member_count=1, issued_at=iso(), issued_by="server"))
    await db.observations.insert_one(base(f"o-seed-ready-finding{sfx}", workspace_id=WS1, visit_id=vid, kind="finding", category="visible tie-surface deterioration",
                                          text="Confirmed: 8 ties with splitting/plate cutting on Spur 1 (human-reviewed)", evidence_id=pid,
                                          human_reviewed=True, quantity=None, specification=None, source_candidate_id=None))
    await db.engagements.update_one({"visit_id": vid}, {"$setOnInsert": base(f"eng-seed-ready{sfx}", workspace_id=WS1, visit_id=vid, site_id="s-cascade", customer_id="c-cascade",
                                    draft_id=f"draft-seed-ready{sfx}", status="Open", latest_version_id=None, accepted_version_id=None,
                                    changes_requested_version_ids=[], proposal_number=f"RR-READY1{sfx}")}, upsert=True)
    ws = await db.workspaces.find_one({"uuid": WS1})
    await upsert("estimate_drafts", base(f"draft-seed-ready{sfx}", workspace_id=WS1, engagement_id=f"eng-seed-ready{sfx}", visit_id=vid, lines=[], tax_rate=ws["tax_rate"],
                                         terms=dict(ws["default_terms"]), terms_reviewed=True, contractor_identity=ws["legal_identity"], selected_photo_ids=[pid],
                                         expiry_local="2026-12-15T17:00", agreement_preview=None, feedback_history=[]))
    await upsert("scope_items", base(f"scope-seed-ready{sfx}", workspace_id=WS1, visit_id=vid, engagement_id=f"eng-seed-ready{sfx}", kind="tie_replacement",
                                     location="Spur 1, gate to scale house", inspected_quantity=12, repair_quantity=8, unit="each", tie_type="crosstie",
                                     specification="Crosstie 7x9x8'6\" hardwood grade 5", material_responsibility="Contractor",
                                     access_disposition="Customer confirms track time; gate code at dispatch", reason=None, confirmed_by=E1))
