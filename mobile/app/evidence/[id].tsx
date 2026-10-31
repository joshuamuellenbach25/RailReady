import { useFocusEffect, useLocalSearchParams } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";
import { Pressable, View } from "react-native";
import { Image } from "expo-image";
import { useAudioPlayer, useAudioPlayerStatus } from "expo-audio";
import { API, ApiError, api, errText, getToken, mediaUrl } from "@/src/api";
import { Seek, VideoPlayer } from "@/src/videoPlayer";
import { useAuth } from "@/src/auth";
import { mediaUri } from "@/src/local/db";
import * as repo from "@/src/local/repo";
import { Badge, Banner, Btn, Card, fmt, H, Input, Row, Screen, Sheet, T } from "@/src/ui";
import { useTheme } from "@/src/theme";
import { goToStep, NextStep, StepGuide, useStepProgress } from "@/src/stepGuide";

const STAGE_LABEL: Record<string, string> = { image_analysis: "Photo check", transcription: "Voice to text", extraction: "Reading notes" };
const CATS = ["possible missing/displaced fastener", "visible tie-surface deterioration", "other visible condition"];
// Phase 8: plain wording only (no model/AI/score language). Internal categories stay in the database.
export const CAT_PLAIN: Record<string, string> = {
  "possible missing/displaced fastener": "Possible missing or loose fastening",
  "visible tie-surface deterioration": "Possible damaged tie",
  "other visible condition": "Something else worth a look",
  // rail_surface_v1 (joint is a normal component, not damage)
  crack: "Possible crack in the rail",
  flaking: "Possible flaking on the rail top",
  groove: "Possible groove worn into the rail",
  joint: "Rail joint",
  shelling: "Possible shelling on the rail",
  spalling: "Possible chipped rail surface",
  squat: "Possible squat (dent) on the rail top",
};
const RS_CATS = ["crack", "flaking", "groove", "joint", "shelling", "spalling", "squat"];
const TERMINAL = ["complete", "partial", "failed", "unavailable", "needs_review"];
const fmtT = (t: number) => `${Math.floor(t / 60)}:${(t % 60).toFixed(1).padStart(4, "0")}`;

function FrameView({ evidenceId, c }: { evidenceId: string; c: any }) {
  const { colors } = useTheme();
  const f = c.frame;
  if (!f) return null;
  const ratio = f.width && f.height ? f.width / f.height : 16 / 9;
  return (
    <View testID={`finding-frame-${c.uuid}`} style={{ width: "100%", aspectRatio: ratio, backgroundColor: colors.surfaceInverse, borderRadius: 8, overflow: "hidden" }}>
      <Image source={{ uri: `${API}/evidence/${evidenceId}/frames/${f.id}?auth=${encodeURIComponent(getToken() || "")}` }} style={{ width: "100%", height: "100%" }} contentFit="contain" />
      {Array.isArray(c.region) ? (
        <View testID={`finding-region-${c.uuid}`} pointerEvents="none"
          style={{ position: "absolute", left: `${c.region[0] * 100}%`, top: `${c.region[1] * 100}%`, width: `${c.region[2] * 100}%`, height: `${c.region[3] * 100}%`,
            borderWidth: 2, borderColor: c.review_state === "Dismissed" ? colors.muted : colors.brandPrimary, borderStyle: c.review_state === "Dismissed" ? "dashed" : "solid" }} />
      ) : null}
    </View>
  );
}

function StageRow({ stage, job, onRetry }: { stage: string; job: any; onRetry: () => void }) {
  return (
    <View style={{ gap: 6 }} testID={`stage-${stage}`}>
      <Row>
        <Badge testID={`stage-${stage}-status`} prefix={STAGE_LABEL[stage]} label={job?.status || "Not started"} />
        {job?.attempts ? <T muted size={12}>attempts {job.attempts}</T> : null}
      </Row>
      {job?.blocker ? <Banner testID={`stage-${stage}-blocker`} tone="warning" icon="cancel" text={job.blocker} /> : null}
      {job?.status === "Failed" ? (
        <>
          <Banner testID={`stage-${stage}-error`} tone="error" icon="alert-circle-outline" text="This step didn't finish. You can try again - nothing needs to be re-taken." />
          <Btn testID={`stage-${stage}-retry-button`} small title="Try again" icon="refresh" onPress={onRetry} />
        </>
      ) : null}
    </View>
  );
}

function PhotoOverlay({ uri, candidates }: { uri: string; candidates: any[] }) {
  const { colors } = useTheme();
  const [ratio, setRatio] = useState(4 / 3);
  return (
    <View testID="photo-overlay" style={{ width: "100%", aspectRatio: ratio, backgroundColor: colors.surfaceInverse, borderRadius: 8, overflow: "hidden" }}>
      <Image source={{ uri }} style={{ width: "100%", height: "100%" }} contentFit="contain" onLoad={(e) => e.source?.width && setRatio(e.source.width / e.source.height)} />
      {candidates.map((c, i) =>
        c.region ? (
          <View key={c.uuid} testID={`candidate-region-${i + 1}`} pointerEvents="none"
            style={{ position: "absolute", left: `${c.region[0] * 100}%`, top: `${c.region[1] * 100}%`, width: `${c.region[2] * 100}%`, height: `${c.region[3] * 100}%`,
              borderWidth: 2, borderColor: c.review_state === "Dismissed" ? colors.muted : colors.brandPrimary, borderStyle: c.review_state === "Dismissed" ? "dashed" : "solid" }}>
            <View style={{ backgroundColor: colors.brandPrimary, alignSelf: "flex-start", paddingHorizontal: 6 }}>
              <T bold style={{ color: colors.onBrandPrimary }}>{i + 1}</T>
            </View>
          </View>
        ) : null,
      )}
    </View>
  );
}

function AudioBox({ uri }: { uri: string }) {
  const player = useAudioPlayer(uri);
  const st = useAudioPlayerStatus(player);
  return (
    <Card testID="audio-player">
      <Row>
        <Btn testID="audio-play-button" small icon={st.playing ? "pause" : "play"} title={st.playing ? "Pause" : "Play"}
          onPress={() => { if (st.playing) player.pause(); else { if (st.didJustFinish || (st.duration && st.currentTime >= st.duration - 0.1)) player.seekTo(0); player.play(); } }} />
        <T testID="audio-position">{Math.floor(st.currentTime || 0)}s / {Math.floor(st.duration || 0)}s</T>
      </Row>
    </Card>
  );
}

function TextChecks({ evidenceId, visible }: { evidenceId: string; visible: boolean }) {
  const { colors } = useTheme();
  const [d, setD] = useState<any>(null);
  useEffect(() => {
    if (!visible) return;
    const f = () => api(`/evidence/${evidenceId}/text-checks`).then(setD).catch(() => {});
    f();
    const t = setInterval(f, 5000);
    return () => clearInterval(t);
  }, [evidenceId, visible]);
  if (!d) return null;
  const urgent = d.checks.some((c: any) => c.status === "Done" && c.check?.result?.urgent);
  if (!urgent) return null; // only the urgent-concern reminder is user-facing; other checks stay internal
  return (
    <Card testID="text-checks-card">
      {d.checks.map((c: any, i: number) => {
        const r = c.check?.result;
        return (
          <View key={c.target_id} style={{ gap: 6 }} testID={`text-check-${i}`}>
            {c.status !== "Done" ? null : (
              <>
                {r.urgent ? (
                  <Banner testID={`text-check-urgent-${i}`} tone="error" icon="alert-octagon-outline" text="This sounds urgent - follow your escalation steps">
                    <T>{d.escalation_text}</T>
                    <T bold>Saving does not notify anyone.</T>
                  </Banner>
                ) : null}
                {null}
                {null}
              </>
            )}
          </View>
        );
      })}
    </Card>
  );
}

export default function EvidenceScreen() {
  const { id, visit } = useLocalSearchParams<{ id: string; visit?: string }>();
  const { user } = useAuth();
  const uid = user ? user.uuid : "";
  const [local, setLocal] = useState<repo.LocalEvidence | null>(null);
  const [uri, setUri] = useState<string | null>(null);
  const [server, setServer] = useState<any>(null);
  const [kind, setKind] = useState<string | null>(null);
  const [transcripts, setTranscripts] = useState<any[]>([]);
  const [jobs, setJobs] = useState<Record<string, any>>({});
  const [msg, setMsg] = useState<{ tone: any; text: string } | null>(null);
  const [correctFor, setCorrectFor] = useState<any>(null);
  const [corr, setCorr] = useState({ category: CATS[0], note: "" });
  const [manual, setManual] = useState<string | null>(null);
  const [seek, setSeek] = useState<Seek>(null);
  const ctl = useRef<AbortController | null>(null);
  const terminal = useRef(false);
  const [tEdit, setTEdit] = useState<string | null>(null);
  const [locked, setLocked] = useState(false);
  const stepVid = visit || local?.visit_id || null;
  const steps = useStepProgress(uid, stepVid);
  const [details, setDetails] = useState(false);

  const load = useCallback(async () => {
    const l = uid ? await repo.getEvidence(uid, id) : null;
    setLocal(l);
    if (l) {
      setKind(l.kind);
      if (l.path) setUri(await mediaUri(uid, l.path));
    }
    if (l && l.sync.state !== "Verified") return;
    // U3: one in-flight load per photo; switching photo / leaving the screen cancels the stale one
    ctl.current?.abort();
    const c = new AbortController();
    ctl.current = c;
    const signal = c.signal;
    try {
      const vid = visit || l?.visit_id;
      const p = vid ? await api(`/visits/${vid}/processing`, { signal }) : null;
      if (signal.aborted) return;
      setJobs(p?.by_evidence?.[id] || {});
      const evs = vid ? await api(`/visits/${vid}/evidence`, { signal }) : [];
      if (signal.aborted) return;
      const e = evs.find((x: any) => x.uuid === id);
      if (e) {
        setKind(e.kind);
        if (!l && e.kind !== "note") setUri(mediaUrl(id));
      }
      if ((l?.kind || e?.kind) === "photo" || (l?.kind || e?.kind) === "video") {
        const a = await api(`/evidence/${id}/analysis`, { signal });
        if (signal.aborted) return;
        setServer(a);
        terminal.current = TERMINAL.includes(a.result_state); // stop auto-refresh once the server state is final
        setLocked(a.visit_status === "Submitted" && !!user && user.role === "foreman");
      } else if ((l?.kind || e?.kind) === "audio") {
        const ts = await api(`/evidence/${id}/transcripts`, { signal });
        if (!signal.aborted) setTranscripts(ts);
      }
      if (!l && e) setServer((s: any) => ({ ...(s || {}), evidence: e }));
    } catch {
      /* offline */
    }
  }, [uid, id, visit, user]);
  useFocusEffect(useCallback(() => {
    terminal.current = false;
    load();
    const t = setInterval(() => { if (!terminal.current) load(); }, 4000);
    return () => { clearInterval(t); ctl.current?.abort(); }; // leaving the screen or switching evidence aborts stale reads
  }, [load]));

  async function retry(stage: string) {
    try {
      await api(`/jobs/${jobs[stage].uuid}/retry`, { method: "POST" });
      setMsg({ tone: "info", text: "Trying again - nothing needs to be re-taken." });
      load();
    } catch (e) {
      setMsg({ tone: "error", text: errText(e) });
    }
  }

  async function decide(c: any, action: string, extra: any = {}) {
    try {
      // same expected_revision on a timeout retry: the server returns the decision that already won (no second operation)
      await api(`/candidates/${c.uuid}/decision`, { body: { action, expected_revision: c.revision, ...extra }, sameKeyRetries: 1 });
      setMsg({ tone: "success", text: action === "confirm" ? "Thanks - added to the inspection." : action === "dismiss" ? "Thanks - we'll leave it out." : action === "request_closer_photo" ? "Noted - please take a closer photo." : "Thanks - your correction is saved." });
      setCorrectFor(null);
      terminal.current = false;
      load();
    } catch (e) {
      if (e instanceof ApiError && e.status === 409 && e.detail?.server) {
        if (uid && local) await repo.saveRecovery(uid, { visit_id: local.visit_id, what: CAT_PLAIN[c.category] || "Photo question", value: action, server_value: e.detail.server.review_state });
        setMsg({ tone: "warning", text: "Someone else answered this at the same time - showing the latest answer." });
        load();
      } else setMsg({ tone: "error", text: errText(e) });
    }
  }

  async function addManual() {
    if (!manual?.trim()) return;
    const vid = visit || local?.visit_id;
    try {
      if (user && user.role === "foreman" && vid) await repo.addObservation(uid, vid, { kind: "finding", text: `${manual.trim()} (photo ${id.slice(0, 8)})` });
      else await api(`/visits/${vid}/observations`, { body: { uuid: `${Date.now()}-${Math.random().toString(16).slice(2)}`, kind: "finding", text: manual.trim() }, sameKeyRetries: 1 });
      setManual(null);
      setMsg({ tone: "success", text: "Note saved" });
    } catch (e) {
      setMsg({ tone: "error", text: errText(e) });
    }
  }

  async function saveTranscript() {
    const latest = transcripts[transcripts.length - 1];
    try {
      await api(`/evidence/${id}/transcripts`, { body: { text: tEdit, base_version: latest.version } });
      setTEdit(null);
      setMsg({ tone: "success", text: "Corrected version saved. Machine version kept." });
      load();
    } catch (e) {
      setMsg({ tone: "error", text: errText(e) });
    }
  }

  const cands: any[] = server?.candidates || [];
  const lastRun = server?.runs?.[server.runs.length - 1];
  const synced = !local || local.sync.state === "Verified";
  return (
    <Screen testID="evidence-screen" title={kind === "photo" ? "Photo" : kind === "video" ? "Video" : kind === "audio" ? "Recording" : "Note"} subtitle={local ? fmt(local.captured_at) : undefined}>
      {stepVid ? <StepGuide testID="evidence-steps" current="review" done={steps.done} repair={steps.repair} onGo={(s) => goToStep(stepVid, s)} /> : null}
      {msg ? <Banner testID="evidence-message" tone={msg.tone} icon="information" text={msg.text} /> : null}
      {kind === "photo" && uri ? <PhotoOverlay uri={uri} candidates={cands} /> : null}
      {kind === "video" && uri ? <VideoPlayer testID="evidence-video-player" uri={uri} token={getToken()} seek={seek} /> : null}
      {(kind === "video" || kind === "photo") && synced && server?.result_label ? (
        <Card testID="evidence-result-state">
          <T bold testID="evidence-result-label">{server.result_label}</T>
          {server.result_empty_copy ? <T testID="evidence-result-empty" size={14}>{server.result_empty_copy}</T> : null}
        </Card>
      ) : null}
      {kind === "video" && cands.length ? (
        <Card testID="evidence-video-moments">
          {cands.map((c: any) => (
            <Pressable key={c.uuid} testID={`evidence-video-moment-${c.uuid}`} accessibilityRole="button"
              onPress={() => setSeek({ t: c.timestamp_s ?? 0, n: Date.now() })} style={{ minHeight: 44, justifyContent: "center" }}>
              <T>{CAT_PLAIN[c.category] || "Something worth a look"} at {(c.timestamps_s || [c.timestamp_s]).map((t: number) => fmtT(t)).join(", ")}</T>
            </Pressable>
          ))}
        </Card>
      ) : null}
      {kind === "audio" && uri ? <AudioBox uri={uri} /> : null}
      {kind === "note" ? <Card><T size={16} testID="evidence-note-text">{local?.text || server?.evidence?.text}</T></Card> : null}
      {user && user.role === "admin" ? (
        <Pressable testID="evidence-details-toggle" accessibilityRole="button" onPress={() => setDetails(!details)} style={{ minHeight: 44, justifyContent: "center" }}>
          <T muted size={13}>{details ? "Hide diagnostics" : "Diagnostics (admin)"}</T>
        </Pressable>
      ) : null}
      {details && user && user.role === "admin" ? (
        <Card testID="evidence-details">
          {local ? <T testID="evidence-upload-badge" muted size={12}>{`state ${local.sync.state}`}</T> : null}
          {local ? <T muted size={12}>{`sha256 ${local.sha256} - ${local.size} B`}</T> : null}
          {lastRun ? <T muted size={12}>{`${lastRun.model_id} - ${lastRun.prompt_version} - ${lastRun.duration_s}s`}</T> : null}
          {(kind === "photo" ? ["image_analysis"] : kind === "video" ? ["video_analysis"] : kind === "audio" ? ["transcription", "extraction"] : ["extraction"]).map((s) => (
            <T key={s} muted size={12}>{`${s}: ${jobs[s]?.status || "-"}${jobs[s]?.error ? ` - ${jobs[s].error}` : ""}`}</T>
          ))}
        </Card>
      ) : null}

      {kind === "note" || kind === "audio" ? <TextChecks evidenceId={id} visible={synced} /> : null}
      {synced ? (kind === "photo" ? ["image_analysis"] : kind === "video" ? ["video_analysis"] : kind === "audio" ? ["transcription", "extraction"] : ["extraction"]).filter((s) => jobs[s]?.status === "Failed").map((s) => (
        <StageRow key={s} stage={s} job={jobs[s]} onRetry={() => retry(s)} />
      )) : null}

      {kind === "photo" && lastRun?.status === "Done" && lastRun.cannot_assess_reason ? (
        <T testID="analysis-cannot-assess-reason" size={14}>Hard to see clearly in this photo - a closer photo would help.</T>
      ) : null}
      {cands.map((c, i) => (
        <Card key={c.uuid} testID={`candidate-card-${i + 1}`}>
          <T bold size={16}>{CAT_PLAIN[c.category] || "Something worth a look"} - does this look right?</T>
          {kind === "video" ? (
            <>
              <Pressable testID={`candidate-seek-${i + 1}`} accessibilityRole="button" onPress={() => setSeek({ t: c.timestamp_s ?? 0, n: Date.now() })} style={{ minHeight: 44, justifyContent: "center" }}>
                <T size={14} style={{ textDecorationLine: "underline" }}>Seen at {(c.timestamps_s || [c.timestamp_s]).map((t: number) => fmtT(t)).join(", ")}. Tap to play from here.</T>
              </Pressable>
              <FrameView evidenceId={id} c={c} />
              {!Array.isArray(c.region) ? <T testID={`candidate-image-level-${i + 1}`} muted size={13}>Applies to the whole frame. No exact spot marked.</T> : null}
            </>
          ) : null}
          {c.visible_reason ? <T size={14}>{c.visible_reason}</T> : null}
          {c.review_state !== "Pending" ? <T testID={`candidate-state-${i + 1}`} muted size={13}>{c.review_state === "Confirmed" ? "You said yes" : c.review_state === "Dismissed" ? "You said no" : c.review_state === "Corrected" ? "You corrected this" : "Closer photo requested"}</T> : null}
          {!locked && c.review_state === "Pending" ? (
            <>
              <Row style={{ flexWrap: "nowrap" }}>
                <Btn small testID={`candidate-confirm-${i + 1}`} title="Confirm" icon="check" onPress={() => decide(c, "confirm")} style={{ flex: 1 }} />
                <Btn small kind="secondary" testID={`candidate-correct-${i + 1}`} title="Correct" icon="pencil-outline" onPress={() => { setCorr({ category: c.category, note: "" }); setCorrectFor(c); }} style={{ flex: 1 }} />
                <Btn small kind="secondary" testID={`candidate-dismiss-${i + 1}`} title="Dismiss" icon="close" onPress={() => decide(c, "dismiss")} style={{ flex: 1 }} />
              </Row>
              <Btn small kind="ghost" testID={`candidate-closer-${i + 1}`} title="I'll take a closer photo" icon="camera-outline" onPress={() => decide(c, "request_closer_photo")} />
            </>
          ) : null}
        </Card>
      ))}
      {kind === "photo" && !locked ? <Btn testID="evidence-add-observation-button" kind="secondary" title="Add a note about this photo" icon="plus" onPress={() => setManual("")} /> : null}

      {kind === "audio" && transcripts.length ? (
        <Card testID="transcript-card">
          <T bold>What you said</T>
          <T testID="transcript-text" size={15}>{transcripts[transcripts.length - 1].text}</T>
          {!locked ? <Btn small kind="secondary" testID="transcript-correct-button" title="Edit text" icon="pencil-outline" onPress={() => setTEdit(transcripts[transcripts.length - 1].text)} /> : null}
        </Card>
      ) : kind === "audio" && synced ? <T testID="transcript-pending" muted size={13}>The written version of this recording will appear here shortly.</T> : null}

      <Sheet visible={!!correctFor} onClose={() => setCorrectFor(null)} title="What do you see?" testID="candidate-correct-sheet">
        {(correctFor?.schema === "rail_surface" ? RS_CATS : CATS).map((c) => (
          <Btn key={c} small testID={`correct-category-${c.split(" ")[0]}`} kind={corr.category === c ? "primary" : "secondary"} title={CAT_PLAIN[c].replace("Possible ", "")} icon={corr.category === c ? "radiobox-marked" : "radiobox-blank"} onPress={() => setCorr({ ...corr, category: c })} />
        ))}
        <Input testID="correct-note-input" label="In your words (optional)" multiline value={corr.note} onChangeText={(t) => setCorr({ ...corr, note: t })} />
        <Btn testID="correct-save-button" title="Save" icon="check" onPress={() => decide(correctFor, "correct", { corrected_category: corr.category, note: corr.note || undefined })} />
      </Sheet>
      {stepVid ? <NextStep to="details" repair={steps.repair} onPress={() => goToStep(stepVid, "details")} /> : null}
      <Sheet visible={manual !== null} onClose={() => setManual(null)} title="Add a note" testID="manual-observation-sheet">
        <Input testID="manual-observation-input" label="Note" multiline value={manual || ""} onChangeText={setManual} />
        <Btn testID="manual-observation-save" title="Save" icon="content-save" onPress={addManual} />
      </Sheet>
      <Sheet visible={tEdit !== null} onClose={() => setTEdit(null)} title="Correct transcript" testID="transcript-edit-sheet">
        <Input testID="transcript-edit-input" label="Transcript text" multiline value={tEdit || ""} onChangeText={setTEdit} />
        <Btn testID="transcript-save-button" title="Save as new version" icon="content-save" onPress={saveTranscript} />
      </Sheet>
    </Screen>
  );
}
