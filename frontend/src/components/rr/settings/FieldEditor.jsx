import { ArrowDown, ArrowUp, Plus, Trash2 } from "lucide-react";
import { APPLIES, NON_ANSWERS, ROLES, STAGES, TYPES } from "@/lib/settings";
import { Btn, Checkbox, Field, Select } from "../ui";

let seq = 0;
export const toRow = (f) => ({ ...f, _k: `r${++seq}`, optionsText: (f.options || []).join(", ") });
export const blankRow = () => toRow({ key: "", label: "", type: "text", unit: null, applies_to: "inspection", stage: "capture", required: false, options: null, conditional_on: null, allowed_non_answers: ["unknown", "defer"], confirming_role: "foreman", help: null });
export const fromRow = ({ _k, optionsText, ...f }) => ({
  ...f,
  key: f.key.trim(),
  label: f.label.trim(),
  unit: f.unit?.trim() || null,
  help: f.help?.trim() || null,
  options: f.type === "choice" ? optionsText.split(",").map((s) => s.trim()).filter(Boolean) : null,
});

function Row({ f, i, n, set, move, remove }) {
  const p = `tf-${i}`;
  const toggle = (k, on) => set({ allowed_non_answers: on ? [...f.allowed_non_answers, k] : f.allowed_non_answers.filter((x) => x !== k) });
  return (
    <li data-testid={`field-row-${i}`} className="space-y-3 rounded-lg border border-[#D9DEE2] bg-white p-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-semibold">Field {i + 1}</span>
        <div className="ml-auto flex gap-1">
          <Btn small kind="ghost" icon={ArrowUp} testid={`field-up-${i}`} disabled={i === 0} onClick={() => move(-1)} aria-label={`Move field ${i + 1} up`}>Up</Btn>
          <Btn small kind="ghost" icon={ArrowDown} testid={`field-down-${i}`} disabled={i === n - 1} onClick={() => move(1)} aria-label={`Move field ${i + 1} down`}>Down</Btn>
          <Btn small kind="danger" icon={Trash2} testid={`field-remove-${i}`} disabled={n === 1} onClick={remove}>Remove</Btn>
        </div>
      </div>
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <Field id={`${p}-key`} testid={`field-key-${i}`} label="Short name" value={f.key} onChange={(v) => set({ key: v })} hint="Lowercase letters and digits, no spaces" />
        <Field id={`${p}-label`} testid={`field-label-${i}`} label="Label" value={f.label} onChange={(v) => set({ label: v })} />
        <Select id={`${p}-type`} testid={`field-type-${i}`} label="Type" value={f.type} options={TYPES} onChange={(v) => set({ type: v })} />
        <Field id={`${p}-unit`} testid={`field-unit-${i}`} label="Unit" value={f.unit || ""} onChange={(v) => set({ unit: v })} placeholder="e.g. each, sq ft" />
        <Select id={`${p}-applies`} testid={`field-applies-${i}`} label="Applies to" value={f.applies_to} options={APPLIES} onChange={(v) => set({ applies_to: v })} />
        <Select id={`${p}-stage`} testid={`field-stage-${i}`} label="Stage" value={f.stage} options={STAGES} onChange={(v) => set({ stage: v })} />
        <Select id={`${p}-role`} testid={`field-role-${i}`} label="Confirmed by" value={f.confirming_role} options={ROLES} onChange={(v) => set({ confirming_role: v })} />
        <div className="flex items-end"><Checkbox id={`${p}-req`} testid={`field-required-${i}`} label="Required" checked={f.required} onChange={(v) => set({ required: v })} /></div>
      </div>
      {f.type === "choice" ? <Field id={`${p}-opts`} testid={`field-options-${i}`} label="Options (comma separated)" value={f.optionsText} onChange={(v) => set({ optionsText: v })} /> : null}
      <fieldset className="flex flex-wrap items-center gap-x-5">
        <legend className="mb-1 text-sm font-medium">Allowed non-answers</legend>
        {NON_ANSWERS.map(([k, l]) => <Checkbox key={k} id={`${p}-na-${k}`} testid={`field-na-${k}-${i}`} label={l} checked={f.allowed_non_answers.includes(k)} onChange={(on) => toggle(k, on)} />)}
      </fieldset>
      <Field id={`${p}-help`} testid={`field-help-${i}`} label="Help text" value={f.help || ""} onChange={(v) => set({ help: v })} />
      {f.conditional_on ? <p className="text-[13px] text-[#59636B]">Kept from the earlier edition: only asked when {Object.entries(f.conditional_on).map(([k, v]) => `${k} = ${Array.isArray(v) ? v.join(" / ") : v}`).join(", ")}</p> : null}
    </li>
  );
}

/** Editable field rows for "save as new version". */
export default function FieldEditor({ rows, onChange }) {
  const upd = (i, patch) => onChange(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const move = (i, d) => { const a = [...rows]; [a[i], a[i + d]] = [a[i + d], a[i]]; onChange(a); };
  return (
    <div className="space-y-3">
      <ol className="space-y-3">
        {rows.map((f, i) => <Row key={f._k} f={f} i={i} n={rows.length} set={(p) => upd(i, p)} move={(d) => move(i, d)} remove={() => onChange(rows.filter((_, j) => j !== i))} />)}
      </ol>
      <Btn kind="secondary" icon={Plus} testid="field-add-button" onClick={() => onChange([...rows, blankRow()])}>Add field</Btn>
    </div>
  );
}
