from p2helpers import *


def line(c, e, **kw):
    body = dict(expected_revision=rev(c, e), category="labor", description="tscheck-money", quantity="1", unit="each",
                unit_cost="1", markup_pct="0", taxable=True, reason="tscheck")
    body.update(kw)
    return c.post(f"/engagements/{e}/lines", json=body)


def set_tax(c, e, rate):
    r = c.patch(f"/engagements/{e}/draft", json={"expected_revision": rev(c, e), "tax_rate": rate})
    assert r.status_code == 200, r.text[:300]


def test_exact_money():
    c, D = demo(); e = D["jobs"]["empty_draft"]["visit_id"]
    e = D["jobs"]["ready_to_estimate"]["engagement_id"]
    set_tax(c, e, "7.5")
    r = line(c, e, quantity="3", unit_cost="0.335", markup_pct="25")
    assert r.status_code == 200, r.text[:300]
    g = eng(c, e); l = g["draft"]["lines"][-1]; t = g["totals"]
    assert (l["internal_cost"], l["line_total"]) == ("1.01", "1.26"), l
    assert (t["tax"], t["total"]) == ("0.09", "1.35"), t


def test_two_nickels():
    c, D = demo(); e = D["jobs"]["ready_to_estimate"]["engagement_id"]
    set_tax(c, e, "5")
    for _ in range(2):
        assert line(c, e, quantity="1", unit_cost="0.05").status_code == 200
    t = eng(c, e)["totals"]
    assert (t["subtotal"], t["tax"], t["total"]) == ("0.10", "0.01", "0.11"), t


def test_invalid_inputs_rejected_and_client_total_ignored():
    c, D = demo(); e = D["jobs"]["ready_to_estimate"]["engagement_id"]
    for bad in [dict(quantity="0"), dict(quantity="-1"), dict(unit_cost="-5"), dict(markup_pct="NaN"), dict(unit_cost="1.12345")]:
        r = line(c, e, **bad)
        assert r.status_code in (400, 422), (bad, r.status_code, r.text[:200])
    assert eng(c, e)["draft"]["lines"] == []
    r = line(c, e, quantity="2", unit_cost="10", total="999")
    assert r.status_code in (200, 422)
    assert eng(c, e)["totals"]["total"] != "999.00"


def test_zero_subtotal_margin_na_and_tax_text():
    c, D = demo(); e = D["jobs"]["ready_to_estimate"]["engagement_id"]
    g = eng(c, e)
    assert g["totals"]["margin_pct"] == "N/A"
    assert "0%" in g["tax_treatment_text"] and "Taxes not included" not in g["tax_treatment_text"]
