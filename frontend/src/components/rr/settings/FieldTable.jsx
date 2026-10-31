import { APPLIES, ROLES, STAGES, TYPES, nonAnswerLabel, optLabel } from "@/lib/settings";

const TH = "px-3 py-2 text-left font-medium";
const TD = "px-3 py-2.5 align-top";

/** Read-only field definition table (REQ-214). */
export default function FieldTable({ fields }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-[#D9DEE2]">
      <table data-testid="template-fields-table" className="w-full min-w-[980px] bg-white text-sm">
        <thead className="border-b border-[#D9DEE2] bg-[#F3F4F4] text-[13px] text-[#3C444B]">
          <tr>{["Field", "Type / unit", "Applies to", "Stage", "Required", "Options", "Allowed non-answers", "Confirmed by", "Help"].map((h) => <th key={h} scope="col" className={TH}>{h}</th>)}</tr>
        </thead>
        <tbody>
          {fields.map((f, i) => (
            <tr key={f.key} data-testid={`template-field-${f.key}`} className={i ? "border-t border-[#D9DEE2]" : ""}>
              <td className={TD}>
                <span className="block font-medium">{f.label}</span>
                
                {f.conditional_on ? <span className="mt-1 block text-xs text-[#59636B]">Asked when {Object.entries(f.conditional_on).map(([k, v]) => `"${(fields.find((x) => x.key === k) || {}).label || "another answer"}" is ${Array.isArray(v) ? v.join(" or ") : v}`).join(", ")}</span> : null}
              </td>
              <td className={TD}>{optLabel(TYPES, f.type)}{f.unit ? <span className="block text-xs text-[#59636B]">{f.unit}</span> : null}</td>
              <td className={TD}>{optLabel(APPLIES, f.applies_to)}</td>
              <td className={TD}>{optLabel(STAGES, f.stage)}</td>
              <td className={TD}>{f.required ? "Required" : "Optional"}</td>
              <td className={TD}>{f.options?.length ? f.options.join(", ") : "-"}</td>
              <td className={TD}>{f.allowed_non_answers?.length ? f.allowed_non_answers.map(nonAnswerLabel).join(", ") : "None"}</td>
              <td className={TD}>{optLabel(ROLES, f.confirming_role)}</td>
              <td className={`${TD} max-w-[240px] text-[#59636B]`}>{f.help || "-"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
