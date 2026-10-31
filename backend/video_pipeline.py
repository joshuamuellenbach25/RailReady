"""Phase 12 video: validation (PyAV/libav probe - the ffprobe binary is not installed in this environment), frame
extraction with original timestamps, sharp + distinct frame selection (max 6 per video, each counted against the
global image-call budget), per-frame provenance, nearby-duplicate merging into one finding listing its frames."""
import asyncio
import hashlib
import io
import logging

import numpy as np

import ai_image
import calibration
import storage
from core import db, iso, new_id

log = logging.getLogger("video")
MAX_SECONDS, MAX_BYTES, MAX_FRAMES = 60.0, 200 * 1024 * 1024, 4  # 4 frames x 2 schemas = at most 8 primary sends per video
SCHEMAS = ("tie_fastener", "rail_surface")
VIDEO_DEADLINE_S = 900  # stop sending after this; remaining frames are recorded as not checked (partial, retryable)
SAMPLE_EVERY_S, MERGE_WINDOW_S = 0.5, 3.0
PIPELINE = "video_v1"
SUPPORTED_MIMES = {"video/mp4", "video/quicktime", "video/x-m4v", "video/3gpp"}


def probe(data: bytes) -> dict:
    """Returns {ok, reason, duration_s, width, height, codec, container}. Never truncates or modifies the original."""
    import av
    try:
        with av.open(io.BytesIO(data)) as c:
            vs = next((s for s in c.streams if s.type == "video"), None)
            if vs is None:
                return {"ok": False, "reason": "This file has no video track."}
            dur = float(c.duration / 1_000_000) if c.duration else (float(vs.duration * vs.time_base) if vs.duration else None)
            info = {"duration_s": dur, "width": vs.codec_context.width, "height": vs.codec_context.height,
                    "codec": vs.codec_context.name, "container": c.format.name}
    except Exception as e:
        return {"ok": False, "reason": "This video cannot be read. Record it again or choose another file.", "error": type(e).__name__}
    if info["duration_s"] is None:
        return {"ok": False, "reason": "The video length cannot be read.", **info}
    if info["duration_s"] > MAX_SECONDS + 0.5:
        return {"ok": False, "reason": f"Video is {round(info['duration_s'])} s long. The limit is {int(MAX_SECONDS)} s. The original is kept on your phone.", **info}
    return {"ok": True, "reason": None, **info}


def _gray(img) -> np.ndarray:
    return np.asarray(img.convert("L").resize((320, 180)), dtype=np.float32)


def sharpness(g: np.ndarray) -> float:
    lap = -4 * g[1:-1, 1:-1] + g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:]
    return float(lap.var())


def dhash(g: np.ndarray) -> int:
    from PIL import Image
    s = np.asarray(Image.fromarray(g.astype(np.uint8)).resize((9, 8)), dtype=np.int16)
    bits = (s[:, 1:] > s[:, :-1]).ravel()
    return int("".join("1" if b else "0" for b in bits), 2)


def select_frames(data: bytes) -> list[dict]:
    """Decode a frame every SAMPLE_EVERY_S (original pts timestamps), keep the sharpest distinct ones (<= MAX_FRAMES)."""
    import av
    cands, next_t, n = [], 0.0, -1
    with av.open(io.BytesIO(data)) as c:
        vs = c.streams.video[0]
        for fr in c.decode(vs):
            n += 1  # decode-order frame number (PyAV 18 frames have no .index)
            if fr.pts is None:
                continue
            t = float(fr.pts * vs.time_base)
            if t + 1e-6 < next_t:
                continue
            next_t = t + SAMPLE_EVERY_S
            img = fr.to_image()
            g = _gray(img)
            cands.append({"t": round(t, 3), "frame_index": n, "sharp": sharpness(g), "hash": dhash(g), "img": img})
    chosen = []
    for f in sorted(cands, key=lambda x: -x["sharp"]):
        if all(bin(f["hash"] ^ o["hash"]).count("1") > 10 and abs(f["t"] - o["t"]) >= 1.0 for o in chosen):
            chosen.append(f)
        if len(chosen) >= MAX_FRAMES:
            break
    return sorted(chosen, key=lambda x: x["t"])


def _iou(a, b):
    if not (isinstance(a, list) and isinstance(b, list)):
        return 1.0 if a == b else 0.0
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix, iy = max(0, min(ax + aw, bx + bw) - max(ax, bx)), max(0, min(ay + ah, by + bh) - max(ay, by))
    inter = ix * iy
    return inter / (aw * ah + bw * bh - inter) if inter else 0.0


def _qbox(r) -> str:
    """Quantized normalized box (0.02 steps) or 'image' for whole-frame findings."""
    if isinstance(r, list) and len(r) == 4:
        return ",".join(f"{round(v / 0.02) * 0.02:.2f}" for v in r)
    return "image"


def finding_id(evidence_id: str, schema: str, frame_sha: str, category: str, region, idx: int) -> str:
    """Stable across retries/recovery/worker restarts: no run id, no clock. Includes the frame, the schema and a
    quantized box, plus the region index after a deterministic sort (two identical quantized boxes stay distinct)."""
    key = f"{evidence_id}|{schema}|{frame_sha}|{category}|{_qbox(region)}|{idx}"
    return "vf-" + hashlib.sha256(key.encode()).hexdigest()[:32]


def merge(dets: list[dict]) -> list[dict]:
    """Merge ONLY the same finding: same schema, same category, IoU >= 0.3 (or both whole-frame), within MERGE_WINDOW_S.
    Spatially distinct findings stay separate. Deterministic order so ids are reproducible."""
    out = []
    for d in sorted(dets, key=lambda x: (x["frame"]["t"], x["schema"], x["category"], _qbox(x.get("region")))):
        m = next((o for o in out if o["schema"] == d["schema"] and o["category"] == d["category"]
                  and d["frame"]["t"] - o["frames"][-1]["t"] <= MERGE_WINDOW_S and d["frame"]["t"] != o["frames"][-1]["t"]
                  and _iou(o.get("region"), d.get("region")) >= 0.3), None)
        if m:
            m["frames"].append({**d["frame"], "region": d.get("region")})
        else:
            out.append({**d, "frames": [{**d["frame"], "region": d.get("region")}]})
    seen: dict = {}
    for f in out:  # region index after deterministic sort, per (schema, frame, category, quantized box)
        k = (f["schema"], f["frames"][0]["sha256"], f["category"], _qbox(f.get("region")))
        f["region_index"] = seen.get(k, 0)
        seen[k] = f["region_index"] + 1
    return out


VERSION_KEY = hashlib.sha256(f"{PIPELINE}|{ai_image.PROMPT_VERSION}|rs|cap{MAX_FRAMES}|every{SAMPLE_EVERY_S}".encode()).hexdigest()[:10]
CONFIG = {"frame_cap": MAX_FRAMES, "schemas": list(SCHEMAS), "sample_every_s": SAMPLE_EVERY_S, "merge_window_s": MERGE_WINDOW_S,
          "merge_iou": 0.3, "box_quantum": 0.02, "video_deadline_s": VIDEO_DEADLINE_S, "max_primary_sends": MAX_FRAMES * len(SCHEMAS)}
OK_FRAME = ("Done",)


def _run_status(results: list, budget_hit: bool, n_frames: int) -> str:
    if budget_hit:
        return "budget_limited"
    if not n_frames:
        return "failed"  # unreadable video: visible failure, never empty success
    ok = sum(1 for r in results if r["status"] in OK_FRAME)
    bad = len(results) - ok + max(0, n_frames - len(results))
    if not ok:
        return "failed"
    return "partial" if bad or any(r.get("rejected") or r.get("cannot_assess") or r.get("assessment_status") == "partial" for r in results) else "complete"


async def run_video(job, visit, finish, holds_lease):
    """Phase 12 video: tie/fastener (video_v1) AND rail surface (rail_surface_v1) on the same selected frames.
    Deterministic run ids + per-frame cached results: a retry / recovery / worker restart re-sends only frames that were
    never answered, and creates no new finding records (stable finding ids)."""
    import photo_pipeline as PP
    import rail_surface as RS
    ev = await db.evidence.find_one({"uuid": job["target_id"]})
    data = await asyncio.to_thread(storage.get_object, ev["storage_path"])
    if hashlib.sha256(data).hexdigest() != ev["sha256"]:
        return await finish(job, "Failed", "Stored video does not match its recorded hash", "source")
    ident = {"tie_fastener": {"model_id": ai_image.PROVIDER.model_id, "prompt_version": ai_image.PROMPT_VERSION, "schema_id": "tie-fastener", "schema_version": ai_image.PROMPT_VERSION},
             "rail_surface": {"model_id": PP.MODEL_ID, "prompt_version": RS.PROMPT_VERSION, "schema_id": RS.SCHEMA_ID, "schema_version": RS.SCHEMA_VERSION}}
    versions = {s: hashlib.sha256(f"{VERSION_KEY}|{s}|{i['model_id']}|{i['prompt_version']}|{i['schema_version']}|{PP.RSV.VERSION if s == 'rail_surface' else ''}".encode()).hexdigest()[:10]
                for s, i in ident.items()}
    rid = {"tie_fastener": f"vrun-{ev['uuid']}-tf-{versions['tie_fastener']}", "rail_surface": f"vrun-{ev['uuid']}-rs-{versions['rail_surface']}"}
    # Reuse matching pre-detail tie checks without paying for them again. Rail results
    # have their own versioned identity; old completed results are never relabelled.
    legacy_tie = await db.image_analysis_runs.find_one({"uuid": f"vrun-{ev['uuid']}-tf-{VERSION_KEY}",
        "photo_sha256": ev["sha256"], "model_id": ai_image.PROVIDER.model_id, "prompt_version": ai_image.PROMPT_VERSION})
    if legacy_tie:
        rid["tie_fastener"] = legacy_tie["uuid"]
    pipes = {"tie_fastener": PIPELINE, "rail_surface": RS.PIPELINE}
    done = {s: await db.image_analysis_runs.find_one({"uuid": rid[s], "status": "complete"}) for s in SCHEMAS}
    if all(done.values()):
        return await finish(job, "Done", run_id=rid["tie_fastener"])  # replay, zero sends
    base = {"workspace_id": ev["workspace_id"], "visit_id": ev["visit_id"], "evidence_id": ev["uuid"], "photo_sha256": ev["sha256"],
            "video_sha256": ev["sha256"], "source_kind": "video_frames", "config": CONFIG,
            "frame_cap": MAX_FRAMES, "created_at": iso(), "created_by": "system"}
    for s in SCHEMAS:
        if done[s]:
            continue
        await db.image_analysis_runs.update_one({"uuid": rid[s]}, {"$setOnInsert": {"uuid": rid[s], "pipeline": pipes[s], "version_key": versions[s], **ident[s], **base,
                                                "frame_results": {}, "raw_responses": []},
                                                "$set": {"status": "checking", "job_id": job["uuid"], "updated_at": iso()}}, upsert=True)
    runs = {s: await db.image_analysis_runs.find_one({"uuid": rid[s]}) for s in SCHEMAS}
    rs_run = PP.Run(runs["rail_surface"])
    try:
        frames = await asyncio.to_thread(select_frames, data)
    except Exception as e:
        frames = []
        log.warning("video %s: frames unreadable: %s", ev["uuid"], e)
    t0, budget_hit, fr_docs, dets = asyncio.get_running_loop().time(), False, [], []
    results = {s: [] for s in SCHEMAS}
    for f in frames:
        buf = io.BytesIO()
        img = f["img"].convert("RGB")
        img.save(buf, "JPEG", quality=90)
        b = buf.getvalue()
        fsha = hashlib.sha256(b).hexdigest()
        path = f"{ev['storage_path']}.frames/{fsha[:24]}.jpg"
        await asyncio.to_thread(storage.put_object, path, b, "image/jpeg")
        frame = {"id": f"frame-{fsha[:16]}", "sha256": fsha, "t": f["t"], "frame_index": f["frame_index"], "storage_path": path,
                 "width": img.width, "height": img.height}
        fr_docs.append({**frame, "sharpness": round(f["sharp"], 2),
                        "provenance": {"video_evidence_id": ev["uuid"], "video_sha256": ev["sha256"], "timestamp_s": f["t"], "method": "pyav-decode+jpeg-q90"}})
        for s in SCHEMAS:
            key = fsha
            r = (runs[s].get("frame_results") or {}).get(key)
            if done[s] and not r:
                # A historical completed record without frame details is preserved,
                # never silently re-inferred or rewritten under a new analysis version.
                r = {"status": "not_checked", "error": "Historical frame details unavailable"}
            if not (r and r["status"] in OK_FRAME + ("rejected",)):  # cached answers are never re-sent (no double pay)
                if done[s]:
                    results[s].append(r)
                    continue
                if asyncio.get_running_loop().time() - t0 > VIDEO_DEADLINE_S:
                    r = {"status": "not_checked", "error": "deadline"}
                elif not await holds_lease(job):
                    return  # fenced: a stale worker stops sending and commits nothing
                elif s == "tie_fastener":
                    res = await ai_image.analyze(b, f"vid-{ev['uuid']}-{fsha[:12]}", reserve=lambda: calibration.reserve_call(1))
                    if res.get("error_stage") == "budget":
                        budget_hit = True
                        break
                    r = ({"status": "Done", "candidates": res.get("candidates") or [], "raw_responses": res.get("raw_responses")}
                         if res["status"] == "Done" else {"status": "failed", "error": res.get("error"), "raw_responses": res.get("raw_responses")})
                else:
                    try:
                        acc, rej = await PP.assess_rail_surface(rs_run, img, purpose=f"rail_surface:{fsha[:12]}")
                        assessment_status, assessment_label = RS.outcome(acc, rej)
                        r = {"status": "rejected" if rej and not acc else "Done", "accepted": acc, "rejected": rej,
                             "assessment_status": assessment_status, "outcome_label": assessment_label,
                             "cannot_assess": any(a["choice"] == "not_assessable" for a in acc),
                             "rail_surface_input": rs_run.doc.get("rail_surface_input")}
                    except PP.BudgetReached:
                        budget_hit = True
                        break
                    except Exception as e:  # unparseable / provider failure: visible, never empty success
                        r = {"status": "failed", "error": f"{type(e).__name__}: {e}"[:300]}
                r = {**r, "t": f["t"], "frame_id": frame["id"]}
                if r["status"] != "not_checked":
                    await db.image_analysis_runs.update_one({"uuid": rid[s]}, {"$set": {f"frame_results.{key}": r, "updated_at": iso()}})
                    runs[s].setdefault("frame_results", {})[key] = r
            results[s].append(r)
            if s == "tie_fastener" and r["status"] == "Done":
                for c in r.get("candidates") or []:
                    reg = c.get("region") if isinstance(c.get("region"), list) else None
                    dets.append({"schema": s, "pipeline": PIPELINE, "category": c["category"], "condition_kind": "possible_defect", "region": reg,
                                 "visible_reason": c.get("visible_reason"), "uncertainty": c.get("uncertainty"), "alternatives": c.get("alternatives") or [],
                                 "assessability": c.get("assessability"), "frame": frame})
            if s == "rail_surface" and r["status"] == "Done":
                for a in r.get("accepted") or []:
                    if a["choice"] in RS.CLASSES:  # not_assessable / no_visible_surface_fault are outcomes, not review items
                        dets.append({"schema": s, "pipeline": RS.PIPELINE, "category": a["choice"], "condition_kind": a["condition_kind"],
                                     "region": a["bbox"], "rail_surface": a, "visible_reason": a.get("evidence"), "uncertainty": a.get("limitations"),
                                     "alternatives": [c for c, _ in a["top_alternatives"]], "frame": {**frame, "source_view": a.get("source_view")}})
        if budget_hit:
            break
    if not await holds_lease(job):  # C6 fence before any finding/result commit
        return
    findings = merge(dets)
    for c in findings:
        f0 = c["frames"][0]
        s = c["schema"]
        if done[s]:
            continue
        finding_schema = s if s == "tie_fastener" and legacy_tie else f"{s}:{versions[s]}"
        cid = finding_id(ev["uuid"], finding_schema, f0["sha256"], c["category"], c.get("region"), c["region_index"])
        await db.visual_candidates.update_one({"uuid": cid}, {"$setOnInsert": {
            "uuid": cid, "workspace_id": ev["workspace_id"], "visit_id": ev["visit_id"], "evidence_id": ev["uuid"], "photo_sha256": ev["sha256"],
            "video_evidence_id": ev["uuid"], "video_sha256": ev["sha256"], "run_id": rid[s], "pipeline": c["pipeline"], "schema": s, **ident[s],
            "config": CONFIG, "source": "server_model", "category": c["category"], "condition_kind": c["condition_kind"],
            "region": c.get("region"), "localized": isinstance(c.get("region"), list), "scope": "localized" if isinstance(c.get("region"), list) else "image",
            "rail_surface": c.get("rail_surface"), "visible_reason": c.get("visible_reason"), "uncertainty": c.get("uncertainty"),
            "alternatives": c.get("alternatives") or [], "assessability": c.get("assessability"),
            "frame": {k: f0[k] for k in ("id", "sha256", "t", "frame_index", "width", "height")}, "frames": c["frames"],
            "timestamp_s": f0["t"], "timestamps_s": [x["t"] for x in c["frames"]],
            "region_frame": {"kind": "video_frame", "frame_id": f0["id"], "t": f0["t"], "width": f0["width"], "height": f0["height"]},
            "admitted": True, "review_state": "Pending", "decisions": [], "revision": 1,
            "created_at": iso(), "created_by": "system", "updated_at": iso(), "updated_by": "system"}}, upsert=True)
    statuses = {}
    for s in SCHEMAS:
        if done[s]:
            statuses[s] = "complete"
            continue
        st = _run_status(results[s], budget_hit, len(frames))
        statuses[s] = st
        n = sum(1 for c in findings if c["schema"] == s)
        rej = [x for r in results[s] for x in (r.get("rejected") or [])]
        label = (f"{n} finding(s)" if n else ("Could not finish the check" if st != "complete" else "No visible issue identified in this video. This does not confirm the track is safe."))
        cannot_assess = s == "rail_surface" and any(r.get("cannot_assess") for r in results[s])
        if cannot_assess:
            label = f"{n} finding(s); some selected rail-surface frames could not be assessed" if n else "Rail surface not clear enough to check"
        await db.image_analysis_runs.update_one({"uuid": rid[s]}, {"$set": {
            "status": st, "frames": fr_docs, "candidates": n, "rejected_candidates": rej,
            "frame_errors": [{"t": r.get("t"), "status": r["status"], "error": r.get("error")} for r in results[s] if r["status"] not in OK_FRAME],
            "outcome_label": label,
            **({"image_assessability": "cannot_assess", "cannot_assess_reason": label} if cannot_assess else {}),
            "completed_at": iso(), "updated_at": iso()}})
    if budget_hit:
        from jobs import _set_fenced, budget_reason
        return await _set_fenced(job, {"status": "Blocked", "blocker": calibration.BUDGET_MSG, "block_reason": await budget_reason()})
    if all(v == "failed" for v in statuses.values()):
        return await finish(job, "Failed", "Could not finish the check", "video", rid["tie_fastener"])
    await finish(job, "Done", None if all(v == "complete" for v in statuses.values()) else "Some frames could not be checked", None, rid["tie_fastener"])
