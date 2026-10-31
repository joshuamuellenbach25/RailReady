import { router, useFocusEffect, useLocalSearchParams } from "expo-router";
import { useCallback, useState } from "react";
import { ApiError, api, errText } from "@/src/api";
import { useAuth } from "@/src/auth";
import * as repo from "@/src/local/repo";
import { Badge, Banner, Btn, Card, H, Input, Loading, Row, Screen, T } from "@/src/ui";
import { fieldAction, RecoveryList } from "./fields";

export default function Departure() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { user } = useAuth();
  const uid = user ? user.uuid : "";
  const [d, setD] = useState<any>(null);
  const [val, setVal] = useState("");
  const [reason, setReason] = useState("");
  const [mode, setMode] = useState<"answer" | "estimator">("answer");
  const [msg, setMsg] = useState<{ tone: any; text: string } | null>(null);
  const [localUnsynced, setLocalUnsynced] = useState(0);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setD(await api(`/visits/${id}/departure`));
      if (uid) setLocalUnsynced(await repo.unsyncedCount(uid, id));
    } catch (e) {
      setMsg({ tone: "error", text: errText(e) });
    }
  }, [id, uid]);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  async function act(action: string, extra: any) {
    setMsg(null);
    try {
      const r = await fieldAction(uid, id, d.question.field, { expected_revision: d.visit_revision, action, source: "departure_check", ...extra }, (m) => setMsg({ tone: "warning", text: m }));
      if (r) {
        setVal("");
        setReason("");
        setMode("answer");
      }
    } catch (e) {
      setMsg({ tone: "error", text: errText(e) });
    }
    load();
  }

  async function submit() {
    setBusy(true);
    setMsg(null);
    try {
      await api(`/visits/${id}/submit`, { body: { expected_revision: d.visit_revision, device_unsynced: localUnsynced } });
      const v = await repo.getLocalVisit(uid, id);
      if (v) await repo.saveVisit(uid, { ...v, status: "Submitted" });
      setMsg({ tone: "success", text: "Visit submitted. It is now read-only for you." });
      load();
    } catch (e) {
      if (e instanceof ApiError && e.status === 409 && e.detail?.code === "stale_revision") {
        await repo.saveRecovery(uid, { visit_id: id, what: "Submit", value: "submit", server_value: `revision ${e.detail.server.revision}` });
      }
      setMsg({ tone: "error", text: errText(e) });
      load();
    } finally {
      setBusy(false);
    }
  }

  if (!d) return <Screen title="Departure check">{msg ? <Banner tone="error" text={msg.text} /> : <Loading />}</Screen>;
  const q = d.question;
  const fi = q?.field_info;
  const missing = d.uploads.missing + localUnsynced;
  const submitted = d.status === "Submitted";
  return (
    <Screen testID="departure-screen" title="Departure check" subtitle={submitted ? "Submitted" : `${d.remaining} question(s) remaining`}
      footer={!submitted ? (
        <>
          {missing ? <Banner testID="submit-blocked-message" tone="error" icon="cloud-alert" text={`${missing} item${missing === 1 ? " isn't" : "s aren't"} backed up yet. Stay connected for a moment, then finish.`} /> : null}
          <Btn testID="submit-visit-button" title="Finish inspection" icon="send-lock" disabled={missing > 0} loading={busy} onPress={submit} />
        </>
      ) : undefined}>
      {msg ? <Banner testID="departure-message" tone={msg.tone} icon="information" text={msg.text} /> : null}
      {submitted ? <Banner testID="departure-submitted-banner" tone="success" icon="lock" text="Submitted - ask estimator to reopen." /> : null}
      <RecoveryList visitId={id} />
      {d.readiness.note ? <Banner testID="departure-audio-note" tone="info" icon="waveform" text={d.readiness.note} /> : null}
      {q && !submitted ? (
        <Card testID="departure-question-card">
          <T muted>Question {d.readiness.fields.length - d.remaining + 1} of {d.readiness.fields.length}</T>
          <T testID="departure-question-text" bold size={22}>{q.prompt}</T>
          <Badge label={fi.state} testID="departure-question-state" />
          {fi.review_reason ? <Banner testID="departure-review-reason" tone="warning" icon="message-alert" text={`${fi.review_reason}: '${fi.answer?.value}'. Answer again or mark Needs estimator input.`} /> : null}
          {fi.proposals.map((p: any) => (
            <Card key={p.uuid}>
              <T>Proposed {String(p.value)} - &apos;{p.excerpt}&apos;</T>
              {p.untrusted ? <Badge testID={`departure-untrusted-${p.uuid}`} label="From untrusted text - review in Proposed fields" icon="shield-alert" tone="warning" /> : <Btn small kind="secondary" testID={`departure-accept-${p.uuid}`} title={`Use ${p.value}`} icon="check" onPress={() => act("accept_proposal", { proposal_id: p.uuid })} />}
            </Card>
          ))}
          <Row>
            <Btn small testID="departure-mode-answer" kind={mode === "answer" ? "primary" : "secondary"} title="Answer" icon="keyboard" onPress={() => setMode("answer")} style={{ flexGrow: 1 }} />
            <Btn small testID="departure-mode-estimator" kind={mode === "estimator" ? "primary" : "secondary"} title="Needs estimator input" icon="account-tie" onPress={() => setMode("estimator")} style={{ flexGrow: 1 }} />
          </Row>
          {mode === "answer" ? (
            fi.type === "enum" ? (
              fi.options.map((o: string) => <Btn key={o} kind="secondary" testID={`departure-option-${o.toLowerCase()}`} title={o} onPress={() => act("answer", { value: o })} />)
            ) : (
              <>
                <Input testID="departure-answer-input" label="Typed answer" value={val} onChangeText={setVal} keyboardType={fi.type === "integer" ? "number-pad" : "default"} />
                <T muted size={12}>Audio alone never satisfies a field - type the value.</T>
                <Btn testID="departure-answer-submit" title="Save answer" icon="check" disabled={!val.trim()} onPress={() => act("answer", { value: val })} />
              </>
            )
          ) : (
            <>
              <Input testID="departure-reason-input" label="Reason (what the estimator must decide)" multiline value={reason} onChangeText={setReason} />
              <Btn testID="departure-estimator-submit" title="Mark Needs estimator input" icon="account-tie" disabled={!reason.trim()} onPress={() => act("needs_estimator_input", { reason })} />
            </>
          )}
        </Card>
      ) : !submitted ? (
        <Banner testID="departure-all-answered" tone="success" icon="check-all" text="All fields have a status. Review below, then submit." />
      ) : null}
      <Card testID="readiness-card">
        <H>Readiness</H>
        {d.readiness.fields.map((f: any) => (
          <Row key={f.field}>
            <Badge testID={`readiness-${f.field}`} label={f.state} />
            <T style={{ flex: 1 }}>{f.label}{f.answer?.value != null ? `: ${f.answer.value}` : ""}</T>
            {f.review_reason ? <T testID={`readiness-reason-${f.field}`} muted size={12}>{f.review_reason}</T> : null}
          </Row>
        ))}
      </Card>
      <Btn kind="secondary" testID="departure-fields-button" title="Review proposed fields" icon="format-list-checks" onPress={() => router.push(`/visit/${id}/fields`)} />
    </Screen>
  );
}
