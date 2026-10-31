// Contract helpers. GET /api/contracts*; until it is deployed the detail page
// falls back to the frozen agreement inside the published version (GET /api/versions/{id}). Display only.
import { api, endpoints, hasRoute } from "@/lib/api";

const pick = (...xs) => xs.find((x) => x !== undefined && x !== null && x !== "");

export function normContract(c) {
  const ag = c.agreement || c.snapshot?.agreement || c.document || {};
  const acc = c.acceptance_evidence || c.acceptance || (c.decisions || []).find((x) => x.type === "accept") || null;
  return {
    id: pick(c.contract_id, c.uuid, c.id, c.version_id),
    versionId: pick(c.version_id, c.proposal_version_id, c.snapshot ? c.uuid : null),
    engagementId: c.engagement_id,
    visitId: c.visit_id,
    proposalNumber: pick(c.proposal_number, c.snapshot?.proposal_number),
    versionNo: pick(c.version_no, c.proposal_version),
    status: pick(c.contract_status, c.status_label, typeof c.status === "string" && !c.snapshot ? c.status : null, c.snapshot ? c.contract_status : null),
    customerSite: pick(c.customer_site, c.snapshot?.customer_site, [c.customer_name, c.site_name].filter(Boolean).join(", ")),
    issuedAt: pick(c.issued_at, c.published_at),
    text: pick(ag.document_text, c.document_text),
    templateVersion: pick(ag.template_version, c.template_version),
    templateHash: pick(ag.template_hash, c.template_hash),
    documentHash: pick(ag.document_hash, c.document_hash),
    snapshotHash: c.snapshot_hash,
    variables: pick(ag.variables, c.variables),
    acceptance: acc,
    workOrder: pick(c.work_order, c.work_order_id ? { uuid: c.work_order_id, number: c.work_order_number } : null),
    changeRequests: c.change_requests || (c.decisions || []).filter((x) => x.type === "changes"),
    links: c.links || [],
    total: pick(c.total, c.totals?.total, c.snapshot?.totals?.total),
  };
}

export async function loadContract(id) {
  if (await hasRoute("/contracts/{}")) return { c: normContract(await endpoints.contract(id)), fallback: false };
  return { c: normContract(await api(`/versions/${id}`)), fallback: true };
}

export async function contractPrintPath(id, versionId) {
  return (await hasRoute("/contracts/{}/print")) ? `/contracts/${id}/print` : `/proposals/${versionId || id}/print`;
}
