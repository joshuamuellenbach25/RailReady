import { useFocusEffect, useLocalSearchParams } from "expo-router";
import { useCallback, useState } from "react";
import { View } from "react-native";
import { ApiError, api, errText } from "@/src/api";
import { useAuth } from "@/src/auth";
import * as repo from "@/src/local/repo";
import { Badge, Banner, Btn, Card, H, Loading, Row, Screen, T } from "@/src/ui";
import { useTheme } from "@/src/theme";

export async function fieldAction(uid: string, visitId: string, field: string, body: any, onConflict: (m: string) => void) {
  try {
    return await api(`/visits/${visitId}/fields/${field}`, { body });
  } catch (e) {
    if (e instanceof ApiError && e.status === 409 && e.detail?.server) {
      const srv = e.detail.server.answers?.[field];
      if (uid) await repo.saveRecovery(uid, { visit_id: visitId, what: field, value: String(body.value ?? body.proposal_id ?? body.reason ?? body.action), server_value: srv ? `${srv.state}${srv.value != null ? ": " + srv.value : ""}` : "unchanged" });
      onConflict("Someone else changed this answer at the same time - showing the latest version.");
      return null;
    }
    throw e;
  }
}

export function RecoveryList({ visitId }: { visitId: string }) {
  const { user } = useAuth();
  const [items, setItems] = useState<repo.Recovery[]>([]);
  useFocusEffect(useCallback(() => { if (user) repo.listRecovery(user.uuid, visitId).then(setItems); }, [user, visitId]));
  if (!items.length) return null;
  return (
    <Card testID="recovery-copies">
      <H>Recovery copies on this device</H>
      {items.map((r) => (
        <T key={r.id} testID={`recovery-${r.id}`}>{r.what}: your entry &apos;{r.value}&apos; - server kept &apos;{r.server_value}&apos;</T>
      ))}
    </Card>
  );
}

export default function Fields() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { user } = useAuth();
  const { colors } = useTheme();
  const uid = user ? user.uuid : "";
  const [data, setData] = useState<any>(null);
  const [msg, setMsg] = useState<{ tone: any; text: string } | null>(null);
  const [armed, setArmed] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setData(await api(`/visits/${id}/proposals`));
    } catch (e) {
      setMsg({ tone: "error", text: errText(e) });
    }
  }, [id]);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  async function accept(field: string, p: any) {
    setMsg(null);
    try {
      const r = await fieldAction(uid, id, field, { expected_revision: data.visit_revision, action: "accept_proposal", proposal_id: p.uuid, source: "review" }, (m) => setMsg({ tone: "warning", text: m }));
      if (r) setMsg({ tone: "success", text: `${field.replace(/_/g, " ")} set to ${p.value}` });
    } catch (e) {
      setMsg({ tone: "error", text: errText(e) });
    }
    load();
  }

  if (!data) return <Screen title="Proposed fields">{msg ? <Banner testID="fields-load-error" tone="error" icon="alert" text={msg.text} /> : <Loading />}</Screen>;
  const locked = data.status === "Submitted" && user && user.role === "foreman";
  return (
    <Screen testID="fields-screen" title="All answers" subtitle="What we found in your notes and voice notes">
      {msg ? <Banner testID="fields-message" tone={msg.tone} icon="information" text={msg.text} /> : null}
      <RecoveryList visitId={id} />
      {data.runs.filter((r: any) => r.status === "Failed").map((r: any) => (
        <Banner key={r.uuid} testID={`fields-run-failed-${r.uuid}`} tone="error" icon="close-octagon" text="We couldn't read one of your notes yet. Open it and tap Try again - you can still answer by hand." />
      ))}
      {data.fields.map((f: any) => (
        <Card key={f.field} testID={`field-card-${f.field}`}>
          <Row>
            <H>{f.label}</H>
            <Badge testID={`field-state-${f.field}`} label={f.state} />
          </Row>
          {f.answer?.state === "Provided" ? <T testID={`field-value-${f.field}`} bold size={16}>Value: {String(f.answer.value)}</T> : null}
          {f.answer?.reason ? <T muted>Reason: {f.answer.reason}</T> : null}
          {f.review_reason ? <Banner testID={`field-review-reason-${f.field}`} tone="warning" icon="message-alert" text={f.review_reason} /> : null}
          {f.discrepancy ? (
            <Banner testID={`field-discrepancy-${f.field}`} tone="warning" icon="scale-unbalanced" text={`Your notes say different things (${f.distinct_values.join(" or ")}). Pick the right one, or answer it when you finish.`} />
          ) : null}
          {!f.proposals.length && f.state === "Missing required" ? <T muted>Not mentioned in your photos, voice notes or notes yet.</T> : null}
          {f.proposals.map((p: any) => (
            <View key={p.uuid} testID={`proposal-${p.uuid}`} style={{ gap: 4, borderTopWidth: 1, borderTopColor: colors.border, paddingTop: 8 }}>
              <T bold>We think: {String(p.value)}</T>
              <T testID={`proposal-excerpt-${p.uuid}`}>&apos;{p.excerpt}&apos;</T>
              {p.untrusted ? <Badge testID={`proposal-untrusted-${p.uuid}`} label="Please double-check this one" icon="alert-outline" tone="warning" /> : null}
              <T muted size={12}>From your {p.source_kind === "audio" ? "voice note" : "typed note"}</T>
              {!locked && f.answer?.proposal_id !== p.uuid ? (
                <Btn small kind={p.untrusted && armed === p.uuid ? "danger" : "secondary"} testID={`proposal-accept-${p.uuid}`}
                  title={p.untrusted ? (armed === p.uuid ? "Yes, use it" : "Check this answer") : "Yes, that's right"} icon="check"
                  onPress={() => (p.untrusted && armed !== p.uuid ? setArmed(p.uuid) : accept(f.field, p))} />
              ) : f.answer?.proposal_id === p.uuid ? <Badge label="Accepted" icon="check" tone="success" /> : null}
            </View>
          ))}
        </Card>
      ))}
    </Screen>
  );
}
