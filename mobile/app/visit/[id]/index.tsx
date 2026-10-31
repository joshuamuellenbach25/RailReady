import { router, useFocusEffect, useLocalSearchParams } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";
import { AppState, Platform, Pressable, ScrollView, View } from "react-native";
import { Image } from "expo-image";
import * as ImagePicker from "expo-image-picker";
import { setAudioModeAsync } from "expo-audio";
import { crumb, flushCrumbs } from "@/src/crumbs";
import { RecordSheet } from "@/src/recordSheet";
import { ReviewQuestions } from "@/src/reviewQuestions";
import { mediaUri } from "@/src/local/db";
import { api } from "@/src/api";
import { storage } from "@/src/utils/storage";
import { isOnline } from "@/src/queue";
import { useAuth } from "@/src/auth";
import * as repo from "@/src/local/repo";
import { usePermission } from "@/src/permissions";
import { isSyncing, subscribe, syncAll } from "@/src/sync";
import { Badge, Banner, Btn, Card, Empty, fmt, H, Icon, Input, Row, Screen, Sheet, T } from "@/src/ui";
import { useTheme } from "@/src/theme";
import { volumeModulePresent } from "@/src/volumeCapture";
import { RepairPanel } from "@/src/repairPanel";
import { NextStep, StepGuide, stepDone } from "@/src/stepGuide";

type FormKind = "note" | "measurement" | "location" | "not_inspected" | "urgent" | null;
const STAGES: Record<string, string[]> = { photo: ["image_analysis", "photo_analysis"], video: ["video_analysis"], audio: ["transcription", "extraction"], note: ["extraction"] };

// Quiet one-line processing status (details live in Evidence details).
const VIDEO_MAX_S = 60;
const VIDEO_MAX_MB = 200;

// C4: the server's result_state is shown as-is (Checking / Needs review / Partial result / Check failed / Cannot assess / No issues marked).
// "No issues marked" only ever comes from the server when a check completed with zero candidates.
function itemState(kind: string, synced: boolean, syncing: boolean, jobs?: Record<string, any>, needsReview?: boolean) {
  const noun = kind === "video" ? "video" : "photo";
  if (!synced) return kind === "photo" || kind === "video" ? (syncing ? "Uploading" : isOnline() === false ? "Waiting for connection" : "Saved on phone") : "Saved on phone";
  if (kind !== "photo" && kind !== "video") return "";
  // REQ-1610: held by the processing policy until an admin allows this item; the release watcher then starts the check
  if (jobs?.result_state === "unavailable" && jobs?.result_reason === "policy") return "Waiting for permission";
  if (jobs?.result_state === "failed") return "Could not finish the check";
  if (jobs?.result_label) return jobs.result_label as string;
  const js = (STAGES[kind] || []).map((s) => jobs?.[s]?.status).filter(Boolean);
  if (js.some((s) => s === "Failed")) return "Could not finish the check";
  if (js.some((s) => s === "Running" || s === "Queued")) return `Checking ${noun}`;
  return needsReview ? "Needs review" : "";
}

function Thumb({ uid, path }: { uid: string; path?: string }) {
  const [uri, setUri] = useState<string | null>(null);
  useEffect(() => {
    if (path) mediaUri(uid, path).then(setUri).catch(() => {});
  }, [uid, path]);
  return uri ? <Image source={{ uri }} style={{ width: 56, height: 56, borderRadius: 6 }} contentFit="cover" recyclingKey={uri} /> : <View style={{ width: 56, height: 56 }} />;
}

export default function VisitScreen() {
  const { id, step } = useLocalSearchParams<{ id: string; step?: string }>();
  const { user } = useAuth();
  const uid = user ? user.uuid : "";
  const { colors } = useTheme();
  const [visit, setVisit] = useState<repo.LocalVisit | null>(null);
  const [procKnown, setProcKnown] = useState(false); // results loaded at least once (Review is never "done" without them)
  const [openQ, setOpenQ] = useState<number | null>(null); // open review questions; unknown = Review not done
  const [bundle, setBundle] = useState<repo.Bundle | null>(null);
  const [ev, setEv] = useState<repo.LocalEvidence[]>([]);
  const [obs, setObs] = useState<repo.LocalObs[]>([]);
  const [proc, setProc] = useState<Record<string, any>>({});
  const [form, setForm] = useState<FormKind>(null);
  const [f, setF] = useState<Record<string, string>>({});
  const [toast, setToast] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [scn, setScn] = useState<Record<string, any>>({});
  const [loc, setLoc] = useState<any>(null);
  const [pol, setPol] = useState<{ allowed: boolean; message: string | null } | null>(null);
  const [recOpen, setRecOpen] = useState(false);
  const [seg, setSeg] = useState<"capture" | "review" | "details">(step === "review" || step === "details" ? step : "capture");
  const [lastStep, setLastStep] = useState(step); // a new ?step= from the step guide on another screen selects that step
  if (step !== lastStep) {
    setLastStep(step);
    if (step === "capture" || step === "review" || step === "details") setSeg(step);
  }
  const [sitesForMove, setSitesForMove] = useState<any[]>([]);
  const camBusy = useRef(false); // REQ-188 single-flight camera/picker lock
  const savingRef = useRef(false); // B5 single-flight form save
  const [saving, setSaving] = useState(false);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  const perm = usePermission(() => openForm("note"), () => addPhoto(false));

  // U3: in-flight reads are cancelled when the screen is left (and replaced by the next poll)
  const ctl = useRef<AbortController | null>(null);
  useFocusEffect(useCallback(() => () => ctl.current?.abort(), []));
  useEffect(() => () => ctl.current?.abort(), []);
  const load = useCallback(async () => {
    const v = await repo.getLocalVisit(uid, id);
    setVisit(v);
    if (!v) return;
    setBundle(await repo.getBundle(uid, v.site_id));
    setEv(await repo.listEvidence(uid, id));
    setObs(await repo.listObs(uid, id));
    if (v.sync.state === "Verified") {
      ctl.current?.abort();
      const c = new AbortController();
      ctl.current = c;
      const signal = c.signal;
      try {
        const [sv, p] = await Promise.all([api(`/visits/${id}`, { signal }), api(`/visits/${id}/processing`, { signal })]);
        if (signal.aborted) return;
        setProc(p.by_evidence);
        setProcKnown(true);
        api(`/visits/${id}/review-questions`, { signal }).then((q) => setOpenQ(q.questions.length)).catch(() => {});
        if (sv.location) setLoc(sv.location);
        api(`/visits/${id}/scenes`, { signal }).then((s) => setScn(Object.fromEntries(s.scenes.map((x: any) => [x.evidence_id, x])))).catch(() => {});
        api(`/visits/${id}/processing-policy`, { signal }).then(setPol).catch(() => {});
        if (sv.status !== v.status || sv.revision !== v.server_revision) {
          const nv = { ...v, status: sv.status, server_revision: sv.revision, processing_permission: v.pending_permission ? v.processing_permission : sv.processing_permission };
          await repo.saveVisit(uid, nv);
          setVisit(nv);
        }
      } catch {
        /* offline: device copy */
      }
    }
  }, [uid, id]);
  useFocusEffect(useCallback(() => { load(); }, [load]));
  useEffect(() => subscribe(load), [load]);
  useEffect(() => {
    const t = setInterval(load, 5000);
    // automatic backup while an inspection is open (honors backoff; no user action needed)
    if (uid) syncAll(uid).catch(() => {});
    const s = setInterval(() => { if (uid) syncAll(uid).catch(() => {}); }, 15_000);
    const a = AppState.addEventListener("change", (st) => { if (st === "active" && uid) syncAll(uid).catch(() => {}); });
    return () => { clearInterval(t); clearInterval(s); a.remove(); };
  }, [load, uid]);

  async function retryItem(kind: string, jobs: Record<string, any> | undefined) {
    const failed = (STAGES[kind] || []).map((s) => jobs?.[s]).filter((j) => j && j.status === "Failed" && j.uuid);
    try {
      for (const j of failed) await api(`/jobs/${j.uuid}/retry`, { method: "POST" });
      flash(failed.length ? "Checking again" : "Nothing to retry yet");
    } catch (e: any) {
      setErr(`Retry not started: ${e?.message || "try again"}`);
    }
    load();
  }

  function flash(msg: string) {
    setToast(msg);
    setTimeout(() => setToast(null), 3500);
  }
  function openForm(k: FormKind) {
    setF({});
    setErr(null);
    setForm(k);
  }
  // U3: unsent typed notes survive refresh / app restart / offline / permission failures until saved or closed
  const draftKey = `draft:${uid}:${id}`;
  const restored = useRef(false);
  useEffect(() => {
    if (restored.current || !uid) return;
    restored.current = true;
    storage.getItem<string | null>(draftKey, null).then((raw) => {
      const d = raw ? (JSON.parse(raw) as { form: FormKind; f: Record<string, string> }) : null;
      if (d?.form && Object.values(d.f || {}).some((x) => (x || "").trim()) && alive.current) {
        setForm(d.form);
        setF(d.f);
        flash("Your unsaved note is back");
      }
    });
  }, [uid, draftKey]);
  useEffect(() => {
    if (!uid || !restored.current) return;
    if (form && Object.values(f).some((x) => (x || "").trim())) storage.setItem(draftKey, JSON.stringify({ form, f }));
  }, [form, f, uid, draftKey]);
  function closeForm() {
    storage.removeItem(draftKey);
    setForm(null);
  }

  async function commitPhoto(a: ImagePicker.ImagePickerAsset) {
    const mime = a.mimeType || "image/jpeg";
    const ext = mime.includes("png") ? "png" : mime.includes("heic") || mime.includes("heif") ? "heic" : mime.includes("webp") ? "webp" : "jpg";
    await crumb("photo.copy_hash_commit");
    await repo.addMedia(uid, id, "photo", a.uri, mime, ext); // durable copy -> chunked hash -> commit -> read-back
    await crumb("photo.committed");
    if (!alive.current) return;
    flash(ext === "heic" ? "Photo saved" : "Photo saved");
    load();
    syncAll(uid).catch(() => {});
  }

  // Android may destroy the activity while the camera is open: recover the pending result on return.
  useEffect(() => {
    if (Platform.OS !== "android") return;
    ImagePicker.getPendingResultAsync().then(async (r: any) => {
      if (r && !("code" in r) && !r.canceled && r.assets?.[0]) {
        await crumb("photo.pending_result_recovered");
        commitPhoto(r.assets[0]).catch((e) => setErr(`Photo not saved: ${e?.message}`));
      }
    }).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function addPhoto(fromCamera: boolean) {
    if (camBusy.current) return; // ignore extra taps while a launch is in progress
    camBusy.current = true;
    setErr(null);
    try {
      const useCamera = fromCamera && Platform.OS !== "web";
      await crumb(useCamera ? "photo.tap_camera" : "photo.tap_library", `${Platform.OS} ${Platform.Version}`);
      if (useCamera && volumeModulePresent()) {
        // Phase 13: supported native builds use the in-app camera (shutter + volume buttons). Expo Go/web keep the picker.
        await crumb("photo.open_in_app_camera");
        router.push(`/camera/${id}`);
        return;
      }
      if (useCamera) {
        await crumb("photo.permission_check");
        const shown = await perm.ensure("camera"); // system permission always granted BEFORE launching the camera
        if (!shown) return crumb("photo.permission_not_granted");
        await setAudioModeAsync({ allowsRecording: false, playsInSilentMode: true }).catch(() => {}); // no recording session held
        await new Promise((r) => setTimeout(r, 450)); // let any permission sheet finish dismissing before presenting the camera
      }
      await crumb(useCamera ? "photo.launch_camera" : "photo.launch_library");
      const opts: ImagePicker.ImagePickerOptions = { mediaTypes: ["images"], quality: 0.8, exif: false, base64: false, allowsEditing: false };
      const r = useCamera ? await ImagePicker.launchCameraAsync(opts) : await ImagePicker.launchImageLibraryAsync(opts);
      await crumb("photo.returned", r.canceled ? "canceled" : `${r.assets?.[0]?.width}x${r.assets?.[0]?.height} ${r.assets?.[0]?.mimeType}`);
      if (r.canceled || !r.assets?.[0]) return;
      await commitPhoto(r.assets[0]);
    } catch (e: any) {
      await crumb("photo.error", e?.message);
      if (alive.current) setErr(fromCamera ? `Camera unavailable: ${e?.message ?? "unknown error"}. Use photo library instead.` : `Photo not saved: ${e?.message}`);
    } finally {
      camBusy.current = false;
      flushCrumbs();
    }
  }

  // Phase 12 video: limits are shown BEFORE recording/import (REQ-1241); over-limit or unsupported files are refused with a
  // reason and never truncated or silently dropped (REQ-1242). The original stays where it was (camera roll / not saved).
  const [videoAsk, setVideoAsk] = useState<null | "camera" | "library">(null);
  async function addVideo(fromCamera: boolean) {
    if (camBusy.current) return;
    camBusy.current = true;
    setErr(null);
    try {
      const useCamera = fromCamera && Platform.OS !== "web";
      await crumb(useCamera ? "video.tap_record" : "video.tap_choose");
      if (useCamera) {
        if (!(await perm.ensure("camera"))) return crumb("video.permission_not_granted");
        if (!(await perm.ensure("microphone"))) return crumb("video.mic_not_granted");
        await new Promise((r) => setTimeout(r, 450));
      }
      const opts: ImagePicker.ImagePickerOptions = { mediaTypes: ["videos"], videoMaxDuration: VIDEO_MAX_S, allowsEditing: false, quality: 1 };
      const r = useCamera ? await ImagePicker.launchCameraAsync(opts) : await ImagePicker.launchImageLibraryAsync(opts);
      await crumb("video.returned", r.canceled ? "canceled" : `${r.assets?.[0]?.duration}ms ${r.assets?.[0]?.fileSize}B ${r.assets?.[0]?.mimeType}`);
      if (r.canceled || !r.assets?.[0]) return;
      const a = r.assets[0];
      const secs = (a.duration || 0) / 1000;
      const mime = a.mimeType || (a.uri.toLowerCase().endsWith(".mov") ? "video/quicktime" : "video/mp4");
      if (secs > VIDEO_MAX_S + 0.5) return setErr(`Video not added: it is ${Math.round(secs)} s long and the limit is ${VIDEO_MAX_S} s. Nothing was cut. Trim it on your phone and choose it again.`);
      if ((a.fileSize || 0) > VIDEO_MAX_MB * 1024 * 1024) return setErr(`Video not added: it is over ${VIDEO_MAX_MB} MB. Nothing was cut. Record a shorter video.`);
      if (!/mp4|quicktime|m4v|3gpp/.test(mime)) return setErr("Video not added: this format is not supported. Use MP4 or MOV.");
      await repo.addMedia(uid, id, "video", a.uri, mime, mime.includes("quicktime") ? "mov" : "mp4", secs);
      await crumb("video.committed");
      if (!alive.current) return;
      flash("Video saved on phone");
      load();
      syncAll(uid).catch(() => {});
    } catch (e: any) {
      await crumb("video.error", e?.message);
      if (alive.current) setErr(`Video not saved: ${e?.message ?? "the camera did not return a file"}. Try again or choose a video.`);
    } finally {
      camBusy.current = false;
      flushCrumbs();
    }
  }

  async function openRecorder() {
    if (camBusy.current) return;
    camBusy.current = true;
    try {
      await crumb("record.tap", `${Platform.OS} ${Platform.Version}`);
      // Mic permission (explain sheet + system alert) is settled BEFORE the record sheet opens: no alert or second
      // RN Modal is ever presented over an open Modal (suspected iOS freeze).
      if (Platform.OS !== "web") {
        const ok = await perm.ensure("microphone");
        await crumb("record.permission_before_sheet", ok ? "granted" : "not granted");
        if (!ok) return;
        await new Promise((r) => setTimeout(r, 450)); // let the permission sheet finish dismissing
      }
      if (alive.current) setRecOpen(true);
    } finally {
      camBusy.current = false;
      flushCrumbs();
    }
  }

  async function saveRecording(uri: string, secs: number, interrupted: boolean) {
    const web = Platform.OS === "web";
    await repo.addMedia(uid, id, "audio", uri, web ? "audio/webm" : "audio/mp4", web ? "webm" : "m4a", secs);
    if (!alive.current) return;
    flash(interrupted ? "Recording stopped early - we kept what was recorded" : "Voice note saved");
    load();
    syncAll(uid).catch(() => {});
  }

  async function saveForm() {
    if (savingRef.current) return; // B5: one save per tap - a double tap must not create two records
    savingRef.current = true;
    setSaving(true);
    setErr(null);
    try {
      if (form === "note") {
        if (!f.text?.trim()) return setErr("Type the note first");
        await repo.addNote(uid, id, f.text.trim());
      } else if (form === "measurement") {
        if (!f.label?.trim() || !/^-?\d+(\.\d+)?$/.test((f.value || "").trim())) return setErr("Label and a number are required");
        await repo.addObservation(uid, id, { kind: "measurement", label: f.label.trim(), value: f.value.trim(), unit: f.unit?.trim() || undefined });
      } else if (form === "location") {
        if (!f.text?.trim()) return setErr("Location text required");
        await repo.addObservation(uid, id, { kind: "location", text: f.text.trim() });
      } else if (form === "not_inspected") {
        if (!f.area?.trim() || !f.reason?.trim()) return setErr("Area and reason are both required");
        await repo.addObservation(uid, id, { kind: "not_inspected", area: f.area.trim(), reason: f.reason.trim() });
      } else if (form === "urgent") {
        if (!f.text?.trim()) return setErr("Describe the concern");
        await repo.addObservation(uid, id, { kind: "finding", text: `URGENT CONCERN: ${f.text.trim()}` });
      }
      closeForm();
      flash("Saved");
      load();
      syncAll(uid).catch(() => {});
    } catch (e: any) {
      setErr("Not saved yet. Your text is still here. Tap Save again.");
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  }

  if (!visit) return <Screen title="Visit"><T muted>Visit not found on this device.</T></Screen>;
  const locked = visit.status === "Submitted";
  const unsynced = ev.filter((e) => e.sync.state !== "Verified").length + obs.filter((o) => o.sync.state !== "Verified").length;

  return (
    <Screen testID="visit-screen" title={visit.title} subtitle={visit.site_name}
      right={<T testID="visit-status-badge" size={13} style={{ color: colors.onSurfaceInverse }}>{visit.status}</T>}>
      <StepGuide testID="visit-segments" current={seg} onGo={setSeg} repair={!!visit.repair} done={stepDone(visit, ev, obs, procKnown ? proc : null, openQ)} />
      {toast ? <Banner testID="visit-saved-toast" tone="success" icon="content-save-check-outline" text={toast} /> : null}
      {err ? <Banner testID="visit-error-message" tone="error" icon="alert-circle-outline" text={err} /> : null}
      {locked ? <Banner testID="visit-locked-banner" tone="info" icon="lock-outline" text="Submitted - ask estimator to reopen. This inspection is read-only." /> : null}

      {pol && !pol.allowed ? (
        <T testID="visit-policy-message" muted size={13}>Automatic photo checks are turned off for this site. You can still capture and review everything.</T>
      ) : null}

      {seg === "review" ? <ReviewQuestions visitId={id} locked={locked} available={visit.sync.state === "Verified"} onTakePhoto={() => { setSeg("capture"); addPhoto(true); }} /> : null}

      {seg === "details" ? (
        <View testID="visit-details" style={{ gap: 12 }}>
          {visit.repair ? <RepairPanel uid={uid} visit={visit} onChange={load} /> : null}
          <Card testID="visit-location-card">
            <T bold>Location</T>
            <T size={14} testID="visit-location">{(() => {
              const l = loc || visit.links?.location;
              if (!l) return "Location: Not set";
              const rail = [l.railroad, l.subdivision, l.milepost ? `MP ${l.milepost}` : null].filter(Boolean).join(", ");
              return `${Number(l.lat).toFixed(6)}, ${Number(l.lon).toFixed(6)} - ${l.method_label}${rail ? ` - ${rail}` : ""}`;
            })()}</T>
          </Card>
          <Card>
            <T bold size={16}>{visit.title}</T>
            <T muted size={13}>{visit.site_name} - started {fmt(visit.created_at)}</T>
            <T muted size={13} testID="visit-sync-line">{unsynced ? `${unsynced} item${unsynced === 1 ? "" : "s"} not backed up yet` : "Everything is backed up"}</T>
            {visit.manifest ? <T testID="visit-transfer-state" muted size={13}>Transfer: {visit.manifest.state}</T> : null}
          </Card>
          {visit.sync.state === "Blocked" && !locked ? (
            <Card testID="visit-reconcile-card">
              <T bold>This inspection couldn&apos;t be filed under {visit.site_name}</T>
              <T muted size={13}>{visit.sync.error || "This site isn't on your list."} Choose one of your assigned sites; all captures move with it.</T>
              {sitesForMove.map((s) => (
                <Btn key={s.uuid} small kind="secondary" testID={`visit-reconcile-site-${s.uuid}`} title={s.name} icon="map-marker-outline"
                  onPress={async () => {
                    await repo.saveVisit(uid, { ...visit, site_id: s.uuid, site_name: s.name, sync: { state: "Queued", attempts: 0 } });
                    flash(`Moved to ${s.name}`);
                    load();
                    syncAll(uid, true).catch(() => {});
                  }} />
              ))}
              {!sitesForMove.length ? <Btn small kind="secondary" testID="visit-reconcile-load-sites" title="Show my sites" icon="refresh" onPress={() => api("/sites").then(setSitesForMove).catch(() => setErr("No connection right now - try again in a moment."))} /> : null}
            </Card>
          ) : null}
          <Btn testID="visit-departure-button" title="Departure check & submit" icon="flag-checkered" disabled={visit.sync.state !== "Verified"} onPress={() => router.push(`/visit/${id}/departure`)} />
          <Btn testID="visit-fields-button" kind="secondary" title="All answers" icon="format-list-checks" disabled={visit.sync.state !== "Verified"} onPress={() => router.push(`/visit/${id}/fields`)} />
          {user && user.role === "admin" ? <Btn testID="visit-outbox-button" kind="secondary" title="Diagnostics (admin)" icon="stethoscope" onPress={() => router.push("/outbox")} /> : null}
          {visit.sync.state !== "Verified" ? <T muted size={13}>Review and finish open once your items are backed up. Everything is safe on this phone.</T> : null}
        </View>
      ) : null}

      {seg === "capture" && !locked ? (
        <View testID="visit-capture-card" style={{ gap: 8 }}>
          <Row style={{ flexWrap: "nowrap" }}>
            <Btn testID="capture-take-photo-button" title={Platform.OS === "web" ? "Add photo" : "Take photo"} icon="camera-outline" onPress={() => addPhoto(true)} style={{ flex: 1, minHeight: 56 }} />
            <Btn testID="capture-pick-photo-button" kind="secondary" title="Choose photo" icon="image-outline" onPress={() => addPhoto(false)} style={{ flex: 1, minHeight: 56 }} />
          </Row>
          <Row style={{ flexWrap: "nowrap" }}>
            <Btn testID="capture-record-video-button" kind="secondary" title="Record video" icon="video-outline" onPress={() => setVideoAsk("camera")} style={{ flex: 1 }} />
            <Btn testID="capture-choose-video-button" kind="secondary" title="Choose video" icon="filmstrip" onPress={() => setVideoAsk("library")} style={{ flex: 1 }} />
          </Row>
          <Row style={{ flexWrap: "nowrap" }}>
            <Btn testID="capture-record-button" kind="secondary" icon="microphone-outline" title="Record note" onPress={openRecorder} style={{ flex: 1 }} />
            <Btn testID="capture-note-button" kind="secondary" title="Type note" icon="note-text-outline" onPress={() => openForm("note")} style={{ flex: 1 }} />
          </Row>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8 }} style={{ flexGrow: 0 }}>
            <Btn small testID="capture-measurement-button" kind="ghost" title="Measurement" icon="ruler" onPress={() => openForm("measurement")} style={{ flexShrink: 0 }} />
            <Btn small testID="capture-location-button" kind="ghost" title="Location" icon="map-marker-outline" onPress={() => openForm("location")} style={{ flexShrink: 0 }} />
            <Btn small testID="capture-not-inspected-button" kind="ghost" title="Not inspected" icon="eye-off-outline" onPress={() => openForm("not_inspected")} style={{ flexShrink: 0 }} />
            <Btn small testID="capture-urgent-button" kind="ghost" title="Urgent concern" icon="alert-octagon-outline" onPress={() => openForm("urgent")} style={{ flexShrink: 0 }} />
          </ScrollView>
        </View>
      ) : null}

      {seg === "capture" ? <H>Evidence ({ev.length + obs.length})</H> : null}
      {seg === "capture" && !ev.length && !obs.length ? <Empty testID="visit-empty" icon="camera-outline" text="Nothing captured yet. Photos, recordings and notes appear here in order." /> : null}
      {seg !== "capture" ? null : [...ev.map((e) => ({ t: e.captured_at, e, o: undefined as repo.LocalObs | undefined })), ...obs.map((o) => ({ t: o.captured_at, e: undefined as repo.LocalEvidence | undefined, o }))]
        .sort((a, b) => String(b.t).localeCompare(String(a.t))).map((x) => x.e ? (
        <Pressable key={x.e.uuid} testID={`visit-item-${x.e.uuid}`} onPress={() => router.push(`/evidence/${x.e!.uuid}?visit=${id}`)}
          style={({ pressed }) => ({ opacity: pressed ? 0.8 : 1 })}>
          <Card>
            <Row style={{ flexWrap: "nowrap" }}>
              {x.e.kind === "photo" ? <Thumb uid={uid} path={x.e.path} /> : <Icon name={x.e.kind === "audio" ? "waveform" : "note-text-outline"} size={22} color={colors.onSurface} />}
              <View style={{ flex: 1, gap: 2 }}>
                <T bold>{x.e.kind === "photo" ? "Photo" : x.e.kind === "audio" ? `Recording ${x.e.duration_s ?? ""}s` : "Note"}</T>
                {x.e.kind === "note" ? <T numberOfLines={2} size={14}>{x.e.text}</T> : null}
                {itemState(x.e.kind, x.e.sync.state === "Verified", isSyncing(), proc[x.e.uuid], proc[x.e.uuid]?.needs_review) ? (
                  <Badge testID={`visit-item-state-${x.e.uuid}`} label={itemState(x.e.kind, x.e.sync.state === "Verified", isSyncing(), proc[x.e.uuid], proc[x.e.uuid]?.needs_review)} />
                ) : null}
                {proc[x.e.uuid]?.result_state === "complete" && proc[x.e.uuid]?.result_empty_copy ? <T size={13} testID={`visit-item-result-${x.e.uuid}`}>{proc[x.e.uuid].result_empty_copy}</T> : null}
                {itemState(x.e.kind, x.e.sync.state === "Verified", isSyncing(), proc[x.e.uuid], proc[x.e.uuid]?.needs_review) === "Could not finish the check" ? (
                  <Btn small kind="secondary" testID={`visit-item-retry-${x.e.uuid}`} icon="refresh" title="Retry" onPress={() => retryItem(x.e!.kind, proc[x.e!.uuid])} />
                ) : null}
              </View>
              <Icon name="chevron-right" size={20} color={colors.muted} />
            </Row>
          </Card>
        </Pressable>
      ) : (
        <Card key={x.o!.uuid} testID={`visit-obs-${x.o!.uuid}`}>
          <Row style={{ flexWrap: "nowrap" }}>
            <Icon name={x.o!.kind === "not_inspected" ? "eye-off-outline" : x.o!.kind === "measurement" ? "ruler" : x.o!.kind === "location" ? "map-marker-outline" : "alert-octagon-outline"} size={22} color={colors.onSurface} />
            <View style={{ flex: 1, gap: 2 }}>
              <T bold>{x.o!.kind === "not_inspected" ? "Not inspected" : x.o!.kind === "measurement" ? "Measurement" : x.o!.kind === "location" ? "Location" : "Finding"}</T>
              <T size={14}>{x.o!.kind === "measurement" ? `${x.o!.label}: ${x.o!.value} ${x.o!.unit || ""}` : x.o!.kind === "not_inspected" ? `${x.o!.area} - reason: ${x.o!.reason}` : x.o!.text}</T>
            </View>
          </Row>
        </Card>
      ))}

      {seg === "capture" ? <NextStep to="review" repair={!!visit.repair} onPress={() => setSeg("review")} /> : null}
      {seg === "review" ? <NextStep to="details" repair={!!visit.repair} onPress={() => setSeg("details")} /> : null}

      <Sheet visible={!!videoAsk} onClose={() => setVideoAsk(null)} title="Video limits" testID="video-limits-sheet">
        <T testID="video-limits-text">Up to {VIDEO_MAX_S} seconds and {VIDEO_MAX_MB} MB. MP4 or MOV. Longer videos are refused, never cut.</T>
        <Btn testID="video-limits-continue-button" title="Continue" icon="check" onPress={() => { const m = videoAsk; setVideoAsk(null); setTimeout(() => addVideo(m === "camera"), 350); }} />
        <Btn testID="video-limits-cancel-button" kind="ghost" title="Cancel" onPress={() => setVideoAsk(null)} />
      </Sheet>
      <Sheet visible={!!form} onClose={closeForm} testID="capture-form-sheet"
        title={{ note: "Typed note", measurement: "Manual measurement", location: "Location", not_inspected: "Not inspected area", urgent: "Urgent concern", x: "" }[form || "x"] as string}>
        {form === "urgent" ? (
          <Banner testID="urgent-escalation-text" tone="error" icon="phone-alert" text={bundle?.data?.escalation_text || "Follow your company escalation procedure."}>
            <T bold style={{ color: colors.onError }}>Saving does not notify anyone.</T>
          </Banner>
        ) : null}
        {form === "note" || form === "location" || form === "urgent" ? (
          <Input testID="capture-form-text-input" label={form === "location" ? "Location (track, mile post, landmark)" : "Text"} multiline={form !== "location"} value={f.text || ""} onChangeText={(t) => setF({ ...f, text: t })} />
        ) : null}
        {form === "measurement" ? (
          <>
            <Input testID="capture-form-label-input" label="What was measured" value={f.label || ""} onChangeText={(t) => setF({ ...f, label: t })} placeholder="e.g. gauge at MP 2.1" />
            <Input testID="capture-form-value-input" label="Value" keyboardType="decimal-pad" value={f.value || ""} onChangeText={(t) => setF({ ...f, value: t })} />
            <Input testID="capture-form-unit-input" label="Unit" value={f.unit || ""} onChangeText={(t) => setF({ ...f, unit: t })} placeholder="in, ft, mm" />
          </>
        ) : null}
        {form === "not_inspected" ? (
          <>
            <Input testID="capture-form-area-input" label="Area not inspected" value={f.area || ""} onChangeText={(t) => setF({ ...f, area: t })} />
            <Input testID="capture-form-reason-input" label="Reason" multiline value={f.reason || ""} onChangeText={(t) => setF({ ...f, reason: t })} />
            <T muted>No quantities are recorded for areas not inspected.</T>
          </>
        ) : null}
        {err ? <Banner tone="error" icon="alert" text={err} /> : null}
        <Btn testID="capture-form-save-button" title="Save" icon="content-save" loading={saving} disabled={saving} onPress={saveForm} />
      </Sheet>
      {perm.element}
      <RecordSheet visible={recOpen} onClose={() => setRecOpen(false)} onSaved={saveRecording} />
      <View style={{ height: 8 }} />
    </Screen>
  );
}
