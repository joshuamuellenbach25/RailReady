import { useFocusEffect, useLocalSearchParams } from "expo-router";
import { useCallback, useState } from "react";
import { api, errText } from "@/src/api";
import { Badge, Banner, Card, H, Loading, Screen, T } from "@/src/ui";

export default function AgreementPreview() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const [a, setA] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  useFocusEffect(useCallback(() => { api(`/engagements/${id}/agreement-preview`).then(setA).catch((e) => setErr(errText(e))); }, [id]));
  if (!a) return <Screen title="Agreement preview">{err ? <Banner tone="error" text={err} /> : <Loading />}</Screen>;
  return (
    <Screen testID="agreement-screen" title="Agreement preview" subtitle={a.status ? `Status: ${a.status}` : undefined}>
      <Banner testID="agreement-label" tone="warning" icon="alert" text={a.label} />
      {a.missing.length ? a.missing.map((m: string) => <Badge key={m} label={`Missing agreement variable: ${m}`} icon="alert-circle" tone="error" />) : <Badge label="All required variables filled" icon="check" tone="success" />}
      <Card testID="agreement-estimate-summary">
        <H>Estimate</H>
        <T>Subtotal ${a.totals.subtotal} - Tax ${a.totals.tax} - Total ${a.totals.total} USD</T>
      </Card>
      <Card testID="agreement-document">
        <T>{a.document_text}</T>
        <T muted size={11}>Template v{a.template_version} - {a.template_hash.slice(0, 16)} - document {a.document_hash.slice(0, 16)} (frozen only at publish)</T>
      </Card>
    </Screen>
  );
}
