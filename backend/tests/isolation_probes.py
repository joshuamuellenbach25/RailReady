"""Cross-workspace isolation probes (Q-5): isolation foreman must get 404 on all Ridgeline IDs, with no writes."""
import os, requests, sys

BASE = os.environ.get("BACKEND_URL", "http://localhost:8001").rstrip("/") + "/api"

def login(email, pwd=os.environ["SEED_PASSWORD"]):
    r = requests.post(f"{BASE}/auth/login", json={"email": email, "password": pwd}, timeout=10)
    r.raise_for_status()
    return r.json()["token"]

def main():
    iso = login("foreman@isolation.example")
    rid = login("foreman@ridgeline.example")
    H = {"Authorization": f"Bearer {iso}"}
    HR = {"Authorization": f"Bearer {rid}"}

    probes = [
        ("GET",  f"{BASE}/visits/v-seed-pinecrest"),
        ("GET",  f"{BASE}/visits/v-seed-pinecrest/evidence"),
        ("GET",  f"{BASE}/visits/v-seed-pinecrest/readiness"),
        ("GET",  f"{BASE}/visits/v-seed-pinecrest/review"),
        ("GET",  f"{BASE}/visits/v-seed-cascade"),
        ("GET",  f"{BASE}/visits/v-seed-cascade/evidence"),
        ("GET",  f"{BASE}/evidence/n-seed-1"),
        ("GET",  f"{BASE}/evidence/n-seed-1/analysis"),
        ("GET",  f"{BASE}/evidence/n-seed-1/transcripts"),
        ("POST", f"{BASE}/jobs/n-seed-1/retry"),
    ]
    fails = 0
    for method, url in probes:
        r = requests.request(method, url, headers=H, timeout=10, json={} if method == "POST" else None)
        ok = r.status_code == 404
        print(f"{'PASS' if ok else 'FAIL'} iso {method} {url} -> {r.status_code}")
        if not ok: fails += 1

    # Confirm Ridgeline user still has access to its own data (no accidental deletion)
    r = requests.get(f"{BASE}/visits/v-seed-pinecrest", headers=HR, timeout=10)
    print(f"{'PASS' if r.status_code == 200 else 'FAIL'} ridgeline still sees v-seed-pinecrest -> {r.status_code}")
    if r.status_code != 200: fails += 1

    sys.exit(1 if fails else 0)

if __name__ == "__main__":
    main()
