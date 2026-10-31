import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, RefreshCw } from "lucide-react";
import { endpoints, errText, hasRoute } from "@/lib/api";
import { normContract } from "@/lib/contracts";
import { Badge, Banner, Btn, Loading, PageHead, fmt } from "@/components/rr/ui";

export default function Contracts() {
  const [rows, setRows] = useState(null);
  const [err, setErr] = useState(null);
  const [missing, setMissing] = useState(false);
  const [drafts, setDrafts] = useState([]);
  const load = useCallback(async () => {
    setErr(null);
    try {
      if (!(await hasRoute("/contracts"))) {
        setMissing(true);
        setRows([]);
        return;
      }
      const r = await endpoints.contracts();
      setRows((Array.isArray(r) ? r : r.contracts || r.items || []).map(normContract));
      setDrafts(Array.isArray(r) ? [] : r.drafts || []);
      setMissing(false);
    } catch (e) {
      setErr(errText(e));
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  return (
    <div data-testid="contracts-page">
      <PageHead kicker="Office" title="Agreements" subtitle="Every issued agreement, exactly as published."
        right={<Btn small kind="secondary" icon={RefreshCw} testid="contracts-refresh-button" onClick={load}>Refresh</Btn>} />
      {missing ? <div className="mb-4"><Banner testid="contracts-missing-banner" tone="warning" text="The agreement list did not load. Open an agreement from its proposal instead." /></div> : null}
      {err ? <div className="mb-4"><Banner testid="contracts-error" tone="error" text={err} /></div> : null}
      {!rows && !err ? <Loading /> : null}
      {rows && !rows.length && !missing ? <p data-testid="contracts-empty" className="text-[#59636B]">No agreements yet. Sending a proposal sends its agreement too.</p> : null}
      {rows && rows.length ? (
        <div className="overflow-x-auto rounded-lg border border-[#D9DEE2]">
          <table data-testid="contracts-table" className="w-full min-w-[760px] bg-white text-sm">
            <thead className="bg-[#22272B] text-left text-xs uppercase tracking-wider text-gray-100">
              <tr>{["Proposal", "Customer / site", "Status", "Issued", ""].map((h) => <th key={h} scope="col" className="px-3 py-2">{h}</th>)}</tr>
            </thead>
            <tbody>
              {rows.map((c, i) => (
                <tr key={c.id || i} data-testid={`contract-row-${i}`} className="border-b border-[#D9DEE2] hover:bg-[#F3F4F4]/50">
                  <td className="px-3 py-3 font-bold">{c.proposalNumber || "-"}{c.versionNo ? ` - v${c.versionNo}` : ""}</td>
                  <td data-raw="1" className="px-3 py-3">{c.customerSite || "-"}</td>
                  <td className="px-3 py-3">{c.status ? <Badge label={c.status} /> : "-"}</td>
                  <td className="px-3 py-3">{fmt(c.issuedAt)}</td>
                  <td className="px-3 py-3"><Link to={`/office/contracts/${c.id}`} data-testid={`contract-open-${i}`} className="rr-focus inline-flex items-center gap-1 font-bold text-[#B32624] hover:underline">Open <ArrowRight aria-hidden className="h-3.5 w-3.5" /></Link></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      {drafts.length ? (
        <section aria-labelledby="drafts-h" className="mt-8">
          <h2 id="drafts-h" className="mb-2 text-lg font-semibold">Not published yet ({drafts.length})</h2>
          <p className="mb-3 text-sm text-[#59636B]">An agreement is issued when its proposal is published. Until then it is only a preview.</p>
          <ul className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
            {drafts.map((x, i) => (
              <li key={x.engagement_id} data-testid={`contract-draft-${i}`} className="flex flex-wrap items-center gap-2 rounded-lg border border-[#D9DEE2] bg-white p-3">
                <span className="font-bold">{x.proposal_number}</span>
                <Badge label={x.status || "Draft"} />
                <Link to={`/office/visits/${x.visit_id}/estimate`} data-testid={`contract-draft-open-${i}`} className="rr-focus ml-auto inline-flex items-center gap-1 text-sm font-bold text-[#B32624] hover:underline">Estimate <ArrowRight aria-hidden className="h-3.5 w-3.5" /></Link>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
