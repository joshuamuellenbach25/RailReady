import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, Handshake } from "lucide-react";
import { ApiError, api, errText, apiWrite } from "@/lib/api";
import { Banner, Loading, Mono, Msg, PageHead } from "@/components/rr/ui";
import { EditLineModal, LineModal, PackageModal, ScopeModal, TermsModal, blankLine } from "@/components/rr/estimate/Forms";
import { AgreementPanel, GateCard, LinesList, PhotosTerms, ScopeList, TotalsCard, VersionsList } from "@/components/rr/estimate/Sections";

export default function Estimate() {
  const { id: visitId } = useParams();
  const nav = useNavigate();
  const [eid, setEid] = useState(null);
  const [d, setD] = useState(null);
  const [msg, setMsg] = useState(null);
  const [val, setVal] = useState(null);
  const [ag, setAg] = useState(null);
  const [agErr, setAgErr] = useState(null);
  const [busy, setBusy] = useState(null);
  const [preview, setPreview] = useState(null);
  const [line, setLine] = useState(null);
  const [edit, setEdit] = useState(null);
  const [scope, setScope] = useState(null);
  const [terms, setTerms] = useState(null);
  const first = useRef(true);
  const inflight = useRef(false); // one write at a time: same-tick double clicks never send a second (stale) request

  useEffect(() => {
    api(`/visits/${visitId}/engagement`, { method: "POST" }).then((r) => setEid(r.engagement_id)).catch((e) => setMsg({ tone: "error", text: errText(e) }));
  }, [visitId]);

  const validate = useCallback(async () => {
    try {
      setVal(await api(`/engagements/${eid}/validate`, { method: "POST" }));
    } catch (e) {
      setMsg({ tone: "error", text: errText(e) });
    }
  }, [eid]);
  const loadAgreement = useCallback(async () => {
    setBusy("agreement");
    setAgErr(null);
    try {
      setAg(await api(`/engagements/${eid}/agreement-preview`));
    } catch (e) {
      setAgErr(errText(e));
    }
    setBusy(null);
  }, [eid]);
  const load = useCallback(async () => {
    try {
      setD(await api(`/engagements/${eid}`));
    } catch (e) {
      setMsg({ tone: "error", text: errText(e) });
    }
  }, [eid]);
  useEffect(() => {
    if (!eid) return;
    (async () => {
      await load();
      if (first.current) {
        first.current = false;
        await loadAgreement();
      }
      validate();
    })();
  }, [eid, load, loadAgreement, validate]);

  // Every action: server call -> reload -> re-validate. Returns true on success so dialogs close only then (inputs kept on error).
  async function run(fn, ok) {
    if (inflight.current) return false;
    inflight.current = true;
    setMsg(null);
    try {
      const r = await fn();
      if (ok) setMsg({ tone: "success", text: typeof ok === "function" ? ok(r) : ok });
      await load();
      validate();
      return r ?? true;
    } catch (e) {
      const det = e instanceof ApiError ? e.detail : null;
      if (det?.blockers) setVal({ blockers: det.blockers, ok: false, draft_revision: d?.draft.revision });
      setMsg({ tone: e instanceof ApiError && e.status === 409 ? "warning" : "error", text: errText(e) });
      await load();
      return false;
    } finally {
      inflight.current = false;
    }
  }

  if (!d) return msg ? <Banner testid="estimate-error" tone="error" text={msg.text} /> : <Loading text="Opening estimate..." />;
  const dr = d.draft;
  const rev = dr.revision;
  const accepted = !!d.engagement.accepted_version_id;
  const patchLine = (l, body) => run(() => api(`/engagements/${eid}/lines/${l.uuid}`, { method: "PATCH", body: { expected_revision: rev, ...body } }));
  const patchDraft = (body, ok) => run(() => api(`/engagements/${eid}/draft`, { method: "PATCH", body: { expected_revision: rev, ...body } }), ok);
  const modalErr = msg && msg.tone !== "success" ? <Banner tone={msg.tone} text={msg.text} testid="estimate-modal-error" /> : null;

  async function publish() {
    if (inflight.current) return;
    setBusy("publish");
    const v = await run(() => apiWrite(`/engagements/${eid}/publish`, { body: { expected_revision: rev, idempotency_key: `${eid}-${rev}` }, idempotencyKey: `${eid}-${rev}` }));
    setBusy(null);
    if (v && v.uuid) nav(`/office/proposals/${v.uuid}`, { state: { published: v.version_no > 1 ? `Proposal ${v.version_no} published. The agreement is now issued and frozen.` : "Published. The agreement is now issued and frozen." } });
  }
  function saveScope() {
    const s = scope;
    const body = {
      kind: s.kind || "tie_replacement", tie_type: s.tie_type, location: s.location || null, unit: s.unit || null, specification: s.specification || null,
      material_responsibility: s.material_responsibility || null, access_disposition: s.access_disposition || null,
      inspected_quantity: s.inspected_quantity === "" || s.inspected_quantity == null ? null : Number(s.inspected_quantity),
      repair_quantity: s.repair_quantity === "" || s.repair_quantity == null ? null : Number(s.repair_quantity),
    };
    run(() => (s.new ? api(`/engagements/${eid}/scope-items`, { body }) : api(`/scope-items/${s.uuid}`, { method: "PATCH", body: { ...body, expected_revision: s.revision } }))).then((ok) => ok && setScope(null));
  }
  function newScope() {
    const a = d.visit.answers || {};
    setScope({ new: true, kind: "tie_replacement", tie_type: "crosstie", unit: "each", location: a.work_location?.value || "", inspected_quantity: a.inspected_quantity?.value ?? "", repair_quantity: a.repair_quantity?.value ?? "", specification: a.tie_specification?.value || "", material_responsibility: a.material_responsibility?.value || "", access_disposition: "" });
  }
  function saveTerms() {
    const { expiry_local, contractor_identity, ...tt } = terms;
    patchDraft({ terms: tt, expiry_local: expiry_local || undefined, contractor_identity }).then((ok) => ok && setTerms(null));
  }

  return (
    <div data-testid="estimate-page">
      <PageHead kicker={`Estimate, draft revision ${rev}`} title={`Estimate ${d.engagement.proposal_number}`} subtitle={d.visit.title}
        right={<Link to={`/office/visits/${visitId}`} data-testid="estimate-back-to-visit" className="rr-focus inline-flex min-h-[44px] items-center gap-1 rounded-md border border-[#C5CCD2] bg-white px-3 text-sm font-bold hover:bg-[#F3F4F4]"><ArrowLeft aria-hidden className="h-4 w-4" />Review inspection</Link>} />
      <div className="mb-4 space-y-3">
        <Mono testid="estimate-ids" label="Estimate details">engagement {eid} - draft {dr.uuid} - rev {rev}</Mono>
        <Msg msg={msg} testid="estimate-message" />
        {accepted ? <Banner testid="estimate-accepted-banner" tone="success" icon={Handshake} text="Accepted by the customer. Prices and scope are locked." /> : null}
      </div>
      <div className="grid gap-6 lg:grid-cols-12">
        <div className="space-y-6 lg:col-span-7">
          <ScopeList d={d} accepted={accepted} onAdd={newScope} onEdit={(s) => setScope({ ...s })}
            onPreview={(s) => run(async () => setPreview({ sid: s.uuid, ...(await api(`/scope-items/${s.uuid}/package-preview`)) }))} />
          <LinesList lines={dr.lines} accepted={accepted} onAdd={() => setLine({ ...blankLine })}
            onReview={(l) => patchLine(l, { reviewed: true })} onToggle={(l) => patchLine(l, { included: !l.included })}
            onEdit={(l) => setEdit({ uuid: l.uuid, quantity: l.quantity, unit_cost: l.unit_cost, markup_pct: l.markup_pct, duplicate_reason: l.duplicate_reason || "" })} />
          <PhotosTerms d={d} accepted={accepted}
            onTogglePhoto={(p, on) => patchDraft({ selected_photo_ids: on ? dr.selected_photo_ids.filter((x) => x !== p.uuid) : [...dr.selected_photo_ids, p.uuid] })}
            onEditTerms={() => setTerms({ ...dr.terms, expiry_local: dr.expiry_local || "", contractor_identity: dr.contractor_identity || "" })}
            onReviewTerms={() => patchDraft({ terms_reviewed: true })} />
        </div>
        <aside className="space-y-4 lg:col-span-5 lg:self-start">
          <TotalsCard d={d} />
          <GateCard val={val} stale={val && val.draft_revision !== rev} accepted={accepted} busy={busy}
            onValidate={async () => { setBusy("validate"); await validate(); setBusy(null); }} onPublish={publish} />
          <AgreementPanel a={ag} err={agErr} rev={rev} busy={busy === "agreement"} onRefresh={async () => { await loadAgreement(); validate(); }} />
          <VersionsList d={d} />
          {d.decisions.length ? (
            <div data-testid="estimate-decisions" className="rounded-lg border border-[#D9DEE2] bg-white p-4 text-sm">
              <p className="font-semibold">Customer decisions</p>
              {d.decisions.map((x) => <p key={x.uuid} className="mt-1">{x.type === "accept" ? "Accepted" : "Changes requested"} by {x.name} ({x.email}){x.comment ? `: "${x.comment}"` : ""}</p>)}
            </div>
          ) : null}
        </aside>
      </div>
      <PackageModal preview={preview} onClose={() => setPreview(null)} error={modalErr}
        onAdd={() => run(() => api(`/scope-items/${preview.sid}/package`, { method: "POST" }), (r) => (r.added ? "Package lines added" : "Already added")).then((ok) => ok && setPreview(null))} />
      <LineModal line={line} setLine={setLine} error={modalErr}
        onSave={() => run(() => api(`/engagements/${eid}/lines`, { body: { ...line, expected_revision: rev, duplicate_reason: line.duplicate_reason || null } })).then((ok) => ok && setLine(null))} />
      <EditLineModal edit={edit} setEdit={setEdit} error={modalErr}
        onSave={() => patchLine(edit, { quantity: edit.quantity, unit_cost: edit.unit_cost, markup_pct: edit.markup_pct, duplicate_reason: edit.duplicate_reason || undefined }).then((ok) => ok && setEdit(null))} />
      <ScopeModal scope={scope} setScope={setScope} onSave={saveScope} error={modalErr} />
      <TermsModal terms={terms} setTerms={setTerms} onSave={saveTerms} error={modalErr} />
    </div>
  );
}
