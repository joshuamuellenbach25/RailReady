import { Link } from "react-router-dom";
import { AlertTriangle, ArrowRight, Check, CheckSquare, Eye, FileCheck2, MinusCircle, Package, Pencil, Plus, Printer, RefreshCw, Square, Truck, X } from "lucide-react";
import { mediaUrl, openPrint } from "@/lib/api";
import { Badge, Banner, Blocker, Btn, Card, H2, Mono, short } from "../ui";

export function TotalsCard({ d }) {
  const t = d.totals;
  return (
    <Card testid="estimate-totals" className="space-y-2">
      <H2>Totals <span className="text-sm font-normal text-[#59636B]">(USD)</span></H2>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
        <dt>Subtotal</dt><dd data-testid="estimate-subtotal" className="text-right font-mono">${t.subtotal}</dd>
        <dt>Tax ({t.tax_rate}%)</dt><dd data-testid="estimate-tax" className="text-right font-mono">${t.tax}</dd>
        <dt className="text-lg font-semibold">Total</dt><dd data-testid="estimate-total" className="text-right font-mono text-lg font-semibold">${t.total}</dd>
        <dt className="text-[#59636B]">Internal cost</dt><dd data-testid="estimate-internal-cost" className="text-right font-mono text-[#59636B]">${t.internal_cost}</dd>
        <dt className="text-[#59636B]">Margin</dt><dd data-testid="estimate-margin" className="text-right font-mono text-[#59636B]">{t.margin_pct === "N/A" ? "N/A" : `${t.margin_pct}% margin`}</dd>
      </dl>
      <p data-testid="estimate-tax-treatment" className="text-xs text-[#59636B]">{d.tax_treatment_text}</p>
      {d.warnings.map((w) => <Badge key={w.code} label={w.message + (w.resolved ? " (reason given)" : "")} icon={AlertTriangle} tone="warning" />)}
    </Card>
  );
}

export function GateCard({ val, stale, accepted, busy, onValidate, onPublish }) {
  const blocked = !val || stale || !val.ok;
  return (
    <Card testid="estimate-blockers" className="space-y-3">
      <H2>{!val ? "Ready to publish" : stale ? "The estimate changed. Check it again." : val.blockers.length ? `A few things to finish (${val.blockers.length})` : "Ready to send to the customer"}</H2>
      {val && !stale ? (
        <ul className="space-y-1">
          {val.blockers.map((b, i) => <li key={`${i}-${b}`}><Blocker testid={`blocker-${i}`} text={b} /></li>)}
        </ul>
      ) : null}
      <p className="text-[13px] text-[#59636B]">Select Check estimate. Anything left to finish is listed here.</p>
      <div className="flex flex-wrap gap-2">
        <Btn small kind="secondary" icon={FileCheck2} testid="estimate-validate-button" loading={busy === "validate"} onClick={onValidate}>Check estimate</Btn>
        <Btn small icon={ArrowRight} testid="estimate-publish-button" disabled={accepted || blocked} loading={busy === "publish"} onClick={onPublish}>Publish and make link</Btn>
      </div>
      {accepted || blocked ? (
        <Blocker testid="estimate-publish-reason"
          text={accepted ? "The customer already accepted this proposal. Make a copy to change the scope." : !val ? "Select Check estimate first." : stale ? "The estimate changed. Select Check estimate again." : "Finish the items above, then publish."} />
      ) : null}
    </Card>
  );
}

export function AgreementPanel({ a, err, rev, onRefresh, busy }) {
  const stale = a && a.draft_revision !== rev;
  return (
    <Card testid="agreement-panel" className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <H2>Agreement preview</H2>
        <Btn small kind={stale || !a ? "primary" : "secondary"} icon={RefreshCw} testid="estimate-agreement-button" loading={busy} onClick={onRefresh}>{a ? "Refresh agreement preview" : "Open agreement preview"}</Btn>
      </div>
      {err ? <Banner tone="error" text={err} testid="agreement-error" /> : null}
      {a ? (
        <>
          {stale ? <Badge testid="agreement-stale" label={`Out of date: previewed revision ${a.draft_revision}, draft is now ${rev}`} icon={AlertTriangle} tone="warning" /> : null}
          {a.missing.length ? a.missing.map((m) => <Badge key={m} label={`Missing agreement variable: ${m}`} tone="error" />) : <Badge label="All required variables filled" icon={Check} tone="success" />}
          <p data-testid="agreement-estimate-summary" className="text-sm">Subtotal ${a.totals.subtotal}, tax ${a.totals.tax}, <b>total ${a.totals.total} USD</b></p>
          <div data-testid="agreement-document" data-raw="1" tabIndex={0} aria-label="Agreement text" className="max-h-80 overflow-y-auto whitespace-pre-wrap rounded border border-[#D9DEE2] bg-[#F3F4F4] p-3 text-sm leading-relaxed">{a.document_text}</div>
          <Mono label="Document details" className="block">Template v{a.template_version}, {short(a.template_hash)}, document {short(a.document_hash)}, draft rev {a.draft_revision} (frozen only at publish)</Mono>
        </>
      ) : null}
    </Card>
  );
}

const scopeTitle = (s) => (s.kind === "tie_replacement" ? `${s.tie_type === "crosstie" ? "Crosstie" : "Switch tie"} replacement` : "Further assessment");

export function ScopeList({ d, accepted, onPreview, onEdit, onAdd }) {
  return (
    <section aria-labelledby="scope-h" className="space-y-3">
      <H2 id="scope-h">Confirmed scope</H2>
      {d.scope_items.map((s) => (
        <Card key={s.uuid} testid={`scope-${s.uuid}`} className="space-y-2">
          <p className="font-semibold">{scopeTitle(s)}</p>
          <p className="text-sm">Location: {s.location || "Not set"}. Repair <b>{s.repair_quantity ?? "-"}</b> {s.unit} (inspected {s.inspected_quantity ?? "-"})</p>
          <p className="text-sm">Spec: {s.specification || "Not set"}. Supply: {s.material_responsibility || "Not set"}. Access: {s.access_disposition || "Not set"}</p>
          {s.material_responsibility === "Customer" ? <Badge label="Ties supplied by customer" icon={Truck} /> : null}
          {!accepted ? (
            <div className="flex flex-wrap gap-2">
              <Btn small icon={Package} testid={`scope-preview-${s.uuid}`} onClick={() => onPreview(s)}>Preview tie package</Btn>
              <Btn small kind="secondary" icon={Pencil} testid={`scope-edit-${s.uuid}`} onClick={() => onEdit(s)}>Correct facts</Btn>
            </div>
          ) : null}
        </Card>
      ))}
      {!d.scope_items.some((s) => s.kind === "tie_replacement") ? <p className="text-sm text-[#59636B]">No confirmed tie scope yet.</p> : null}
      {!accepted ? <Btn small kind="secondary" icon={Plus} testid="scope-add-button" onClick={onAdd}>Confirm tie scope from visit</Btn> : null}
    </section>
  );
}

export function LinesList({ lines, accepted, onReview, onEdit, onToggle, onAdd }) {
  return (
    <section aria-labelledby="lines-h" className="space-y-3">
      <H2 id="lines-h">Lines ({lines.length})</H2>
      {lines.map((l) => (
        <Card key={l.uuid} testid={`line-${l.uuid}`} className={`space-y-2 ${l.included ? "" : "bg-[#F3F4F4]"}`}>
          <div className="flex flex-wrap items-start justify-between gap-2">
            <p className="font-bold">{l.description}</p>
            <div className="flex flex-wrap gap-1">
              <Badge testid={`line-review-state-${l.uuid}`} label={l.reviewed ? "Checked" : "Needs a quick check"} icon={l.reviewed ? Check : Eye} tone={l.reviewed ? "success" : "warning"} />
              {!l.included ? <Badge label="Excluded" icon={MinusCircle} /> : null}
            </div>
          </div>
          <p className="text-sm">
            <span className="font-mono">{l.quantity} {l.unit} x ${l.unit_cost} + {l.markup_pct}%</span> = <b className="font-mono">${l.line_total}</b>
            <span className="text-[#59636B]"> (cost ${l.internal_cost}){l.taxable ? ", taxable" : ""}</span>
          </p>
          <p data-testid={`line-origin-${l.uuid}`} className="text-xs text-[#59636B]">
            {l.category}, quantity from {ORIGIN[l.quantity_origin] || "the estimator"}
          </p>
          {l.needs_review_reason ? <p className="text-xs text-amber-800">{l.needs_review_reason}</p> : null}
          {!accepted ? (
            <div className="flex flex-wrap gap-2">
              {!l.reviewed ? <Btn small icon={Check} testid={`line-review-${l.uuid}`} onClick={() => onReview(l)}>Looks right</Btn> : null}
              <Btn small kind="secondary" icon={Pencil} testid={`line-edit-${l.uuid}`} onClick={() => onEdit(l)}>Edit</Btn>
              <Btn small kind="secondary" icon={l.included ? MinusCircle : Plus} testid={`line-include-${l.uuid}`} onClick={() => onToggle(l)}>{l.included ? "Exclude" : "Include"}</Btn>
            </div>
          ) : null}
        </Card>
      ))}
      {!accepted ? <Btn small kind="secondary" icon={Plus} testid="line-add-button" onClick={onAdd}>Add manual line</Btn> : null}
    </section>
  );
}

export function PhotosTerms({ d, accepted, onTogglePhoto, onEditTerms, onReviewTerms }) {
  const dr = d.draft;
  return (
    <Card testid="estimate-terms" className="space-y-3">
      <H2>Photos, terms, expiry</H2>
      <fieldset>
        <legend className="mb-2 text-sm font-bold">Photos shown to the customer</legend>
        {!d.photos.length ? <p className="text-sm text-[#59636B]">No verified photos on this visit.</p> : null}
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
          {d.photos.map((p) => {
            const on = dr.selected_photo_ids.includes(p.uuid);
            return (
              <button key={p.uuid} type="button" role="checkbox" aria-checked={on} data-testid={`photo-select-${p.uuid}`} disabled={accepted} onClick={() => onTogglePhoto(p, on)}
                className={`rr-focus overflow-hidden rounded-md border text-left disabled:opacity-60 ${on ? "border-[#B32624]" : "border-[#D9DEE2]"}`}>
                <img src={mediaUrl(p.uuid)} alt="" className="h-24 w-full bg-[#22272B] object-cover" />
                <span className="flex items-center gap-1 p-1.5 text-xs font-bold">{on ? <CheckSquare aria-hidden className="h-4 w-4 text-[#B32624]" /> : <Square aria-hidden className="h-4 w-4" />}{p.caption || p.filename || p.uuid.slice(0, 8)}</span>
              </button>
            );
          })}
        </div>
      </fieldset>
      <p className="text-sm" data-testid="estimate-expiry">Expiry (site-local): <b>{dr.expiry_local || "-"}</b></p>
      <p className="text-sm">Terms: <Badge testid="estimate-terms-state" label={dr.terms_reviewed ? "Reviewed" : "Unreviewed edits"} icon={dr.terms_reviewed ? Check : Eye} tone={dr.terms_reviewed ? "success" : "warning"} /></p>
      {!accepted ? (
        <div className="flex flex-wrap gap-2">
          <Btn small kind="secondary" icon={Pencil} testid="terms-edit-button" onClick={onEditTerms}>Edit terms / expiry</Btn>
          {!dr.terms_reviewed ? <Btn small icon={Check} testid="terms-review-button" onClick={onReviewTerms}>Mark terms reviewed</Btn> : null}
        </div>
      ) : null}
      {dr.feedback_history?.length ? <p data-testid="estimate-feedback" className="text-sm text-[#59636B]">Customer feedback: {dr.feedback_history.map((f) => `${f.comment || "-"}`).join(" | ")}</p> : null}
    </Card>
  );
}

const ORIGIN = { package: "the tie package", observation: "the inspection", manual: "the estimator", confirmed_finding: "a confirmed finding" };

export function VersionsList({ d }) {
  if (!d.versions.length && !d.work_order) return null;
  return (
    <Card testid="estimate-versions" className="space-y-2">
      <H2>Published</H2>
      {d.versions.map((v) => (
        <div key={v.uuid} data-testid={`version-${v.version_no}`} className="flex flex-wrap items-center gap-2 border-t border-[#D9DEE2] pt-2">
          <span className="font-semibold">Proposal {v.version_no}</span>
          <Badge testid={`version-status-${v.version_no}`} label={v.status} />
          <Badge label={v.contract_status === "Accepted" ? "Agreement signed" : "Agreement sent"} tone="neutral" />
          <Link to={`/office/proposals/${v.uuid}`} data-testid={`version-open-${v.version_no}`} className="rr-focus ml-auto inline-flex items-center gap-1 text-sm font-bold text-[#B32624] hover:underline">Open proposal <ArrowRight aria-hidden className="h-3.5 w-3.5" /></Link>
          <Btn small kind="ghost" icon={Printer} testid={`version-print-${v.version_no}`} onClick={() => openPrint(`/proposals/${v.uuid}/print`)}>Print</Btn>
        </div>
      ))}
      {d.work_order ? (
        <Link to={`/office/work-orders/${d.work_order.uuid}`} data-testid="estimate-workorder-button" className="rr-focus inline-flex min-h-[44px] items-center gap-2 rounded-md border border-[#B32624] bg-[#B32624] px-3 font-bold text-white hover:bg-[#B32624]">
          Work order {d.work_order.number} <ArrowRight aria-hidden className="h-4 w-4" />
        </Link>
      ) : null}
    </Card>
  );
}
