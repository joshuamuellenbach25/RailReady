// Handoff items from the inspection's PINNED checklist (e.g. "Access / track time arrangement"), asked in the Details step.
// Answer, or an allowed disposition (Defer / Unknown, only if the template allows it). Unknown never counts as confirmed.
import { useState } from "react";
import { ApiError, api, errText } from "@/src/api";
import { Badge, Banner, Btn, Card, H, Input, Row, T } from "@/src/ui";

const NON = { defer: "Defer", unknown: "Unknown" } as const;

function statusLabel(it: any) {
  if (it.open) return "Missing required";
  return it.disposition || "Answered";
}

export function HandoffCard({ visitId, items, revision, locked, onSaved }: { visitId: string; items: any[]; revision: number; locked: boolean; onSaved: () => void }) {
  if (!items?.length) return null;
  return (
    <Card testID="handoff-card">
      <H>Before you leave</H>
      {items.map((it) => <HandoffItem key={it.key} visitId={visitId} it={it} revision={revision} locked={locked} onSaved={onSaved} />)}
    </Card>
  );
}

function HandoffItem({ visitId, it, revision, locked, onSaved }: any) {
  const [mode, setMode] = useState<"answer" | "defer" | "unknown">("answer");
  const [val, setVal] = useState("");
  const [reason, setReason] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const allowed: string[] = (it.allowed_non_answers || []).filter((x: string) => x in NON);
  const tone = it.open ? "error" : it.disposition === "Answered" ? "success" : "warning";

  async function save() {
    setBusy(true);
    setErr(null);
    try {
      const body = mode === "answer" ? { expected_revision: revision, action: "correct", value: val.trim() } : { expected_revision: revision, action: mode, reason: reason.trim() };
      await api(`/visits/${visitId}/checklist/${it.key}`, { body });
      setVal("");
      setReason("");
      onSaved();
    } catch (e) {
      setErr(e instanceof ApiError && e.status === 409 ? "This inspection changed elsewhere - reloaded. Check the answer and save again." : errText(e));
      if (e instanceof ApiError && e.status === 409) onSaved();
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card testID={`handoff-item-${it.key}`}>
      <T bold>{it.label}</T>
      <Badge testID={`handoff-status-${it.key}`} label={statusLabel(it)} tone={tone as any} />
      {!it.open && it.answer ? (
        <T testID={`handoff-saved-${it.key}`} muted>
          {it.disposition === "Answered" ? `Answer: ${it.answer.value}` : `${it.disposition}${it.answer.reason ? ` - ${it.answer.reason}` : ""}${it.disposition === "Unknown" ? " (access not confirmed)" : ""}${it.disposition === "Deferred" ? " (to coordinate later)" : ""}`}
        </T>
      ) : null}
      {it.open && it.blocker ? <Banner testID={`handoff-blocker-${it.key}`} tone="error" icon="alert" text={it.blocker} /> : null}
      {it.open && !locked ? (
        <>
          <Row>
            <Btn small testID={`handoff-mode-answer-${it.key}`} kind={mode === "answer" ? "primary" : "secondary"} title="Answer" icon="keyboard" onPress={() => setMode("answer")} style={{ flexGrow: 1 }} />
            {allowed.map((x) => (
              <Btn key={x} small testID={`handoff-mode-${x}-${it.key}`} kind={mode === x ? "primary" : "secondary"} title={NON[x as keyof typeof NON]} icon={x === "defer" ? "clock-outline" : "help-circle-outline"} onPress={() => setMode(x as any)} style={{ flexGrow: 1 }} />
            ))}
          </Row>
          {mode === "answer" ? (
            <Input testID={`handoff-answer-input-${it.key}`} label="Answer" value={val} onChangeText={setVal} multiline />
          ) : (
            <Input testID={`handoff-reason-input-${it.key}`} label={mode === "defer" ? "Why defer? Who coordinates it later?" : "Why is it unknown?"} value={reason} onChangeText={setReason} multiline />
          )}
          {err ? <Banner testID={`handoff-error-${it.key}`} tone="error" icon="alert" text={err} /> : null}
          <Btn testID={`handoff-save-${it.key}`} title={mode === "answer" ? "Save answer" : mode === "defer" ? "Mark Deferred" : "Mark Unknown"} icon="check" loading={busy}
            disabled={mode === "answer" ? !val.trim() : !reason.trim()} onPress={save} />
        </>
      ) : null}
    </Card>
  );
}
