import { router, useFocusEffect, useLocalSearchParams } from "expo-router";
import { useCallback, useState } from "react";
import { View } from "react-native";
import * as Linking from "expo-linking";
import * as WebBrowser from "expo-web-browser";
import { API, ApiError, api, errText, getToken } from "@/src/api";
import { Badge, Banner, Btn, Card, H, Input, Loading, Row, Screen, Sheet, T } from "@/src/ui";

const CATS = ["material", "labor", "handling", "equipment", "mobilization", "general_repair", "other"];
const blank = { category: "other", description: "", quantity: "", unit: "", unit_cost: "", markup_pct: "0", taxable: false, reason: "", duplicate_reason: "", material_dependent: false };

export default function Estimate() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const [d, setD] = useState<any>(null);
  const [msg, setMsg] = useState<{ tone: any; text: string } | null>(null);
  const [preview, setPreview] = useState<any>(null);
  const [blockers, setBlockers] = useState<string[] | null>(null);
  const [line, setLine] = useState<any>(null);
  const [edit, setEdit] = useState<any>(null);
  const [scope, setScope] = useState<any>(null);
  const [terms, setTerms] = useState<any>(null);
  const [shared, setShared] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setD(await api(`/engagements/${id}`));
    } catch (e) {
      setMsg({ tone: "error", text: errText(e) });
    }
  }, [id]);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  async function run(fn: () => Promise<any>, ok?: string) {
    setMsg(null);
    try {
      const r = await fn();
      if (ok) setMsg({ tone: "success", text: ok });
      await load();
      return r;
    } catch (e) {
      const det = e instanceof ApiError ? e.detail : null;
      if (det?.blockers) setBlockers(det.blockers);
      setMsg({ tone: e instanceof ApiError && e.status === 409 ? "warning" : "error", text: det?.field ? `${det.field}: ${det.message}` : errText(e) });
      await load();
    }
  }

  if (!d) return <Screen title="Estimate">{msg ? <Banner tone="error" text={msg.text} /> : <Loading />}</Screen>;
  const dr = d.draft;
  const t = d.totals;
  const accepted = !!d.engagement.accepted_version_id;
  const rev = dr.revision;
  const ties = d.scope_items.filter((s: any) => s.kind === "tie_replacement");

  return (
    <Screen testID="estimate-screen" title={`Estimate ${d.engagement.proposal_number}`} subtitle={d.visit.title}
      footer={
        <Row>
          <Btn small kind="secondary" testID="estimate-agreement-button" title="Agreement preview" icon="file-document" onPress={() => router.push(`/agreement/${id}`)} style={{ flexGrow: 1 }} />
          <Btn small kind="secondary" testID="estimate-validate-button" title="Validate" icon="check-decagram" onPress={() => run(async () => setBlockers((await api(`/engagements/${id}/validate`, { method: "POST" })).blockers))} style={{ flexGrow: 1 }} />
          <Btn small testID="estimate-publish-button" title="Publish" icon="publish" disabled={accepted}
            onPress={() => run(() => api(`/engagements/${id}/publish`, { body: { expected_revision: rev, idempotency_key: `${id}-${rev}` } }).then((v) => { setBlockers(null); setMsg({ tone: "success", text: `Version ${v.version_no} published - snapshot ${v.snapshot_hash.slice(0, 12)} - agreement ${v.document_hash.slice(0, 12)}` }); }))} style={{ flexGrow: 1 }} />
        </Row>
      }>
      {msg ? <Banner testID="estimate-message" tone={msg.tone} icon="information" text={msg.text} /> : null}
      {accepted ? <Banner testID="estimate-accepted-banner" tone="success" icon="handshake" text="Engagement accepted - commercial changes are locked." /> : null}
      {blockers ? (
        <Card testID="estimate-blockers">
          <H>{blockers.length ? `Publish blocked (${blockers.length})` : "No blockers - ready to publish"}</H>
          {blockers.map((b, i) => <Badge key={`${i}-${b}`} label={b} icon="alert-circle" tone="error" />)}
        </Card>
      ) : null}

      <Card testID="estimate-totals">
        <H>Totals (USD)</H>
        <T>Subtotal ${t.subtotal} - Tax {t.tax_rate}% ${t.tax}</T>
        <T testID="estimate-total" bold size={20}>Total ${t.total}</T>
        <T muted>Internal cost ${t.internal_cost} - Margin {t.margin_pct === "N/A" ? "N/A" : `${t.margin_pct}%`}</T>
        <T muted size={12}>{d.tax_treatment_text}</T>
        {d.warnings.map((w: any) => <Badge key={w.code} label={w.message + (w.resolved ? " (reason given)" : "")} icon="alert" tone="warning" />)}
      </Card>

      <H>Confirmed scope</H>
      {d.scope_items.map((s: any) => (
        <Card key={s.uuid} testID={`scope-${s.uuid}`}>
          <T bold>{s.kind === "tie_replacement" ? `${s.tie_type === "crosstie" ? "Crosstie" : "Switch tie"} replacement` : "Further assessment"} - rev {s.revision}</T>
          <T>Location: {s.location || "-"} - Repair {s.repair_quantity ?? "-"} {s.unit} (inspected {s.inspected_quantity ?? "-"})</T>
          <T>Spec: {s.specification || "-"} - Supply: {s.material_responsibility || "-"} - Access: {s.access_disposition || "-"}</T>
          {s.material_responsibility === "Customer" ? <Badge label="Ties supplied by customer" icon="truck" /> : null}
          {!accepted ? (
            <Row>
              <Btn small testID={`scope-preview-${s.uuid}`} title="Preview tie package" icon="package-variant" onPress={() => run(async () => setPreview({ sid: s.uuid, ...(await api(`/scope-items/${s.uuid}/package-preview`)) }))} style={{ flexGrow: 1 }} />
              <Btn small kind="secondary" testID={`scope-edit-${s.uuid}`} title="Correct facts" icon="pencil" onPress={() => setScope({ ...s })} style={{ flexGrow: 1 }} />
            </Row>
          ) : null}
        </Card>
      ))}
      {!accepted ? <Btn small kind="secondary" testID="scope-add-button" title="Confirm tie scope from visit" icon="plus" onPress={() => {
        const a = d.visit.answers || {};
        setScope({ new: true, kind: "tie_replacement", tie_type: "crosstie", unit: "each", location: a.work_location?.value || "", inspected_quantity: a.inspected_quantity?.value ?? "", repair_quantity: a.repair_quantity?.value ?? "", specification: a.tie_specification?.value || "", material_responsibility: a.material_responsibility?.value || "", access_disposition: "" });
      }} /> : null}
      {!ties.length ? <T muted>No confirmed tie scope yet.</T> : null}

      <H>Lines ({dr.lines.length})</H>
      {dr.lines.map((l: any) => (
        <Card key={l.uuid} testID={`line-${l.uuid}`}>
          <Row>
            <T bold style={{ flex: 1 }}>{l.description}</T>
            <Badge label={l.reviewed ? "Reviewed" : "Needs review"} icon={l.reviewed ? "check" : "eye"} tone={l.reviewed ? "success" : "warning"} />
            {!l.included ? <Badge label="Excluded" icon="minus-circle" /> : null}
          </Row>
          <T>{l.quantity} {l.unit} x ${l.unit_cost} + {l.markup_pct}% = <T bold>${l.line_total}</T> (cost ${l.internal_cost}){l.taxable ? " - taxable" : ""}</T>
          <T muted size={12}>{(l.category || "").replace("_", " ")}{l.quantity_origin ? ` - quantity from ${String(l.quantity_origin).replace("_", " ")}` : ""}</T>
          {l.needs_review_reason ? <T muted size={12}>{l.needs_review_reason}</T> : null}
          {!accepted ? (
            <Row>
              {!l.reviewed ? <Btn small testID={`line-review-${l.uuid}`} title="Mark reviewed" icon="check" onPress={() => run(() => api(`/engagements/${id}/lines/${l.uuid}`, { method: "PATCH", body: { expected_revision: rev, reviewed: true } }))} /> : null}
              <Btn small kind="secondary" testID={`line-edit-${l.uuid}`} title="Edit" icon="pencil" onPress={() => setEdit({ uuid: l.uuid, quantity: l.quantity, unit_cost: l.unit_cost, markup_pct: l.markup_pct, duplicate_reason: l.duplicate_reason || "" })} />
              <Btn small kind="secondary" testID={`line-include-${l.uuid}`} title={l.included ? "Exclude" : "Include"} icon="swap-horizontal" onPress={() => run(() => api(`/engagements/${id}/lines/${l.uuid}`, { method: "PATCH", body: { expected_revision: rev, included: !l.included } }))} />
            </Row>
          ) : null}
        </Card>
      ))}
      {!accepted ? <Btn small kind="secondary" testID="line-add-button" title="Add manual line" icon="plus" onPress={() => setLine({ ...blank })} /> : null}

      <Card testID="estimate-terms">
        <H>Photos, terms, expiry</H>
        <T bold>Selected photos</T>
        {d.photos.map((p: any) => {
          const on = dr.selected_photo_ids.includes(p.uuid);
          return <Btn key={p.uuid} small kind={on ? "primary" : "secondary"} testID={`photo-select-${p.uuid}`} icon={on ? "checkbox-marked" : "checkbox-blank-outline"} title={p.caption || p.filename || p.uuid.slice(0, 8)}
            disabled={accepted} onPress={() => run(() => api(`/engagements/${id}/draft`, { method: "PATCH", body: { expected_revision: rev, selected_photo_ids: on ? dr.selected_photo_ids.filter((x: string) => x !== p.uuid) : [...dr.selected_photo_ids, p.uuid] } }))} />;
        })}
        <T>Expiry (site-local): {dr.expiry_local || "-"}</T>
        <T>Terms: {dr.terms_reviewed ? "Reviewed" : "Unreviewed edits"}</T>
        {!accepted ? <Btn small kind="secondary" testID="terms-edit-button" title="Edit terms / expiry" icon="pencil" onPress={() => setTerms({ ...dr.terms, expiry_local: dr.expiry_local || "", contractor_identity: dr.contractor_identity || "" })} /> : null}
        {!dr.terms_reviewed && !accepted ? <Btn small testID="terms-review-button" title="Mark terms reviewed" icon="check" onPress={() => run(() => api(`/engagements/${id}/draft`, { method: "PATCH", body: { expected_revision: rev, terms_reviewed: true } }))} /> : null}
        {dr.feedback_history?.length ? <T muted>Customer feedback: {dr.feedback_history.map((f: any) => `v${f.version_no}: ${f.comment || "-"}`).join(" | ")}</T> : null}
      </Card>

      <H>Versions</H>
      {shared ? <Banner testID="share-link-banner" tone="success" icon="link" text={`Customer link: ${shared}`} /> : null}
      {d.versions.map((v: any) => (
        <Card key={v.uuid} testID={`version-${v.version_no}`}>
          <Row>
            <T bold>Version {v.version_no}</T>
            <Badge testID={`version-status-${v.version_no}`} label={v.status} icon="file-certificate" />
            <Badge label={`Contract ${v.contract_status}`} icon="file-sign" />
          </Row>
          <T muted size={12}>Expires {v.snapshot?.expiry?.local || "-"}</T>
          {v.links.map((l: any) => <T key={l.uuid} muted size={12}>Link {l.uuid.slice(0, 8)} - {l.revoked ? "Revoked" : "Active"}</T>)}
          <Row>
            <Btn small kind="secondary" testID={`version-print-${v.version_no}`} title="Print" icon="printer" onPress={() => WebBrowser.openBrowserAsync(`${API}/proposals/${v.uuid}/print?auth=${encodeURIComponent(getToken() || "")}`)} />
            {["Published", "Accepted"].includes(v.status) ? <Btn small testID={`version-share-${v.version_no}`} title="Share" icon="share-variant" onPress={() => run(async () => { const r = await api(`/versions/${v.uuid}/share`, { method: "POST" }); setShared(Linking.createURL(r.path)); })} /> : null}
            {v.links.filter((l: any) => !l.revoked).map((l: any) => <Btn key={l.uuid} small kind="danger" testID={`link-revoke-${l.uuid}`} title="Revoke link" icon="link-off" onPress={() => run(() => api(`/links/${l.uuid}/revoke`, { method: "POST" }), "Link revoked")} />)}
            {v.status === "Changes requested" && !accepted ? <Btn small testID={`version-copy-${v.version_no}`} title="Copy to draft" icon="content-copy" onPress={() => run(() => api(`/versions/${v.uuid}/copy-to-draft`, { method: "POST" }), "Copied into draft with feedback")} /> : null}
          </Row>
        </Card>
      ))}
      {d.decisions.length ? (
        <Card testID="estimate-decisions">
          <H>Customer decisions</H>
          {d.decisions.map((x: any) => (
            <View key={x.uuid} style={{ gap: 4 }}>
              <T>v{x.version_no} - {x.type === "accept" ? "Accepted" : "Changes requested"} by {x.name} ({x.email}){x.comment ? `: '${x.comment}'` : ""}</T>
              {x.topic_suggestion ? <Badge testID={`decision-topic-${x.uuid}`} label={x.topic_suggestion.status === "Done" ? `Topic suggestion: ${x.topic_suggestion.topic} (staff only)` : "Topic: Not run"} icon="tag" /> : null}
            </View>
          ))}
        </Card>
      ) : null}
      {d.work_order ? <Btn testID="estimate-workorder-button" title={`Work order ${d.work_order.number}`} icon="clipboard-text" onPress={() => router.push(`/workorder/${d.work_order.uuid}`)} /> : null}

      <Sheet visible={!!preview} onClose={() => setPreview(null)} title="Tie package preview" testID="package-preview-sheet">
        {preview?.blockers?.map((b: string, i: number) => <Badge key={`${i}-${b}`} label={b} icon="alert-circle" tone="error" />)}
        {preview?.ties_supplied_by_customer ? <Badge label="Ties supplied by customer" icon="truck" /> : null}
        {preview?.lines?.map((l: any) => <T key={l.uuid}>- {l.description}: {l.quantity} {l.unit} = ${l.line_total} ({l.quantity_origin}){l.needs_review_reason?.startsWith("Configured") ? " - Needs review" : ""}</T>)}
        {preview && !preview.blockers.length ? <Btn testID="package-add-button" title="Add package" icon="plus" onPress={() => run(() => api(`/scope-items/${preview.sid}/package`, { method: "POST" }).then((r) => { setPreview(null); setMsg({ tone: "success", text: r.added ? "Package lines added" : "Already added - no duplicates" }); }))} /> : null}
      </Sheet>
      <Sheet visible={!!line} onClose={() => setLine(null)} title="Manual line" testID="line-form-sheet">
        {line ? (
          <>
            <Row>{CATS.map((c) => <Btn key={c} small kind={line.category === c ? "primary" : "secondary"} testID={`line-cat-${c}`} title={c.replace("_", " ")} onPress={() => setLine({ ...line, category: c })} />)}</Row>
            {(["description", "quantity", "unit", "unit_cost", "markup_pct", "reason"] as const).map((k) => (
              <Input key={k} testID={`line-${k}-input`} label={k.replace("_", " ")} value={String(line[k])} keyboardType={["quantity", "unit_cost", "markup_pct"].includes(k) ? "decimal-pad" : "default"} onChangeText={(x) => setLine({ ...line, [k]: x })} />
            ))}
            {line.category === "mobilization" ? <Input testID="line-duplicate-reason-input" label="Reason to keep duplicate mobilization" value={line.duplicate_reason} onChangeText={(x) => setLine({ ...line, duplicate_reason: x })} /> : null}
            <Btn small kind="secondary" testID="line-taxable-toggle" title={`Taxable: ${line.taxable ? "Yes" : "No"}`} icon="percent" onPress={() => setLine({ ...line, taxable: !line.taxable })} />
            {line.category === "general_repair" ? <Btn small kind="secondary" testID="line-material-toggle" title={`Material-dependent: ${line.material_dependent ? "Yes" : "No"}`} onPress={() => setLine({ ...line, material_dependent: !line.material_dependent })} /> : null}
            <Btn testID="line-save-button" title="Add line" icon="content-save" onPress={() => run(() => api(`/engagements/${id}/lines`, { body: { ...line, expected_revision: rev, duplicate_reason: line.duplicate_reason || null } }).then(() => setLine(null)))} />
          </>
        ) : null}
      </Sheet>
      <Sheet visible={!!edit} onClose={() => setEdit(null)} title="Edit line" testID="line-edit-sheet">
        {edit ? (
          <>
            {(["quantity", "unit_cost", "markup_pct", "duplicate_reason"] as const).map((k) => <Input key={k} testID={`edit-${k}-input`} label={k.replace("_", " ")} value={String(edit[k])} onChangeText={(x) => setEdit({ ...edit, [k]: x })} />)}
            <Btn testID="edit-save-button" title="Save" icon="content-save" onPress={() => run(() => api(`/engagements/${id}/lines/${edit.uuid}`, { method: "PATCH", body: { expected_revision: rev, quantity: edit.quantity, unit_cost: edit.unit_cost, markup_pct: edit.markup_pct, duplicate_reason: edit.duplicate_reason || undefined } }).then(() => setEdit(null)))} />
          </>
        ) : null}
      </Sheet>
      <Sheet visible={!!scope} onClose={() => setScope(null)} title={scope?.new ? "Confirm tie scope" : "Correct scope facts"} testID="scope-form-sheet">
        {scope ? (
          <>
            <Row>{["crosstie", "switch_tie"].map((x) => <Btn key={x} small kind={scope.tie_type === x ? "primary" : "secondary"} testID={`scope-type-${x}`} title={x === "crosstie" ? "Crosstie" : "Switch tie"} onPress={() => setScope({ ...scope, tie_type: x })} />)}</Row>
            {(["location", "inspected_quantity", "repair_quantity", "unit", "specification", "access_disposition"] as const).map((k) => <Input key={k} testID={`scope-${k}-input`} label={k.replace("_", " ")} value={String(scope[k] ?? "")} onChangeText={(x) => setScope({ ...scope, [k]: x })} />)}
            <Row>{["Contractor", "Customer", "Unresolved"].map((x) => <Btn key={x} small kind={scope.material_responsibility === x ? "primary" : "secondary"} testID={`scope-supply-${x.toLowerCase()}`} title={x} onPress={() => setScope({ ...scope, material_responsibility: x })} />)}</Row>
            <Btn testID="scope-save-button" title="Save scope" icon="content-save" onPress={() => {
              const body: any = { kind: scope.kind || "tie_replacement", tie_type: scope.tie_type, location: scope.location || null, unit: scope.unit || null, specification: scope.specification || null,
                material_responsibility: scope.material_responsibility || null, access_disposition: scope.access_disposition || null,
                inspected_quantity: scope.inspected_quantity === "" ? null : Number(scope.inspected_quantity), repair_quantity: scope.repair_quantity === "" ? null : Number(scope.repair_quantity) };
              run(() => (scope.new ? api(`/engagements/${id}/scope-items`, { body }) : api(`/scope-items/${scope.uuid}`, { method: "PATCH", body: { ...body, expected_revision: scope.revision } })).then(() => setScope(null)));
            }} />
          </>
        ) : null}
      </Sheet>
      <Sheet visible={!!terms} onClose={() => setTerms(null)} title="Terms & expiry" testID="terms-form-sheet">
        {terms ? (
          <>
            {["contractor_identity", "payment_terms", "schedule_wording", "assumptions", "exclusions", "validity", "acceptance_wording"].map((k) => <Input key={k} multiline testID={`terms-${k}-input`} label={k.replace(/_/g, " ")} value={terms[k] || ""} onChangeText={(x) => setTerms({ ...terms, [k]: x })} />)}
            <Input testID="terms-expiry-input" label="Expiry, site-local (YYYY-MM-DDTHH:MM)" value={terms.expiry_local} onChangeText={(x) => setTerms({ ...terms, expiry_local: x })} />
            <Btn testID="terms-save-button" title="Save" icon="content-save" onPress={() => {
              const { expiry_local, contractor_identity, ...tt } = terms;
              run(() => api(`/engagements/${id}/draft`, { method: "PATCH", body: { expected_revision: rev, terms: tt, expiry_local: expiry_local || undefined, contractor_identity } }).then(() => setTerms(null)));
            }} />
          </>
        ) : null}
      </Sheet>
    </Screen>
  );
}
