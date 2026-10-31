import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState } from "react";
import { resolveSceneAsset } from "@/lib/photoScene";
import ScenePinLayer from "./ScenePinLayer";
import "@playcanvas/supersplat-viewer/viewer.css";

// Constrained navigation near the capture viewpoint, applied to the viewer's own orbit controller (engine OrbitController).
const YAW = 30;
const PITCH = 25;
const ZOOM = [0.6, 1.6]; // x capture distance (also floored so the camera stays in front of the nearest surface)
const PAN = 0.15; // x capture distance, focus may move this far on x/y/z

// One live viewer at most (V07). Exposed for the tester.
const live = { viewers: 0 };
const FIRST_FRAME_MS = 20000; // bounded first-frame deadline
let capturedOrbit = null; // engine OrbitController most recently attached (only one viewer exists at a time)
function patchOrbit(pc) {
  const proto = pc.OrbitController?.prototype;
  if (!proto || proto.__rrPatched) return;
  const attach = proto.attach;
  proto.attach = function rrAttach(...args) {
    capturedOrbit = this;
    return attach.apply(this, args);
  };
  proto.__rrPatched = true;
}

/** Settings fov on the axis the viewer applies (horizontal when the canvas is landscape), from the manifest fov + axis. */
function viewerFov(cam, W, H) {
  const t = Math.tan(((cam.fov || 55) * Math.PI) / 360);
  const tanH = cam.fov_axis === "vertical" ? t * (W / H) : t;
  const tanV = tanH * (H / W);
  return (360 * Math.atan(W > H ? tanH : tanV)) / Math.PI;
}

/**
 * Renderer adapter around @playcanvas/supersplat-viewer: load (asset transport -> createViewer), destroy, reset, camera state,
 * project, resize, input enable/disable. One instance = one load generation; the parent remounts it (key) for a new asset.
 * Phases: downloading -> rendering -> ready | expired | denied | failed | graphics.
 */
const PhotoSceneCanvas = forwardRef(function PhotoSceneCanvas({ asset, manifest, sceneTag, pins, selectedId, showPins, onSelect, onPhase, onNotice }, ref) {
  const hostRef = useRef(null);
  const pinRef = useRef(null);
  const S = useRef({ viewer: null, pc: null, orbit: null, splat: null, vp: null, v4: null, out: null, ready: false });
  const gen = useRef(0);
  const [ready, setReady] = useState(false);
  const cbs = useRef({ onPhase, onNotice });
  cbs.current = { onPhase, onNotice };

  const project = useCallback((xyz) => {
    const { viewer, pc, splat } = S.current;
    const host = hostRef.current;
    if (!viewer || !pc || !host || !xyz) return null;
    const cam = viewer.app.root.findComponents("camera").find((c) => c.enabled && c.entity.enabled);
    if (!cam) return null;
    const s = S.current;
    s.vp = s.vp || new pc.Mat4();
    s.v4 = s.v4 || new pc.Vec4();
    s.out = s.out || new pc.Vec4();
    const w = new pc.Vec3(xyz[0], xyz[1], xyz[2]);
    splat?.getWorldTransform().transformPoint(w, w); // anchors are in the asset's local frame
    s.vp.mul2(cam.projectionMatrix, cam.viewMatrix);
    s.vp.transformVec4(s.v4.set(w.x, w.y, w.z, 1), s.out);
    const { x, y, z, w: cw } = s.out;
    if (!(cw > 1e-6)) return null; // behind the camera
    const nx = x / cw;
    const ny = y / cw;
    const nz = z / cw;
    if (nx < -1 || nx > 1 || ny < -1 || ny > 1 || nz < -1 || nz > 1) return null; // outside clip
    const W = host.clientWidth; // CSS px: independent of devicePixelRatio / drawing-buffer size
    const H = host.clientHeight;
    return { x: ((nx + 1) * W) / 2, y: ((1 - ny) * H) / 2 };
  }, []);

  const frame = useCallback(() => {
    const host = hostRef.current;
    if (host && S.current.ready) pinRef.current?.update(project, host.clientWidth, host.clientHeight);
  }, [project]);

  const lookFrom = useCallback((position, target, smooth = true) => {
    const { pc, orbit, viewer } = S.current;
    if (!pc || !orbit || !viewer?.state.loaded) return false;
    const pose = new pc.Pose().look(new pc.Vec3(...position), new pc.Vec3(...target));
    orbit.attach(pose, smooth);
    viewer.app.renderNextFrame = true;
    return true;
  }, []);

  useImperativeHandle(ref, () => ({
    reset: () => S.current.viewer?.state.loaded && S.current.viewer.resetCamera(),
    focus: (xyz) => {
      // authored view of a finding: capture position, looking towards its anchor, orbit focus kept at the capture distance
      const P = manifest.camera?.position;
      const T = manifest.camera?.target;
      if (!P || !T || !xyz) return false;
      const d0 = Math.hypot(T[0] - P[0], T[1] - P[1], T[2] - P[2]) || 1;
      const v = [xyz[0] - P[0], xyz[1] - P[1], xyz[2] - P[2]];
      const n = Math.hypot(...v) || 1;
      return lookFrom(P, [P[0] + (v[0] / n) * d0, P[1] + (v[1] / n) * d0, P[2] + (v[2] / n) * d0]);
    },
    getCameraState: () => {
      const { viewer, orbit } = S.current;
      const cam = viewer?.app.root.findComponents("camera").find((c) => c.enabled);
      if (!cam) return null;
      const p = cam.entity.getPosition();
      const f = orbit?._rootPose?.position;
      const fwd = cam.entity.forward;
      const d = orbit?._childPose?.position?.z || 4;
      return { position: [p.x, p.y, p.z], target: f ? [f.x, f.y, f.z] : [p.x + fwd.x * d, p.y + fwd.y * d, p.z + fwd.z * d], fov: manifest.camera?.fov };
    },
    setCameraState: (c) => !!c?.position && !!c?.target && lookFrom(c.position, c.target),
    project,
    setInputEnabled: (on) => S.current.viewer && (S.current.viewer.state.inputEnabled = !!on),
  }));

  const key = `${asset?.url}`;
  useEffect(() => {
    const my = ++gen.current;
    const alive = () => gen.current === my && !!hostRef.current;
    const host = hostRef.current;
    const ctrl = new AbortController();
    const cleanups = [];
    let viewer = null;
    let res = null;
    const t0 = performance.now();
    const phase = (p) => alive() && cbs.current.onPhase?.(p);
    S.current.ready = false;
    setReady(false);
    const destroy = (v) => {
      if (!v || v.__rrDestroyed) return;
      v.__rrDestroyed = true;
      v.state.inputEnabled = false;
      v.destroy();
      live.viewers -= 1;
    };

    // Any failure in the whole lifecycle (imports, setup, viewer creation, async viewer errors, first-frame deadline)
    // ends this generation: partial viewer destroyed, asset released, one plain "failed" phase.
    let over = false;
    const fail = (e, why) => {
      if (over || !alive()) return;
      over = true;
      clearTimeout(deadline);
      cleanups.forEach((f) => f());
      cleanups.length = 0;
      destroy(viewer);
      viewer = null;
      res?.dispose();
      res = null;
      S.current = { viewer: null, pc: null, orbit: null, splat: null, ready: false };
      phase({ k: "failed", reason: why, error: String(e?.message || e || why) });
    };
    const deadline = setTimeout(() => !S.current.ready && fail(null, "timeout"), FIRST_FRAME_MS);
    cleanups.push(() => clearTimeout(deadline));
    const onRejection = (ev) => { if (viewer && !S.current.ready) fail(ev.reason, "viewer"); };
    window.addEventListener("unhandledrejection", onRejection);
    cleanups.push(() => window.removeEventListener("unhandledrejection", onRejection));

    (async () => {
     try {
      phase({ k: "downloading" });
      try {
        res = await resolveSceneAsset(asset, ctrl.signal);
      } catch (e) {
        if (e?.name === "AbortError" || !alive()) return;
        over = true; // generation ends here: no later deadline "failed" on top of this state
        clearTimeout(deadline);
        return phase(e.kind === "expired" || e.kind === "denied" ? { k: e.kind, status: e.status, error: e.message } : { k: "failed", reason: e.kind === "missing" ? "asset" : e.kind || "asset", error: e.message });
      }
      if (!alive()) return res.dispose();
      phase({ k: "rendering", bytes: res.bytes });
      let mods;
      try {
        mods = await Promise.all([import("@playcanvas/supersplat-viewer/viewer"), import("@playcanvas/supersplat-viewer/settings"), import("playcanvas")]);
      } catch (e) {
        return fail(e, "import");
      }
      const [{ createViewer }, { defaultSettings }, pc] = mods;
      if (!alive()) return res.dispose();
      patchOrbit(pc);
      capturedOrbit = null;
      const cam = manifest.camera || {};
      const iW = manifest.width || host.clientWidth;
      const iH = manifest.height || host.clientHeight;
      const settings = defaultSettings();
      settings.background = { color: [0.03, 0.05, 0.055] };
      settings.tonemapping = "linear";
      settings.cameras = [{ initial: { position: cam.position || [0, 0, 0], target: cam.target || [0, 0, -4], fov: viewerFov(cam, iW, iH) } }];
      settings.annotations = [];
      try {
        viewer = await createViewer({
          container: host, settings, contentUrl: res.url, contentFilename: "scene.ply", ...(res.contents ? { contents: Promise.resolve(res.contents) } : {}),
          ui: false, renderer: "webgl", noanim: true, nofx: true,
        });
        live.viewers += 1;
      } catch (e) {
        return fail(e, "viewer");
      }
      if (!alive()) {
        destroy(viewer); // late stale viewer
        return res.dispose();
      }
      S.current = { ...S.current, viewer, pc };
      window.__rrScene = { viewer, project, live, resolve: resolveSceneAsset, timings: { t0 } };

      // The viewer rotates PLYs 180 deg about Z (3DGS y-down convention). The scene contract is X right / Y up / looking -Z,
      // verified against the original photo, so that flip is undone on the splat entity.
      const yDown = /y[\s_-]*down/i.test(String(manifest.coordinate_system || ""));
      const upright = (e) => {
        if (e?.name !== "gsplat") return;
        S.current.splat = e;
        const r = e.getLocalEulerAngles();
        if (window.__rrScene) window.__rrScene.plyRotation = { before: [r.x, r.y, r.z], corrected: !yDown };
        if (!yDown) e.setLocalEulerAngles(0, 0, 0);
        viewer.app.renderNextFrame = true;
      };
      const existing = viewer.app.root.findByName("gsplat");
      if (existing) upright(existing);
      else {
        viewer.app.root.on("childinsert", upright);
        cleanups.push(() => viewer.app.root.off("childinsert", upright));
      }

      const canvas = host.querySelector("canvas");
      const lost = (ev) => {
        ev.preventDefault();
        S.current.ready = false;
        phase({ k: "graphics", error: "The graphics context was lost." });
      };
      canvas?.addEventListener("webglcontextlost", lost);
      cleanups.push(() => canvas?.removeEventListener("webglcontextlost", lost));

      const constrain = () => {
        const orbit = capturedOrbit;
        S.current.orbit = orbit;
        if (!orbit || !cam.position || !cam.target) return;
        const P = cam.position;
        const T = cam.target;
        const d0 = Math.hypot(T[0] - P[0], T[1] - P[1], T[2] - P[2]) || 1;
        // nearest surface along the view axis (local aabb max z; the camera looks down -Z)
        const aabb = S.current.splat?.gsplat?.resource?.aabb;
        const nearZ = aabb ? aabb.center.z + aabb.halfExtents.z : T[2] + d0 * 0.5;
        const cos = Math.cos((Math.max(YAW, PITCH) * Math.PI) / 180);
        const focusZ = T[2] + PAN * d0;
        const minD = Math.max(ZOOM[0] * d0, (nearZ + 0.02 * d0 - focusZ) / cos, 0.05 * d0);
        orbit.yawRange = new pc.Vec2(-YAW, YAW);
        orbit.pitchRange = new pc.Vec2(-PITCH, PITCH);
        const zoom = [Math.min(minD, d0), Math.max(ZOOM[1] * d0, d0)];
        orbit.zoomRange = new pc.Vec2(zoom[0], zoom[1]);
        const rp = orbit._targetRootPose;
        if (rp?.xRange) {
          // focus may move across the capture frustum at the capture distance (so finding views stay reachable), little in depth
          const tanH = Math.tan((viewerFov({ ...cam, fov_axis: cam.fov_axis }, iW, iH) * Math.PI) / 360) * (iW > iH ? 1 : iW / iH);
          const tanV = tanH * (iH / iW);
          rp.xRange.set(T[0] - d0 * tanH, T[0] + d0 * tanH);
          rp.yRange.set(T[1] - d0 * tanV, T[1] + d0 * tanV);
          rp.zRange.set(T[2] - PAN * d0, T[2] + PAN * d0);
        }
        S.current.limits = { yaw: YAW, pitch: PITCH, zoom, pan: PAN * d0, nearZ };
        window.__rrScene.limits = S.current.limits;
      };

      const markReady = () => {
        if (!alive()) return;
        viewer.state.cameraMode = "orbit";
        constrain();
        // "Interactive ready" only after loaded + one more complete rendered frame
        viewer.app.renderNextFrame = true;
        viewer.app.once("postrender", () =>
          viewer.app.once("frameend", () => {
            if (!alive()) return;
            S.current.ready = true;
            clearTimeout(deadline);
            setReady(true);
            const ms = Math.round(performance.now() - t0);
            window.__rrScene.timings.firstFrameMs = ms;
            host.dataset.firstFrameMs = String(ms);
            phase({ k: "ready", ms });
            frame();
          }),
        );
      };
      viewer.events.on("progress:changed", (p) => !viewer.state.loaded && phase({ k: "rendering", progress: Math.round(p) }));
      if (viewer.state.loaded) markReady();
      else viewer.events.on("loaded:changed", (v) => v && markReady());
      viewer.app.on("frameend", frame);
      cleanups.push(() => viewer.app.off("frameend", frame));

      if (!capturedOrbit) {
        // fallback if the orbit controller could not be reached: return to capture view after excessive excursion
        const end = () => setTimeout(() => {
          if (S.current.orbit || !viewer.state.loaded || viewer.__rrDestroyed) return;
          const c = viewer.app.root.findComponents("camera").find((x) => x.enabled);
          const p = c?.entity.getPosition();
          if (p && Math.hypot(p.x - (cam.position?.[0] || 0), p.y - (cam.position?.[1] || 0)) > 1.5) {
            viewer.resetCamera();
            cbs.current.onNotice?.("The view is limited near the capture point. Returned to the capture view.");
          }
        }, 350);
        host.addEventListener("pointerup", end);
        cleanups.push(() => host.removeEventListener("pointerup", end));
      }

      // Camera keyboard disabled while typing (REQ-152) and released on window blur.
      const typing = () => {
        const a = document.activeElement;
        return !!a && (a.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(a.tagName));
      };
      const sync = () => {
        if (!viewer.__rrDestroyed) viewer.state.inputEnabled = !typing() && document.hasFocus();
      };
      const out = () => setTimeout(sync, 0);
      document.addEventListener("focusin", sync);
      document.addEventListener("focusout", out);
      window.addEventListener("blur", sync);
      window.addEventListener("focus", sync);
      cleanups.push(() => {
        document.removeEventListener("focusin", sync);
        document.removeEventListener("focusout", out);
        window.removeEventListener("blur", sync);
        window.removeEventListener("focus", sync);
      });
      sync();
      const ro = new ResizeObserver(() => {
        if (!viewer.__rrDestroyed) viewer.app.renderNextFrame = true;
        frame();
      });
      ro.observe(host);
      cleanups.push(() => ro.disconnect());
     } catch (e) {
      if (e?.name !== "AbortError") fail(e, "setup");
     }
    })();

    return () => {
      gen.current += 1;
      ctrl.abort();
      cleanups.forEach((f) => f());
      destroy(viewer);
      res?.dispose();
      S.current = { viewer: null, pc: null, orbit: null, splat: null, ready: false };
      if (window.__rrScene?.viewer === viewer) window.__rrScene = { live };
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  useEffect(() => { frame(); }, [pins, showPins, selectedId, frame]);

  return (
    <div className="absolute inset-0">
      <div ref={hostRef} data-testid="scene-canvas-host" className="absolute inset-0" />
      <ScenePinLayer ref={pinRef} sceneTag={sceneTag} pins={pins} selectedId={selectedId} visible={showPins && ready} onSelect={onSelect} sample={[manifest.width, manifest.height]} />
    </div>
  );
});

export default PhotoSceneCanvas;
