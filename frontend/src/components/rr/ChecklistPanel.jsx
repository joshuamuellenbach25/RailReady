import { useCallback, useEffect, useState } from "react";
import { ChevronRight, ClipboardList, Repeat } from "lucide-react";
import { ApiError, api, errText } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { ROLES, STAGES, optLabel, pinBasisLabel } from "@/lib/settings";
import { Badge, Banner, Blocker, Btn, Card, H2, Modal, Select, fmt } from "./ui";

const STATUS_LABEL = { confirmed: "Answered", deferred: "Deferred / unknown", missing: "Missing" };

function ChangeTemplate({ open, onClose, visitId, revision, pin, onDone, onStale }) {
  const [list, setList] = useState([]);
  const [tid, setTid] = useState(pin.template_id);
  const [versions, setVersions] = useState([]);
  const [ver, setVer] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  useEffect(() => { if (open) api("/templates").then((r) => setList(r.templates || [])).catch((e) => setErr(errText(e))); }, [open]);
  useEffect(() => { if (open && tid) api(`/templates/${tid}`).then((r) => setVersions(r.versions || [])).catch(() => setVersions([])); }, [open, tid]);
  const t = list.find((x) => x.template_id === tid);
  const target = ver ? Number(ver) : t?.version;
  const same = tid === pin.template_id && target === pin.version;
  async function confirm() {
    setBusy(true);
    setErr(null);
    try {
      await api(`/visits/${visitId}/template`, { method: "PUT", body: { template_id: tid, version: ver ? Number(ver) : null, expected_revision: revision } });
      onDone(`Now using the ${t?.name} checklist.`);
    } catch (e) {
      setErr(errText(e));
      if (e instanceof ApiError && e.status === 409) onStale(); // reload inspection + checklist; dialog keeps the choice
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal open={open} onClose={onClose} testid="change-template-dialog" title="Use a different checklist" description="Pick the checklist the foreman and office should follow for this inspection.">
      <Select id="ct-template" testid="change-template-select" label="Checklist" value={tid} options={list.map((x) => [x.template_id, x.name])} onChange={(v) => { setTid(v); setVer(""); }} />
      <Select id="ct-version" testid="change-template-version" label="Edition" value={ver} options={[["", "Latest"], ...versions.filter((n) => n !== t?.version).sort((a, b) => b - a).map((n) => [String(n), `Earlier edition ${n}`])]} onChange={setVer} />
      {t ? <p data-testid="change-template-summary" className="rounded-md border border-[#D9DEE2] bg-[#F3F4F4] p-3 text-sm">This inspection will use the <b className="font-medium">{t.name}</b> checklist. Answers already given are kept. </p> : null}
      {same ? <Blocker testid="change-template-same" text="This inspection already uses this checklist." /> : null}
      {err ? <Banner tone="error" testid="change-template-error" text={err} /> : null}
      <div className="flex flex-wrap gap-2">
        <Btn testid="change-template-confirm" icon={Repeat} loading={busy} disabled={!t || same} onClick={confirm}>Confirm change</Btn>
        <Btn kind="secondary" testid="change-template-cancel" onClick={onClose}>Cancel</Btn>
      </div>
    </Modal>
  );
}

/** Pinned checklist template + missing items for an inspection (REQ-215). */
export default function ChecklistPanel({ visitId, revision, refreshKey, onChanged }) {
  const { canConfigure } = useAuth();
  const [c, setC] = useState(null);
  const [err, setErr] = useState(null);
  const [open, setOpen] = useState(false);
  const [msg, setMsg] = useState(null);
  const load = useCallback(() => api(`/visits/${visitId}/checklist`).then((d) => { setC(d); setErr(null); }).catch((e) => setErr({ text: errText(e), server: e instanceof ApiError && e.status >= 500 })), [visitId]);
  useEffect(() => { load(); }, [load, refreshKey]);
  if (!c) return err ? (
    <Card testid="checklist-error" className="space-y-3">
      <Banner tone="error" text={err.server ? "The checklist didn't load. The rest of this inspection still works." : err.text} />
      <Btn small kind="secondary" icon={Repeat} testid="checklist-retry-button" onClick={load}>Try again</Btn>
    </Card>
  ) : null;
  if (c.state === "needs_repair") return (
    <Card testid="checklist-needs-repair" className="space-y-2">
      <Banner tone="warning" text={c.message || "Checklist version missing. Ask an admin to restore it."} />
      <p className="text-[14px] text-[#59636B]">Photos, videos and their results on this inspection are not affected.</p>
    </Card>
  );
  const missing = (c.fields || []).filter((f) => (c.missing || []).includes(f.key));
  return (
    <Card testid="review-checklist" className="space-y-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <H2>Checklist</H2>
          <p data-testid="checklist-template" className="mt-1 text-sm"><ClipboardList aria-hidden className="mr-1 inline h-4 w-4 align-[-3px]" /><b className="font-medium">{c.template.name}</b></p>
          <p data-testid="checklist-pin-basis" className="text-[13px] text-[#59636B]">{pinBasisLabel(c.pin.basis)} - {fmt(c.pin.at)}</p>
        </div>
        {canConfigure ? <Btn small kind="secondary" icon={Repeat} testid="checklist-change-template" onClick={() => { setMsg(null); setOpen(true); }}>Change template</Btn> : null}
      </div>
      {msg ? <Banner tone="success" testid="checklist-message" text={msg} /> : null}
      <div data-testid="checklist-missing">
        <p className="text-[15px] font-medium">Still needed ({missing.length})</p>
        {missing.length ? missing.map((f) => <Blocker key={f.key} testid={`checklist-missing-${f.key}`} text={`${f.label} - ${optLabel(ROLES, f.confirming_role).toLowerCase()} confirms at ${optLabel(STAGES, f.stage).toLowerCase()}`} />)
          : <p className="mt-1 text-sm text-[#59636B]">Nothing missing. Every must-have answer is in.</p>}
      </div>
      <details data-testid="checklist-all" className="group/all text-sm">
        <summary className="rr-focus inline-flex min-h-[32px] cursor-pointer list-none items-center gap-1 rounded font-medium text-[#3C444B] [&::-webkit-details-marker]:hidden"><ChevronRight aria-hidden className="h-3.5 w-3.5 transition-transform group-open/all:rotate-90" />All checklist items ({c.fields.length})</summary>
        <ul className="mt-2 space-y-1.5">
          {c.fields.map((f) => (
            <li key={f.key} className="flex flex-wrap items-center gap-2">
              <span className="min-w-0 flex-1">{f.label}{f.inherited_by_findings ? <span className="text-[#59636B]"> - findings inherit</span> : null}</span>
              <Badge label={STATUS_LABEL[f.status] || f.status} tone={f.status === "confirmed" ? "success" : f.status === "missing" && f.required ? "error" : "neutral"} />
            </li>
          ))}
        </ul>
      </details>
      {open ? <ChangeTemplate open={open} onClose={() => setOpen(false)} visitId={visitId} revision={revision} pin={c.pin} onStale={onChanged} onDone={(m) => { setOpen(false); setMsg(m); onChanged(); }} /> : null}
    </Card>
  );
}
