import { useState } from "react";
import { Plus, Save, Truck } from "lucide-react";
import { Badge, Blocker, Btn, Field, Modal } from "../ui";

export const LINE_CATS = ["material", "labor", "handling", "equipment", "mobilization", "general_repair", "other"];
export const blankLine = { category: "other", description: "", quantity: "", unit: "", unit_cost: "", markup_pct: "0", taxable: false, reason: "", duplicate_reason: "", material_dependent: false };
const label = (k) => k.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());

function Choice({ name, options, value, onChange, testid, render = (x) => x }) {
  return (
    <div role="radiogroup" className="flex flex-wrap gap-2">
      {options.map((o) => (
        <label key={o} className={`flex min-h-[44px] cursor-pointer items-center gap-2 rounded-md border px-3 text-sm font-bold ${value === o ? "border-[#B32624] bg-[#F3F4F4]" : "border-[#C5CCD2]"}`}>
          <input type="radio" name={name} data-testid={`${testid}-${String(o).toLowerCase()}`} checked={value === o} onChange={() => onChange(o)} className="accent-[#B32624]" />
          {render(o)}
        </label>
      ))}
    </div>
  );
}

function Check({ id, checked, onChange, children, testid }) {
  return (
    <label htmlFor={id} className="flex min-h-[44px] cursor-pointer items-center gap-3 rounded-md border border-[#C5CCD2] px-3 font-bold">
      <input id={id} type="checkbox" data-testid={testid} checked={checked} onChange={(e) => onChange(e.target.checked)} className="h-5 w-5 accent-[#B32624]" />
      {children}
    </label>
  );
}

export function PackageModal({ preview, onClose, onAdd, error }) {
  return (
    <Modal open={!!preview} onClose={onClose} title="Tie package" description="These lines come from your saved tie package. Nothing is added until you confirm." testid="package-preview-sheet" wide>
      {preview?.blockers?.map((b, i) => <Blocker key={`${i}-${b}`} testid={`package-blocker-${i}`} text={b} />)}
      {preview?.ties_supplied_by_customer ? <Badge label="Ties supplied by customer" icon={Truck} /> : null}
      <ul className="space-y-1 text-sm">
        {preview?.lines?.map((l) => (
          <li key={l.uuid} className="border-b border-[#D9DEE2] py-1">
            {l.description}: {l.quantity} {l.unit} = <b>${l.line_total}</b> <span className="text-[#59636B]">({l.needs_review_reason?.startsWith("Configured") ? ", needs review" : ""}</span>
          </li>
        ))}
      </ul>
      {error}
      {preview && !preview.blockers?.length ? <Btn testid="package-add-button" icon={Plus} onClick={onAdd}>Add package</Btn> : null}
    </Modal>
  );
}

export function LineModal({ line, setLine, onSave, error }) {
  return (
    <Modal open={!!line} onClose={() => setLine(null)} title="Manual line" description="Enter the quantity and price. The line total is worked out for you." testid="line-form-sheet" wide>
      {line ? (
        <>
          <fieldset><legend className="mb-2 text-sm font-bold">Category</legend>
            <Choice name="line-cat" testid="line-cat" options={LINE_CATS} value={line.category} onChange={(c) => setLine({ ...line, category: c })} render={(c) => c.replace("_", " ")} />
          </fieldset>
          <div className="grid gap-3 sm:grid-cols-2">
            {["description", "quantity", "unit", "unit_cost", "markup_pct", "reason"].map((k) => (
              <Field key={k} id={`line-${k}`} testid={`line-${k}-input`} label={label(k)} value={String(line[k])} inputMode={["quantity", "unit_cost", "markup_pct"].includes(k) ? "decimal" : undefined} onChange={(x) => setLine({ ...line, [k]: x })} />
            ))}
          </div>
          {line.category === "mobilization" ? <Field id="line-dup" testid="line-duplicate-reason-input" label="Reason to keep duplicate mobilization" value={line.duplicate_reason} onChange={(x) => setLine({ ...line, duplicate_reason: x })} /> : null}
          <Check id="line-taxable" testid="line-taxable-toggle" checked={line.taxable} onChange={(x) => setLine({ ...line, taxable: x })}>Taxable</Check>
          {line.category === "general_repair" ? <Check id="line-matdep" testid="line-material-toggle" checked={line.material_dependent} onChange={(x) => setLine({ ...line, material_dependent: x })}>Material-dependent</Check> : null}
          {error}
          <Btn testid="line-save-button" icon={Save} onClick={onSave}>Add line</Btn>
        </>
      ) : null}
    </Modal>
  );
}

export function EditLineModal({ edit, setEdit, onSave, error }) {
  return (
    <Modal open={!!edit} onClose={() => setEdit(null)} title="Edit line" testid="line-edit-sheet">
      {edit ? (
        <>
          {["quantity", "unit_cost", "markup_pct", "duplicate_reason"].map((k) => <Field key={k} id={`edit-${k}`} testid={`edit-${k}-input`} label={label(k)} value={String(edit[k] ?? "")} onChange={(x) => setEdit({ ...edit, [k]: x })} />)}
          {error}
          <Btn testid="edit-save-button" icon={Save} onClick={onSave}>Save</Btn>
        </>
      ) : null}
    </Modal>
  );
}

export function ScopeModal({ scope, setScope, onSave, error }) {
  return (
    <Modal open={!!scope} onClose={() => setScope(null)} title={scope?.new ? "Confirm tie scope" : "Correct scope facts"} testid="scope-form-sheet" wide>
      {scope ? (
        <>
          <fieldset><legend className="mb-2 text-sm font-bold">Tie type</legend>
            <Choice name="scope-type" testid="scope-type" options={["crosstie", "switch_tie"]} value={scope.tie_type} onChange={(x) => setScope({ ...scope, tie_type: x })} render={(x) => (x === "crosstie" ? "Crosstie" : "Switch tie")} />
          </fieldset>
          <div className="grid gap-3 sm:grid-cols-2">
            {["location", "inspected_quantity", "repair_quantity", "unit", "specification", "access_disposition"].map((k) => (
              <Field key={k} id={`scope-${k}`} testid={`scope-${k}-input`} label={label(k)} value={String(scope[k] ?? "")} onChange={(x) => setScope({ ...scope, [k]: x })} inputMode={k.endsWith("quantity") ? "numeric" : undefined} />
            ))}
          </div>
          <fieldset><legend className="mb-2 text-sm font-bold">Material supply</legend>
            <Choice name="scope-supply" testid="scope-supply" options={["Contractor", "Customer", "Unresolved"]} value={scope.material_responsibility} onChange={(x) => setScope({ ...scope, material_responsibility: x })} />
          </fieldset>
          {error}
          <Btn testid="scope-save-button" icon={Save} onClick={onSave}>Save scope</Btn>
        </>
      ) : null}
    </Modal>
  );
}

export function TermsModal({ terms, setTerms, onSave, error }) {
  return (
    <Modal open={!!terms} onClose={() => setTerms(null)} title="Terms & expiry" description="Payment, schedule and expiry terms shown to the customer." testid="terms-form-sheet" wide>
      {terms ? (
        <>
          {["contractor_identity", "payment_terms", "schedule_wording", "assumptions", "exclusions", "validity", "acceptance_wording"].map((k) => (
            <Field key={k} id={`terms-${k}`} multiline testid={`terms-${k}-input`} label={label(k)} value={terms[k] || ""} onChange={(x) => setTerms({ ...terms, [k]: x })} />
          ))}
          <Field id="terms-expiry" testid="terms-expiry-input" type="datetime-local" label="Expiry, site-local time" value={terms.expiry_local || ""} onChange={(x) => setTerms({ ...terms, expiry_local: x })} hint="Converted to UTC by the server using the site time zone." />
          {error}
          <Btn testid="terms-save-button" icon={Save} onClick={onSave}>Save</Btn>
        </>
      ) : null}
    </Modal>
  );
}

export function useModalState() {
  const [s, set] = useState(null);
  return [s, set];
}
