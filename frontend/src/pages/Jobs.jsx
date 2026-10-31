import { useCallback, useEffect, useState } from "react";
import { Link, Navigate, useLocation } from "react-router-dom";
import { ArrowRight, Plus, RefreshCw } from "lucide-react";
import { NewVisit } from "@/pages/Inbox";
import { api, endpoints, errText, hasRoute } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Badge, Banner, Btn, Empty, Loading, PageHead } from "@/components/rr/ui";

// /api/office/jobs rows are read tolerantly so field-name drift does not break the page.
const pick = (...xs) => xs.find((x) => x !== undefined && x !== null && x !== "");
function normJob(j) {
  const wo = typeof j.work_order === "object" && j.work_order ? j.work_order : null;
  const ver = typeof j.proposal === "object" && j.proposal ? j.proposal : null;
  const con = typeof j.contract === "object" && j.contract ? j.contract : null;
  const visitId = pick(j.visit_id, j.visit?.uuid, j.uuid);
  return {
    key: pick(j.uuid, j.job_id, visitId),
    visitId,
    customer: pick(j.customer_name, j.customer?.name),
    site: pick(j.site_name, j.site?.name),
    title: pick(j.visit_title, j.title, j.visit?.title),
    visitStatus: pick(j.visit_status, j.visit?.status, j.status),
    findings: pick(j.findings_count, j.confirmed_findings, j.findings),
    pending: pick(j.pending_candidate_count, j.pending_candidates),
    candidates: j.candidate_count,
    estimate: pick(j.estimate_status, j.estimate?.status),
    versionNo: pick(j.proposal_version, j.latest_version_no, j.version_no, ver?.version_no),
    versionId: pick(j.latest_version_id, j.proposal_version_id, j.version_id, ver?.uuid),
    proposalStatus: pick(j.latest_version_status, j.proposal_status, ver?.status),
    proposalNumber: j.proposal_number,
    contract: pick(j.contract_status, con?.status),
    contractId: pick(j.contract_id, con?.uuid, con?.id),
    woId: pick(j.work_order_id, wo?.uuid),
    woNumber: pick(j.work_order_number, wo?.number, typeof j.work_order === "string" ? j.work_order : null),
    woAccess: pick(j.work_order_access_status, wo?.access_status),
    saved: !!pick(j.saved_analysis, j.has_saved_analysis, j.label === "Saved analysis" ? true : null),
    fromInbox: !!j._fromInbox,
  };
}

const linkCls = "rr-focus inline-flex min-h-[36px] items-center gap-1 rounded-md px-1 text-[14px] font-medium text-[#3C444B] transition-colors hover:text-[#202428] hover:underline";

/** One plain status per job (display only - every value comes from the server row). Drafts are never sent to the estimate. */
function stage(j) {
  const visit = `/office/visits/${j.visitId}`;
  if (j.woId) return ["Work scheduled", "success", "View work order", `/office/work-orders/${j.woId}`];
  if (j.proposalStatus === "Accepted") return ["Customer accepted", "success", "View proposal", `/office/proposals/${j.versionId}`];
  if (j.proposalStatus === "Changes requested") return ["Customer asked for changes", "warning", "View proposal", `/office/proposals/${j.versionId}`];
  if (j.versionId && j.proposalStatus) return ["Link ready to share", "neutral", "View proposal", `/office/proposals/${j.versionId}`];
  if (j.visitStatus !== "Submitted") return ["Inspection in progress", "neutral", "Continue inspection", visit];
  if (j.pending) return ["Needs review", "warning", "Answer questions", visit];
  if (j.estimate === "Draft") return ["Estimate in progress", "neutral", "Open estimate", `${visit}/estimate`]; // server: draft has lines
  return ["Ready for the office", "neutral", "Start the estimate", `${visit}/estimate`];
}

function JobCard({ j, i }) {
  const [label, tone, next, to] = stage(j);
  const [hasPhoto, setHasPhoto] = useState(false); // 3D view only once a received photo is confirmed
  useEffect(() => {
    if (!j.visitId) return undefined;
    const c = new AbortController();
    api(`/visits/${j.visitId}/evidence`, { signal: c.signal })
      .then((list) => setHasPhoto((list || []).some((e) => e.kind === "photo" && e.upload_state === "Verified")))
      .catch(() => {});
    return () => c.abort();
  }, [j.visitId]);
  return (
    <li data-testid={`job-row-${i}`} className="rr-rise flex flex-col gap-4 rounded-xl border border-[#E3E7EA] bg-white p-5 shadow-[0_1px_2px_rgba(32,36,40,0.04)] transition-shadow duration-200 hover:shadow-[0_6px_20px_rgba(32,36,40,0.08)] md:flex-row md:items-center">
      <div className="min-w-0 flex-1">
        <p className="text-[13px] text-[#59636B]">{[j.customer, j.site].filter(Boolean).join(", ")}</p>
        <Link to={`/office/visits/${j.visitId}`} data-testid={`job-visit-link-${i}`} className="rr-focus mt-0.5 block rounded text-[17px] font-semibold text-[#202428] hover:underline">{j.title || "Inspection"}</Link>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <Badge testid={`job-status-${i}`} label={label} tone={tone} />
          {j.pending && j.woId == null && label !== "Needs review" ? <span className="text-[13px] text-[#7A4A00]">{j.pending} question{j.pending > 1 ? "s" : ""} to answer</span> : null}
          {j.findings ? <span data-testid={`job-findings-${i}`} className="text-[13px] text-[#59636B]">{j.findings} finding{j.findings > 1 ? "s" : ""}</span> : null}
        </div>
        <div className="mt-2 flex flex-wrap gap-x-3">
          {hasPhoto ? <Link to={`/office/visits/${j.visitId}/scene`} data-testid={`job-scene-link-${i}`} className={linkCls}>3D view</Link> : null}
          {j.visitStatus === "Submitted" ? <Link to={`/office/visits/${j.visitId}/estimate`} data-testid={`job-estimate-link-${i}`} className={linkCls}>Estimate</Link> : null}
          {j.versionId ? <Link to={`/office/proposals/${j.versionId}`} data-testid={`job-proposal-link-${i}`} className={linkCls}>Proposal</Link> : null}
          {j.contract && (j.contractId || j.versionId) ? <Link to={`/office/contracts/${j.contractId || j.versionId}`} data-testid={`job-contract-link-${i}`} className={linkCls}>Agreement</Link> : null}
          {j.woId ? <Link to={`/office/work-orders/${j.woId}`} data-testid={`job-workorder-link-${i}`} className={linkCls}>Work order</Link> : null}
        </div>
      </div>
      <Link to={to} data-testid={`job-next-${i}`} className="rr-focus inline-flex min-h-[44px] shrink-0 items-center justify-center gap-1.5 rounded-lg border border-[#D2D8DD] bg-white px-4 text-[15px] font-medium text-[#202428] transition-colors hover:border-[#B32624] hover:text-[#B32624]">{next}<ArrowRight aria-hidden className="h-4 w-4" /></Link>
    </li>
  );
}

export default function Jobs() {
  const { isForeman } = useAuth();
  const loc = useLocation();
  const [rows, setRows] = useState(null);
  const [err, setErr] = useState(null);
  const [fallback, setFallback] = useState(false);
  const [nv, setNv] = useState(false);

  const load = useCallback(async () => {
    setErr(null);
    try {
      if (await hasRoute("/office/jobs")) {
        const r = await endpoints.jobs();
        setRows((Array.isArray(r) ? r : r.jobs || r.items || []).map(normJob));
        setFallback(false);
      } else {
        // Route not deployed yet: show inbox visits so the demo path still works (no derived business state).
        const r = isForeman ? { submitted: await api("/visits"), draft_transfers: [] } : await api("/office/inbox");
        setRows([...r.submitted, ...r.draft_transfers].map((v) => normJob({ ...v, visit_id: v.uuid, visit_status: v.status, _fromInbox: true })));
        setFallback(true);
      }
    } catch (e) {
      setErr(errText(e));
    }
  }, [isForeman]);
  useEffect(() => { load(); }, [load, loc.state]);

  if (isForeman) return <Navigate to="/office/inbox" replace />; // jobs board is staff-only on the server
  return (
    <div data-testid="jobs-page">
      <PageHead kicker="Office" title="Jobs" subtitle="Every job from site visit to scheduled work. The button on each one shows what to do next."
        right={<Btn small kind="secondary" icon={RefreshCw} testid="jobs-refresh-button" onClick={load}>Refresh</Btn>} />
      {fallback ? <div className="mb-4"><Banner testid="jobs-fallback-banner" tone="info" text="Showing inspections only. Prices and work orders did not load. Refresh to try again." /></div> : null}
      {err ? <div className="mb-4"><Banner testid="jobs-error" tone="error" text={err} /></div> : null}
      {!rows && !err ? <Loading text="Loading jobs..." /> : null}
      {rows && !rows.length ? <Empty testid="jobs-empty" text="No jobs yet."><p className="text-[14px]">Select + to start your first inspection.</p></Empty> : null}
      {rows && rows.length ? <ul data-testid="jobs-table" className="space-y-3">{rows.map((j, i) => <JobCard key={j.key || i} j={j} i={i} />)}</ul> : null}
      <button type="button" data-testid="jobs-new-inspection-fab" aria-label="New inspection" title="New inspection" onClick={() => setNv(true)}
        className="rr-focus fixed bottom-6 right-6 z-30 flex h-14 w-14 items-center justify-center rounded-full bg-[#B32624] text-white shadow-[0_8px_24px_rgba(179,38,36,0.35)] transition-transform duration-200 hover:scale-105 hover:bg-[#962020] active:scale-95">
        <Plus aria-hidden className="h-7 w-7" />
      </button>
      <NewVisit open={nv} onClose={() => setNv(false)} />
    </div>
  );
}
