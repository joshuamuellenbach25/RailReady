import { router, useFocusEffect, useLocalSearchParams } from "expo-router";
import { useCallback, useState } from "react";
import { View } from "react-native";
import { Image } from "expo-image";
import { api, errText, mediaUrl } from "@/src/api";
import { useAuth } from "@/src/auth";
import { Badge, Banner, Btn, Card, fmt, H, Loading, Row, Screen, T } from "@/src/ui";

const KIND_LABEL: Record<string, string> = { photo: "Photo", audio: "Voice note", note: "Note" };
const SUGGESTION: Record<string, string> = {
  "possible missing/displaced fastener": "Possible missing or loose fastening",
  "visible tie-surface deterioration": "Possible damaged tie",
};

export default function Review() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { user } = useAuth();
  const [d, setD] = useState<any>(null);
  const [msg, setMsg] = useState<{ tone: any; text: string } | null>(null);
  const load = useCallback(async () => {
    try {
      setD(await api(`/visits/${id}/review`));
    } catch (e) {
      setMsg({ tone: "error", text: errText(e) });
    }
  }, [id]);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  async function reopen() {
    try {
      await api(`/visits/${id}/reopen`, { body: { expected_revision: d.visit.revision } });
      setMsg({ tone: "success", text: "Visit reopened for the foreman." });
      load();
    } catch (e) {
      setMsg({ tone: "error", text: errText(e) });
    }
  }

  if (!d) return <Screen title="Visit review">{msg ? <Banner tone="error" text={msg.text} /> : <Loading />}</Screen>;
  const v = d.visit;
  const cByEv: Record<string, any[]> = {};
  d.candidates.forEach((c: any) => (cByEv[c.evidence_id] = [...(cByEv[c.evidence_id] || []), c]));
  return (
    <Screen testID="review-screen" title={v.title} subtitle={`${d.site?.name} - ${d.summary.foreman_name}`} right={<Badge label={v.status} />}>
      {msg ? <Banner testID="review-message" tone={msg.tone} icon="information" text={msg.text} /> : null}
      <Card>
        <Row>
          {!v.processing_policy || v.processing_policy.allowed ? null : <Badge label="Automatic photo checks are off for this site" icon="information-outline" tone="neutral" />}
        </Row>
        <T muted>Started {fmt(v.created_at)} - submitted {fmt(v.submitted_at)}</T>
        {v.status === "Submitted" && user && user.role !== "foreman" ? (
          <Btn testID="review-estimate-button" title="Open estimate" icon="calculator" onPress={async () => {
            try {
              const r = await api(`/visits/${id}/engagement`, { method: "POST" });
              router.push(`/estimate/${r.engagement_id}`);
            } catch (e) {
              setMsg({ tone: "error", text: errText(e) });
            }
          }} />
        ) : null}
        {v.status === "Submitted" && user && user.role !== "foreman" ? <Btn small kind="secondary" testID="review-reopen-button" title="Reopen for foreman" icon="lock-open" onPress={reopen} /> : null}
      </Card>
      {d.prior_findings.length ? (
        <Card testID="review-prior-findings">
          <H>Prior outstanding findings</H>
          {d.prior_findings.map((f: any) => <T key={f.id}>- {f.text} ({f.recorded_at})</T>)}
        </Card>
      ) : null}
      <Card testID="review-readiness">
        <H>Estimating fields</H>
        {d.readiness.fields.map((f: any) => (
          <View key={f.field} style={{ gap: 4 }}>
            <Row>
              <Badge testID={`review-field-${f.field}`} label={f.state} />
              <T bold>{f.label}{f.answer?.value != null ? `: ${f.answer.value}` : ""}</T>
            </Row>
            {f.answer?.reason ? <T muted>Reason: {f.answer.reason}</T> : null}
            {f.discrepancy ? <Banner testID={`review-discrepancy-${f.field}`} tone="warning" icon="scale-unbalanced" text={`The notes say different things: ${f.distinct_values.join(" or ")}`} /> : null}
            {f.proposals.map((p: any) => <T key={p.uuid} muted>Suggested {String(p.value)} - &apos;{p.excerpt}&apos; (from a {p.source_kind === "audio" ? "voice note" : "typed note"})</T>)}
          </View>
        ))}
        <Btn small kind="secondary" testID="review-fields-button" title="See all answers" icon="format-list-checks" onPress={() => router.push(`/visit/${id}/fields`)} />
      </Card>
      <H>Evidence ({d.evidence.length})</H>
      {d.evidence.map((e: any) => (
        <Card key={e.uuid} testID={`review-evidence-${e.uuid}`} onPress={() => router.push(`/evidence/${e.uuid}?visit=${id}`)}>
          <T bold>{KIND_LABEL[e.kind] || "Item"}</T>
          {e.kind === "photo" && e.upload_state === "Verified" ? (
            <Image source={{ uri: mediaUrl(e.uuid) }} style={{ width: "100%", height: 180, borderRadius: 6 }} contentFit="cover" />
          ) : null}
          {e.kind === "note" ? <T>{e.text}</T> : null}
          {e.transcripts?.length ? <T>What was said: &apos;{e.transcripts[e.transcripts.length - 1].text}&apos;</T> : null}
          {(cByEv[e.uuid] || []).map((c: any) => <T key={c.uuid} muted>- {SUGGESTION[c.category] || "Something worth a closer look"} - {c.review_state === "Pending" ? "not checked yet" : (c.review_state || "").toLowerCase()}</T>)}
        </Card>
      ))}
      <Card testID="review-observations">
        <H>Observations ({d.observations.length})</H>
        {d.observations.map((o: any) => (
          <T key={o.uuid}>
            - {o.kind === "not_inspected" ? `Not inspected: ${o.area} - ${o.reason}` : o.kind === "measurement" ? `${o.label}: ${o.value} ${o.unit || ""}` : `${o.kind}${o.category ? ` (${o.category})` : ""}: ${o.text}`}
            {o.source_candidate_id ? " [from reviewed candidate]" : ""}
          </T>
        ))}
      </Card>
      <Card testID="review-audit">
        <H>Audit</H>
        {d.audit.slice(0, 15).map((a: any) => <T key={a.uuid} muted size={12}>{fmt(a.at)} - {a.actor_role} - {a.action}</T>)}
      </Card>
    </Screen>
  );
}
