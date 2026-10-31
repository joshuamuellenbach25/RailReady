import { useState } from "react";
import { Play, X } from "lucide-react";
import { api, errText } from "@/lib/api";
import { ACTIVE, BUDGET_MSG, num, usePoll } from "@/lib/calibration";
import { Badge, Banner, Blocker, Btn, Card, H2, Modal, Mono, Select, fmt } from "../ui";
import { BaselineView, EvaluationView, useRun } from "./RunViews";

function Budget({ b }) {
  if (!b) return null;
  return (
    <div data-testid="cal-budget" className="flex flex-wrap items-center gap-2 text-sm">
      <Badge label={`Image-call budget: ${num(b.used)} of ${num(b.cap)} used - ${num(b.remaining)} left`} tone={b.remaining > 0 ? "neutral" : "error"} />
      {b.remaining <= 0 ? <Blocker testid="cal-budget-blocker" text={b.message || BUDGET_MSG} /> : null}
      {b.seeded_from ? <span className="text-[12px] text-[#59636B]">Seeded from {b.seeded_from}</span> : null}
    </div>
  );
}

function StartRun({ partitions, profiles, budget, onStarted }) {
  const done = partitions.filter((p) => p.status === "Complete");
  const [f, setF] = useState({ kind: "training", model: "local_crop_logreg", partition_id: "", profile_id: "", max_images: 12 });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [confirm, setConfirm] = useState(false);
  const pid = f.partition_id || done[0]?.uuid || "";
  const prof = f.profile_id || profiles[0]?.uuid || "";
  const maxCalls = Math.min(48, budget?.remaining ?? 0);
  const block = f.kind === "evaluation" ? (!prof ? "Needs a fitted calibration profile." : null)
    : !pid ? "Needs a Complete partition." : f.kind === "baseline" && maxCalls <= 0 ? (budget?.message || BUDGET_MSG) : null;
  async function go() {
    setConfirm(false);
    setBusy(true);
    setErr(null);
    try {
      const body = f.kind === "evaluation" ? { kind: "evaluation", profile_id: prof }
        : { kind: f.kind, partition_id: pid, model: f.kind === "baseline" ? "hosted_vision" : f.model, ...(f.kind === "baseline" ? { max_images: Math.min(Number(f.max_images), maxCalls) } : {}) };
      const x = await api("/calibration/runs", { body });
      onStarted(x.run);
    } catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  }
  return (
    <div data-testid="cal-start-run" className="space-y-3 rounded-md border border-[#D9DEE2] p-3">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Select id="run-kind" testid="cal-run-kind" label="Run" value={f.kind} onChange={(v) => setF({ ...f, kind: v })} options={[["training", "Training (local model)"], ["baseline", "Baseline (hosted model, uses budget)"], ["evaluation", "Evaluation on locked val"]]} />
        {f.kind !== "evaluation" ? <Select id="run-part" testid="cal-run-partition" label="Partition" value={pid} onChange={(v) => setF({ ...f, partition_id: v })} placeholder={done.length ? undefined : "No Complete partition"} options={done.map((p) => [p.uuid, `Partition v${p.version}`])} /> : (
          <Select id="run-prof" testid="cal-run-profile" label="Calibration profile" value={prof} onChange={(v) => setF({ ...f, profile_id: v })} placeholder={profiles.length ? undefined : "No profile"} options={profiles.map((p) => [p.uuid, `Profile v${p.version} - ${p.status}`])} />
        )}
        {f.kind === "training" ? <Select id="run-model" testid="cal-run-model" label="Model" value={f.model} onChange={(v) => setF({ ...f, model: v })} options={[["local_crop_logreg", "Local crop classifier (logistic regression)"], ["hosted_vision", "Hosted vision model"]]} /> : null}
        {f.kind === "baseline" ? <Select id="run-max" testid="cal-run-max" label={`Images (max ${maxCalls})`} value={String(f.max_images)} onChange={(v) => setF({ ...f, max_images: v })} options={[6, 12, 24, 48].filter((n) => n <= Math.max(1, maxCalls)).map((n) => [String(n), `${n} images`])} /> : null}
      </div>
      {f.kind === "training" && f.model === "hosted_vision" ? <Blocker testid="cal-hosted-training-blocker" text="Unsupported. The hosted model offers no weight training, and prompting is not training. The run is recorded as Unsupported." /> : null}
      {block ? <Blocker testid="cal-run-blocker" text={block} /> : null}
      {err ? <Banner tone="error" testid="cal-run-error" text={err} /> : null}
      <Btn icon={Play} testid="cal-run-start" loading={busy} disabled={!!block} onClick={() => (f.kind === "baseline" ? setConfirm(true) : go())}>Start run</Btn>
      <Modal open={confirm} onClose={() => setConfirm(false)} testid="cal-baseline-confirm" title="Start hosted baseline?"
        description={`Uses up to ${Math.min(Number(f.max_images), maxCalls)} of the ${num(budget?.remaining)} remaining image calls. Train images only; labels are withheld from the model.`}>
        <div className="flex gap-2"><Btn testid="cal-baseline-confirm-button" onClick={go}>Start baseline</Btn><Btn kind="secondary" testid="cal-baseline-cancel" onClick={() => setConfirm(false)}>Cancel</Btn></div>
      </Modal>
    </div>
  );
}

function RunDetail({ id, onClose }) {
  const [r, err, load] = useRun(id);
  usePoll(load, !!r && ACTIVE.includes(r.status));
  if (err) return <Banner tone="error" text={err} />;
  if (!r) return null;
  const t = r.training_summary;
  return (
    <div data-testid="cal-run-detail" className="space-y-4 rounded-md border border-[#202428] p-4">
      <div className="flex flex-wrap items-center gap-2">
        <H2>{r.kind} run</H2><Badge testid="cal-run-detail-status" label={r.status} />
        <span className="text-[13px] text-[#59636B]">{r.config?.model} - {fmt(r.created_at)}</span>
        <Btn small kind="ghost" icon={X} testid="cal-run-detail-close" className="ml-auto" onClick={onClose}>Close</Btn>
      </div>
      {r.blocker ? <Banner tone="warning" testid="cal-run-detail-blocker" text={r.blocker} /> : null}
      {r.checkpoint ? <p data-testid="cal-checkpoint" className="text-sm">Checkpoint saved ({num(r.checkpoint.bytes)} bytes, {r.checkpoint.format}) <Mono label="Checkpoint details">sha256 {r.checkpoint.sha256}</Mono></p> : null}
      {t ? <p data-testid="cal-training-summary" className="text-sm">Fit crops {num(t.fit_crops)} (Bad {num(t.fit_bad)}, abstained {num(t.fit_abstained)}) - calibration crops scored {num(t.calibration_crops_scored)} (abstained {num(t.calibration_abstained)}). <span className="text-[#59636B]">Training-set fit only. Not a test result.</span></p> : null}
      {r.baseline ? <BaselineView b={r.baseline} items={r.items} /> : null}
      {r.evaluation ? <EvaluationView ev={r.evaluation} /> : null}
      <details data-testid="cal-run-logs" className="text-sm">
        <summary className="rr-focus inline-flex min-h-[32px] cursor-pointer items-center rounded font-medium">Logs ({r.logs?.length || 0})</summary>
        <ol className="mt-1 max-h-56 overflow-auto font-mono text-xs text-[#59636B]">{(r.logs || []).map((l, i) => <li key={i}>{fmt(l.at)} - {l.msg}</li>)}</ol>
      </details>
      <Mono label="Run details">{r.uuid} - partition {r.partition_id || "-"} - config sha256 {r.config_sha256 || "-"}</Mono>
    </div>
  );
}

export default function RunsSection({ runs, budget, partitions, profiles, onChanged }) {
  const [open, setOpen] = useState(null);
  return (
    <Card testid="cal-runs" className="space-y-3">
      <H2>Runs</H2>
      <Budget b={budget} />
      <StartRun partitions={partitions} profiles={profiles} budget={budget} onStarted={(run) => { onChanged(); setOpen(run.uuid); }} />
      {open ? <RunDetail id={open} onClose={() => setOpen(null)} /> : null}
      {runs.length ? (
        <div className="overflow-x-auto rounded-md border border-[#D9DEE2]">
          <table data-testid="cal-runs-table" className="w-full min-w-[640px] bg-white text-sm">
            <thead className="bg-[#F3F4F4] text-left text-[13px] text-[#3C444B]"><tr>{["Run", "Model", "Status", "Started", ""].map((h) => <th key={h} scope="col" className="px-2 py-1.5 font-medium">{h}</th>)}</tr></thead>
            <tbody>
              {runs.map((x) => (
                <tr key={x.uuid} className="border-t border-[#D9DEE2]">
                  <td className="px-2 py-2 font-medium">{x.kind}</td><td className="px-2 py-2">{x.config?.model || "-"}</td>
                  <td className="px-2 py-2"><Badge label={x.status} /></td><td className="px-2 py-2">{fmt(x.created_at)}</td>
                  <td className="px-2 py-2"><Btn small kind="secondary" testid={`cal-run-open-${x.uuid}`} onClick={() => setOpen(x.uuid)}>Open</Btn></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <p data-testid="cal-runs-empty" className="text-sm text-[#59636B]">No runs yet.</p>}
    </Card>
  );
}
