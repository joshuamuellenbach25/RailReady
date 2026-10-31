import { useState } from "react";
import { BadgeCheck, Sigma } from "lucide-react";
import { api, errText } from "@/lib/api";
import { DOMAIN_LABEL, dec, num } from "@/lib/calibration";
import { Badge, Banner, Blocker, Btn, Card, H2, Modal, Mono, Select, fmt } from "../ui";
import { Semantics, SfUnknown } from "./Metrics";

function ClassTable({ classes, testid }) {
  return (
    <div className="overflow-x-auto rounded-md border border-[#D9DEE2]">
      <table data-testid={testid} className="w-full min-w-[620px] bg-white text-sm">
        <thead className="bg-[#F3F4F4] text-left text-[13px] text-[#3C444B]"><tr>{["Class", "a", "b", "n (Bad / Good)", "Calibrated probability"].map((h) => <th key={h} scope="col" className="px-2 py-1.5 font-medium">{h}</th>)}</tr></thead>
        <tbody>
          {Object.entries(classes || {}).map(([k, c]) => (
            <tr key={k} data-testid={`${testid}-${k}`} className="border-t border-[#D9DEE2]">
              <th scope="row" className="px-2 py-1.5 text-left font-medium">{k}</th>
              <td className="px-2 py-1.5 font-mono">{c.a == null ? "null" : dec(c.a, 4)}</td>
              <td className="px-2 py-1.5 font-mono">{c.b == null ? "null" : dec(c.b, 4)}</td>
              <td className="px-2 py-1.5 font-mono">{c.n == null ? "-" : `${num(c.n)} (${num(c.n_bad)} / ${num(c.n_good)})`}</td>
              <td className="px-2 py-1.5">{c.a == null ? <span className="text-[13px] text-[#59636B]">null - {c.reason}</span> : <span className="text-[13px]">Platt-fitted on calibration partition{c.calibration_partition_brier_in_sample != null ? ` (in-sample Brier ${dec(c.calibration_partition_brier_in_sample, 4)})` : ""}</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Profile({ p, onActivate }) {
  const [confirm, setConfirm] = useState(false);
  return (
    <li data-testid={`cal-profile-${p.version}`} className="space-y-2 rounded-md border border-[#D9DEE2] p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">Profile v{p.version}</span><Badge testid={`cal-profile-status-${p.version}`} label={p.status} />
        <span className="text-[13px] text-[#59636B]">{p.method} - {num(p.calibration_records)} calibration records - {fmt(p.created_at)}</span>
        {p.status !== "Active" ? <Btn small kind="secondary" icon={BadgeCheck} className="ml-auto" testid={`cal-profile-activate-${p.version}`} onClick={() => setConfirm(true)}>Activate</Btn> : null}
      </div>
      <Semantics semantics={p.score_semantics} />
      <p className="text-[13px] text-[#59636B]">Task: {p.task} - Domain: {p.domain?.dataset}, {p.domain?.region}, {p.domain?.image_size}, {p.domain?.input}</p>
      <ClassTable classes={p.classes} testid={`cal-profile-classes-${p.version}`} />
      <p data-testid={`cal-profile-ccp-${p.version}`} className="text-sm">candidate_correctness_probability: <span className="font-mono">null</span> - {p.candidate_correctness_probability?.reason}</p>
      {p.activated_at ? <p className="text-[13px] text-[#59636B]">Activated {fmt(p.activated_at)} by {p.activated_by_role || "staff"} - {p.applies_to}</p> : null}
      <Mono label="Profile details">{p.uuid} - model run {p.binding?.model_run_id} - checkpoint sha256 {p.binding?.checkpoint_sha256} - membership sha256 {p.membership_sha256}</Mono>
      <Modal open={confirm} onClose={() => setConfirm(false)} testid="cal-activate-confirm" title={`Activate profile v${p.version}?`}
        description={`Applies only to new runs within its declared task, classes and domain (${DOMAIN_LABEL}). Any current Active profile becomes Superseded; historical runs keep their recorded versions.`}>
        <div className="flex gap-2"><Btn testid="cal-activate-confirm-button" onClick={async () => { setConfirm(false); await onActivate(p); }}>Activate</Btn><Btn kind="secondary" testid="cal-activate-cancel" onClick={() => setConfirm(false)}>Cancel</Btn></div>
      </Modal>
    </li>
  );
}

export default function ProfilesSection({ data, runs, onChanged }) {
  const trained = runs.filter((r) => r.kind === "training" && r.status === "Done");
  const [tr, setTr] = useState("");
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);
  const run = async (fn, ok) => {
    setBusy(true);
    setMsg(null);
    try { const x = await fn(); setMsg({ tone: "success", text: ok(x) }); onChanged(); } catch (e) { setMsg({ tone: "error", text: errText(e) }); } finally { setBusy(false); }
  };
  const sel = tr || trained[0]?.uuid || "";
  const profiles = data?.profiles || [];
  return (
    <Card testid="cal-profiles" className="space-y-3">
      <H2>Calibration profiles</H2>
      <Banner tone="warning" testid="cal-profiles-label" text={data?.label || DOMAIN_LABEL} />
      <SfUnknown sf={data?.sf_validation} testid="cal-profiles-sf" />
      <div className="flex flex-wrap items-end gap-3">
        <Select id="cal-prof-run" testid="cal-profile-run" label="Completed training run" value={sel} onChange={setTr} placeholder={trained.length ? undefined : "No completed training run"} options={trained.map((r) => [r.uuid, `${fmt(r.created_at)} - ${r.config?.model}`])} />
        <Btn icon={Sigma} testid="cal-profile-fit" loading={busy} disabled={!sel} onClick={() => run(() => api("/calibration/profiles", { body: { training_run_id: sel } }), (x) => `Profile v${x.version} fitted (Draft).`)}>Fit profile</Btn>
      </div>
      {!sel ? <Blocker testid="cal-profile-blocker" text="Fitting needs a completed local training run." /> : null}
      {msg ? <Banner tone={msg.tone} text={msg.text} testid="cal-profile-message" /> : null}
      {profiles.length ? <ul className="space-y-3">{profiles.map((p) => <Profile key={p.uuid} p={p} onActivate={(x) => run(() => api(`/calibration/profiles/${x.uuid}/activate`, { method: "POST" }), () => `Profile v${x.version} is Active.`)} />)}</ul>
        : <p data-testid="cal-profiles-empty" className="text-sm text-[#59636B]">No profiles yet.</p>}
    </Card>
  );
}
