import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { Bookmark, BookmarkCheck, Box, Eye, EyeOff, Image as ImageIcon, RotateCcw, TrainFront } from "lucide-react";
import { ApiError, api, errText, hasRoute, mediaUrl } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { absUrl, isPlanar, sceneApi } from "@/lib/scene";
import { DEPTH_LABEL, getView, loadAnchors, moveAnchor, putView } from "@/lib/photoScene";
import Inventory from "@/components/scene/Inventory";
import EvidenceDrawer from "@/components/scene/EvidenceDrawer";
import PhotoInspectionView from "@/components/scene/PhotoInspectionView";
import { STATES, StateIcon } from "@/components/scene/SceneState";
import { WS } from "@/components/scene/ws";

const SCENE_H = "h-[min(46vh,400px)] md:h-[clamp(510px,64vh,640px)]";
const TOUCH = "[@media(pointer:coarse)]:inline-flex [@media(pointer:coarse)]:min-h-[44px] [@media(pointer:coarse)]:items-center";

function Provenance({ scene, filename }) {
  const [open, setOpen] = useState(false);
  const s = scene?.info || {};
  const m = s.model || {};
  const p = s.projection || {};
  const cam = scene?.manifest?.camera || {};
  const planar = isPlanar(s);
  const { isAdmin } = useAuth();
  if (!isAdmin) return <div data-testid="scene-provenance" className={`border-b ${WS.line} bg-[#16191B] px-3 py-1.5 text-[13px]`}><p data-testid="scene-mode-label" className="font-medium text-[#E6E8EA]">3D view is approximate. Use the photo for details.</p></div>;
  return (
    <div data-testid="scene-provenance" className={`flex flex-wrap items-baseline gap-x-4 border-b ${WS.line} bg-[#16191B] px-3 py-1 text-[12px] md:flex-nowrap`}>
      <p data-testid="scene-mode-label" className="min-w-0 font-semibold text-[#E6E8EA] md:shrink-0">{planar ? "Flat photo preview, depth not reconstructed. Manual annotation. Not assessed." : `Single-photo depth view - ${DEPTH_LABEL}`}</p>
      {scene?.scene_id ? (
        <>
          <p data-testid="scene-geometry-desc" className={`${WS.sub} min-w-0 flex-1 basis-40 md:text-right ${open ? "break-words" : "truncate"}`}>
            Geometry: {p.depth_mode || s.depth_mode || "relative depth"}, {scene.manifest.width || "-"}x{scene.manifest.height || "-"} samples, FOV {cam.fov ?? "-"} deg {cam.fov_axis || ""}{s.focal_pixels ? `, focal ${Number(s.focal_pixels).toFixed(1)} px` : ""}{p.scale_note || s.units ? ` (${p.scale_note || `units ${s.units}`})` : ""}
            {open ? <>{` - Source ${s.source_filename || filename || "-"} sha256 ${String(s.source_sha256 || scene.scene_hash || "").slice(0, 12)}...`}
            {s.exif_transform ? ` - EXIF ${typeof s.exif_transform === "object" ? JSON.stringify(s.exif_transform) : s.exif_transform}` : ""} - Model {m.id || "-"}@{String(m.revision || "").slice(0, 8)} onnx {String(m.onnx_sha256 || "").slice(0, 12)}... {m.license ? `(${m.license})` : ""}
            {s.gaussians ? ` - ${s.gaussians} samples` : ""}{s.inference_run === false ? " - reused earlier inference (no new run)" : s.inference_run ? " - new inference run" : ""}{scene.scene_hash ? ` - scene hash ${String(scene.scene_hash).slice(0, 12)}...` : ""}</> : null}
          </p>
          <button type="button" data-testid="scene-provenance-toggle" aria-expanded={open} onClick={() => setOpen(!open)} className={`rr-focus shrink-0 font-semibold text-[#9FD3CF] underline-offset-2 hover:underline ${TOUCH}`}>{open ? "Less" : "Details"}</button>
        </>
      ) : <p className={WS.sub}>No scene geometry for this photo yet.</p>}
    </div>
  );
}

// An anchor is drawn only on the exact scene + revision it was authored on (never transferred between photos).
const placedOn = (a, scene) => !!(a?.xyz && scene?.scene_id && (!a.scene_id || a.scene_id === scene.scene_id) && (a.scene_revision == null || a.scene_revision === scene.revision));
function whyUnplaced(it, a, scene) {
  if (a && scene && a.scene_revision != null && a.scene_revision !== scene.revision) return `Anchor belongs to scene revision ${a.scene_revision}, not the current one`;
  if (a?.unplaced && a.reason) return a.reason;
  return it.unplaced_reason || (Array.isArray(it.region) ? (scene?.status === "ready" ? "No anchor placed yet" : "Scene not ready") : "No image region. It could not be located in the photo.");
}

export default function SceneWorkspace() {
  const { id } = useParams();
  const { isForeman, isAdmin } = useAuth();
  const [sp, setSp] = useSearchParams();
  const viewerRef = useRef(null);
  const [review, setReview] = useState(null);
  const [scenes, setScenes] = useState(null);
  const [listErr, setListErr] = useState(null);
  const [scene, setScene] = useState(null);
  const [inv, setInv] = useState([]);
  const [anchors, setAnchors] = useState({});
  const [invErr, setInvErr] = useState(null);
  const [state, setState] = useState({ k: "loading" });
  const [notice, setNotice] = useState(null);
  const [msg, setMsg] = useState(null);
  const [placing, setPlacing] = useState(null); // anchor move in progress: {item_id, point, reason, saving, prevMode}
  const key = `rr_scene_${id}`;

  // Selection lives in the URL (?evidence&finding&mode&markers) + sessionStorage, so refresh, direct links and returning restore it.
  useEffect(() => {
    if (!sp.get("evidence") && !sp.get("photo")) {
      const s = sessionStorage.getItem(key);
      if (s) setSp(new URLSearchParams(s), { replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => { if (sp.get("evidence")) sessionStorage.setItem(key, sp.toString()); }, [sp, key]);
  const photo = sp.get("evidence") || sp.get("photo") || scenes?.[0]?.evidence_id || null;
  const itemId = sp.get("finding") || sp.get("item");
  const mode = sp.get("mode") === "3d" ? "scene" : "photo"; // the photo + result is the default; 3D is optional
  const markers = sp.get("markers") !== "off";
  const setParams = (p) => {
    const n = { evidence: photo, finding: itemId, mode: mode === "scene" ? "3d" : null, markers: markers ? null : "off", check: sp.get("check"), ...p };
    setSp(Object.fromEntries(Object.entries(n).filter(([, v]) => v)), { replace: true });
  };

  const loadReview = useCallback(() => api(`/visits/${id}/review`).then(setReview).catch(() => {}), [id]);
  const loadScenes = useCallback(async () => {
    try {
      setScenes((await sceneApi.list(id)).scenes || []);
      setListErr(null);
    } catch (e) {
      const missing = e instanceof ApiError && e.status === 404 && !(await hasRoute("/visits/{}/scenes"));
      setListErr(missing ? "Scene service is not available on the server yet (GET /api/visits/{id}/scenes)." : errText(e));
      setScenes((s) => s || []);
    }
  }, [id]);
  const photoRef = useRef(null);
  const invAc = useRef(null);
  useEffect(() => () => invAc.current?.abort(), []);
  photoRef.current = photo;
  const showReview = sp.get("check") === "1"; // "Show items to check": adds candidates that still need a person
  const loadInv = useCallback(async () => {
    if (!photo) return [];
    invAc.current?.abort();
    const ac = new AbortController();
    invAc.current = ac;
    try {
      const r = await sceneApi.inventory(id, photo, showReview, ac.signal);
      if (photoRef.current !== photo || ac.signal.aborted) return [];
      const list = (r.items || []).filter((i) => i.evidence_id === photo); // never show another photo's items
      setInv(list);
      setInvErr(null);
      return list;
    } catch (e) {
      if (photoRef.current === photo && e?.name !== "AbortError") setInvErr(errText(e));
      return [];
    }
  }, [id, photo, showReview]);
  const sceneRef = useRef(null);
  sceneRef.current = scene;
  const loadAnch = useCallback(async (list) => {
    const s = sceneRef.current;
    if (!s || s.evidence_id !== photoRef.current || s.status !== "ready") return setAnchors({});
    try {
      const a = await loadAnchors(s, list);
      if (sceneRef.current?.scene_id === s.scene_id && sceneRef.current?.revision === s.revision) setAnchors(a);
    } catch (e) {
      setInvErr(`Anchors: ${errText(e)}`);
    }
  }, []);
  const reloadItems = useCallback(async () => loadAnch(await loadInv()), [loadInv, loadAnch]);

  useEffect(() => { loadReview(); loadScenes(); }, [loadReview, loadScenes]);
  // Reset per-photo state only when the photo really changes (not when callbacks are re-created). The scene itself is
  // written only by PhotoInspectionView (onScene), so the header/inventory/footer always describe the scene on screen.
  const shownPhoto = useRef(photo);
  useEffect(() => {
    if (shownPhoto.current === photo) return;
    shownPhoto.current = photo;
    setInv([]); setAnchors({}); setNotice(null); setMsg(null); setPlacing(null);
  }, [photo]);
  useEffect(() => { loadInv(); }, [loadInv]);
  useEffect(() => { reloadItems(); }, [scene?.scene_id, scene?.revision, scene?.status, reloadItems]);
  // Footer photo chips follow the scene on screen (a rebuild starting / finishing / failing).
  const prevShown = state.k === "previous" || state.k === "previous-failed";
  useEffect(() => { if (scene?.scene_id) loadScenes(); }, [scene?.scene_id, scene?.revision, prevShown, loadScenes]);

  const items = useMemo(() => inv.map((it, i) => {
    const a = anchors[it.item_id] || anchors[it.finding_id] || anchors[it.candidate_id] || null;
    const placed = it.located !== false && placedOn(a, scene);
    return { ...it, n: i + 1, anchor: a, placed, unplacedReason: placed ? null : whyUnplaced(it, a, scene) };
  }), [inv, anchors, scene]);
  const pins = useMemo(() => items.filter((i) => i.placed).map((i) => ({ item_id: i.item_id, n: i.n, label: i.label, xyz: i.anchor.xyz, u: i.anchor.u, v: i.anchor.v, scene_id: i.anchor.scene_id, scene_revision: i.anchor.scene_revision })), [items]);
  const sel = items.find((i) => i.item_id === itemId) || null;
  const original = absUrl(scene?.assets?.original?.url) || (photo ? mediaUrl(photo) : null);
  const ready = mode === "scene" && state.k === "ready"; // the current scene is on screen
  const live = mode === "scene" && ["ready", "previous", "previous-failed"].includes(state.k); // some scene revision is on screen

  function select(next, fromRow) {
    if (placing && placing.item_id !== next) setPlacing(null);
    setParams({ finding: next });
    const it = items.find((i) => i.item_id === next);
    if (fromRow && live && it?.placed) viewerRef.current?.focus(it.anchor.xyz); // restore its authored view
    if (!fromRow) setTimeout(() => document.querySelector(`[data-testid="scene-row-${next}"]`)?.scrollIntoView({ block: "nearest" }), 0);
  }
  async function decide(item, action, extra = {}) {
    setMsg(null);
    const cid = item.candidate_id || item.item_id;
    let rev = review?.candidates?.find((c) => c.uuid === cid)?.revision;
    try {
      if (rev == null) rev = (await api(`/evidence/${item.evidence_id}/analysis`)).candidates.find((c) => c.uuid === cid)?.revision;
      if (extra.corrected_category) await api(`/candidates/${cid}/decision`, { body: { action, expected_revision: rev, ...extra } });
      else await api(`/visual-candidates/${cid}/review`, { body: { action, expected_revision: rev, ...(extra.note ? { note: extra.note } : {}) } });
      setMsg({ tone: "success", text: { confirm: "Marked as confirmed.", correct: "Correction saved.", dismiss: "Marked as not an issue." }[action] || "Saved." });
      await Promise.all([reloadItems(), loadReview()]);
      return true;
    } catch (e) {
      setMsg({ tone: e?.status === 409 ? "warning" : "error", text: errText(e) });
      reloadItems();
      return false;
    }
  }
  function startMove(item) {
    setMsg(null);
    setPlacing({ item_id: item.item_id, point: item.anchor?.u != null ? [item.anchor.u, item.anchor.v] : null, reason: "", saving: false, prevMode: mode });
    if (mode !== "photo") setParams({ finding: item.item_id, mode: null, markers: null }); // the new spot is picked on the real photo
  }
  function endMove() {
    const back = placing?.prevMode;
    setPlacing(null);
    if (back === "scene") setParams({ mode: "3d" });
  }
  async function saveMove() {
    const it = items.find((i) => i.item_id === placing?.item_id);
    if (!it || !placing.point || !scene || (!it.anchor?.xyz && scene.contract !== "v2")) return;
    setPlacing((p) => ({ ...p, saving: true }));
    setMsg(null);
    try {
      const r = await moveAnchor(scene, it, placing.point, placing.reason.trim());
      setMsg({ tone: "success", text: "Marker moved and saved. Review status, quantities and documents are unchanged." });
      endMove();
      await reloadItems();
    } catch (e) {
      setPlacing((p) => p && { ...p, saving: false }); // keep the picked point and reason
      setMsg({ tone: e?.status === 409 ? "warning" : "error", text: errText(e) });
      if (e?.status === 409) reloadItems();
    }
  }
  const move = { placing, onStart: startMove, onChange: (patch) => setPlacing((p) => p && { ...p, ...patch }), onCancel: endMove, onSave: saveMove, canPlace: scene?.contract === "v2" && scene.status === "ready" && state.k !== "previous" && state.k !== "previous-failed" };

  async function saveView() {
    const c = viewerRef.current?.getCameraState();
    if (!c || !scene) return;
    try {
      await putView(scene, { camera: { position: c.position, target: c.target, fov_deg: c.fov }, selected_finding_id: itemId || null });
      setNotice("View saved for this scene.");
    } catch (e) {
      setNotice(`View not saved: ${errText(e)}`);
    }
  }
  async function restoreView() {
    try {
      const v = await getView(scene);
      if (v?.saved === false || !viewerRef.current?.setCameraState(v?.camera)) return setNotice("No saved view for this scene. Showing the capture view.");
      if (v.selected_finding_id && items.some((i) => i.item_id === v.selected_finding_id)) setParams({ finding: v.selected_finding_id });
      setNotice(`Saved view restored${v.updated_at ? ` (${new Date(v.updated_at).toLocaleString()})` : ""}.`);
    } catch (e) {
      setNotice(e?.status === 404 ? "No saved view for this scene." : errText(e));
    }
  }

  const canDecide = !!sel && (sel.kind === "candidate" || !!sel.candidate_id) && !(isForeman && review?.visit?.status === "Submitted");
  const statusText = mode === "photo" ? "Original photo" : STATES[state.k]?.[1] || state.k;
  const onState = useCallback((k) => setState({ k }), []);
  return (
    <div data-testid="scene-workspace" className={`flex min-h-screen flex-col bg-[#111315] font-[system-ui,-apple-system,'Segoe_UI',Arial,sans-serif] text-[14px] leading-snug ${WS.text} ${sel ? "pb-[36vh] md:pb-0" : ""}`}>
      <header className={`flex flex-wrap items-center gap-x-4 gap-y-1.5 border-b ${WS.line} bg-[#22272B] px-3 py-1.5 md:px-6`}>
        <Link to="/office/jobs" data-testid="scene-brand" className="rr-focus flex min-h-[44px] items-center gap-1.5 font-bold md:min-h-0 [@media(pointer:coarse)]:min-h-[44px]"><TrainFront aria-hidden className="h-4 w-4" />RailReady</Link>
        <nav aria-label="Breadcrumb" className="min-w-0 flex-1">
          <ol className="flex items-center gap-1 overflow-hidden whitespace-nowrap text-[13px] text-[#C9CED3] md:flex-wrap md:whitespace-normal">
            <li className="shrink-0"><Link to="/office/jobs" data-testid="scene-crumb-jobs" className={`rr-focus hover:underline ${TOUCH}`}>Jobs</Link> /</li>
            <li className="hidden truncate md:block">{review?.site?.name || "Site"} /</li>
            <li className="min-w-0 truncate"><Link to={`/office/visits/${id}${photo ? `?e=${photo}` : ""}`} data-testid="scene-crumb-visit" className={`rr-focus hover:underline ${TOUCH}`}>{review?.visit?.title || "Inspection"}</Link> /</li>
            <li aria-current="page" className="shrink-0 font-semibold text-[#E6E8EA]">Inspection</li>
          </ol>
        </nav>
        <div className="flex flex-wrap gap-1.5">
          <button type="button" data-testid="scene-toggle-original" aria-pressed={mode === "photo"} className={`${WS.btn} ${mode === "photo" ? WS.on : ""}`} onClick={() => setParams({ mode: mode === "photo" ? "3d" : null })}>
            {mode === "photo" ? <Box aria-hidden className="h-4 w-4" /> : <ImageIcon aria-hidden className="h-4 w-4" />}{mode === "photo" ? "3D view" : "Photo"}
          </button>
          <button type="button" data-testid="scene-show-items-to-check" aria-pressed={showReview} className={`${WS.btn} ${showReview ? WS.on : ""}`} onClick={() => setParams({ check: showReview ? null : "1" })}>
            {showReview ? <Eye aria-hidden className="h-4 w-4" /> : <EyeOff aria-hidden className="h-4 w-4" />}Show items to check
          </button>
          <button type="button" data-testid="scene-toggle-markers" aria-pressed={markers} className={`${WS.btn} ${markers ? WS.on : ""}`} onClick={() => setParams({ markers: markers ? "off" : null })}>
            {markers ? <Eye aria-hidden className="h-4 w-4" /> : <EyeOff aria-hidden className="h-4 w-4" />}Markers {markers ? "on" : "off"}
          </button>
          <button type="button" data-testid="scene-reset-view" className={WS.btn} disabled={!live} onClick={() => { setNotice(null); viewerRef.current?.reset(); }}><RotateCcw aria-hidden className="h-4 w-4" />Reset view</button>
          {scene?.contract === "v2" ? (
            <>
              <button type="button" data-testid="scene-save-view" className={WS.btn} disabled={!ready} onClick={saveView}><Bookmark aria-hidden className="h-4 w-4" />Save view</button>
              <button type="button" data-testid="scene-restore-view" className={WS.btn} disabled={!ready} onClick={restoreView}><BookmarkCheck aria-hidden className="h-4 w-4" />Saved view</button>
            </>
          ) : null}
        </div>
      </header>
      <Provenance scene={scene} filename={scenes?.find((s) => s.evidence_id === photo)?.filename} />
      {listErr && photo ? <p data-testid="scene-list-error" role="alert" className="border-b border-[#B35A55] bg-[#2A1B1A] px-3 py-1 text-[13px] text-[#F3C4C0]">{listErr}</p> : null}
      {invErr ? <p data-testid="scene-inventory-error" role="alert" className="border-b border-[#B35A55] bg-[#2A1B1A] px-3 py-1 text-[13px] text-[#F3C4C0]">Inventory: {invErr}</p> : null}
      <main className="grid grid-cols-1 content-start gap-px bg-[#2E3337] md:grid-cols-[170px_minmax(0,1fr)] min-[1200px]:grid-cols-[190px_minmax(0,1fr)_minmax(230px,300px)]">
        <div className={`order-2 flex max-h-[40vh] min-h-0 min-w-0 flex-col md:order-1 md:max-h-none ${SCENE_H.split(" ")[1]}`}>
          <Inventory items={items} selectedId={itemId} onSelect={select} />
        </div>
        <section aria-label="Scene" data-testid="scene-centre" data-state={state.k} data-scene-id={scene?.scene_id || ""} data-scene-revision={scene?.revision ?? ""} className={`relative order-1 min-h-0 min-w-0 overflow-hidden bg-[#0D0F10] md:order-2 ${SCENE_H}`}>
          {scenes ? (
            <PhotoInspectionView ref={viewerRef} photo={photo} mode={mode} showMarkers={markers} items={items} pins={pins} selectedId={itemId} onSelect={(x) => select(x, false)}
              placing={placing && placing.item_id === itemId ? placing : null} onPlace={(pt) => setPlacing((p) => p && { ...p, point: pt })}
              originalFallback={photo ? mediaUrl(photo) : null} onScene={setScene} onState={onState} onNotice={setNotice} onShowOriginal={() => setParams({ mode: null })} />
          ) : (
            <p data-testid="scene-state-loading" role="status" className="flex h-full items-center justify-center gap-2 text-[15px] font-bold"><StateIcon k="loading" />Loading photos...</p>
          )}
          {notice ? <p data-testid="scene-notice" role="status" className="absolute right-2 top-2 z-30 max-w-[60%] border border-[#4A5157] bg-[#111315] px-2 py-1 text-[12px]">{notice}</p> : null}
        </section>
        <div className={`order-3 min-w-0 md:col-span-2 min-[1200px]:col-span-1 min-[1200px]:h-[clamp(510px,64vh,640px)] ${sel ? "fixed inset-x-0 bottom-0 z-40 flex max-h-[36vh] flex-col border-t-2 border-[#3F8F8C] md:static md:max-h-none md:border-t-0" : "hidden md:flex md:flex-col"}`}>
          <EvidenceDrawer item={sel} visitId={id} originalHref={original} canDecide={canDecide} onDecide={decide} msg={msg} move={move} onClose={sel ? () => { setPlacing(null); setParams({ finding: null }); } : null} />
        </div>
      </main>
      <footer data-testid="scene-footer" className={`border-t ${WS.line} bg-[#1B1E21] px-3 py-1.5 text-[12px]`}>
        <div className="flex flex-wrap items-center gap-x-5 gap-y-1">
          <div role="list" aria-label="Photos in this visit" className="flex max-w-full gap-1.5 overflow-x-auto py-0.5">
            {(scenes || []).map((s, i) => (
              <button key={s.evidence_id} role="listitem" type="button" data-testid={`scene-photo-${s.evidence_id}`} aria-current={s.evidence_id === photo ? "true" : undefined}
                onClick={() => setSp(Object.fromEntries(Object.entries({ evidence: s.evidence_id, mode: mode === "scene" ? "3d" : null, markers: markers ? null : "off" }).filter(([, v]) => v)), { replace: true })}
                className={`rr-focus flex min-h-[44px] shrink-0 items-center gap-1.5 rounded-[3px] border px-1.5 text-left ${s.evidence_id === photo ? "border-[#3F8F8C] bg-[#1F3A3A]" : "border-[#4A5157] hover:bg-[#24282C]"}`}>
                <img src={absUrl(s.thumbnail_url) || mediaUrl(s.evidence_id)} alt="" className="h-9 w-12 bg-black object-cover" />
                <span className="leading-tight"><span className="block font-semibold">Photo {i + 1}</span><span className="block text-[#A9B0B6]">{s.error_code === "regeneration_failed" ? "Update didn't work" : s.status}</span></span>
              </button>
            ))}
          </div>
          <p data-testid="scene-footer-source" className="min-w-0 break-words text-[#C9CED3]">
            {isAdmin ? <>Source: {scene?.info?.source_filename || "-"} - Scene {scene?.scene_id ? `${String(scene.scene_id).slice(0, 12)} rev ${scene.revision}` : "-"} - Mode: {scene?.info?.mode || "-"} - </> : null}View: <span data-testid="scene-status">{statusText}</span>
          </p>
        </div>
      </footer>
    </div>
  );
}
