import { useLocalSearchParams } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";
import { Image } from "expo-image";
import * as WebBrowser from "expo-web-browser";
import { API, ApiError, api, errText } from "@/src/api";
import { Badge, Banner, Btn, Card, H, Input, Loading, Row, Screen, T } from "@/src/ui";

export default function CustomerProposal() {
  const { token } = useLocalSearchParams<{ token: string }>();
  const [p, setP] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const [mode, setMode] = useState<"accept" | "changes" | null>(null);
  const [f, setF] = useState({ name: "", email: "", comment: "", agree: false });
  const [fieldErr, setFieldErr] = useState<Record<string, string>>({});
  const [done, setDone] = useState<string | null>(null);
  const load = useCallback(() => api(`/public/proposals/${token}`).then(setP).catch((e) => setErr(errText(e))), [token]);
  useEffect(() => { load(); }, [load]);

  const op = useRef<{ id: string; payload: string } | null>(null);
  async function submit() {
    setFieldErr({});
    setErr(null);
    try {
      // stable operation id: a retry of the same details reuses it; edited details get a new one
      const payload = JSON.stringify([f.name.trim(), f.email.trim().toLowerCase(), f.comment.trim()]);
      if (!op.current || op.current.payload !== payload) op.current = { id: `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`, payload };
      const r = mode === "accept"
        ? await api(`/public/proposals/${token}/accept`, { body: { name: f.name, email: f.email, agree: f.agree } })
        : await api(`/public/proposals/${token}/changes`, { body: { name: f.name, email: f.email, comment: f.comment, request_key: op.current.id } });
      op.current = null;
      setDone(mode === "accept" ? `Accepted. Work order ${r.work_order_number} created for planning.` : r.message);
      setMode(null);
      load();
    } catch (e) {
      if (e instanceof ApiError && e.detail?.errors) setFieldErr(e.detail.errors);
      else setErr(errText(e));
    }
  }

  if (!p) return <Screen back={false} title="Proposal">{err ? <Banner testID="public-error" tone="error" icon="link-off" text={err} /> : <Loading />}</Screen>;
  return (
    <Screen testID="public-proposal-screen" back={false} title={`Proposal ${p.proposal_number} - v${p.version_no}`} subtitle={p.contractor.legal_identity}>
      {done ? <Banner testID="public-done-message" tone="success" icon="check" text={done} /> : null}
      {err ? <Banner testID="public-error" tone="error" icon="alert" text={err} /> : null}
      <Row>
        <Badge testID="public-status" label={p.status} icon="file-certificate" />
        <Badge label={`Agreement ${p.contract_status}`} icon="file-sign" />
      </Row>
      {!p.can_decide && p.status !== "Accepted" ? <Banner testID="public-readonly" tone="warning" icon="lock" text={`This version is ${p.status} - read-only, acceptance disabled.`} /> : null}
      <Card>
        <T>{p.customer_site}</T>
        <T testID="public-expiry" bold>Valid until {p.expiry.local} ({p.expiry.timezone}) = {p.expiry.utc} UTC</T>
      </Card>
      {p.ties_supplied_by_customer ? <Banner tone="info" icon="truck" text="Ties supplied by customer" /> : null}
      <Card testID="public-scope">
        <H>Scope</H>
        {p.findings.map((x: string) => <T key={x}>- {x}</T>)}
        {p.not_inspected.map((n: any) => <T key={n.area} muted>Not inspected: {n.area} - {n.reason} (no charges)</T>)}
      </Card>
      {p.photos.map((ph: any) => <Image key={ph.url} source={{ uri: `${API}${ph.url.slice(4)}` }} style={{ width: "100%", height: 220, borderRadius: 8 }} contentFit="cover" />)}
      <Card testID="public-price">
        <H>Price (USD)</H>
        {p.lines.map((l: any) => <T key={l.description}>{l.description}: {l.quantity} {l.unit} - ${l.line_total}</T>)}
        <T>Subtotal ${p.totals.subtotal} - Tax ({p.totals.tax_rate}%) ${p.totals.tax}</T>
        <T testID="public-total" bold size={20}>Total ${p.totals.total}</T>
        <T muted>{p.tax_treatment_text}</T>
      </Card>
      <Card testID="public-agreement">
        <Banner tone="warning" icon="alert" text={p.agreement.label} />
        <T>{p.agreement.document_text}</T>
      </Card>
      <Btn kind="secondary" testID="public-print-button" title="Printable version" icon="printer" onPress={() => WebBrowser.openBrowserAsync(`${API}/public/proposals/${token}/print`)} />
      {p.can_decide && !done ? (
        <Row>
          <Btn testID="public-accept-button" title="Accept" icon="handshake" onPress={() => setMode("accept")} style={{ flexGrow: 1 }} />
          <Btn kind="secondary" testID="public-changes-button" title="Request changes" icon="comment-edit" onPress={() => setMode("changes")} style={{ flexGrow: 1 }} />
        </Row>
      ) : null}
      {mode ? (
        <Card testID="public-decision-form">
          <Input testID="public-name-input" label="Your name" value={f.name} onChangeText={(x) => setF({ ...f, name: x })} />
          {fieldErr.name ? <Badge testID="public-name-error" label={fieldErr.name} tone="error" icon="alert-circle" /> : null}
          <Input testID="public-email-input" label="Email" keyboardType="email-address" value={f.email} onChangeText={(x) => setF({ ...f, email: x })} />
          {fieldErr.email ? <Badge testID="public-email-error" label={fieldErr.email} tone="error" icon="alert-circle" /> : null}
          {mode === "accept" ? (
            <>
              <Btn kind="secondary" testID="public-agree-checkbox" icon={f.agree ? "checkbox-marked" : "checkbox-blank-outline"} title="I have read and accept the agreement above" onPress={() => setF({ ...f, agree: !f.agree })} />
              {fieldErr.agree ? <Badge testID="public-agree-error" label={fieldErr.agree} tone="error" icon="alert-circle" /> : null}
            </>
          ) : (
            <>
              <Input testID="public-comment-input" label="What should change?" multiline value={f.comment} onChangeText={(x) => setF({ ...f, comment: x })} />
              {fieldErr.comment ? <Badge label={fieldErr.comment} tone="error" icon="alert-circle" /> : null}
            </>
          )}
          <Btn testID="public-submit-button" title={mode === "accept" ? "Confirm acceptance" : "Send change request"} icon="send" onPress={submit} />
        </Card>
      ) : null}
    </Screen>
  );
}
