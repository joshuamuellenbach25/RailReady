import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { ArrowRight, Copy, ExternalLink, FileSignature, Link2, Link2Off, Printer, Share2, Tag } from "lucide-react";
import { api, errText, openPrint, withAuth } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Badge, Banner, Btn, Card, H2, Loading, Mono, Msg, PageHead, fmt } from "@/components/rr/ui";

const expiryText = (e) => {
  if (!e?.utc) return "Not set";
  try {
    return new Intl.DateTimeFormat([], { year: "numeric", month: "long", day: "numeric", hour: "numeric", minute: "2-digit", timeZone: e.timezone || undefined, timeZoneName: "short" }).format(new Date(e.utc));
  } catch {
    return new Date(e.utc).toLocaleString();
  }
};

// Customer-safe preview: renders ONLY snapshot fields the public page also gets (never internal_snapshot).
function SafePreview({ v }) {
  const s = v.snapshot;
  return (
    <Card testid="proposal-safe-preview" className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <H2>Customer-safe preview</H2>
        <Badge label="What the customer sees" tone="neutral" />
      </div>
      <p data-raw="1" className="text-sm text-[#59636B]">{s.customer_site}</p>
      <p data-testid="proposal-expiry" className="text-sm font-medium">Price good until {expiryText(s.expiry)}</p>
      <div>
        <h3 className="font-bold">Scope</h3>
        <ul className="list-disc pl-5 text-sm">{s.findings.map((f) => <li key={f}>{f}</li>)}</ul>
        {s.not_inspected.map((n) => <p key={n.area} className="text-sm text-[#59636B]">Not inspected: {n.area} - {n.reason} (no charges)</p>)}
      </div>
      <table className="w-full text-sm">
        <thead><tr className="border-b-2 border-[#D9DEE2] text-left"><th className="py-1">Item</th><th className="py-1 text-right">Qty</th><th className="py-1 text-right">Unit price</th><th className="py-1 text-right">Amount</th></tr></thead>
        <tbody>
          {s.lines.map((l, i) => (
            <tr key={`${l.description}-${i}`} className="border-b border-[#D9DEE2]">
              <td className="py-1.5 pr-2">{l.description}</td><td className="py-1.5 text-right font-mono">{l.quantity} {l.unit}</td>
              <td className="py-1.5 text-right font-mono">${l.unit_price}</td><td className="py-1.5 text-right font-mono">${l.line_total}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="text-sm">Subtotal ${s.totals.subtotal}, tax ({s.totals.tax_rate}%) ${s.totals.tax}</p>
      <p data-testid="proposal-total" className="text-xl font-semibold">Total ${s.totals.total} USD</p>
      <p data-raw="1" className="text-xs text-[#59636B]">{s.tax_treatment_text}</p>
      {s.photos?.length ? (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
          {s.photos.map((p) => <img key={p.evidence_id} src={withAuth(`/proposals/${v.uuid}/media/${p.evidence_id}`)} alt={p.caption || "Selected site photo"} className="h-28 w-full rounded border border-[#D9DEE2] bg-[#22272B] object-contain" />)}
        </div>
      ) : null}
      <details className="rounded border border-[#D9DEE2] p-3">
        <summary className="rr-focus cursor-pointer font-bold">Agreement text</summary>
        <div data-raw="1" className="mt-2 whitespace-pre-wrap text-sm leading-relaxed">{s.agreement.document_text}</div>
      </details>
    </Card>
  );
}

function ShareCard({ v, links, canShare, run, isForeman }) {
  const [shared, setShared] = useState(null);
  const [copied, setCopied] = useState(false);
  async function share() {
    const r = await run(() => api(`/versions/${v.uuid}/share`, { method: "POST" }), "Customer link created. Copy it now. For security it can't be shown again.");
    if (r?.path) setShared(`${window.location.origin}${r.path}`);
  }
  return (
    <Card testid="proposal-share-card" className="space-y-3">
      <H2>Customer link</H2>
      {!isForeman && canShare ? <Btn icon={Share2} testid="proposal-share-button" onClick={share}>Get customer link</Btn> : null}
      {!canShare ? <p className="text-sm text-[#59636B]">Only Published or Accepted versions can be shared (this one is {v.status}).</p> : null}
      {shared ? (
        <div data-testid="share-link-banner" className="space-y-2 rounded-md border border-green-700 bg-green-50 p-3">
          <p className="text-sm font-bold text-green-900">Customer link (open in a private window):</p>
          <p data-testid="share-link-url" className="break-all font-mono text-sm">{shared}</p>
          <div className="flex flex-wrap gap-2">
            <Btn small kind="secondary" icon={Copy} testid="share-link-copy" onClick={async () => { try { await navigator.clipboard.writeText(shared); setCopied(true); } catch { setCopied(false); } }}>{copied ? "Copied" : "Copy link"}</Btn>
            <a href={shared} target="_blank" rel="noopener noreferrer" data-testid="share-link-open" className="rr-focus inline-flex min-h-[44px] items-center gap-2 rounded-md border border-[#C5CCD2] bg-white px-3 text-sm font-bold hover:bg-[#F3F4F4]"><ExternalLink aria-hidden className="h-4 w-4" />Open customer page</a>
          </div>
        </div>
      ) : null}
      <ul className="space-y-2">
        {links.map((l) => (
          <li key={l.uuid} data-testid={`link-${l.uuid}`} className="flex flex-wrap items-center gap-2 border-t border-[#D9DEE2] pt-2">
            <Badge label={l.revoked ? "Revoked" : "Active"} icon={l.revoked ? Link2Off : Link2} />
            <Mono label="Link details">link {l.uuid.slice(0, 8)}, created {fmt(l.created_at)}{l.revoked_at ? `, revoked ${fmt(l.revoked_at)}` : ""}</Mono>
            {!l.revoked && !isForeman ? <Btn small kind="danger" icon={Link2Off} testid={`link-revoke-${l.uuid}`} className="ml-auto" onClick={() => run(() => api(`/links/${l.uuid}/revoke`, { method: "POST" }), "Link revoked. The customer page no longer opens and no decisions can be made from it.")}>Revoke link</Btn> : null}
          </li>
        ))}
      </ul>
    </Card>
  );
}

function Decisions({ decisions }) {
  return (
    <Card testid="proposal-decisions" className="space-y-2">
      <H2>Customer decisions & change requests</H2>
      {!decisions.length ? <p className="text-sm text-[#59636B]">None yet.</p> : null}
      {decisions.map((x) => (
        <div key={x.uuid} data-testid={`decision-${x.uuid}`} className="space-y-1 border-t border-[#D9DEE2] pt-2 text-sm">
          <p><b>v{x.version_no} - {x.type === "accept" ? "Accepted" : "Changes requested"}</b> by {x.name} ({x.email}) - {fmt(x.at)}</p>
          {x.comment ? <blockquote className="border-l border-amber-700 pl-3 italic">"{x.comment}"</blockquote> : null}
          {x.topic_suggestion ? <Badge testid={`decision-topic-${x.uuid}`} icon={Tag} tone="neutral" label={x.topic_suggestion.status === "Done" ? `Topic suggestion: ${x.topic_suggestion.topic} (staff only)` : "Topic: Not run"} /> : null}
        </div>
      ))}
    </Card>
  );
}

export default function Proposal() {
  const { id } = useParams();
  const loc = useLocation();
  const nav = useNavigate();
  const { isForeman } = useAuth();
  const [v, setV] = useState(null);
  const [e, setE] = useState(null);
  const inflight = useRef(false);
  const [msg, setMsg] = useState(loc.state?.published ? { tone: "success", text: loc.state.published } : null);
  const load = useCallback(async () => {
    try {
      const ver = await api(`/versions/${id}`);
      setV(ver);
      setE(await api(`/engagements/${ver.engagement_id}`));
    } catch (x) {
      setMsg({ tone: "error", text: errText(x) });
    }
  }, [id]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (loc.state?.published) nav(loc.pathname, { replace: true, state: null }); // one-shot success message
  }, [loc.state, loc.pathname, nav]);
  async function run(fn, ok) {
    if (inflight.current) return null; // same-tick double clicks send one request (one link, one revoke)
    inflight.current = true;
    try {
      const r = await fn();
      if (ok) setMsg({ tone: "success", text: ok });
      await load();
      return r;
    } catch (x) {
      setMsg({ tone: x?.status === 409 ? "warning" : "error", text: errText(x) });
      return null;
    } finally {
      inflight.current = false;
    }
  }

  if (!v) return msg ? <Banner testid="proposal-error" tone="error" text={msg.text} /> : <Loading />;
  const ev = e?.versions.find((x) => x.uuid === v.uuid);
  const links = ev?.links || [];
  const accepted = !!e?.engagement.accepted_version_id;
  const decisions = (e?.decisions || []).filter((x) => x.version_id === v.uuid || x.version_no === v.version_no);
  const linkCls = "rr-focus inline-flex min-h-[44px] items-center gap-1 rounded-md border border-[#C5CCD2] bg-white px-3 text-sm font-bold hover:bg-[#F3F4F4]";
  return (
    <div data-testid="proposal-page">
      <PageHead kicker="Proposal" title={`${v.snapshot.proposal_number}${v.version_no > 1 ? `, revision ${v.version_no}` : ""}`} subtitle={`Published ${fmt(v.published_at)}`}
        right={<>
          <Badge testid="proposal-status" label={v.status} />
          <Badge testid="proposal-contract-status" label={`Contract ${v.contract_status}`} icon={FileSignature} tone="neutral" />
          <Btn small kind="secondary" icon={Printer} testid="proposal-print-button" onClick={() => openPrint(`/proposals/${v.uuid}/print`)}>Print</Btn>
          <Link to={`/office/contracts/${v.uuid}`} data-testid="proposal-contract-link" className={linkCls}>Contract <ArrowRight aria-hidden className="h-4 w-4" /></Link>
          {!isForeman ? <Link to={`/office/visits/${v.visit_id}/estimate`} data-testid="proposal-estimate-link" className={linkCls}>Estimate <ArrowRight aria-hidden className="h-4 w-4" /></Link> : null}
        </>} />
      <div className="mb-4 space-y-3">
        <Msg msg={msg} testid="proposal-message" />
        <Mono testid="proposal-hashes" label="Document details" className="block">version {v.uuid} - snapshot {v.snapshot_hash} - agreement {v.document_hash} - draft rev {v.draft_revision}</Mono>
        {v.status === "Changes requested" && !accepted && !isForeman ? (
          <Banner tone="warning" text="The customer asked for changes to this proposal.">
            <Btn small kind="secondary" icon={Copy} testid={`version-copy-${v.version_no}`} onClick={async () => { const r = await run(() => api(`/versions/${v.uuid}/copy-to-draft`, { method: "POST" }), "Copied into draft with feedback"); if (r) nav(`/office/visits/${v.visit_id}/estimate`); }}>Copy to draft</Btn>
          </Banner>
        ) : null}
        {e?.work_order ? <Link to={`/office/work-orders/${e.work_order.uuid}`} data-testid="proposal-workorder-link" className="rr-focus inline-flex min-h-[48px] items-center gap-2 rounded-md bg-[#B32624] px-4 font-bold text-white hover:bg-[#B32624]">Work order {e.work_order.number} <ArrowRight aria-hidden className="h-4 w-4" /></Link> : null}
      </div>
      <div className="grid gap-6 lg:grid-cols-12">
        <div className="lg:col-span-7"><SafePreview v={v} /></div>
        <aside className="space-y-4 lg:col-span-5">
          <ShareCard v={v} links={links} canShare={["Published", "Accepted"].includes(v.status)} run={run} isForeman={isForeman} />
          <Decisions decisions={decisions} />
          <Card testid="proposal-versions" className="space-y-2">
            <H2>All versions</H2>
            {(e?.versions || []).map((x) => (
              <Link key={x.uuid} to={`/office/proposals/${x.uuid}`} data-testid={`version-${x.version_no}`} aria-current={x.uuid === v.uuid ? "page" : undefined}
                className={`rr-focus flex flex-wrap items-center gap-2 rounded border p-2 ${x.uuid === v.uuid ? "border-[#B32624] bg-[#F3F4F4]" : "border-[#D9DEE2] hover:border-[#C5CCD2]"}`}>
                <span className="font-semibold">Proposal {x.version_no}</span>
                <Badge testid={`version-status-${x.version_no}`} label={x.status} />
                <Badge label={`Contract ${x.contract_status}`} tone="neutral" />
              </Link>
            ))}
          </Card>
        </aside>
      </div>
    </div>
  );
}
