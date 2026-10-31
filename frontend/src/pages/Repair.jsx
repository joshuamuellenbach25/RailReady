// Phase 15 office view: repairs, their findings, report/forms, invoice, delivery status and blockers. Reuses rr/ui.
import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { API, api, errText, getToken } from "@/lib/api";
import { Badge, Banner, Btn, Card, Field, H2, Loading, Msg, PageHead } from "@/components/rr/ui";

function Blockers({ list, testid }) {
  if (!list || !list.length) return null;
  return (
    <ul data-testid={testid} className="mt-2 list-disc pl-5 text-sm text-[#9A3412]">
      {list.map((b) => <li key={b}>{b}</li>)}
    </ul>
  );
}

export function Repairs() {
  const [rows, setRows] = useState(null);
  const [msg, setMsg] = useState(null);
  useEffect(() => { api("/repairs").then(setRows).catch((e) => setMsg({ tone: "error", text: errText(e) })); }, []);
  if (!rows) return msg ? <Banner testid="repairs-error" tone="error" text={msg.text} /> : <Loading />;
  return (
    <div>
      <PageHead kicker="Repairs" title="Authorized repairs" subtitle="Repairs opened on the phone. No proposal or acceptance step." />
      <Card testid="repairs-list">
        {rows.length ? rows.map((r) => (
          <Link key={r.uuid} to={`/office/repairs/${r.visit_id}`} data-testid={`repair-row-${r.visit_id}`} className="flex justify-between border-b border-[#D9DEE2] py-2">
            <span>{r.operator_name || "Not set"} - PO {r.po || "Not set"} - {r.railroad || "Not set"} MP {r.milepost || "Not set"}</span>
            <Badge label={r.completion ? "Finished" : "Open"} tone={r.completion ? "success" : "neutral"} />
          </Link>
        )) : <p className="text-sm text-[#59636B]">No repairs yet.</p>}
      </Card>
    </div>
  );
}

// Contract-level documents (progress-payment operators): contract record, progress packets, final closeout.
function ContractPanel({ cid, op, po, onChange }) {
  const [c, setC] = useState(null);
  const [pk, setPk] = useState({});
  const [f, setF] = useState({ contractor_legal_name: "", contract_no: "", contract_date: "", retainage_pct: "" });
  const [per, setPer] = useState({ period_start: "", period_end: "" });
  const [pe, setPe] = useState("");
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    if (!cid) return;
    const x = await api(`/operator-contracts/${cid}`);
    setC(x);
    const det = {};
    for (const p of x.packets) det[p.uuid] = await api(`/operator-contracts/${cid}/packets/${p.uuid}`);
    setPk(det);
  }, [cid]);
  useEffect(() => { load().catch((e) => setMsg({ tone: "error", text: errText(e) })); }, [load]);
  const run = async (path, body, ok) => {
    setBusy(true);
    try { await api(path, { method: "POST", body: body || {} }); setMsg({ tone: "success", text: ok }); }
    catch (e) { setMsg({ tone: "error", text: e?.detail?.blockers ? e.detail.blockers.join(" ") : errText(e) }); }
    finally { setBusy(false); await load().catch(() => {}); onChange(); }
  };
  const auth = `?auth=${encodeURIComponent(getToken() || "")}`;
  return (
    <Card testid="contract-panel">
      <H2>Contract PO {po || "Not set"}</H2>
      <Msg msg={msg} testid="contract-message" />
      {c ? <p className="text-sm" data-testid="contract-fields">Contractor: {c.contract.contractor_legal_name || "Not set"}. Project/Spec. #: {c.contract.contract_no || "Not set"}. Contract date: {c.contract.contract_date || "Not set"}. Retainage: {c.contract.retainage_pct ? `${c.contract.retainage_pct}%` : "Not set"}.</p> : null}
      <div className="mt-2 flex flex-wrap items-end gap-2">
        {["contractor_legal_name", "contract_no", "contract_date", "retainage_pct"].map((k) => <Field key={k} id={`ctr-${k}`} testid={`contract-${k}-input`} label={{ contractor_legal_name: "Contractor legal name", contract_no: "Project/Spec. #", contract_date: "Contract date (YYYY-MM-DD)", retainage_pct: "Retainage %" }[k]} value={f[k]} onChange={(v) => setF({ ...f, [k]: v })} />)}
        <Btn small kind="secondary" testid="contract-save-button" disabled={busy || !po} onClick={() => run("/operator-contracts", { operator_id: op.uuid, po, ...Object.fromEntries(Object.entries(f).map(([k, v]) => [k, v || (c ? c.contract[k] : null) || null])) }, "Contract saved")}>Save contract</Btn>
      </div>
      {c ? (
        <>
          <p className="mt-4 text-sm font-semibold">Progress-payment packets</p>
          {c.packets.map((p) => { const x = pk[p.uuid]; return x ? (
            <div key={p.uuid} className="mt-2 border-t border-[#D9DEE2] pt-2" data-testid={`contract-packet-${p.seq}`}>
              <p className="text-sm">{p.period_start} to {p.period_end} <Badge label={x.status} tone={x.status === "Issued" ? "success" : "neutral"} /> Amount due ${x.computed.amount_due} (value to date ${x.computed.value_todate}, retainage ${x.computed.retainage}, previous ${x.computed.previous_payments})
                {" "}<a className="underline" data-testid={`contract-packet-${p.seq}-print`} href={`${API}/operator-contracts/${cid}/packets/${p.uuid}/print${auth}`} target="_blank" rel="noreferrer">Open</a></p>
              <Blockers list={x.status === "Issued" ? x.submit_blockers : x.blockers} testid={`contract-packet-${p.seq}-blockers`} />
              {x.submission ? <p className="text-sm" data-testid={`contract-packet-${p.seq}-submission`}>{x.submission.status === "Sent" ? `Sent${x.delivery_label ? ` - ${x.delivery_label}` : ""}` : x.submission.status}</p> : null}
              {x.status !== "Issued" ? <div className="mt-1 flex flex-wrap items-end gap-2">
                <Field id={`pe-${p.seq}`} testid={`contract-packet-${p.seq}-engineer-input`} label="Project Engineer (name as given)" value={pe} onChange={setPe} />
                <Btn small kind="secondary" testid={`contract-packet-${p.seq}-engineer-button`} disabled={busy || !pe} onClick={() => run(`/operator-contracts/${cid}/packets/${p.uuid}/engineer-approval`, { engineer_name: pe }, "Project Engineer approval recorded")}>Record Project Engineer approval</Btn>
                <Btn small testid={`contract-packet-${p.seq}-issue-button`} disabled={busy || x.blockers.length > 0} onClick={() => run(`/operator-contracts/${cid}/packets/${p.uuid}/issue`, null, "Packet issued")}>Issue packet</Btn>
              </div> : !x.submission || x.submission.status === "Failed" ? <Btn small testid={`contract-packet-${p.seq}-submit-button`} disabled={busy || x.submit_blockers.length > 0} onClick={() => {
                const email = op.channel === "email";
                if (email && !window.confirm(`Send this progress-payment packet by email to ${op.recipient_label || "Not set"} <${op.destination}>? This emails ${op.name}.`)) return;
                run(`/operator-contracts/${cid}/packets/${p.uuid}/submit`, email ? { confirm_recipient: op.destination } : null, "Submitted");
              }}>Submit packet</Btn> : null}
            </div>) : null; })}
          <div className="mt-2 flex flex-wrap items-end gap-2">
            <Field id="per-s" testid="contract-period-start-input" label="Period start (YYYY-MM-DD)" value={per.period_start} onChange={(v) => setPer({ ...per, period_start: v })} />
            <Field id="per-e" testid="contract-period-end-input" label="Period end (YYYY-MM-DD)" value={per.period_end} onChange={(v) => setPer({ ...per, period_end: v })} />
            <Btn small kind="secondary" testid="contract-new-packet-button" disabled={busy || !per.period_start || !per.period_end} onClick={() => run(`/operator-contracts/${cid}/packets`, per, "Packet drafted")}>New packet</Btn>
          </div>
          <p className="mt-4 text-sm font-semibold">Final closeout (contract level)</p>
          <ul className="mt-1 text-sm" data-testid="contract-closeout-items">
            {c.closeout.items.map((i) => <li key={i.key}><label><input type="checkbox" data-testid={`contract-closeout-${i.key}`} checked={i.received} disabled={busy}
              onChange={(e) => run(`/operator-contracts/${cid}/closeout/${i.key}`, { received: e.target.checked }, "Saved")} /> {i.label}</label>{i.received ? ` - received, recorded by ${i.recorded_by_name || "Not set"} ${i.recorded_at}` : ""}</li>)}
          </ul>
          {c.general_release_available ? <p className="mt-1 text-sm"><a className="underline" data-testid="contract-general-release-link" href={`${API}/operator-contracts/${cid}/general-release.pdf${auth}`} target="_blank" rel="noreferrer">General Release form (PDF, signatures blank)</a></p> : null}
          <Blockers list={c.closeout.general_release_notes} testid="contract-general-release-notes" />
          <Blockers list={c.closeout.final_acceptance_blockers} testid="contract-final-blockers" />
          <p className="text-sm" data-testid="contract-final-status">{c.closeout.final_acceptance ? `Final acceptance recorded: ${c.closeout.final_acceptance.engineer_name} ${c.closeout.final_acceptance.recorded_at}` : "Final acceptance not recorded."}</p>
        </>
      ) : <p className="mt-2 text-sm" data-testid="contract-missing">No contract record for this PO yet. An admin saves it above.</p>}
    </Card>
  );
}

export default function RepairDetail() {
  const { id } = useParams();
  const [d, setD] = useState(null);
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);
  const [sig, setSig] = useState({ role: "", name: "" });
  const [fv, setFv] = useState({ key: "", value: "" });
  const [summ, setSumm] = useState(null);
  const load = useCallback(async () => {
    try { setD(await api(`/repairs/${id}`)); } catch (e) { setMsg({ tone: "error", text: errText(e) }); }
  }, [id]);
  useEffect(() => { load(); }, [load]);
  const act = async (path, body, ok) => {
    setBusy(true);
    try { await api(path, { method: "POST", body: body || {} }); setMsg({ tone: "success", text: ok }); }
    catch (e) { setMsg({ tone: "error", text: e?.detail?.blockers ? e.detail.blockers.join(" ") : errText(e) }); }
    finally { setBusy(false); load(); }
  };
  if (!d) return msg ? <Banner testid="repair-error" tone="error" text={msg.text} /> : <Loading />;
  const r = d.repair;
  const auth = `?auth=${encodeURIComponent(getToken() || "")}`;
  const sub = d.submission;
  return (
    <div className="space-y-4">
      <PageHead kicker="Repair" title={`${r.operator_name || "Not set"} - PO ${r.po || "Not set"}`}
        subtitle={`${r.railroad || "Not set"} - Track ${r.track || "Not set"} - MP ${r.milepost || "Not set"}`} />
      <Msg msg={msg} testid="repair-message" />
      {d.documents_model ? (
        <Card testid="repair-documents-model">
          <H2>Documents</H2>
          {d.documents_model.map((x) => (
            <div key={x.kind} className="mt-3" data-testid={`repair-doc-${x.kind}`}>
              <p className="text-sm font-semibold">{x.title} <Badge label={x.status} tone={x.status.includes("Issued") || x.status === "Accepted" ? "success" : "neutral"} /></p>
              {x.blockers.length ? <Blockers list={x.blockers} testid={`repair-doc-${x.kind}-blockers`} /> : <p className="text-sm" data-testid={`repair-doc-${x.kind}-ok`}>No blockers.</p>}
            </div>
          ))}
        </Card>
      ) : null}
      {d.documents_model ? <ContractPanel cid={d.documents_model[1].contract_id} op={d.operator} po={r.po} onChange={load} /> : null}
      <Card testid="repair-completion">
        <H2>Completion</H2>
        <p data-testid="repair-completion-text">{r.completion ? `Finished ${r.completion.completion_date || "Not set"} - confirmed by ${r.completion.confirmed_by_name || "Not set"} at ${r.completion.received_at}` : "Not finished yet"}</p>
        <table className="mt-2 w-full text-sm"><tbody>
          {r.work.map((w) => <tr key={w.uuid} className="border-b border-[#D9DEE2]"><td className="py-1">{w.kind}</td><td>{w.description}</td><td className="text-right">{w.quantity} {w.unit}</td></tr>)}
        </tbody></table>
        <p className="mt-2 text-sm" data-testid="repair-approval">{r.approved_work ? `Work approved ${r.approved_work.approved_at}` : "Work not approved yet"}</p>
        {r.completion && !r.approved_work ? <Btn small testid="repair-approve-button" disabled={busy} onClick={() => act(`/repairs/${id}/approve-work`, null, "Work approved")}>Approve actual work</Btn> : null}
      </Card>
      <Card testid="repair-findings">
        <H2>Findings</H2>
        <p className="text-sm">{d.findings.evidence.photo} photo(s), {d.findings.evidence.video} video(s){d.findings.evidence.not_verified ? `, ${d.findings.evidence.not_verified} still sending` : ""}</p>
        <ul className="mt-2 list-disc pl-5 text-sm">
          {d.findings.manual.map((o) => <li key={o.uuid} data-testid={`repair-manual-${o.uuid}`}>Crew: {o.text || o.label || o.kind}</li>)}
          {d.findings.ai.map((c) => <li key={c.uuid} data-testid={`repair-ai-${c.uuid}`}>Photo check: {c.category} ({c.review_state}). Not billed.</li>)}
        </ul>
      </Card>
      <Card testid="repair-documents">
        <H2>Report and forms <Badge label={d.document_status} tone={d.document_status === "Issued" ? "success" : "neutral"} /></H2>
        <p className="mt-2 text-sm"><a data-testid="repair-report-link" className="underline" href={`${API}/repairs/${id}/report${auth}`} target="_blank" rel="noreferrer">Open report</a>
          {(d.operator?.forms || []).map((f) => <span key={f.uuid}> - <a className="underline" data-testid={`repair-form-${f.uuid}`} href={`${API}/repairs/${id}/forms/${f.uuid}${auth}`} target="_blank" rel="noreferrer">{f.name}</a></span>)}</p>
        <Blockers list={d.blockers.report} testid="repair-report-blockers" />
        <div className="mt-3" data-testid="repair-summary">
          <p className="text-sm font-semibold">Summary {r.summary?.status === "draft" ? <span data-testid="repair-summary-draft-label">- Draft. Review before issuing.</span> : r.summary?.status === "approved" ? "- Approved" : ""}</p>
          <textarea data-testid="repair-summary-text" className="mt-1 w-full border border-[#D9DEE2] p-2 text-sm" rows={4} value={summ ?? r.summary?.text ?? ""} onChange={(e) => setSumm(e.target.value)} />
          <div className="mt-1 flex gap-2">
            <Btn small kind="secondary" testid="repair-summary-draft-button" disabled={busy || !r.completion} onClick={async () => {
              setBusy(true);
              try { await api(`/repairs/${id}/summary/draft`, { method: "POST", body: {} }); setSumm(null); setMsg({ tone: "success", text: "Draft ready. Review before issuing." }); }
              catch { setMsg({ tone: "error", text: "Summary not drafted. Write it yourself or try again." }); }
              finally { setBusy(false); load(); }
            }}>Draft summary</Btn>
            <Btn small kind="secondary" testid="repair-summary-approve-button" disabled={busy || !(summ ?? r.summary?.text)} onClick={async () => {
              setBusy(true);
              try { await api(`/repairs/${id}/summary`, { method: "PUT", body: { text: summ ?? r.summary.text, approve: true } }); setSumm(null); setMsg({ tone: "success", text: "Summary approved" }); }
              catch (e) { setMsg({ tone: "error", text: errText(e) }); }
              finally { setBusy(false); load(); }
            }}>Approve summary</Btn>
          </div>
        </div>
        <div className="mt-2 flex flex-wrap items-end gap-2">
          <Field id="fv-key" testid="repair-form-value-key" label="Form value (source)" value={fv.key} onChange={(v) => setFv({ ...fv, key: v })} />
          <Field id="fv-val" testid="repair-form-value-value" label="Value" value={fv.value} onChange={(v) => setFv({ ...fv, value: v })} />
          <Btn small kind="secondary" testid="repair-form-value-button" disabled={busy || !fv.key || !fv.value} onClick={async () => {
            setBusy(true);
            try { await api(`/repairs/${id}/form-values`, { method: "PUT", body: { values: { [fv.key]: fv.value } } }); setFv({ key: "", value: "" }); setMsg({ tone: "success", text: "Form value saved" }); }
            catch (e) { setMsg({ tone: "error", text: errText(e) }); }
            finally { setBusy(false); load(); }
          }}>Save form value</Btn>
        </div>
        <div className="mt-2 flex flex-wrap items-end gap-2">
          <Field id="sig-role" testid="repair-signoff-role" label="Sign-off role" value={sig.role} onChange={(v) => setSig({ ...sig, role: v })} />
          <Field id="sig-name" testid="repair-signoff-name" label="Name as signed" value={sig.name} onChange={(v) => setSig({ ...sig, name: v })} />
          <Btn small kind="secondary" testid="repair-signoff-button" disabled={busy || !sig.role || !sig.name} onClick={() => act(`/repairs/${id}/signoffs`, sig, "Sign-off recorded")}>Record sign-off</Btn>
          <Btn small testid="repair-issue-button" disabled={busy || d.blockers.report.length > 0} onClick={() => act(`/repairs/${id}/issue`, null, "Documents issued")}>Issue documents</Btn>
        </div>
      </Card>
      <Card testid="repair-invoice">
        <H2>Invoice <Badge label={d.invoice_status || "Not started"} tone={d.invoice_status === "Sent" ? "success" : d.invoice_status === "Failed" ? "error" : "neutral"} /></H2>
        {d.invoice ? (
          <table className="mt-2 w-full text-sm"><tbody>
            {d.invoice.lines.map((l) => <tr key={l.work_item_id} className="border-b border-[#D9DEE2]"><td className="py-1">{l.description}</td><td>{l.quantity} {l.unit} x ${l.unit_cost}</td><td className="text-right">${l.line_total}</td></tr>)}
            <tr><td className="pt-2 font-semibold" data-testid="repair-invoice-total">Total ${d.invoice.totals.total} USD - PO {d.invoice.po}</td></tr>
          </tbody></table>
        ) : null}
        {sub ? <p className="mt-2 text-sm" data-testid="repair-submission">{sub.status === "Sent" ? `Sent${d.delivery_label ? ` - ${d.delivery_label}` : ""}. Acknowledged ${sub.acknowledged_at} (${sub.ack.ack_id})` : sub.status === "Failed" ? `Not sent: ${sub.error}` : "Sending..."}</p> : null}
        {d.operator?.channel_label === "Test delivery" ? <p className="mt-1 text-sm" data-testid="repair-test-delivery-label">Channel: Test delivery. Nothing leaves this server.</p> : null}
        {d.operator ? <p className="mt-2 text-sm" data-testid="repair-operator-config">Operator: {d.operator.name}. Contact: {d.operator.contact_name}. Rates: {d.operator.rates_source}.
          {d.operator.channel === "email" ? ` Invoice goes by email to ${d.operator.recipient_label || "Not set"} <${d.operator.destination || "Not set"}>.` : ""}</p> : null}
        {d.blockers.invoice.some((b) => b.startsWith("Confirm these")) && r.po ? <Btn small kind="secondary" testid="repair-confirm-rates-button" disabled={busy}
          onClick={() => window.confirm(`Confirm that ${d.operator.rates_source} apply to PO ${r.po}?`) && act(`/operators/${d.operator.uuid}/rate-confirmations`, { po: r.po }, "Rates confirmed for this PO")}>Confirm rates for PO {r.po}</Btn> : null}
        <Blockers list={d.blockers.submit} testid="repair-invoice-blockers" />
        <div className="mt-2 flex gap-2">
          {d.invoice_status !== "Sent" ? <Btn small kind="secondary" testid="repair-invoice-build" disabled={busy || d.blockers.invoice.length > 0} onClick={() => act(`/repairs/${id}/invoice`, null, "Invoice ready")}>Build invoice</Btn> : null}
          {d.invoice && d.invoice_status !== "Sent" ? <Btn small testid="repair-invoice-submit" disabled={busy || d.blockers.submit.length > 0} onClick={() => {
            const email = d.operator?.channel === "email";
            if (email && !window.confirm(`Send this invoice by email to ${d.operator.recipient_label || "Not set"} <${d.operator.destination}>? This emails ${d.operator.name}.`)) return;
            act(`/invoices/${d.invoice.uuid}/submit`, email ? { confirm_recipient: d.operator.destination } : null, "Submitted");
          }}>Submit invoice</Btn> : null}
        </div>
      </Card>
    </div>
  );
}
