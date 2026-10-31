from p2helpers import *


def test_agreement_preview_and_issue_blocks():
    c, D, e, s = ready()
    a = c.get(f"/engagements/{e}/agreement-preview").json()
    assert a["label"] == "Illustrative sample – not contractor-approved terms"
    assert all(str(v).strip() for v in a["variables"].values()), a["variables"]
    # stale price after preview
    l = eng(c, e)["draft"]["lines"][0]
    c.patch(f"/engagements/{e}/lines/{l['uuid']}", json={"expected_revision": rev(c, e), "unit_cost": "70.00", "reviewed": True})
    bl = " | ".join(c.post(f"/engagements/{e}/validate").json()["blockers"])
    assert "Stale price" in bl or "not previewed" in bl.lower(), bl
    # unreviewed term edit
    terms = dict(eng(c, e)["draft"]["terms"]); terms["payment_terms"] = "tscheck Net 10"
    assert c.patch(f"/engagements/{e}/draft", json={"expected_revision": rev(c, e), "terms": terms}).status_code == 200
    c.get(f"/engagements/{e}/agreement-preview")
    bl = " | ".join(c.post(f"/engagements/{e}/validate").json()["blockers"])
    assert "Unreviewed term edit" in bl, bl
    # missing variable
    c.patch(f"/engagements/{e}/draft", json={"expected_revision": rev(c, e), "contractor_identity": "", "terms_reviewed": True})
    c.get(f"/engagements/{e}/agreement-preview")
    bl = " | ".join(c.post(f"/engagements/{e}/validate").json()["blockers"])
    assert "contractor" in bl.lower(), bl
    assert publish(c, e).status_code in (409, 422)


def test_publish_idempotent_immutable_supersede():
    c, D, e, s = ready()
    r1 = publish(c, e, "tscheck-k1"); assert r1.status_code == 200, r1.text[:300]
    v1 = r1.json()
    assert v1["version_no"] == 1 and len(v1["snapshot_hash"]) == 64 and len(v1["document_hash"]) == 64
    assert any(x.get("status") == "Issued" for x in c.get("/contracts").json()["contracts"] if x["version_id"] == v1["uuid"])
    # same key retry
    r = c.post(f"/engagements/{e}/publish", json={"expected_revision": v1["draft_revision"], "idempotency_key": "tscheck-k1"})
    assert r.status_code == 200 and r.json()["uuid"] == v1["uuid"], r.text[:200]
    p1 = c.get(f"/proposals/{v1['uuid']}/print").text
    # edit draft after publish
    l = eng(c, e)["draft"]["lines"][0]
    assert c.patch(f"/engagements/{e}/lines/{l['uuid']}", json={"expected_revision": rev(c, e), "unit_cost": "99.00", "reviewed": True}).status_code == 200
    v1b = c.get(f"/versions/{v1['uuid']}").json()
    v1b = v1b.get("version", v1b)
    assert v1b["snapshot_hash"] == v1["snapshot_hash"] and v1b["snapshot"]["totals"] == v1["snapshot"]["totals"]
    assert c.get(f"/proposals/{v1['uuid']}/print").text == p1
    t = share(c, v1["uuid"])["token"]
    assert httpx.get(B + f"/public/proposals/{t}").json()["can_decide"] is True
    r2 = publish(c, e, "tscheck-k2"); assert r2.status_code == 200, r2.text[:300]
    assert r2.json()["version_no"] == 2
    v1c = c.get(f"/versions/{v1['uuid']}").json(); v1c = v1c.get("version", v1c)
    assert v1c["status"] == "Superseded"
    pub = httpx.get(B + f"/public/proposals/{t}").json()
    assert pub["can_decide"] is False
    a = httpx.post(B + f"/public/proposals/{t}/accept", json={"name": "tscheck", "email": "t@example.com", "agree": True})
    assert a.status_code >= 400
