import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { Eye, AudioLines, Box, Calculator, FileText, Film, LockOpen, RefreshCw } from "lucide-react";
import { api, errText, mediaUrl } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Blocker, Badge, Banner, Btn, Card, Empty, H2, Loading, Mono, Msg, PageHead, fmt } from "@/components/rr/ui";
import { catLabel } from "@/components/rr/CandidateCard";
import ChecklistPanel from "@/components/rr/ChecklistPanel";
import PolicyStatus from "@/components/rr/PolicyStatus";
import EvidenceDetail from "@/components/rr/EvidenceDetail";
import FieldsPanel from "@/components/rr/FieldsPanel";
import UploadPhoto from "@/components/rr/UploadPhoto";
import SubmitInspection, { DETAIL_LABEL } from "@/components/rr/SubmitInspection";

const TERMINAL = ["Done", "Failed"];
const OPEN_FIELD = ["Missing required", "Needs review"];

/** Required details still open, from the server's submission readiness list and the pinned checklist (deduplicated by key). */
function useRequired(visitId, tick) {
  const [r, setR] = useState(null);
  useEffect(() => {
    let live = true;
    Promise.all([api(`/visits/${visitId}/readiness`), api(`/visits/${visitId}/checklist`)])
      .then(([rd, cl]) => {
        if (!live) return;
        if (cl.state && cl.state !== "ok") return setR({ error: true }); // checklist cannot be resolved: never claim complete
        const m = new Map();
        (rd.fields || []).filter((f) => OPEN_FIELD.includes(f.state)).forEach((f) => m.set(f.field, DETAIL_LABEL[f.field] || f.label));
        (cl.fields || []).filter((f) => f.required && (f.status === "missing" || f.group === "needs_review")).forEach((f) => { if (!m.has(f.key)) m.set(f.key, f.label); });
        setR({ items: [...m].map(([key, label]) => ({ key, label })) });
      })
      .catch(() => { if (live) setR({ error: true }); });
    return () => { live = false; };
  }, [visitId, tick]);
  return r;
}

const KIND = { photo: "Photo", video: "Video", audio: "Voice note", note: "Note" };
const OBS = { finding: "Finding", note: "Note", hazard: "Hazard" };

function EvidencePicker({ list, sel, onSel, candByEv }) {
  return (
    <div role="tablist" aria-label="Evidence" className="flex gap-2 overflow-x-auto pb-1">
      {list.map((e, i) => {
        const on = sel === e.uuid;
        const pend = (candByEv[e.uuid] || []).filter((c) => c.review_state === "Pending").length;
        return (
          <button key={e.uuid} role="tab" aria-selected={on} data-testid={`review-evidence-${e.uuid}`} onClick={() => onSel(e.uuid)}
            className={`rr-focus relative flex h-24 w-28 shrink-0 flex-col items-center justify-center overflow-hidden rounded-md border text-xs font-bold transition-colors ${on ? "border-[#B32624] ring-2 ring-[#B32624]" : "border-[#D9DEE2] hover:border-[#C5CCD2]"} bg-white`}>
            {e.kind === "photo" && e.upload_state === "Verified" ? (
              <img src={mediaUrl(e.uuid)} alt="" className="absolute inset-0 h-full w-full object-cover" />
            ) : (
              <>{e.kind === "audio" ? <AudioLines aria-hidden className="h-6 w-6" /> : e.kind === "video" ? <Film aria-hidden className="h-6 w-6" /> : <FileText aria-hidden className="h-6 w-6" />}</>
            )}
            <span className="absolute bottom-0 left-0 right-0 bg-[#22272B]/85 px-1 py-0.5 text-left text-[11px] text-white">
              {KIND[e.kind] || "Item"} {i + 1}{pend ? ` - ${pend} to answer` : ""}
            </span>
          </button>
        );
      })}
    </div>
  );
}

function NextAction({ d, required, staffSubmitted, isForeman, canSubmit, onEstimate, onPick, onSubmitted }) {
  const v = d.visit;
  const pending = d.candidates.filter((c) => c.review_state === "Pending");
  const gaps = d.observations.filter((o) => o.kind === "not_inspected");
  const reason = v.status !== "Submitted" ? "Submit this inspection to start an estimate." : isForeman ? "The estimator opens the estimate for submitted inspections." : null;
  const req = required?.items || [];
  return (
    <Card testid="review-next-action" className="space-y-3">
      <H2>Next step</H2>
      {v.status === "Draft" && canSubmit ? <SubmitInspection visitId={v.uuid} onSubmitted={onSubmitted} /> : null}
      <div>
        <Btn testid="review-next-estimate-button" icon={Calculator} disabled={!staffSubmitted} onClick={onEstimate}>Open estimate</Btn>
        {reason ? <Blocker testid="review-next-estimate-blocker" text={reason} /> : null}
      </div>
      <div>
        <p className="text-[15px] font-medium">Open questions ({pending.length + gaps.length})</p>
        {required?.error ? <p data-testid="review-required-unknown" className="text-[15px] text-[#59636B]">Required details could not be checked. Refresh to try again.</p> : null}
        {req.length ? (
          <div data-testid="review-required-status">
            <p className="text-[15px] font-medium text-[#8F1D1B]">{req.length} required detail{req.length === 1 ? "" : "s"} still needed</p>
            {req.map((f) => <Blocker key={f.key} testid={`review-required-${f.key}`} text={f.label} />)}
          </div>
        ) : null}
        {required && !required.error && !req.length && !pending.length && !gaps.length ? <p data-testid="review-all-answered" className="text-[15px] text-[#59636B]">All answered.</p> : null}
        <ul className="mt-1 space-y-1">
          {pending.map((c, i) => (
            <li key={c.uuid}>
              <button type="button" data-testid={`review-unresolved-${c.uuid}`} onClick={() => onPick(c.evidence_id)} className="rr-focus inline-flex min-h-[36px] items-start gap-1.5 rounded text-left text-[15px] text-[#202428] hover:underline">
                <Eye aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[#7A4A00]" />{catLabel(c.category)} - does this look right?
              </button>
            </li>
          ))}
          {gaps.map((o) => <li key={o.uuid} className="flex items-start gap-1.5 text-[15px]"><Eye aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[#7A4A00]" />Not checked on site: {o.area} - {String(o.reason || "").replace(/\.+$/, "")}. Is that OK for the estimate?</li>)}
        </ul>
      </div>
    </Card>
  );
}

function SidePanels({ d, isAdmin }) {
  const notInspected = d.observations.filter((o) => o.kind === "not_inspected");
  return (
    <>
      <Card testid="review-coverage" className="space-y-2">
        <H2>Areas not checked</H2>
        {d.visit.coverage_note ? <p className="text-sm">Foreman's note: {d.visit.coverage_note}</p> : null}
        {notInspected.length ? notInspected.map((o) => <p key={o.uuid} className="text-sm"><b className="font-medium">{o.area}</b> - {o.reason}</p>) : <p className="text-sm text-[#59636B]">Everything planned was checked.</p>}
      </Card>
      <Card testid="review-prior-findings" className="space-y-2">
        <H2>Earlier open findings on this site</H2>
        {d.prior_findings.length ? d.prior_findings.map((f) => <p key={f.id} className="text-sm">- {f.text} ({f.recorded_at})</p>) : <p className="text-sm text-[#59636B]">None on this site.</p>}
      </Card>
      <Card testid="review-observations" className="space-y-1">
        <H2>Findings and notes ({d.observations.length})</H2>
        {!d.observations.length ? <p className="text-sm text-[#59636B]">Nothing recorded yet. Answers to the photo questions show up here.</p> : null}
        {d.observations.map((o) => (
          <p key={o.uuid} className="text-sm">
            - {o.kind === "not_inspected" ? `Not inspected: ${o.area} - ${o.reason}` : o.kind === "measurement" ? `${o.label}: ${o.value} ${o.unit || ""}` : `${OBS[o.kind] || "Note"}${o.category ? ` - ${catLabel(o.category).replace(/^Possible /, "")}` : ""}: ${o.text}`}
            {o.source_candidate_id ? <span className="text-[#59636B]"> ({/^v[cf]-/.test(o.source_candidate_id) ? "confirmed from a video" : "confirmed from a photo"})</span> : null}
          </p>
        ))}
      </Card>
      {isAdmin ? <details data-testid="review-audit" className="rounded-lg border border-[#D9DEE2] bg-white p-4">
        <summary className="rr-focus cursor-pointer text-lg font-semibold">Audit ({d.audit.length})</summary>
        <ul className="mt-2 space-y-0.5">{d.audit.slice(0, 40).map((a) => <li key={a.uuid} className="font-mono text-xs text-[#59636B]">{fmt(a.at)} - {a.actor_role} - {a.action}</li>)}</ul>
      </details> : null}
    </>
  );
}

export default function VisitReview() {
  const { id } = useParams();
  const nav = useNavigate();
  const { user, isForeman, isAdmin } = useAuth();
  const canSubmit = !!user && (user.role === "foreman" || (user.roles || []).includes("foreman")); // UI hint; server enforces the role
  const [sp, setSp] = useSearchParams();
  const [d, setD] = useState(null);
  const [msg, setMsg] = useState(null);
  const [tick, setTick] = useState(0);
  const load = useCallback(async () => {
    try {
      setD(await api(`/visits/${id}/review`));
    } catch (e) {
      setMsg({ tone: "error", text: errText(e) });
    }
  }, [id]);
  useEffect(() => { load(); }, [load, tick]);
  const required = useRequired(id, `${tick}:${d?.visit?.revision ?? ""}`);
  const active = d?.evidence.some((e) => Object.values(e.jobs || {}).some((j) => !TERMINAL.includes(j.status)));
  useEffect(() => {
    if (!active) return;
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, [active, load]);

  async function reopen() {
    try {
      await api(`/visits/${id}/reopen`, { body: { expected_revision: d.visit.revision } });
      setMsg({ tone: "success", text: "Inspection reopened for the foreman." });
      load();
    } catch (e) {
      setMsg({ tone: "error", text: errText(e) });
    }
  }
  async function openEstimate() {
    nav(`/office/visits/${id}/estimate`);
  }

  if (!d) return msg ? <Banner testid="review-error" tone="error" text={msg.text} /> : <Loading text="Loading inspection..." />;
  const v = d.visit;
  const candByEv = {};
  d.candidates.forEach((c) => (candByEv[c.evidence_id] = [...(candByEv[c.evidence_id] || []), c]));
  const sel = sp.get("e") || (d.evidence.find((e) => e.kind === "photo") || d.evidence[0])?.uuid;
  const ev = d.evidence.find((e) => e.uuid === sel);
  const locked = v.status === "Submitted" && isForeman;
  const staffSubmitted = v.status === "Submitted" && !isForeman;
  const refresh = () => setTick((t) => t + 1);
  const hasPhoto = d.evidence.some((e) => e.kind === "photo" && e.upload_state === "Verified"); // no photo: no 3D view action

  return (
    <div data-testid="review-page">
      <PageHead kicker="Inspection" title={v.title} subtitle={`${d.site?.name || "Site not set"}. Foreman: ${d.summary.foreman_name || "Not set"}`} testid="review-header"
        right={<>
          <Badge testid="review-visit-status" label={v.status === "Draft" ? "Inspection in progress" : v.status} />
          {hasPhoto ? <Link to={`/office/visits/${id}/scene${ev?.kind === "photo" ? `?evidence=${ev.uuid}` : ""}`} data-testid="review-scene-link" className="rr-focus inline-flex min-h-[44px] items-center gap-2 rounded-md border border-[#C5CCD2] bg-white px-3 text-sm font-semibold text-[#202428] hover:bg-[#F3F4F4]"><Box aria-hidden className="h-4 w-4" />3D view</Link> : null}
          {staffSubmitted ? <Btn testid="review-estimate-button" icon={Calculator} onClick={openEstimate}>Open estimate</Btn> : null}
          {staffSubmitted ? <Btn small kind="secondary" icon={LockOpen} testid="review-reopen-button" onClick={reopen}>Reopen for foreman</Btn> : null}
          <Btn small kind="secondary" icon={RefreshCw} testid="review-refresh-button" onClick={load}>Refresh</Btn>
        </>} />
      <div className="mb-3"><PolicyStatus visitId={id} refreshKey={tick} /></div>
      <div className="mb-5 flex flex-wrap items-center gap-2">
        {d.manifests.length ? <Mono testid="review-sync-details" label="Sync details">{d.manifests.map((m) => `${m.uuid} - ${m.state}`).join(" | ")}</Mono> : null}
        <Mono testid="review-visit-id" label="Inspection details">inspection {v.uuid} - rev {v.revision} - started {fmt(v.created_at)} - submitted {fmt(v.submitted_at)}</Mono>
      </div>
      <div className="mb-4"><Msg msg={msg} testid="review-message" /></div>
      <div className="grid gap-6 lg:grid-cols-12">
        <section aria-labelledby="ev-h" className="min-w-0 space-y-4 lg:col-span-7">
          <H2 id="ev-h">Photos, voice notes and typed notes ({d.evidence.length})</H2>
          {d.evidence.length ? <EvidencePicker list={d.evidence} sel={sel} candByEv={candByEv} onSel={(e) => setSp({ e }, { replace: true })} /> : <Empty text="No photos, voice notes or typed notes yet." testid="review-empty"><p className="text-[14px]">Photos, voice notes and typed notes appear here when they sync from the field app.</p></Empty>}
          {v.status === "Draft" ? <UploadPhoto visitId={id} onUploaded={(uuid) => { setSp({ e: uuid }, { replace: true }); refresh(); }} /> : null}
          {d.evidence.some((e) => e.kind === "note") ? (
            <div data-testid="review-all-notes" className="space-y-2">
              {d.evidence.filter((e) => e.kind === "note" && e.uuid !== sel).map((e) => <button key={e.uuid} type="button" onClick={() => setSp({ e: e.uuid }, { replace: true })} className="rr-focus block w-full rounded-lg border border-[#E3E7EA] bg-white px-4 py-3 text-left text-[15px] transition-colors hover:bg-[#F8F9F9]"><span className="text-[13px] text-[#59636B]">Typed note: </span>{e.text}</button>)}
            </div>
          ) : null}
          {ev ? <EvidenceDetail key={ev.uuid} ev={ev} visitId={id} locked={locked} onChanged={refresh} /> : null}
        </section>
        <aside className="min-w-0 space-y-4 lg:col-span-5">
          <NextAction d={d} required={required} staffSubmitted={staffSubmitted} isForeman={isForeman} canSubmit={canSubmit} onEstimate={openEstimate} onPick={(e) => setSp({ e }, { replace: true })}
            onSubmitted={() => { setMsg({ tone: "success", text: "Inspection submitted. It is ready for the estimate." }); refresh(); }} />
          <ChecklistPanel visitId={id} revision={v.revision} refreshKey={tick} onChanged={refresh} />
          <FieldsPanel visitId={id} locked={locked} refreshKey={tick} onChanged={refresh} />
          <SidePanels d={d} isAdmin={isAdmin} />
        </aside>
      </div>
    </div>
  );
}
