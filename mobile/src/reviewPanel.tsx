// Review inspection (REQ-222..225): grouped Needs your review / Missing information / Ready, focused item with source excerpt
// beside the proposed answer, Confirm / Correct / Ask estimator (reason required). Blockers sit next to the item.
import { useCallback, useEffect, useState } from "react";
import { Pressable, View } from "react-native";
import { ApiError, api, errText } from "./api";
import { Banner, Btn, Icon, Input, Row, Sheet, T } from "./ui";
import { useTheme } from "./theme";

const CORE = new Set(["inspected_quantity", "repair_quantity", "tie_specification", "material_responsibility", "work_location"]);
const GROUPS: [string, string, string][] = [
  ["needs_review", "Needs your review", "eye-outline"],
  ["missing", "Missing information", "help-circle-outline"],
  ["ready", "Ready", "check-circle-outline"],
];

export async function submitAnswer(visitId: string, item: any, rev: number, action: string, extra: any) {
  if (CORE.has(item.key)) {
    const map: Record<string, string> = { confirm: "accept_proposal", correct: "answer", ask_estimator: "needs_estimator_input", unknown: "unknown", not_applicable: "not_applicable" };
    return api(`/visits/${visitId}/fields/${item.key}`, { body: { expected_revision: rev, action: map[action], source: "review", ...extra } });
  }
  return api(`/visits/${visitId}/checklist/${item.key}`, { body: { expected_revision: rev, action, ...extra } });
}

export function ReviewPanel({ visitId, locked, available }: { visitId: string; locked: boolean; available: boolean }) {
  const { colors } = useTheme();
  const [d, setD] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const [focus, setFocus] = useState<any>(null);
  const [mode, setMode] = useState<"view" | "correct" | "ask" | "unknown">("view");
  const [val, setVal] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    if (!available) return;
    try {
      setD(await api(`/visits/${visitId}/checklist`));
      setErr(null);
    } catch (e) {
      setErr(errText(e));
    }
  }, [visitId, available]);
  useEffect(() => { load(); }, [load]);

  function open(item: any) {
    setFocus(item);
    setMode("view");
    setVal(item.answer?.value != null ? String(item.answer.value) : "");
    setReason("");
  }

  async function act(action: string, extra: any = {}) {
    if (busy) return;
    setBusy(true);
    setErr(null);
    try {
      await submitAnswer(visitId, focus, d.revision, action, extra);
      setFocus(null);
      await load();
    } catch (e) {
      setErr(e instanceof ApiError && e.status === 409 ? "This inspection changed elsewhere - reloaded. Check the item again." : errText(e));
      if (e instanceof ApiError && e.status === 409) load();
    } finally {
      setBusy(false);
    }
  }

  if (!available) return <T testID="review-unavailable" muted>Your questions will appear here in a moment. Everything you captured is safe on this phone.</T>;
  if (!d) return err ? <Banner testID="review-load-error" tone="error" icon="alert-circle-outline" text={err} /> : <T muted>Loading review...</T>;
  if (d.state === "needs_repair") return <Banner testID="review-checklist-needs-repair" tone="warning" icon="wrench-outline" text={d.message} />;

  return (
    <View testID="review-panel" style={{ gap: 16 }}>
      <View style={{ gap: 2 }}>
        <T bold size={16}>{d.template.name} checklist - v{d.template.version}</T>
        <T testID="review-template-label" muted size={13}>{d.template.label}</T>
      </View>
      {GROUPS.map(([g, title, icon]) => (
        <View key={g} testID={`review-group-${g}`} style={{ gap: 0 }}>
          <Row style={{ marginBottom: 4 }}>
            <Icon name={icon as any} size={18} color={g === "ready" ? colors.success : g === "missing" ? colors.warning : colors.onSurface} />
            <T bold size={15}>{title} ({d.groups[g].length})</T>
          </Row>
          {d.fields.filter((f: any) => f.group === g).map((f: any) => (
            <Pressable key={f.key} testID={`review-item-${f.key}`} accessibilityRole="button" onPress={() => open(f)}
              style={({ pressed }) => ({ minHeight: 52, paddingVertical: 10, borderTopWidth: 1, borderTopColor: colors.border, opacity: pressed ? 0.7 : 1, gap: 2 })}>
              <Row style={{ flexWrap: "nowrap" }}>
                <T style={{ flex: 1 }} size={15}>{f.label}{f.required ? "" : " (optional)"}</T>
                {f.answer?.value != null ? <T muted size={14}>{String(f.answer.value)}{f.answer.unit ? ` ${f.answer.unit}` : ""}</T> : null}
                <Icon name="chevron-right" size={20} color={colors.muted} />
              </Row>
              {f.blocker ? <T testID={`review-blocker-${f.key}`} muted size={13}>{f.blocker}</T> : null}
              {f.inherited_by_findings ? <T muted size={12}>Applies to all findings unless overridden</T> : null}
            </Pressable>
          ))}
          {!d.groups[g].length ? <T muted size={13}>Nothing here.</T> : null}
        </View>
      ))}

      <Sheet visible={!!focus} onClose={() => setFocus(null)} title={focus?.label || ""} testID="review-item-sheet">
        {focus ? (
          <>
            {focus.help ? <T muted size={13}>{focus.help}</T> : null}
            {focus.blocker ? <T testID="review-item-blocker" size={14}>{focus.blocker}</T> : null}
            {focus.proposals.map((p: any) => (
              <View key={p.uuid} testID={`review-proposal-${p.uuid}`} style={{ borderWidth: 1, borderColor: colors.border, borderRadius: 8, padding: 12, gap: 6 }}>
                <T bold size={16}>Proposed: {String(p.value)}</T>
                <T testID={`review-proposal-excerpt-${p.uuid}`} size={14}>&apos;{p.excerpt}&apos;</T>
                <T muted size={12}>From {p.source_kind === "audio" ? "voice transcript" : "typed note"}{p.untrusted ? " - untrusted text - check carefully" : ""}</T>
                {!locked ? <Btn small testID={`review-confirm-${p.uuid}`} title="Confirm" icon="check" disabled={busy} onPress={() => act("confirm", { proposal_id: p.uuid })} /> : null}
              </View>
            ))}
            {focus.answer?.state ? <T testID="review-item-current" muted size={13}>Current: {focus.answer.state}{focus.answer.value != null ? ` - ${focus.answer.value}` : ""}{focus.answer.reason ? ` (${focus.answer.reason})` : ""}</T> : null}
            {err ? <Banner testID="review-item-error" tone="error" icon="alert-circle-outline" text={err} /> : null}
            {locked ? <T muted>Submitted - read-only.</T> : mode === "view" ? (
              <>
                <Btn kind="secondary" testID="review-correct-button" title={focus.proposals.length ? "Correct" : "Enter answer"} icon="pencil-outline" onPress={() => setMode("correct")} />
                <Btn kind="secondary" testID="review-ask-estimator-button" title="Ask estimator" icon="account-question-outline" onPress={() => setMode("ask")} />
                {focus.allowed_non_answers?.length ? <Btn kind="ghost" testID="review-unknown-button" title="Unknown / later" icon="clock-outline" onPress={() => setMode("unknown")} /> : null}
              </>
            ) : mode === "correct" ? (
              <>
                {focus.options?.length ? (
                  <Row>{focus.options.map((o: string) => <Btn small key={o} kind={val === o ? "primary" : "secondary"} testID={`review-option-${o}`} title={o} onPress={() => setVal(o)} />)}</Row>
                ) : (
                  <Input testID="review-value-input" label={`${focus.label}${focus.unit ? ` (${focus.unit})` : ""}`} value={val} onChangeText={setVal}
                    keyboardType={focus.type === "integer" || focus.type === "number" ? "decimal-pad" : "default"} />
                )}
                <Btn testID="review-save-answer-button" title="Save answer" icon="check" loading={busy} disabled={!val.trim()} onPress={() => act("correct", { value: val.trim(), unit: focus.unit || undefined })} />
              </>
            ) : (
              <>
                <Input testID="review-reason-input" label={mode === "ask" ? "What should the estimator decide? (required)" : "Reason (required)"} value={reason} onChangeText={setReason} multiline />
                <Btn testID="review-save-reason-button" title={mode === "ask" ? "Send to estimator" : "Save"} icon="send-outline" loading={busy} disabled={!reason.trim()}
                  onPress={() => act(mode === "ask" ? "ask_estimator" : focus.allowed_non_answers.includes("defer") && !CORE.has(focus.key) ? "defer" : "unknown", { reason: reason.trim() })} />
                {mode === "ask" ? <T muted size={12}>The item stays unresolved until the estimator answers.</T> : null}
              </>
            )}
          </>
        ) : null}
      </Sheet>
    </View>
  );
}
