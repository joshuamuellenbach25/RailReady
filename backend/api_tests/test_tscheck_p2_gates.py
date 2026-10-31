from p2helpers import *
import datetime


def test_supplier_change_marks_needs_review_keeps_edits():
    c, D, e, s = ready()
    g = eng(c, e)
    lab = next(l for l in g["draft"]["lines"] if l["category"] == "labor")
    r = c.patch(f"/engagements/{e}/lines/{lab['uuid']}", json={"expected_revision": rev(c, e), "description": "tscheck edited labor", "reviewed": True})
    assert r.status_code == 200, r.text[:300]
    sc = next(x for x in eng(c, e)["scope_items"] if x["uuid"] == s)
    r = c.patch(f"/scope-items/{s}", json={"expected_revision": sc["revision"], "material_responsibility": "Customer"})
    assert r.status_code == 200
    lines = eng(c, e)["draft"]["lines"]
    l2 = next(l for l in lines if l["uuid"] == lab["uuid"])
    assert l2["description"] == "tscheck edited labor" and l2["reviewed"] is False
    assert "changed" in l2["needs_review_reason"]
    v = c.post(f"/engagements/{e}/validate").json()
    assert not v["ok"] and any("Unreviewed" in b or "review" in b.lower() for b in v["blockers"]), v


def _line(c, e, **kw):
    b = dict(expected_revision=rev(c, e), category="general_repair", description="tscheck", quantity="1", unit="hour",
             unit_cost="50", markup_pct="0", taxable=False, reason="tscheck")
    b.update(kw)
    return c.post(f"/engagements/{e}/lines", json=b)


def test_duplicate_mobilization_and_labor_only():
    c, D, e, s = ready()
    r = _line(c, e, category="mobilization", description="tscheck mob2", unit="trip")
    assert r.status_code == 422 and r.json()["detail"]["code"] == "duplicate_mobilization"
    assert _line(c, e, category="mobilization", description="tscheck mob2", unit="trip", duplicate_reason="second spur").status_code == 200
    assert any(w["code"] == "duplicate_mobilization" for w in eng(c, e)["warnings"])
    assert _line(c, e, description="tscheck labor-only", material_dependent=False).status_code == 200
    assert _line(c, e, description="tscheck matdep", material_dependent=True).status_code == 200
    review_all(c, e)
    bl = c.post(f"/engagements/{e}/validate").json()["blockers"]
    assert any("tscheck matdep" in b for b in bl) and not any("tscheck labor-only" in b for b in bl), bl


def test_not_applicable_cannot_clear_missing_spec():
    c, D, e, s = ready()
    vid = D["jobs"]["ready_to_estimate"]["visit_id"]
    sc = next(x for x in eng(c, e)["scope_items"] if x["uuid"] == s)
    c.patch(f"/scope-items/{s}", json={"expected_revision": sc["revision"], "specification": ""})
    v = c.get(f"/visits/{vid}").json()
    c.post(f"/visits/{vid}/fields/tie_specification", json={"expected_revision": v["revision"], "action": "not_applicable", "reason": "tscheck"})
    review_all(c, e)
    bl = c.post(f"/engagements/{e}/validate").json()["blockers"]
    assert any("Specification missing" in b for b in bl), bl


def test_discrepancy_unreviewed_nophoto_expired_blockers():
    c, D = demo()
    vid = D["jobs"]["blocked_customer_supplied_8_vs_10"]["visit_id"]
    r = c.post(f"/visits/{vid}/engagement"); assert r.status_code == 200, r.text[:300]
    e = r.json()["engagement_id"]
    bl = c.post(f"/engagements/{e}/validate").json()["blockers"]
    assert any("Unresolved discrepancy: repair quantity" in b for b in bl), bl
    c2, D2, e2, s2 = ready(package=False)
    c2.post(f"/scope-items/{s2}/package")
    r = c2.patch(f"/engagements/{e2}/draft", json={"expected_revision": rev(c2, e2), "selected_photo_ids": [], "expiry_local": "2020-01-01T09:00"})
    assert r.status_code == 200, r.text[:300]
    bl = " | ".join(c2.post(f"/engagements/{e2}/validate").json()["blockers"])
    assert "Unreviewed line" in bl and "photo" in bl.lower() and "expir" in bl.lower(), bl
    assert publish(c2, e2).status_code in (409, 422)


def test_further_assessment_no_charges():
    c, D, e, s = ready()
    r = c.post(f"/engagements/{e}/scope-items", json={"kind": "further_assessment", "location": "tscheck switch 3", "reason": "Needs engineer review"})
    assert r.status_code == 200, r.text[:300]
    pv = c.get(f"/scope-items/{r.json()['uuid']}/package-preview").json()
    assert pv["lines"] == []
    r = publish(c, e); assert r.status_code == 200, r.text[:300]
    f = " ".join(r.json()["snapshot"]["findings"])
    assert "Further assessment" in f and "no quantities or charges" in f
