from p2helpers import *


def test_package_from_repair_count_idempotent():
    c, D, e, s = ready(package=False)
    r = c.post(f"/scope-items/{s}/package"); assert r.status_code == 200
    lines = eng(c, e)["draft"]["lines"]
    mat = [l for l in lines if l["category"] == "material"]
    assert len(mat) == 1 and mat[0]["quantity"] == "8" and mat[0]["unit"] == "each"
    assert mat[0]["quantity_origin"] == "confirmed repair count"
    others = [l for l in lines if l["category"] != "material"]
    assert others and all("Needs review" in (l.get("assumption") or "") + (l.get("needs_review_reason") or "") for l in others if l["category"] in ("labor", "equipment"))
    n = len(lines)
    r2 = c.post(f"/scope-items/{s}/package"); assert r2.status_code == 200
    assert len(eng(c, e)["draft"]["lines"]) == n


def _scope(c, e, s):
    return next(x for x in eng(c, e)["scope_items"] if x["uuid"] == s)


def test_customer_supply_and_missing_spec():
    c, D, e, s = ready(package=False)
    sc = _scope(c, e, s)
    r = c.patch(f"/scope-items/{s}", json={"expected_revision": sc["revision"], "material_responsibility": "Customer"})
    assert r.status_code == 200, r.text[:300]
    pv = c.get(f"/scope-items/{s}/package-preview").json()
    assert not [l for l in pv["lines"] if l["category"] == "material"]
    assert [l for l in pv["lines"] if l["category"] == "labor"]
    c.post(f"/scope-items/{s}/package"); review_all(c, e)
    r = publish(c, e); assert r.status_code == 200, r.text[:300]
    assert r.json()["snapshot"]["ties_supplied_by_customer"] is True
    t = share(c, r.json()["uuid"])["token"]
    assert "Ties supplied by customer" in httpx.get(B + f"/public/proposals/{t}/print").text


def test_missing_spec_blocks():
    c, D, e, s = ready(package=False)
    sc = _scope(c, e, s)
    r = c.patch(f"/scope-items/{s}", json={"expected_revision": sc["revision"], "specification": ""})
    assert r.status_code == 200, r.text[:300]
    pv = c.get(f"/scope-items/{s}/package-preview").json()
    assert any("Specification missing" in b for b in pv["blockers"]), pv["blockers"]
    assert not [l for l in pv["lines"] if l["category"] == "material"]
