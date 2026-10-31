// Phase 8 Review step (REQ-262..266): plain questions and evidence requests across ALL evidence
// (photos, voice notes, typed notes) from GET /visits/{id}/review-questions. No ids, scores or
// technical words are shown; the server phrases every question so mobile and web say the same thing.
import { router } from "expo-router";
import { Image } from "expo-image";
import { useCallback, useEffect, useState } from "react";
import { Pressable, View } from "react-native";
import { ApiError, api, mediaUrl } from "./api";
import { submitAnswer } from "./reviewPanel";
import { useTheme } from "./theme";
import { Banner, Btn, Card, Empty, Input, Row, T } from "./ui";

type Q = any;
type Mode = { q: Q; kind: "value" | "reason" | "words" | "note"; action: string };

export function ReviewQuestions({ visitId, locked, available, onTakePhoto }: { visitId: string; locked: boolean; available: boolean; onTakePhoto: () => void }) {
  const { colors } = useTheme();
  const [d, setD] = useState<any>(null);
  const [fields, setFields] = useState<Record<string, any>>({});
  const [err, setErr] = useState<string | null>(null);
  const [mode, setMode] = useState<Mode | null>(null);
  const [val, setVal] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [cur, setCur] = useState(0);

  const load = useCallback(async () => {
    if (!available) return;
    try {
      const [rq, cl] = await Promise.all([api(`/visits/${visitId}/review-questions`), api(`/visits/${visitId}/checklist`)]);
      setD(rq);
      setFields(Object.fromEntries((cl.fields || []).map((f: any) => [f.key, f])));
      setErr(null);
    } catch {
      setErr("We couldn't load your questions right now. Pull down to try again.");
    }
  }, [visitId, available]);
  useEffect(() => { load(); }, [load]);

  async function run(q: Q, fn: () => Promise<any>, thanks: string) {
    setBusy(q.id);
    setErr(null);
    try {
      await fn();
      setMode(null);
      setVal("");
      setDone(thanks);
      await load();
    } catch (e) {
      setErr(e instanceof ApiError && e.status === 409 ? "Someone else answered this at the same time - here's the latest." : "Not saved yet. Tap your answer again.");
      if (e instanceof ApiError && e.status === 409) load();
    } finally {
      setBusy(null);
    }
  }

  function field(q: Q) { return fields[q.target.key] || { key: q.target.key }; }

  function choose(q: Q, c: string) {
    if (q.kind === "photo_suggestion") {
      const decide = (action: string, extra: any = {}) => run(q, () => api(`/candidates/${q.target.id}/decision`, { body: { action, expected_revision: q.target.revision, ...extra } }),
        action === "confirm" ? "Thanks - added to your findings." : action === "dismiss" ? "Got it - we'll leave that out." : action === "request_closer_photo" ? "Okay - take a closer photo when you can." : "Thanks - noted.");
      if (c === "yes") return decide("confirm");
      if (c === "no") return decide("dismiss");
      if (c === "closer") return decide("request_closer_photo");
      return setMode({ q, kind: "note", action: "correct" });
    }
    if (q.kind === "voice_check") {
      if (c === "yes") return run(q, () => api(`/evidence/${q.evidence.evidence_id}/transcript-ok`, { body: { base_version: q.target.base_version } }), "Thanks - voice note checked.");
      setVal(q.heard);
      return setMode({ q, kind: "words", action: "edit" });
    }
    if (q.kind === "evidence_request") return onTakePhoto();
    if (c.startsWith("pick:")) return run(q, () => submitAnswer(visitId, field(q), d.revision, "confirm", { proposal_id: c.slice(5) }), "Thanks - saved.");
    if (c === "ask") return setMode({ q, kind: "reason", action: "ask_estimator" });
    if (c === "later") return setMode({ q, kind: "reason", action: (q.target && fields[q.target.key]?.allowed_non_answers || []).includes("defer") ? "defer" : "unknown" });
    setVal("");
    setMode({ q, kind: "value", action: "correct" });
  }

  function save() {
    const m = mode!;
    const q = m.q;
    const v = val.trim();
    if (m.kind === "words") return run(q, () => api(`/evidence/${q.evidence.evidence_id}/transcripts`, { body: { text: v, base_version: q.target.base_version } }), "Thanks - words updated.");
    if (m.kind === "note") return run(q, () => api(`/candidates/${q.target.id}/decision`, { body: { action: "correct", expected_revision: q.target.revision, note: v } }), "Thanks - noted.");
    if (m.kind === "value") return run(q, () => submitAnswer(visitId, field(q), d.revision, "correct", { value: v, unit: q.unit || undefined }), "Thanks - saved.");
    return run(q, () => submitAnswer(visitId, field(q), d.revision, m.action, { reason: v }), m.action === "ask_estimator" ? "Sent to the estimator." : "Okay - saved for later.");
  }

  if (!available) return <T testID="review-unavailable" muted>Your questions will appear here in a moment. Everything you captured is safe on this phone.</T>;
  if (!d) return err ? <Banner testID="review-load-error" tone="error" icon="alert-circle-outline" text={err} /> : <T muted>Getting your questions...</T>;

  return (
    <View testID="review-questions" style={{ gap: 12 }}>
      <T testID="review-summary" bold size={17}>{d.summary}</T>
      {done ? <Banner testID="review-done-message" tone="success" icon="check" text={done} /> : null}
      {err ? <Banner testID="review-error" tone="error" icon="alert-circle-outline" text={err} /> : null}
      {!d.questions.length ? <Empty testID="review-empty" icon="check-circle-outline" text="Nothing left to check." /> : null}
      {d.questions.length ? (
        <Row style={{ flexWrap: "nowrap" }}>
          <T testID="review-progress" muted size={13} style={{ flex: 1 }}>Question {Math.min(cur, d.questions.length - 1) + 1} of {d.questions.length}</T>
          {d.questions.length > 1 ? <Btn small kind="ghost" testID="review-skip-button" title="Skip for now" icon="chevron-right"
            onPress={() => { setMode(null); setDone(null); setCur((c) => (Math.min(c, d.questions.length - 1) + 1) % d.questions.length); }} /> : null}
        </Row>
      ) : null}
      {/* U1: one question at a time */}
      {d.questions.map((q: Q, i: number) => i !== Math.min(cur, d.questions.length - 1) ? null : (
        <Card key={q.id} testID={`review-question-${i}`}>
          {q.evidence?.kind === "photo" ? (
            <Pressable testID={`review-question-photo-${i}`} accessibilityRole="imagebutton" accessibilityLabel="Open photo"
              onPress={() => router.push({ pathname: "/evidence/[id]", params: { id: q.evidence.evidence_id } })}>
              <Image source={{ uri: mediaUrl(q.evidence.evidence_id) }} style={{ width: "100%", height: 180, borderRadius: 10, backgroundColor: colors.surfaceTertiary }} contentFit="cover" />
            </Pressable>
          ) : null}
          <T testID={`review-question-text-${i}`} bold size={16}>{q.text}</T>
          {q.detail ? <T muted size={14}>{q.detail}</T> : null}
          {q.heard ? <T testID={`review-question-heard-${i}`} size={15}>&apos;{q.heard}&apos;</T> : null}
          {(q.quotes || []).map((x: any, k: number) => <T key={k} muted size={14}>From your {x.from}: &apos;{x.text}&apos;</T>)}
          {q.hint ? <T muted size={13}>{q.hint}</T> : null}
          {q.careful ? <T muted size={13}>Please double-check this one.</T> : null}
          {locked ? null : mode && mode.q.id === q.id ? (
            <View style={{ gap: 8 }}>
              {mode.kind === "value" && q.options?.length ? (
                <Row>{q.options.map((o: string) => <Btn small key={o} kind={val === o ? "primary" : "secondary"} testID={`review-option-${o}`} title={o} onPress={() => setVal(o)} />)}</Row>
              ) : (
                <Input testID="review-answer-input" multiline={mode.kind !== "value"} value={val} onChangeText={setVal}
                  label={mode.kind === "words" ? "The right words" : mode.kind === "note" ? "What do you see instead?" : mode.kind === "reason" ? (mode.action === "ask_estimator" ? "What should the estimator decide?" : "Why not yet?") : `${q.label}${q.unit ? ` (${q.unit})` : ""}`}
                  keyboardType={mode.kind === "value" && (q.input === "integer" || q.input === "number") ? "decimal-pad" : "default"} />
              )}
              <Row>
                <Btn small testID="review-answer-save" title={mode.action === "ask_estimator" ? "Send" : "Save"} icon="check" loading={busy === q.id} disabled={!val.trim()} onPress={save} />
                <Btn small kind="ghost" testID="review-answer-cancel" title="Cancel" onPress={() => setMode(null)} />
              </Row>
            </View>
          ) : (
            <Row>
              {q.choices.map((c: any) => (
                <Btn small key={c.id} kind={c.id === "yes" || c.id.startsWith("pick:") || c.id === "take_photo" || c.id === "other" && q.kind === "missing" ? "primary" : "secondary"}
                  testID={`review-choice-${i}-${c.id.split(":")[0]}`} title={c.label} disabled={!!busy} onPress={() => choose(q, c.id)} />
              ))}
            </Row>
          )}
        </Card>
      ))}
    </View>
  );
}
