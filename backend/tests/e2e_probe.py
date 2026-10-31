"""E2E API probe: foreman creates a visit, uploads files, verifies, finalizes manifest, waits for processing.
Usage: python e2e_probe.py photo1.jpg [audio.ogg ...]"""
import hashlib, json, mimetypes, os, sys, time, uuid
import requests

API = os.environ.get("API", "http://localhost:8001/api")
s = requests.Session()
tok = s.post(f"{API}/auth/login", json={"email": "foreman@ridgeline.example", "password": os.environ["SEED_PASSWORD"]}).json()["token"]
s.headers["Authorization"] = f"Bearer {tok}"
vid = str(uuid.uuid4())
print("visit", s.post(f"{API}/visits", json={"uuid": vid, "site_id": "s-cascade", "title": "probe " + time.strftime("%H:%M"),
                                              "processing_permission": "Granted"}).status_code, vid)
members, ids = [], {}
for p in sys.argv[1:]:
    data = open(p, "rb").read()
    h = hashlib.sha256(data).hexdigest()
    kind = "photo" if p.lower().endswith((".jpg", ".jpeg", ".png")) else "audio"
    eid = str(uuid.uuid4())
    mime = mimetypes.guess_type(p)[0] or "application/octet-stream"
    s.post(f"{API}/visits/{vid}/evidence", json={"uuid": eid, "kind": kind, "sha256": h, "size": len(data), "mime": mime, "filename": os.path.basename(p)}).raise_for_status()
    r = s.put(f"{API}/evidence/{eid}/content", files={"file": (os.path.basename(p), data, mime)}); r.raise_for_status()
    st = s.post(f"{API}/evidence/{eid}/verify").json()["upload_state"]
    print(os.path.basename(p), kind, st)
    members.append({"evidence_id": eid, "sha256": h, "size": len(data)}); ids[eid] = (p, kind)
m = s.post(f"{API}/visits/{vid}/manifests", json={"members": members}).json()
m2 = s.post(f"{API}/visits/{vid}/manifests", json={"members": members}).json()
print("manifest", m["state"], m["receipt_id"], "retry same receipt:", m["receipt_id"] == m2["receipt_id"] and m["uuid"] == m2["uuid"])
t0 = time.time()
pending = set(ids)
while pending and time.time() - t0 < 400:
    time.sleep(3)
    pr = s.get(f"{API}/visits/{vid}/processing").json()["by_evidence"]
    for eid in list(pending):
        p, kind = ids[eid]
        stages = pr.get(eid, {})
        main = stages.get("image_analysis" if kind == "photo" else "transcription")
        if main and main["status"] in ("Done", "Failed") and (kind == "photo" or stages.get("extraction", {}).get("status") in ("Done", "Failed")):
            pending.discard(eid)
            print(f"\n=== {os.path.basename(p)} done in {time.time()-t0:.0f}s: {json.dumps({k: (v['status'], v['error']) for k, v in stages.items()})}")
            if kind == "photo":
                a = s.get(f"{API}/evidence/{eid}/analysis").json()
                run = a["runs"][-1]
                print("outcome:", a["outcome_label"], "| model:", run["model_id"], run["prompt_version"], "| dur", run["duration_s"], "attempts", run["attempts"])
                print("assessability:", run["image_assessability"], run.get("cannot_assess_reason"), "| rejected:", run["rejected_candidates"])
                for c in a["candidates"]:
                    print(" -", c["category"], c["region"], c["assessability"], "|", c["visible_reason"][:160], "| unc:", c["uncertainty"][:120])
            else:
                t = s.get(f"{API}/evidence/{eid}/transcripts").json()
                print("transcript:", t[-1]["model_id"], t[-1]["audio_duration_s"], "s audio,", t[-1]["processing_s"], "s proc:", t[-1]["text"][:300])
print("readiness:", json.dumps(s.get(f"{API}/visits/{vid}/readiness").json()["counts"]))
print("VISIT", vid)
