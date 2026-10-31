import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowRight, CalendarDays, FileText, KeyRound, Truck } from "lucide-react";
import { api, errText } from "@/lib/api";
import { Badge, Banner, Btn, Card, Field, H2, Loading, Mono, Msg, PageHead, fmt } from "@/components/rr/ui";

const NEXT = { "Not arranged": "Requested", Requested: "Confirmed" };

function FrozenScope({ fs }) {
  return (
    <Card testid="workorder-frozen-scope" className="bg-[#F3F4F4]">
      <div className="flex items-center justify-between gap-2">
        <H2>What the customer accepted</H2>
        <Badge label="Read-only" icon={FileText} tone="neutral" />
      </div>
      <ul className="mt-2 list-disc space-y-1 pl-5">{fs.findings.map((f) => <li key={f}>{f}</li>)}</ul>
      {fs.not_inspected.map((n) => <p key={n.area} className="mt-1 text-sm text-[#59636B]">Not inspected: {n.area} - {n.reason}</p>)}
      {fs.ties_supplied_by_customer ? <div className="mt-2"><Badge label="Ties supplied by customer" icon={Truck} /></div> : null}
      <table className="mt-3 w-full text-sm">
        <tbody>
          {fs.lines.map((l, i) => (
            <tr key={`${l.description}-${i}`} className="border-b border-[#D9DEE2]"><td className="py-1.5 pr-2">{l.description}</td><td className="py-1.5 text-right font-mono">{l.quantity} {l.unit}</td><td className="py-1.5 text-right font-mono">${l.line_total}</td></tr>
          ))}
        </tbody>
      </table>
      <p data-testid="workorder-total" className="mt-3 text-lg font-semibold">Total ${fs.totals.total} USD</p>
      <Mono label="Document details" className="mt-2 block">snapshot {fs.snapshot_hash} - agreement {fs.document_hash}</Mono>
    </Card>
  );
}

export default function WorkOrder() {
  const { id } = useParams();
  const [w, setW] = useState(null);
  const [date, setDate] = useState("");
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    try {
      const r = await api(`/work-orders/${id}`);
      setW(r);
      setDate((d) => d || r.scheduled_date || "");
    } catch (e) {
      setMsg({ tone: "error", text: errText(e) });
    }
  }, [id]);
  useEffect(() => { load(); }, [load]);

  async function patch(body, ok = "Saved") {
    if (busy) return;
    setBusy(true); // all planning controls stay disabled until the save AND the reload (new revision) finish
    try {
      await api(`/work-orders/${id}`, { method: "PATCH", body: { expected_revision: w.revision, ...body } });
      setMsg({ tone: "success", text: ok });
    } catch (e) {
      setMsg({ tone: e?.status === 409 ? "warning" : "error", text: errText(e) }); // date input kept
    }
    await load();
    setBusy(false);
  }

  if (!w) return msg ? <Banner testid="workorder-error" tone="error" text={msg.text} /> : <Loading />;
  const fs = w.frozen_scope;
  return (
    <div data-testid="workorder-page">
      <PageHead kicker="Work order" title={`Work order ${w.number}`} subtitle="Plan the crew, date and site access for the accepted work."
        right={w.accepted_version_id ? (
          <>
            <Link data-testid="workorder-proposal-link" to={`/office/proposals/${w.accepted_version_id}`} className="rr-focus inline-flex min-h-[44px] items-center gap-1 rounded-md border border-[#C5CCD2] bg-white px-3 text-sm font-bold hover:bg-[#F3F4F4]">Proposal <ArrowRight className="h-4 w-4" aria-hidden /></Link>
            <Link data-testid="workorder-contract-link" to={`/office/contracts/${w.accepted_version_id}`} className="rr-focus inline-flex min-h-[44px] items-center gap-1 rounded-md border border-[#C5CCD2] bg-white px-3 text-sm font-bold hover:bg-[#F3F4F4]">Contract <ArrowRight className="h-4 w-4" aria-hidden /></Link>
          </>
        ) : null} />
      <div className="space-y-4">
        <Msg msg={msg} testid="workorder-message" />
        <div className="grid gap-5 lg:grid-cols-12">
          <div className="lg:col-span-7"><FrozenScope fs={fs} /></div>
          <Card testid="workorder-planning" className="space-y-4 lg:col-span-5">
            <H2>Planning (editable)</H2>
            {busy ? <p data-testid="workorder-saving" role="status" className="text-sm font-bold text-[#59636B]">Saving...</p> : null}
            <fieldset>
              <legend className="mb-2 text-sm font-bold">Crew</legend>
              <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="Crew">
                {w.crews.map((c) => (
                  <Btn key={c.uuid} small role="radio" aria-checked={w.crew_id === c.uuid} testid={`workorder-crew-${c.uuid}`} kind={w.crew_id === c.uuid ? "primary" : "secondary"} disabled={busy}
                    onClick={() => patch({ crew_id: c.uuid }, `Crew set: ${c.name}`)}>{c.name}</Btn>
                ))}
              </div>
            </fieldset>
            <div className="flex flex-wrap items-end gap-2">
              <div className="min-w-[200px] flex-1"><Field id="wo-date" testid="workorder-date-input" label="Planned date" type="date" value={date} onChange={setDate} disabled={busy} /></div>
              <Btn small kind="secondary" icon={CalendarDays} testid="workorder-date-save" disabled={busy || !date} onClick={() => patch({ scheduled_date: date }, "Date saved")}>Save date</Btn>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm font-bold">Access:</span>
              <Badge testid="workorder-access-status" label={w.access_status} icon={KeyRound} tone={w.access_status === "Confirmed" ? "success" : "warning"} />
            </div>
            {NEXT[w.access_status] ? (
              <Btn small testid="workorder-access-next" icon={ArrowRight} disabled={busy} onClick={() => patch({ access_status: NEXT[w.access_status] }, `Access marked ${NEXT[w.access_status]}`)}>Mark access {NEXT[w.access_status]}</Btn>
            ) : null}
            <ol data-testid="workorder-access-history" className="space-y-1 text-sm text-[#59636B]">
              {w.access_history.map((h, i) => <li key={i}>{h.from} to {h.to}, by {h.by_name} at {fmt(h.at)}</li>)}
            </ol>
            <p className="text-xs text-[#59636B]">This is a planning record only. Access must be arranged by a person; it does not authorize work.</p>
          </Card>
        </div>
      </div>
    </div>
  );
}
