import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowRight, BadgeCheck, ChevronRight, Printer } from "lucide-react";
import { errText, openPrint } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { contractPrintPath, loadContract } from "@/lib/contracts";
import { Badge, Banner, Btn, Card, H2, Loading, Mono, PageHead, fmt } from "@/components/rr/ui";

export default function ContractDetail() {
  const { isAdmin } = useAuth();
  const { id } = useParams();
  const [c, setC] = useState(null);
  const [fallback, setFallback] = useState(false);
  const [err, setErr] = useState(null);
  useEffect(() => {
    loadContract(id).then((r) => { setC(r.c); setFallback(r.fallback); }).catch((e) => setErr(errText(e)));
  }, [id]);

  if (!c) return err ? <Banner testid="contract-error" tone="error" text={err} /> : <Loading />;
  const acc = c.acceptance;
  const linkCls = "rr-focus inline-flex min-h-[44px] items-center gap-1 rounded-md border border-[#C5CCD2] bg-white px-3 text-sm font-bold hover:bg-[#F3F4F4]";
  return (
    <div data-testid="contract-page">
      <PageHead kicker="Issued agreement" title={`Contract ${c.proposalNumber || ""}${c.versionNo ? `, revision ${c.versionNo}` : ""}`} subtitle={c.customerSite}
        right={<>
          {c.status ? <Badge testid="contract-status" label={c.status} /> : null}
          <Btn small kind="secondary" icon={Printer} testid="contract-print-button" onClick={async () => openPrint(await contractPrintPath(id, c.versionId))}>Print</Btn>
          {c.versionId ? <Link to={`/office/proposals/${c.versionId}`} data-testid="contract-proposal-link" className={linkCls}>Proposal <ArrowRight aria-hidden className="h-4 w-4" /></Link> : null}
          {c.workOrder?.uuid ? <Link to={`/office/work-orders/${c.workOrder.uuid}`} data-testid="contract-workorder-link" className={linkCls}>Work order {c.workOrder.number || ""} <ArrowRight aria-hidden className="h-4 w-4" /></Link> : null}
        </>} />
      {fallback ? <div className="mb-4"><Banner testid="contract-fallback-banner" tone="info" text="Showing the agreement as it was published with the proposal." /></div> : null}
      <div className="grid gap-6 lg:grid-cols-12">
        <Card testid="contract-document" className="space-y-3 lg:col-span-8">
          {c.text ? <div data-raw="1" data-testid="contract-document-text" className="whitespace-pre-wrap text-sm leading-relaxed">{c.text}</div> : <p data-testid="contract-document-missing" className="text-sm">The agreement text did not load. The issued agreement is unchanged. Use Print to open the stored copy.</p>}
        </Card>
        <aside className="space-y-4 lg:col-span-4">
          <Card testid="contract-integrity" className="space-y-2">
            <H2>Integrity</H2>
            <dl className="space-y-2 text-sm">
              <div><dt className="font-bold">Agreement template</dt><dd data-testid="contract-template-version">No. {c.templateVersion ?? "-"}</dd></div>
              <div><dt className="font-bold">Issued</dt><dd>{fmt(c.issuedAt)}</dd></div>
            </dl>
            <Mono testid="contract-document-details" label="Document details">
              <span data-testid="contract-template-hash" className="block">Template hash {c.templateHash || "-"}</span>
              <span data-testid="contract-document-hash" className="block">Document hash {c.documentHash || "-"}</span>
              {c.snapshotHash ? <span className="block">Proposal snapshot hash {c.snapshotHash}</span> : null}
            </Mono>
          </Card>
          <Card testid="contract-acceptance" className="space-y-2">
            <H2>Acceptance evidence</H2>
            {acc ? (
              <>
                <Badge label="Accepted" icon={BadgeCheck} tone="success" />
                <p className="text-sm">By <b>{acc.name}</b> ({acc.email}) at {fmt(acc.at || acc.accepted_at)}</p>
                {acc.agree !== undefined ? <p className="text-sm">Agreement checkbox: {acc.agree ? "ticked" : "not ticked"}</p> : null}
                {acc.uuid ? <Mono label="Decision details">decision {acc.uuid}</Mono> : null}
              </>
            ) : <p className="text-sm text-[#59636B]">Not accepted yet.</p>}
          </Card>
          {c.changeRequests?.length ? (
            <Card testid="contract-change-requests" className="space-y-2">
              <H2>Change requests</H2>
              {c.changeRequests.map((x) => <p key={x.uuid} className="text-sm">{x.name} ({x.email}) - {fmt(x.at)}{x.comment ? `: "${x.comment}"` : ""}</p>)}
            </Card>
          ) : null}
          {c.links?.length ? (
            <Card testid="contract-links" className="space-y-1">
              <H2>Customer links</H2>
              {c.links.map((l) => <div key={l.uuid} className="flex flex-wrap items-center gap-2 text-sm"><Badge label={l.revoked ? "Revoked" : "Active"} /> <Mono label="Link details">link {l.uuid.slice(0, 8)} - {fmt(l.created_at)}</Mono></div>)}
            </Card>
          ) : null}
          {c.variables && isAdmin ? (
            <details data-testid="contract-variables" className="group rounded-lg border border-[#D9DEE2] bg-white p-4">
              <summary className="rr-focus inline-flex cursor-pointer list-none items-center gap-1 font-semibold [&::-webkit-details-marker]:hidden"><ChevronRight aria-hidden className="h-4 w-4 transition-transform group-open:rotate-90" />Agreement variables</summary>
              <dl className="mt-2 space-y-1 text-xs">
                {Object.entries(c.variables).map(([k, v]) => <div key={k}><dt className="font-bold">{k}</dt><dd className="break-words text-[#59636B]">{typeof v === "object" ? JSON.stringify(v) : String(v)}</dd></div>)}
              </dl>
            </details>
          ) : null}
        </aside>
      </div>
    </div>
  );
}
