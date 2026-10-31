import { forwardRef, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Image as ImageIcon, RefreshCw } from "lucide-react";
import { errText } from "@/lib/api";
import { absUrl, webglAvailable } from "@/lib/scene";
import { DEPTH_LABEL, TERMINAL, checkScene, ensureScene, getScene, isApiDenied, pollJob, retryScene } from "@/lib/photoScene";
import PhotoSceneCanvas from "./PhotoSceneCanvas";
import PhotoView from "./PhotoView";
import useAspectFit from "./useAspectFit";
import { StateIcon, StatePanel, STATES } from "./SceneState";
import { WS } from "./ws";

const ERR_STATE = { depth_uninformative: "depth-uninformative", unsupported: "unsupported" };
// What the descriptor itself says before the first check: an explicitly non-current revision is never "ready".
const descriptorPending = (s) => (s?.regen_failed ? { failed: true } : s?.regenerating || s?.is_current === false ? { failed: false } : null);
const LIVE = ["downloading", "rendering", "ready", "previous", "previous-failed"];

/**
 * Derive the single visible state from server scene status + viewer phase. `phase` must belong to the canvas generation of
 * `scene`; `pending` = a newer revision of this photo exists that is not shown yet.
 */
export function sceneStateKey({ photo, scene, job, err, phase, gl, pending, preparing }) {
  if (!photo) return "no-photo";
  if (err) return isApiDenied(err) ? "denied" : "failed";
  if (!scene) return job ? (job.error?.code === "blocked" ? "blocked" : job.stalled ? "stalled" : job.status === "processing" ? "processing" : "queued") : preparing ? "preparing" : "loading";
  if (scene.status === "queued" || scene.status === "processing") return scene.status;
  if (ERR_STATE[scene.status]) return ERR_STATE[scene.status];
  if (scene.error?.code === "unsupported_format") return "unsupported";
  if (scene.status === "failed") return scene.error?.code === "model_unavailable" ? "model" : "failed";
  if (scene.status !== "ready") return "failed";
  if (!scene.scene_id || scene.revision == null || !scene.assets?.splat?.url) return "preparing"; // never "ready" without the scene's own identity
  if (!gl || phase?.k === "graphics") return "graphics";
  if (phase?.k === "expired" || phase?.k === "denied") return phase.k;
  if (phase?.k === "failed") return "failed";
  const k = phase?.k || "downloading";
  const pend = pending || descriptorPending(scene);
  return k === "ready" && pend ? (pend.failed ? "previous-failed" : "previous") : k;
}

/**
 * Centre panel: one photo's scene. Loads via the photo-scene contract (ensure -> job polling ~1s with backoff -> descriptor),
 * mounts one PhotoSceneCanvas per load generation in an aspect-fit viewport, and shows the original photo on demand.
 */
const PhotoInspectionView = forwardRef(function PhotoInspectionView(
  { photo, mode, showMarkers, items, pins, selectedId, onSelect, placing, onPlace, originalFallback, onScene, onState, onNotice, onShowOriginal }, viewerRef,
) {
  const panelRef = useRef(null);
  const [scene, setScene] = useState(null);
  const [job, setJob] = useState(null);
  const [err, setErr] = useState(null);
  const [phase, setPhase] = useState(null);
  const [pending, setPending] = useState(null); // newer revision not shown yet: {status, revision, failed, error}
  const [preparing, setPreparing] = useState(false); // the shown scene disappeared - a fresh load is in progress
  const [checkNow, setCheckNow] = useState(0);
  const [nonce, setNonce] = useState(0); // re-runs ensure/poll
  const [mount, setMount] = useState(0); // remounts the canvas only (same descriptor)
  const refreshed = useRef(false);
  const gl = webglAvailable();
  const cb = useRef({ onScene, onState });
  cb.current = { onScene, onState };

  // Single writer: the workspace always mirrors exactly the scene this view shows (or null while there is none).
  useLayoutEffect(() => { cb.current.onScene?.(scene); }, [scene]); // before paint: no frame where the two disagree
  useEffect(() => { setPreparing(false); }, [photo]);

  useEffect(() => {
    if (!photo) return undefined;
    let stop = false;
    let timer = 0;
    let delay = 1000;
    let jobRef = null;
    let polls = 0;
    const ac = new AbortController(); // photo switch / unmount cancels in-flight requests
    setScene(null); setJob(null); setErr(null); setPhase(null); setPending(null);
    refreshed.current = false;
    const schedule = () => {
      timer = setTimeout(() => run(false), delay);
      delay = Math.min(delay * 1.6, 8000);
    };
    async function run(first) {
      try {
        const r = first || !jobRef ? await ensureScene(photo, ac.signal) : await pollJob(jobRef, photo, ac.signal);
        if (stop) return;
        if (r.scene) {
          setScene(r.scene);
          setJob(null);
          setPreparing(false);
          if (!TERMINAL.includes(r.scene.status)) schedule();
        } else {
          jobRef = r;
          polls += 1;
          // No endless polling: a blocked job waits for a person; after ~10 minutes ask before checking again.
          if (r.error?.code === "blocked") return setJob(r);
          if (polls > 80) return setJob({ ...r, stalled: true });
          setJob(r);
          schedule();
        }
      } catch (e) {
        if (!stop && e?.name !== "AbortError") setErr(e);
      }
    }
    run(true);
    return () => { stop = true; clearTimeout(timer); ac.abort(); };
  }, [photo, nonce]);

  // While a scene is shown, keep checking (GET only) that it is still the current one: a rebuild keeps the shown
  // revision explicitly labelled as previous; a newer ready revision replaces it (new load generation); gone -> reload.
  useEffect(() => {
    if (!scene?.scene_id || scene.status !== "ready") return undefined;
    let stop = false;
    let timer = 0;
    let running = false;
    let delay = 1000;
    const ac = new AbortController();
    const tick = async () => {
      clearTimeout(timer);
      if (stop || running) return;
      if (document.hidden) { timer = setTimeout(tick, 5000); return; }
      running = true;
      try {
        const r = await checkScene(scene, ac.signal);
        if (stop) return;
        if (r.missing) { setPending(null); setPreparing(true); setNonce((n) => n + 1); return; }
        if (r.next) { setPending(null); setPhase(null); setScene(r.next); return; }
        setPending(r.pending || null);
        delay = r.pending && !r.pending.failed ? Math.min(delay * 1.6, 8000) : 4000;
      } catch {
        delay = 10000;
      } finally {
        running = false;
      }
      if (!stop) timer = setTimeout(tick, delay);
    };
    timer = setTimeout(tick, checkNow || descriptorPending(scene) ? 0 : 1500);
    window.addEventListener("focus", tick);
    return () => { stop = true; clearTimeout(timer); ac.abort(); window.removeEventListener("focus", tick); };
  }, [scene, checkNow]);

  // Asset refused (expired/denied): refresh the descriptor once with GET (never regenerates), then reload the same asset.
  const onPhase = useCallback(async (p) => {
    if ((p.k === "expired" || p.k === "denied") && !refreshed.current && scene) {
      refreshed.current = true;
      setPhase(null);
      try {
        const s = await getScene(scene);
        setScene(s.status === "ready" ? { ...s, job_id: scene.job_id } : s);
        setMount((n) => n + 1); // the refreshed descriptor may carry an identical URL - always remount for one reload
      } catch (e) {
        setPhase({ ...p, error: errText(e) });
      }
      return;
    }
    setPhase(p);
  }, [scene]);

  // Phase belongs to one canvas generation: a new scene id / revision / asset / remount never inherits the old "ready".
  const genKey = scene ? `${scene.scene_id}:${scene.revision}:${scene.assets?.splat?.url}:${mount}` : "";
  const ph = phase && phase.gen === genKey ? phase : null;
  const k = sceneStateKey({ photo, scene, job, err, phase: ph, gl, pending, preparing });
  useLayoutEffect(() => { cb.current.onState?.(k, ph); }, [k, ph]);
  useEffect(() => {
    if (k !== "preparing" || !scene) return undefined; // ready descriptor without its identity/asset: load it again
    const t = setTimeout(() => { setPreparing(true); setNonce((n) => n + 1); }, 2000);
    return () => clearTimeout(t);
  }, [k, scene]);

  const m = scene?.manifest || {};
  const fit = useAspectFit(panelRef, m.width || m.oriented_width, m.height || m.oriented_height);
  const original = absUrl(scene?.assets?.oriented_photo?.url || scene?.assets?.original?.url) || originalFallback; // oriented frame = region frame
  const btnOrig = <button type="button" data-testid="scene-view-original" className={WS.btn} onClick={onShowOriginal}><ImageIcon aria-hidden className="h-4 w-4" />View original photo</button>;
  const live3d = LIVE.includes(k);
  // Pins only for anchors authored on the scene revision drawn right now.
  const sid = scene?.scene_id;
  const srev = scene?.revision;
  const shownPins = useMemo(() => (sid ? pins.filter((p) => (p.scene_id == null || p.scene_id === sid) && (p.scene_revision == null || p.scene_revision === srev)) : []), [pins, sid, srev]);
  const prev = k === "previous" || k === "previous-failed";
  const retryUpdate = async () => { try { await retryScene(scene); } catch { /* the next check shows the server state */ } setCheckNow((n) => n + 1); };

  if (mode === "photo" || k === "graphics") {
    return (
      <div ref={panelRef} className="absolute inset-0 min-h-0 min-w-0 overflow-hidden">
        <PhotoView src={original} fallbackSrc={originalFallback} ow={m.oriented_width} oh={m.oriented_height} items={items} selectedId={selectedId} showMarkers={showMarkers} onSelect={onSelect} placing={placing} onPlace={onPlace} />
        {k === "graphics" && mode !== "photo" ? (
          <p data-testid="scene-state-graphics" role="status" className="absolute left-2 top-2 z-30 flex max-w-[90%] items-center gap-1.5 border border-[#8A6A2E] bg-[#111315] px-2 py-1 text-[13px] text-[#F1D9A6]">
            <StateIcon k="graphics" />Graphics unavailable. Showing the photo only{ph?.error ? ` (${ph.error})` : " (WebGL could not start)"}. Review still works.
            {ph?.k === "graphics" ? <button type="button" data-testid="scene-reload-3d" className={`${WS.btn} ml-1`} onClick={() => { setPhase(null); setMount((n) => n + 1); }}>Try 3D again</button> : null}
          </p>
        ) : null}
      </div>
    );
  }

  const retryBtn = (label, testid, fn) => <button type="button" data-testid={testid} className={WS.btn} onClick={fn}><RefreshCw aria-hidden className="h-4 w-4" />{label}</button>;
  let panel = null;
  if (k === "no-photo") panel = <StatePanel k={k} detail="No photos here yet. Add one from the field app or the inspection page." />;
  else if (k === "loading") panel = <StatePanel k={k} />;
  else if (k === "blocked") panel = <StatePanel k={k} detail={`${job?.error?.message || "Photo processing is not allowed for this inspection"}. The photo and review still work. An office admin can allow processing in Photo analysis settings.`}>{btnOrig}{retryBtn("Check again", "scene-check-again", () => setNonce((n) => n + 1))}</StatePanel>;
  else if (k === "stalled") panel = <StatePanel k={k} detail="The photo and review still work.">{btnOrig}{retryBtn("Check again", "scene-check-again", () => setNonce((n) => n + 1))}</StatePanel>;
  else if (k === "preparing") panel = <StatePanel k={k} detail="The original photo and review are already available.">{btnOrig}</StatePanel>;
  else if (k === "queued" || k === "processing") panel = <StatePanel k={k} detail="The original photo and review are already available.">{btnOrig}</StatePanel>;
  else if (k === "depth-uninformative") panel = <StatePanel k={k} detail="Use the photo itself to check the details.">{btnOrig}</StatePanel>;
  else if (k === "unsupported") panel = <StatePanel k={k}>{btnOrig}</StatePanel>;
  else if (k === "model") panel = <StatePanel k={k} detail="3D view did not load. Use the photo, or select Retry.">{btnOrig}{retryBtn("Retry", "scene-model-retry", () => setNonce((n) => n + 1))}</StatePanel>;
  else if (k === "denied") panel = <StatePanel k={k} detail={ph?.error || (err ? errText(err) : "You do not have access to this scene's media.")}>{btnOrig}</StatePanel>;
  else if (k === "expired") panel = <StatePanel k={k} detail={ph?.error || "The short-lived scene link was refused after one refresh."}>{btnOrig}{retryBtn("Refresh media", "scene-refresh-media", () => { refreshed.current = false; setPhase(null); onPhase({ k: "expired" }); })}</StatePanel>;
  else if (k === "failed") {
    const assetFail = ph?.k === "failed";
    const canRetry = !assetFail && !err && scene?.error?.retryable !== false;
    panel = (
      <StatePanel k={k} title={assetFail ? "3D view didn't load. The photo and review still work." : err ? "3D view isn't available" : STATES.failed[1]} detail={assetFail ? null : err ? errText(err) : scene?.error?.message} reason={assetFail ? ph.reason : null}>
        {btnOrig}
        {assetFail ? retryBtn("Try again", "scene-retry-load", () => { setPhase(null); setMount((n) => n + 1); }) : null}
        {err ? retryBtn("Try again", "scene-reload", () => setNonce((n) => n + 1)) : null}
        {canRetry ? retryBtn("Retry", "scene-retry", async () => { try { await retryScene(scene); setNonce((n) => n + 1); } catch (e) { setErr(e); } }) : null}
      </StatePanel>
    );
  }

  return (
    <div ref={panelRef} className="absolute inset-0 min-h-0 min-w-0 overflow-hidden">
      {live3d && fit ? (
        <div data-testid="scene-viewport" data-scene-id={scene.scene_id} data-scene-revision={scene.revision} data-previous={prev ? "1" : "0"} data-view-w={fit.width} data-view-h={fit.height} data-dpr={window.devicePixelRatio} data-sample-w={m.width} data-sample-h={m.height}
          className="absolute" style={{ left: fit.left, top: fit.top, width: fit.width, height: fit.height }}>
          <PhotoSceneCanvas key={genKey} ref={viewerRef} sceneTag={`${scene.scene_id}:${scene.revision}`} asset={scene.assets?.splat} manifest={{ ...m, coordinate_system: scene.info?.projection?.coordinate_system || m.coordinate_system }}
            pins={shownPins} selectedId={selectedId} showPins={showMarkers} onSelect={onSelect} onPhase={(p) => onPhase({ ...p, gen: genKey })} onNotice={onNotice} />
        </div>
      ) : null}
      {live3d ? <p data-testid="scene-depth-label" className="pointer-events-none absolute left-2 top-2 z-20 border border-[#4A5157] bg-[#111315] px-2 py-1 text-[13px] font-semibold text-[#E6E8EA]">{DEPTH_LABEL}</p> : null}
      {k === "downloading" || k === "rendering" ? (
        <StatePanel k={k} overlay detail={ph?.progress != null ? `${ph.progress}%` : ph?.bytes ? `${Math.round(ph.bytes / 1024)} KB received` : null}>
          {ph?.progress != null ? <div role="progressbar" aria-label="Scene loading" aria-valuemin={0} aria-valuemax={100} aria-valuenow={ph.progress} className="h-1.5 w-full bg-[#2E3337]"><div className="h-full bg-[#C9CED3]" style={{ width: `${ph.progress}%` }} /></div> : null}
        </StatePanel>
      ) : null}
      {k === "ready" ? (
        <p data-testid="scene-state-ready" role="status" className="pointer-events-none absolute bottom-2 left-2 z-20 flex items-center gap-1.5 border border-[#4A5157] bg-[#111315] px-2 py-1 text-[12px] font-semibold">
          <StateIcon k="ready" className="h-3.5 w-3.5" />Interactive ready{ph?.ms ? ` - first frame ${(ph.ms / 1000).toFixed(1)} s` : ""}
        </p>
      ) : null}
      {prev ? (
        <div data-testid="scene-state-previous" data-state={k} data-scene-revision={scene.revision} role="status" className="absolute bottom-2 left-2 z-20 flex max-w-[92%] flex-wrap items-center gap-1.5 border border-[#8A6A2E] bg-[#111315] px-2 py-1 text-[12px] font-semibold text-[#F1D9A6]">
          <StateIcon k={k} className="h-3.5 w-3.5" />{STATES[k][1]} - revision {scene.revision}
          {k === "previous-failed" && pending?.error?.retryable !== false ? retryBtn("Try again", "scene-retry-update", retryUpdate) : null}
        </div>
      ) : null}
      {(k === "ready" || prev) && !items.length ? <p data-testid="scene-empty-findings" className="pointer-events-none absolute bottom-2 right-2 z-20 border border-[#4A5157] bg-[#111315] px-2 py-1 text-[12px]">No findings on this photo. The scene is shown for context.</p> : null}
      {panel}
    </div>
  );
});

export default PhotoInspectionView;
