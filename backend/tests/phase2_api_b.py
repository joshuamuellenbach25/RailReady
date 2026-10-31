"""Phase 2 API journeys part 2: JRN-52 supersede, JRN-57 expiry (site-local), JRN-58 change topic, JRN-59 copy, JRN-62 races.
Creates its own fresh ready visits via the seed fixture (never touches v-seed-ready-demo)."""
import asyncio, os, sys, threading, time, uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import requests
sys.path.insert(0, "/app/backend")
os.chdir("/app/backend")
import seed
LOOP = asyncio.new_event_loop()

API = "http://localhost:8001/api"
s = requests.Session()
s.headers["Authorization"] = "Bearer " + s.post(f"{API}/auth/login", json={"email": "estimator@ridgeline.example", "password": os.environ["SEED_PASSWORD"]}).json()["token"]


def ok(c, m):
    print(("PASS " if c else "FAIL ") + m)


def fresh():
    sfx = "-t" + uuid.uuid4().hex[:6]
    LOOP.run_until_complete(seed.seed_ready_visit("v-seed-ready" + sfx, sfx))
    E = "eng-seed-ready" + sfx
    s.post(f"{API}/scope-items/scope-seed-ready{sfx}/package")
    for l in s.get(f"{API}/engagements/{E}").json()["draft"]["lines"]:
        s.patch(f"{API}/engagements/{E}/lines/{l['uuid']}", json={"expected_revision": s.get(f"{API}/engagements/{E}").json()["draft"]["revision"], "reviewed": True})
    return E


def publish(E, expiry_local=None):
    if expiry_local:
        s.patch(f"{API}/engagements/{E}/draft", json={"expected_revision": s.get(f"{API}/engagements/{E}").json()["draft"]["revision"], "expiry_local": expiry_local})
    s.get(f"{API}/engagements/{E}/agreement-preview")
    r = s.get(f"{API}/engagements/{E}").json()["draft"]["revision"]
    v = s.post(f"{API}/engagements/{E}/publish", json={"expected_revision": r, "idempotency_key": str(uuid.uuid4())}).json()
    return v, s.post(f"{API}/versions/{v['uuid']}/share").json()["token"]


acc = lambda tok: requests.post(f"{API}/public/proposals/{tok}/accept", json={"name": "Pat", "email": "pat@example.com", "agree": True})

# JRN-52 supersede
E = fresh()
v1, t1 = publish(E)
l0 = s.get(f"{API}/engagements/{E}").json()["draft"]["lines"][-1]
s.patch(f"{API}/engagements/{E}/lines/{l0['uuid']}", json={"expected_revision": s.get(f"{API}/engagements/{E}").json()["draft"]["revision"], "unit_cost": "1100"})
s.patch(f"{API}/engagements/{E}/lines/{l0['uuid']}", json={"expected_revision": s.get(f"{API}/engagements/{E}").json()["draft"]["revision"], "reviewed": True})
ok(requests.get(f"{API}/public/proposals/{t1}").json()["can_decide"], "JRN-52 v1 still actionable while draft edited")
v2, t2 = publish(E)
p1 = requests.get(f"{API}/public/proposals/{t1}").json()
ok(v2.get("version_no") == 2 and p1["status"] == "Superseded" and not p1["can_decide"] and acc(t1).status_code == 409, f"JRN-52 v2 published, v1 {p1['status']}")
# JRN-58/59 change request
r = requests.post(f"{API}/public/proposals/{t2}/changes", json={"name": "Pat", "email": "pat@example.com", "comment": "Can you lower the trip charge?"})
pub = requests.get(f"{API}/public/proposals/{t2}").json()
dec = [d for d in s.get(f"{API}/engagements/{E}").json()["decisions"] if d["type"] == "changes"][0]
ok(r.status_code == 200 and not pub["can_decide"] and "topic" not in str(pub) and dec["topic_suggestion"].get("topic") == "price", f"JRN-58 topic suggestion {dec['topic_suggestion']}")
ok(acc(t2).status_code == 409, "JRN-58 acceptance disabled after change request")
c = s.post(f"{API}/versions/{v2['uuid']}/copy-to-draft").json()
ok(any(f.get("comment") == "Can you lower the trip charge?" for f in c["feedback_history"]), "JRN-59 feedback preserved in draft")

# JRN-57 expiry 1 minute from now, site-local (America/Los_Angeles)
E = fresh()
tz = ZoneInfo("America/Los_Angeles")
local = (datetime.now(tz) + timedelta(minutes=1)).replace(second=0, microsecond=0) + timedelta(minutes=1)
v, t = publish(E, local.strftime("%Y-%m-%dT%H:%M"))
exp_utc = local.astimezone(ZoneInfo("UTC")).isoformat()
ok(v.get("expiry_utc") == exp_utc, f"JRN-57 local {local.strftime('%Y-%m-%dT%H:%M')} PT -> UTC {v.get('expiry_utc')}")
wait = (local - datetime.now(tz)).total_seconds() + 2
time.sleep(max(0, wait))
r = acc(t)
ok(r.status_code == 409 and "expired" in r.text.lower(), f"JRN-57 after expiry: {r.json()['detail']}")

# JRN-62 races: accept vs revoke / vs new publish / vs change request
for race in ["revoke", "publish", "changes"]:
    E = fresh()
    v, t = publish(E)
    out = {}
    def a():
        out["accept"] = acc(t).status_code
    def b():
        if race == "revoke":
            lid = s.get(f"{API}/engagements/{E}").json()["versions"][0]["links"][0]["uuid"]
            out["other"] = s.post(f"{API}/links/{lid}/revoke").status_code
        elif race == "publish":
            out["other"] = s.post(f"{API}/engagements/{E}/publish", json={"expected_revision": s.get(f"{API}/engagements/{E}").json()["draft"]["revision"], "idempotency_key": "r2"}).status_code
        else:
            out["other"] = requests.post(f"{API}/public/proposals/{t}/changes", json={"name": "P", "email": "p@example.com", "comment": "change"}).status_code
    th = [threading.Thread(target=a), threading.Thread(target=b)]
    [x.start() for x in th]; [x.join() for x in th]
    eng = s.get(f"{API}/engagements/{E}").json()
    nwo = len([w for w in s.get(f"{API}/work-orders").json() if w["engagement_id"] == E])
    consistent = (nwo == 1 and eng["engagement"]["accepted_version_id"] == v["uuid"]) or (nwo == 0 and not eng["engagement"]["accepted_version_id"])
    ok(consistent and nwo <= 1, f"JRN-62 accept vs {race}: {out} -> work orders {nwo}")
