"""Q-11: 20 random manual lines vs formula on a FRESH fixture engagement (eng-seed-ready-mt)."""
import os, requests, random
from decimal import Decimal, ROUND_HALF_UP

API = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "http://localhost:8001").rstrip("/") + "/api"

def login(email, pw=os.environ["SEED_PASSWORD"]):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pw}).json()
    s = requests.Session(); s.headers["Authorization"] = f"Bearer {r['token']}"; return s

est = login("estimator@ridgeline.example")
E = "eng-seed-ready-mt"

def rhu(x):
    return Decimal(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

random.seed(42)
tax_pct = Decimal("8.25")
# set tax rate (if endpoint exists via engagement patch); otherwise rely on default. Just use engagement current state.
pr = est.get(f"{API}/engagements/{E}").json()
tax_rate = pr["draft"].get("tax_rate", "0")
print("rev", pr["draft"]["revision"], "lines", len(pr["draft"].get("lines", [])), "tax_rate", tax_rate)

errors = 0
for i in range(20):
    q = Decimal(str(round(random.uniform(0.1, 50), 3)))
    c = Decimal(str(round(random.uniform(0.01, 500), 4)))
    m = Decimal(str(round(random.uniform(0, 80), 2)))
    taxable = random.choice([True, False])
    exp_internal = rhu(q * c)
    exp_line = rhu(q * c * (Decimal(1) + m / Decimal(100)))
    r = est.get(f"{API}/engagements/{E}").json()
    rev = r["draft"]["revision"]
    payload = {"expected_revision": rev, "category": "other", "description": f"rand-{i}",
               "quantity": str(q), "unit": "ea", "unit_cost": str(c), "markup_pct": str(m),
               "taxable": taxable, "reason": "test"}
    rr = est.post(f"{API}/engagements/{E}/lines", json=payload)
    if rr.status_code != 200:
        print("FAIL add", i, rr.status_code, rr.text[:200]); errors += 1; continue
    j = rr.json()
    got_int = Decimal(j["line"]["internal_cost"]); got_line = Decimal(j["line"]["line_total"])
    if got_int != exp_internal or got_line != exp_line:
        print(f"FAIL row {i} q={q} c={c} m={m} exp_int={exp_internal} got={got_int} exp_line={exp_line} got={got_line}")
        errors += 1

# Final totals vs sum
pr = est.get(f"{API}/engagements/{E}").json()
lines = pr["draft"]["lines"]
sum_taxable = sum((Decimal(l["line_total"]) for l in lines if l.get("taxable")), Decimal(0))
exp_tax = rhu(sum_taxable * (Decimal(tax_rate) / Decimal(100)))
got_tax = Decimal(pr["totals"]["tax"])
print(f"tax_rate={tax_rate} sum_taxable={sum_taxable} exp_tax={exp_tax} got_tax={got_tax}")
if exp_tax != got_tax:
    print("FAIL tax mismatch"); errors += 1

print(f"\nQ-11 result: {errors} errors over 20 lines")
