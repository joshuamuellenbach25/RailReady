// Record note sheet: timer, stop, cancel, playback, save. The recorder only exists while this sheet is open
// (no idle recorder/audio session held by the inspection screen while the camera is used).
import { useEffect, useRef, useState } from "react";
import { AppState, View } from "react-native";
import { RecordingPresets, getRecordingPermissionsAsync, setAudioModeAsync, useAudioPlayer, useAudioPlayerStatus, useAudioRecorder, useAudioRecorderState } from "expo-audio";
import { crumb, flushCrumbs } from "./crumbs";
import { Banner, Btn, Sheet, T } from "./ui";

type Saved = (uri: string, secs: number, interrupted: boolean) => Promise<void>;

function Playback({ uri }: { uri: string }) {
  const player = useAudioPlayer(uri);
  const st = useAudioPlayerStatus(player);
  return (
    <Btn testID="record-sheet-play" kind="secondary" icon={st.playing ? "pause" : "play"} title={st.playing ? "Pause" : "Play back"}
      onPress={() => (st.playing ? player.pause() : (player.seekTo(0), player.play()))} />
  );
}

function withTimeout<T>(p: Promise<T>, ms: number, what: string): Promise<T> {
  return Promise.race([p, new Promise<T>((_, rej) => setTimeout(() => rej(new Error(`${what} timed out after ${ms / 1000}s`)), ms))]);
}

function Recorder({ onSaved, onClose }: { onSaved: Saved; onClose: () => void }) {
  const recorder = useAudioRecorder(RecordingPresets.HIGH_QUALITY);
  const rs = useAudioRecorderState(recorder, 500);
  const [phase, setPhase] = useState<"idle" | "starting" | "recording" | "stopped">("idle");
  const [uri, setUri] = useState<string | null>(null);
  const [secs, setSecs] = useState(0);
  const [err, setErr] = useState<string | null>(null);
  const live = useRef(true);
  const busy = useRef(false);

  // U3: a stopped-but-unsaved recording is kept as a recoverable draft if the sheet goes away without Save/Discard
  const pending = useRef<{ uri: string; secs: number } | null>(null);
  useEffect(() => {
    live.current = true;
    return () => {
      live.current = false;
      const p = pending.current;
      if (p) {
        pending.current = null;
        crumb("record.kept_unsaved");
        onSaved(p.uri, p.secs, true).catch(() => {});
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // REQ-193: interrupted (backgrounded / call) -> stop and keep captured bytes as a recoverable draft
  useEffect(() => {
    const sub = AppState.addEventListener("change", async (s) => {
      if (s !== "active" && phase === "recording") {
        await crumb("record.interrupted");
        try { await recorder.stop(); } catch {}
        if (recorder.uri) await onSaved(recorder.uri, Math.round(rs.durationMillis / 1000), true).catch(() => {});
        setAudioModeAsync({ allowsRecording: false, playsInSilentMode: true }).catch(() => {});
        flushCrumbs();
        if (live.current) onClose();
      }
    });
    return () => sub.remove();
  }, [phase, recorder, rs.durationMillis, onSaved, onClose]);

  async function start() {
    if (busy.current) return;
    busy.current = true;
    setErr(null);
    setPhase("starting");
    try {
      await crumb("record.start_tap");
      // Permission was requested BEFORE this sheet opened (no system alert / second modal over an open Modal).
      const p = await withTimeout(getRecordingPermissionsAsync(), 3000, "permission check");
      await crumb("record.permission", p.granted ? "granted" : p.status);
      if (!p.granted) throw new Error("Microphone permission not granted");
      await withTimeout(setAudioModeAsync({ allowsRecording: true, playsInSilentMode: true }), 3000, "audio mode");
      await crumb("record.mode");
      await withTimeout(recorder.prepareToRecordAsync(), 5000, "prepare");
      await crumb("record.prepared");
      recorder.record();
      await crumb("record.started");
      if (live.current) setPhase("recording");
    } catch (e: any) {
      await crumb("record.error", e?.message);
      setAudioModeAsync({ allowsRecording: false, playsInSilentMode: true }).catch(() => {});
      if (live.current) {
        setPhase("idle");
        setErr(`Microphone unavailable: ${e?.message ?? "unknown error"}. Type a note instead.`);
      }
    } finally {
      busy.current = false;
      flushCrumbs(); // never awaited: UI never waits on the network
    }
  }
  async function stop() {
    const s = Math.round(rs.durationMillis / 1000);
    try {
      await withTimeout(recorder.stop(), 5000, "stop");
    } catch (e: any) {
      await crumb("record.stop_error", e?.message);
    }
    setAudioModeAsync({ allowsRecording: false, playsInSilentMode: true }).catch(() => {});
    await crumb("record.stopped", `${s}s`);
    if (recorder.uri) pending.current = { uri: recorder.uri, secs: s };
    if (!live.current) return;
    setSecs(s);
    setUri(recorder.uri);
    setPhase("stopped");
  }
  async function cancel() {
    if (phase === "recording") await withTimeout(recorder.stop(), 5000, "stop").catch(() => {});
    setAudioModeAsync({ allowsRecording: false, playsInSilentMode: true }).catch(() => {});
    pending.current = null; // explicit Discard / Cancel
    await crumb("record.cancel");
    flushCrumbs();
    onClose();
  }
  async function save() {
    if (!uri) return setErr("Recording failed - nothing saved");
    try {
      await crumb("record.save");
      await onSaved(uri, secs, false); // local commit only; sync/transcription run later in the background
      pending.current = null;
      await crumb("record.saved");
      onClose();
    } catch (e: any) {
      await crumb("record.save_error", e?.message);
      setErr(`Recording not saved: ${e?.message}`);
    } finally {
      flushCrumbs();
    }
  }
  const t = Math.round((phase === "recording" ? rs.durationMillis : secs * 1000) / 1000);
  return (
    <View style={{ gap: 12 }}>
      <T testID="record-sheet-timer" size={24}>{`${Math.floor(t / 60)}:${String(t % 60).padStart(2, "0")}`}</T>
      {err ? <Banner testID="record-sheet-error" tone="error" icon="alert-circle-outline" text={err} /> : null}
      {phase === "idle" || phase === "starting" ? <Btn testID="record-sheet-start" title="Start recording" icon="microphone-outline" loading={phase === "starting"} onPress={start} /> : null}
      {phase === "recording" ? <Btn testID="record-sheet-stop" kind="danger" title="Stop" icon="stop" onPress={stop} /> : null}
      {phase === "stopped" && uri ? (
        <>
          <Playback uri={uri} />
          <Btn testID="record-sheet-save" title="Save recording" icon="content-save-outline" onPress={save} />
        </>
      ) : null}
      <Btn testID="record-sheet-cancel" kind="secondary" title={phase === "stopped" ? "Discard" : "Cancel"} icon="close" onPress={cancel} />
    </View>
  );
}

export function RecordSheet({ visible, onClose, onSaved }: { visible: boolean; onClose: () => void; onSaved: Saved }) {
  if (!visible) return null;
  return (
    <Sheet visible onClose={onClose} title="Record note" testID="record-sheet">
      <Recorder onSaved={onSaved} onClose={onClose} />
    </Sheet>
  );
}
