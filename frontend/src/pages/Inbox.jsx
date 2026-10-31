import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { AlertCircle, ArrowRight, Eye, KeyRound, Paperclip, Plus, RefreshCw } from "lucide-react";
import { api, errText, newId } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Badge, Banner, Btn, Field, H2, Loading, Modal, PageHead, fmt } from "@/components/rr/ui";

function VisitCard({ v }) {
  const rc = v.readiness_counts || {};
  return (
    <Link to={`/office/visits/${v.uuid}`} data-testid={`inbox-visit-${v.uuid}`}
      className="rr-focus rr-rise block rounded-lg border border-[#D9DEE2] bg-white p-4 transition-colors hover:border-[#B32624]">
      <div className="flex items-start justify-between gap-2">
        <p className="font-bold">{v.title}</p>
        <ArrowRight aria-hidden className="h-4 w-4 shrink-0 text-[#B32624]" />
      </div>
      <p className="mt-1 text-sm text-[#59636B]">{[v.site_name, v.foreman_name, fmt(v.submitted_at || v.updated_at)].filter(Boolean).join(", ")}</p>
      <div className="mt-2 flex flex-wrap gap-1">
        <Badge label={v.status === "Draft" ? "Inspection in progress" : v.status} />
        {v.evidence_count != null ? <Badge label={`${v.evidence_count} items`} icon={Paperclip} tone="neutral" /> : null}
        {v.pending_candidates ? <Badge label={`${v.pending_candidates} findings to review`} icon={Eye} tone="warning" /> : null}
        {rc["Missing required"] ? <Badge label={`${rc["Missing required"]} details missing`} icon={AlertCircle} tone="error" /> : null}
        {rc["Needs review"] ? <Badge label={`${rc["Needs review"]} details to review`} icon={Eye} tone="warning" /> : null}
      </div>
    </Link>
  );
}

export function NewVisit({ open, onClose }) {
  const nav = useNavigate();
  const [sites, setSites] = useState(null);
  const [f, setF] = useState({ site_id: "", title: "", processing_permission: "Policy" });
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (open && !sites) api("/sites").then((s) => { setSites(s); setF((x) => ({ ...x, site_id: x.site_id || s[0]?.uuid || "" })); }).catch((e) => setErr(errText(e)));
  }, [open, sites]);
  async function create() {
    setBusy(true);
    setErr(null);
    try {
      const v = await api("/visits", { body: { uuid: newId(), site_id: f.site_id, title: f.title.trim(), processing_permission: f.processing_permission, started_at: new Date().toISOString() } });
      nav(`/office/visits/${v.uuid}`);
    } catch (e) {
      setErr(errText(e)); // inputs kept
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal open={open} onClose={onClose} title="New inspection" description="Start an inspection here and add photos from this computer. Crews on site usually use the field app." testid="new-visit-modal">
      <div className="space-y-1">
        <label htmlFor="nv-site" className="block text-sm font-bold">Site</label>
        <select id="nv-site" data-testid="new-visit-site-select" value={f.site_id} onChange={(e) => setF({ ...f, site_id: e.target.value })} className="rr-focus min-h-[48px] w-full rounded-md border border-[#C5CCD2] bg-white px-3">
          {(sites || []).map((s) => <option key={s.uuid} value={s.uuid}>{s.name}{s.customer_name ? `, ${s.customer_name}` : ""}</option>)}
        </select>
      </div>
      <Field id="nv-title" testid="new-visit-title-input" label="Inspection title" value={f.title} onChange={(x) => setF({ ...f, title: x })} placeholder="e.g. Spur 1 tie survey" />
      <p data-testid="new-visit-policy-note" className="text-[13px] text-[#59636B]">AI analysis follows your company setting.</p>
      {err ? <Banner testid="new-visit-error" tone="error" text={err} /> : null}
      <Btn testid="new-visit-create-button" icon={Plus} loading={busy} disabled={!f.site_id || !f.title.trim()} onClick={create}>Start inspection</Btn>
    </Modal>
  );
}

export default function Inbox() {
  const { isForeman } = useAuth();
  const [data, setData] = useState(null);
  const [wos, setWos] = useState([]);
  const [err, setErr] = useState(null);
  const [nv, setNv] = useState(false);
  const load = useCallback(async () => {
    setErr(null);
    try {
      if (isForeman) {
        const vs = await api("/visits");
        setData({ submitted: vs.filter((v) => v.status === "Submitted"), draft_transfers: vs.filter((v) => v.status !== "Submitted") });
      } else {
        setData(await api("/office/inbox"));
        setWos(await api("/work-orders"));
      }
    } catch (e) {
      setErr(errText(e));
    }
  }, [isForeman]);
  useEffect(() => { load(); }, [load]);

  const grid = "grid gap-3 sm:grid-cols-2 xl:grid-cols-3";
  return (
    <div data-testid="inbox-page">
      <PageHead kicker={isForeman ? "Field" : "Office"} title={isForeman ? "My inspections" : "Office inbox"} subtitle={isForeman ? "Your submitted and draft inspections." : "Inspections ready for the office, and drafts still in progress."}
        right={<>
          <Btn small kind="secondary" icon={Plus} testid="inbox-new-visit-button" onClick={() => setNv(true)}>New inspection</Btn>
          <Btn small kind="secondary" icon={RefreshCw} testid="office-refresh-button" onClick={load}>Refresh</Btn>
        </>} />
      {err ? <Banner testid="office-error" tone="error" text={err} /> : null}
      {!data && !err ? <Loading /> : null}
      {data ? (
        <div className="space-y-8">
          <section aria-labelledby="sub-h">
            <H2 id="sub-h" className="mb-3">Submitted inspections ({data.submitted.length})</H2>
            {data.submitted.length ? <div className={grid}>{data.submitted.map((v) => <VisitCard key={v.uuid} v={v} />)}</div> : <p className="text-[#59636B]">No submitted inspections.</p>}
          </section>
          <section aria-labelledby="dr-h">
            <H2 id="dr-h">Draft inspections ({data.draft_transfers.length})</H2>
            <p className="mb-3 text-sm text-[#59636B]">Not submitted yet. Details may still change.</p>
            {data.draft_transfers.length ? <div className={grid}>{data.draft_transfers.map((v) => <VisitCard key={v.uuid} v={v} />)}</div> : <p className="text-[#59636B]">No draft inspections.</p>}
          </section>
          {wos.length ? (
            <section aria-labelledby="wo-h">
              <H2 id="wo-h" className="mb-3">Work orders ({wos.length})</H2>
              <div className={grid}>
                {wos.map((w) => (
                  <Link key={w.uuid} to={`/office/work-orders/${w.uuid}`} data-testid={`office-wo-${w.uuid}`} className="rr-focus block rounded-lg border border-[#D9DEE2] bg-white p-4 hover:border-[#B32624]">
                    <p className="font-bold">{w.number}</p>
                    <div className="mt-2 flex flex-wrap items-center gap-2">
                      <Badge label={`Access: ${w.access_status}`} icon={KeyRound} tone={w.access_status === "Confirmed" ? "success" : "warning"} />
                      <span className="text-sm text-[#59636B]">{w.scheduled_date || "No date"}</span>
                    </div>
                  </Link>
                ))}
              </div>
            </section>
          ) : null}
        </div>
      ) : null}
      <NewVisit open={nv} onClose={() => setNv(false)} />
    </div>
  );
}
