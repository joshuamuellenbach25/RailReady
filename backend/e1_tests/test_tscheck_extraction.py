from conftest import new_visit, add_note, add_file, manifest, wait_jobs, field, ROOT

NOTE = "inspected twelve ties, replace eight, customer supplies ties"

def test_note_extraction_honest(fm):
    v = new_visit(fm, "extract")
    ev = add_note(fm, v["uuid"], NOTE)
    manifest(fm, v["uuid"], [ev]); wait_jobs(fm, v["uuid"])
    p = fm.get(f"/visits/{v['uuid']}/proposals").json()
    f = {x["field"]: x for x in p["fields"]}
    def val(k): return [x["value"] for x in f[k]["proposals"]]
    assert 12 in val("inspected_quantity") and 8 in val("repair_quantity") and "Customer" in val("material_responsibility"), f
    assert f["tie_specification"]["state"] == "Missing required" and not f["tie_specification"]["proposals"]
    for k in ("inspected_quantity", "repair_quantity", "material_responsibility"):
        for x in f[k]["proposals"]:
            assert x["excerpt"].lower() in NOTE.lower(), x["excerpt"]
    n = len(p["runs"])
    assert len(fm.get(f"/visits/{v['uuid']}/proposals").json()["runs"]) == n
    # discrepancy
    ev2 = add_note(fm, v["uuid"], "actually replace ten ties")
    manifest(fm, v["uuid"], [ev, ev2]); wait_jobs(fm, v["uuid"])
    r = field(fm, v["uuid"], "repair_quantity")
    assert r["discrepancy"] and {"8", "10"} <= set(r["distinct_values"]), r

def test_audio_transcription_correction(fm):
    v = new_visit(fm, "audio")
    ev = add_file(fm, v["uuid"], ROOT / "test_audio/short_note_dictation.mp3", "audio", "audio/mpeg")
    manifest(fm, v["uuid"], [ev]); wait_jobs(fm, v["uuid"], 200)
    ts = fm.get(f"/evidence/{ev['uuid']}/transcripts").json()
    assert ts and ts[0].get("model_id") and ts[0]["text"], ts
    r = fm.post(f"/evidence/{ev['uuid']}/transcripts", json={"text": "tscheck corrected", "base_version": ts[-1]["version"]})
    assert r.status_code == 200, r.text
    ts2 = fm.get(f"/evidence/{ev['uuid']}/transcripts").json()
    assert ts2[0]["text"] == ts[0]["text"] and ts2[0]["model_id"] and ts2[-1]["text"] == "tscheck corrected"
