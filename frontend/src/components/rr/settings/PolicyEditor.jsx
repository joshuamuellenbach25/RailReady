import { useState } from "react";
import { Plus, Save, Trash2, X } from "lucide-react";
import { api } from "@/lib/api";
import { SCOPES } from "@/lib/settings";
import { Btn, Card, Field, H2, Modal, Select } from "../ui";

let seq = 0;
const k = () => `p${++seq}`;
const evLabel = (e) => `${e.kind}${e.filename ? ` - ${e.filename}` : e.text ? ` - "${e.text.slice(0, 40)}..."` : ""}`;

function Restriction({ r, i, targets, set, remove }) {
  return (
    <li data-testid={`edit-restriction-${i}`} className="grid gap-3 rounded-md border border-[#D9DEE2] p-3 md:grid-cols-[160px_1fr_1fr_auto] md:items-end">
      <Select id={`rs-scope-${i}`} testid={`edit-restriction-scope-${i}`} label="Applies to" value={r.scope} options={SCOPES} onChange={(v) => set({ scope: v, id: "" })} />
      <Select id={`rs-id-${i}`} testid={`edit-restriction-target-${i}`} label="Which one" value={r.id} placeholder="Choose..." options={targets(r.scope)} onChange={(v) => set({ id: v })} />
      <Field id={`rs-reason-${i}`} testid={`edit-restriction-reason-${i}`} label="Reason" value={r.reason || ""} onChange={(v) => set({ reason: v })} />
      <Btn small kind="danger" icon={Trash2} testid={`edit-restriction-remove-${i}`} onClick={remove}>Remove</Btn>
    </li>
  );
}

function Exception({ e, i, targets, set, remove }) {
  const [items, setItems] = useState(null);
  const pickVisit = async (vid) => {
    set({ visit_id: vid, evidence_id: "" });
    setItems(vid ? await api(`/visits/${vid}/evidence`).catch(() => []) : null);
  };
  const fixed = e.evidence_id && !e.visit_id;
  return (
    <li data-testid={`edit-exception-${i}`} className="grid gap-3 rounded-md border border-[#D9DEE2] p-3 md:grid-cols-2 xl:grid-cols-[1fr_1fr_170px_1fr_auto] xl:items-end">
      {fixed ? <p className="text-sm md:col-span-2">A photo or note chosen earlier</p> : (
        <>
          <Select id={`ex-visit-${i}`} testid={`edit-exception-visit-${i}`} label="Inspection" value={e.visit_id || ""} placeholder="Choose..." options={targets("visit")} onChange={pickVisit} />
          <Select id={`ex-ev-${i}`} testid={`edit-exception-evidence-${i}`} label="Photo or note" value={e.evidence_id} placeholder={items ? (items.length ? "Choose..." : "No evidence on this inspection") : "Choose an inspection first"}
            options={(items || []).map((x) => [x.uuid, evLabel(x)])} onChange={(v) => set({ evidence_id: v })} disabled={!items?.length} />
        </>
      )}
      <Select id={`ex-allow-${i}`} testid={`edit-exception-allow-${i}`} label="Photo analysis" value={e.allow ? "allow" : "block"} options={[["allow", "On"], ["block", "Off"]]} onChange={(v) => set({ allow: v === "allow" })} />
      <Field id={`ex-reason-${i}`} testid={`edit-exception-reason-${i}`} label="Reason" value={e.reason || ""} onChange={(v) => set({ reason: v })} />
      <Btn small kind="danger" icon={Trash2} testid={`edit-exception-remove-${i}`} onClick={remove}>Remove</Btn>
    </li>
  );
}

/** Admin-only editor. Saves a NEW policy version (PUT with expected_version); the server validates ids and arbitrates conflicts. */
export default function PolicyEditor({ policy, targets, onSave, onCancel, busy }) {
  const [f, setF] = useState(() => ({
    default: policy.default, note: "",
    restrictions: policy.restrictions.map((r) => ({ ...r, _k: k() })),
    evidence_exceptions: policy.evidence_exceptions.map((e) => ({ ...e, _k: k() })),
  }));
  const [confirm, setConfirm] = useState(false);
  const list = (name) => ({
    set: (i, p) => setF({ ...f, [name]: f[name].map((x, j) => (j === i ? { ...x, ...p } : x)) }),
    remove: (i) => setF({ ...f, [name]: f[name].filter((_, j) => j !== i) }),
  });
  const R = list("restrictions");
  const E = list("evidence_exceptions");
  const body = {
    expected_version: policy.version, default: f.default, note: f.note.trim() || null,
    restrictions: f.restrictions.map(({ scope, id, reason }) => ({ scope, id, reason: reason?.trim() || null })),
    evidence_exceptions: f.evidence_exceptions.map(({ evidence_id, allow, reason }) => ({ evidence_id, allow, reason: reason?.trim() || null })),
  };
  return (
    <Card testid="policy-editor" className="space-y-5">
      <H2>Change photo analysis</H2>
      <fieldset className="space-y-2">
        <legend className="text-sm font-medium">For all sites</legend>
        {[["allow", "On, except where turned off below"], ["restrict", "Off, except photos or notes turned on below"]].map(([v, l]) => (
          <label key={v} className={`flex min-h-[44px] cursor-pointer items-center gap-3 rounded-md border px-3 text-sm ${f.default === v ? "border-[#202428]" : "border-[#D9DEE2]"}`}>
            <input type="radio" name="pol-default" data-testid={`policy-default-${v}`} checked={f.default === v} onChange={() => setF({ ...f, default: v })} className="rr-focus h-4 w-4 accent-[#B32624]" />{l}
          </label>
        ))}
      </fieldset>
      <section className="space-y-2">
        <h3 className="text-sm font-medium">Turn off for these sites, customers or inspections</h3>
        <ul className="space-y-2">{f.restrictions.map((r, i) => <Restriction key={r._k} r={r} i={i} targets={targets} set={(p) => R.set(i, p)} remove={() => R.remove(i)} />)}</ul>
        <Btn small kind="secondary" icon={Plus} testid="policy-add-restriction" onClick={() => setF({ ...f, restrictions: [...f.restrictions, { scope: "site", id: "", reason: "", _k: k() }] })}>Turn off somewhere</Btn>
      </section>
      <section className="space-y-2">
        <h3 className="text-sm font-medium">Set single photos or notes by hand</h3>
        <ul className="space-y-2">{f.evidence_exceptions.map((e, i) => <Exception key={e._k} e={e} i={i} targets={targets} set={(p) => E.set(i, p)} remove={() => E.remove(i)} />)}</ul>
        <Btn small kind="secondary" icon={Plus} testid="policy-add-exception" onClick={() => setF({ ...f, evidence_exceptions: [...f.evidence_exceptions, { visit_id: "", evidence_id: "", allow: true, reason: "", _k: k() }] })}>Set a single photo or note</Btn>
      </section>
      <Field id="pol-note" testid="policy-note-input" label="Change note" multiline value={f.note} onChange={(v) => setF({ ...f, note: v })} placeholder="What changed and why" />
      <div className="flex flex-wrap gap-2">
        <Btn icon={Save} testid="policy-save-button" loading={busy} onClick={() => setConfirm(true)}>Save</Btn>
        <Btn kind="secondary" icon={X} testid="policy-cancel-button" onClick={onCancel}>Cancel</Btn>
      </div>
      <Modal open={confirm} onClose={() => setConfirm(false)} testid="policy-confirm-dialog" title="Save this setting?"
        description="It applies straight away to photos and notes waiting to be looked at.">
        <div className="flex flex-wrap gap-2">
          <Btn testid="policy-confirm-button" loading={busy} onClick={async () => { setConfirm(false); await onSave(body); }}>Save</Btn>
          <Btn kind="secondary" testid="policy-confirm-cancel" onClick={() => setConfirm(false)}>Keep editing</Btn>
        </div>
      </Modal>
    </Card>
  );
}
