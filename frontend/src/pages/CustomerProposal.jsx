import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { Check, Clock, Handshake, MessageSquare, Printer, Send, TrainFront, Truck } from "lucide-react";
import { ApiError, BACKEND, api, errText, apiWrite, newId } from "@/lib/api";
import { Details, Badge, Banner, Btn, Card, Field, H2, Loading } from "@/components/rr/ui";

const TERM = { payment_terms: "Payment", schedule_wording: "Schedule", assumptions: "What we assumed", exclusions: "Not included", validity: "Offer valid", acceptance_wording: "Accepting this proposal" };

// Customer bearer-link page. Uses only the public proposal endpoints - no internal costs or notes.
function DecisionForm({ token, mode, onDone, onCancel }) {
  const [f, setF] = useState({ name: "", email: "", comment: "", agree: false });
  const [fieldErr, setFieldErr] = useState({});
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const inFlight = useRef(false); // synchronous guard: a double click/Enter must not send a second decision (JRN-131)
  // Change requests carry a stable client operation id: one id per set of details, reused on every retry of
  // those details. Server: same id + same details -> replayed:true; same id + different details -> 409 operation_id_reused.
  const op = useRef({ id: null, sig: null });
  function operationId() {
    const sig = JSON.stringify([f.name.trim(), f.email.trim().toLowerCase(), f.comment.trim()]);
    if (op.current.sig !== sig) op.current = { id: newId(), sig };
    return op.current.id;
  }
  async function submit(e) {
    e.preventDefault();
    if (inFlight.current) return;
    inFlight.current = true;
    setFieldErr({});
    setErr(null);
    setBusy(true);
    try {
      const r = mode === "accept"
        ? await apiWrite(`/public/proposals/${token}/accept`, { body: { name: f.name, email: f.email, agree: f.agree } },
          async () => { const p2 = await api(`/public/proposals/${token}`); return p2?.accepted?.work_order_number ? p2.accepted : undefined; }) // reconcile, never re-send
        : await apiWrite(`/public/proposals/${token}/changes`, { body: { name: f.name, email: f.email, comment: f.comment, request_key: operationId() } });
      if (mode === "accept") onDone(`Accepted. Work order ${r.work_order_number} created for planning.`);
      else onDone(r?.replayed ? "Request already sent." : "Request sent. Your contractor will reply with an updated proposal.");
    } catch (x) {
      if (x instanceof ApiError && x.detail?.errors) setFieldErr(x.detail.errors);
      else if (x instanceof ApiError && x.status === 409 && x.detail?.code === "operation_id_reused") {
        op.current = { id: null, sig: null }; // the next send is a new request
        setErr("A request with different details was already sent from this page. Your text is still here. Send again to make it a new request.");
      } else setErr(errText(x)); // inputs kept
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }
  const fe = (k) => (fieldErr[k] ? <p data-testid={`public-${k}-error`} role="alert" className="text-sm font-bold text-red-700">{fieldErr[k]}</p> : null);
  return (
    <form data-testid="public-decision-form" onSubmit={submit} className="space-y-4 rounded-lg border border-[#B32624] bg-white p-5">
      <H2>{mode === "accept" ? "Accept this proposal" : "Request changes"}</H2>
      <Field id="pub-name" testid="public-name-input" label="Your name" value={f.name} onChange={(x) => setF({ ...f, name: x })} autoComplete="name" />
      {fe("name")}
      <Field id="pub-email" testid="public-email-input" label="Email" type="email" value={f.email} onChange={(x) => setF({ ...f, email: x })} autoComplete="email" />
      {fe("email")}
      {mode === "accept" ? (
        <label htmlFor="pub-agree" className="flex min-h-[48px] cursor-pointer items-start gap-3 rounded-md border border-[#C5CCD2] bg-[#F3F4F4] p-3">
          <input id="pub-agree" data-testid="public-agree-checkbox" type="checkbox" checked={f.agree} onChange={(e) => setF({ ...f, agree: e.target.checked })} className="mt-1 h-5 w-5 accent-[#B32624]" />
          <span className="font-bold">I have read and accept the agreement above</span>
        </label>
      ) : (
        <Field id="pub-comment" testid="public-comment-input" label="What should change?" multiline value={f.comment} onChange={(x) => setF({ ...f, comment: x })} />
      )}
      {fe(mode === "accept" ? "agree" : "comment")}
      {err ? <Banner testid="public-form-error" tone="error" text={err} /> : null}
      <div className="flex flex-wrap gap-2">
        <Btn type="submit" testid="public-submit-button" icon={Send} loading={busy}>{mode === "accept" ? "Confirm acceptance" : "Send change request"}</Btn>
        <Btn kind="secondary" testid="public-cancel-button" onClick={onCancel}>Cancel</Btn>
      </div>
    </form>
  );
}

export default function CustomerProposal() {
  const { token } = useParams();
  const [p, setP] = useState(null);
  const [err, setErr] = useState(null);
  const [mode, setMode] = useState(null);
  const [done, setDone] = useState(null);
  const load = useCallback(() => api(`/public/proposals/${token}`).then(setP).catch((e) => setErr(errText(e))), [token]);
  useEffect(() => { load(); }, [load]);

  const shell = (children) => (
    <div className="min-h-screen bg-[#F3F4F4]">
      <header className="border-b border-[#B32624] bg-[#22272B] text-white">
        <div className="mx-auto flex max-w-5xl items-center gap-3 px-4 py-3">
          <TrainFront aria-hidden className="h-6 w-6 text-[#B32624]" />
          <span className="font-semibold">{p?.contractor?.legal_identity || "Proposal"}</span>
        </div>
      </header>
      <main className="mx-auto max-w-5xl space-y-5 px-4 py-6">{children}</main>
    </div>
  );
  if (!p) return shell(err ? <Banner testid="public-error" tone="error" text={err} /> : <Loading />);

  return shell(
    <div data-testid="public-proposal-page" className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3 border-b-2 border-[#D9DEE2] pb-4">
        <div>
          <p className="text-[14px] font-medium text-[#59636B]">Your proposal</p>
          <h1 data-testid="public-title" className="text-3xl font-semibold tracking-tight">{p.proposal_number}</h1>
          <p className="mt-1 text-[#59636B]">{p.customer_site}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          {p.status === "Accepted" || p.status === "Changes requested" ? <Badge testid="public-status" label={p.status === "Accepted" ? "You accepted this" : "You asked for changes"} /> : <Badge testid="public-status" label="Waiting for your answer" icon={Clock} tone="neutral" />}
        </div>
      </div>
      {done ? <Banner testid="public-done-message" tone="success" text={done} /> : null}
      {err ? <Banner testid="public-error" tone="error" text={err} /> : null}
      {!p.can_decide && p.status !== "Accepted" ? <Banner testid="public-readonly" tone="warning" text={p.status === "Superseded" ? "There is a newer proposal for this job. Use the latest link from your contractor." : p.status === "Expired" ? "This proposal has expired. Ask your contractor for an updated one." : "This proposal can no longer be accepted. Contact your contractor."} /> : null}
      <Card testid="public-expiry-card">
        <p data-testid="public-expiry" className="text-[15px]">This price is good until <b className="font-semibold">{p.expiry?.local ? new Date(p.expiry.local).toLocaleString([], { dateStyle: "long", timeStyle: "short" }) : "-"}</b>.</p>
      </Card>
      {p.ties_supplied_by_customer ? <Banner testid="public-customer-ties" tone="info" icon={Truck} text="You are supplying the ties for this job." /> : null}
      <div className="grid gap-5 lg:grid-cols-2">
        <Card testid="public-scope">
          <H2>What we'll do</H2>
          <ul className="mt-2 list-disc space-y-1 pl-5">{p.findings.map((x) => <li key={x}>{x}</li>)}</ul>
          {p.not_inspected.map((n) => <p key={n.area} className="mt-2 text-sm text-[#59636B]">Not checked on site: {n.area} - {n.reason}. Nothing is charged for this.</p>)}
        </Card>
        <Card testid="public-price">
          <H2>Price</H2>
          <table className="mt-2 w-full text-sm">
            <thead><tr className="border-b-2 border-[#D9DEE2] text-left"><th className="py-1">Item</th><th className="py-1 text-right">Qty</th><th className="py-1 text-right">Amount</th></tr></thead>
            <tbody>
              {p.lines.map((l, i) => (
                <tr key={`${l.description}-${i}`} className="border-b border-[#D9DEE2]"><td className="py-1.5 pr-2">{l.description}</td><td className="py-1.5 text-right font-mono">{l.quantity} {l.unit}</td><td className="py-1.5 text-right font-mono">${l.line_total}</td></tr>
              ))}
            </tbody>
          </table>
          <p className="mt-3 text-sm">Subtotal ${p.totals.subtotal}, tax ({p.totals.tax_rate}%) ${p.totals.tax}</p>
          <p data-testid="public-total" className="text-2xl font-semibold">Total ${p.totals.total}</p>
          <p className="mt-1 text-xs text-[#59636B]">{p.tax_treatment_text}</p>
        </Card>
      </div>
      {p.photos.length ? (
        <div data-testid="public-photos" className="grid gap-3 sm:grid-cols-2">
          {p.photos.map((ph, i) => (
            <figure key={ph.url} className="overflow-hidden rounded-lg border border-[#D9DEE2] bg-[#22272B]">
              <img data-testid={`public-photo-${i + 1}`} src={`${BACKEND}${ph.url}`} alt={ph.caption || `Site photo ${i + 1}`} className="h-64 w-full object-contain" />
              {ph.caption ? <figcaption className="bg-white p-2 text-sm">{ph.caption}</figcaption> : null}
            </figure>
          ))}
        </div>
      ) : null}
      <Card testid="public-agreement">
        <H2>Agreement</H2>
        <div data-raw="1" data-testid="public-agreement-text" className="mt-3 whitespace-pre-wrap text-sm leading-relaxed">{p.agreement.document_text}</div>
        <Details className="mt-3">Template v{p.agreement.template_version} - agreement hash {p.agreement.document_hash}</Details>
      </Card>
      {p.terms ? (
        <Card testid="public-terms">
          <H2>Terms</H2>
          <dl className="mt-2 grid gap-2 text-sm sm:grid-cols-2">
            {Object.entries(p.terms).filter(([k, v]) => v && TERM[k]).map(([k, v]) => (
              <div key={k}><dt className="font-medium">{TERM[k]}</dt><dd data-raw="1" className="whitespace-pre-wrap text-[#202428]">{String(v)}</dd></div>
            ))}
          </dl>
        </Card>
      ) : null}
      <div className="flex flex-wrap gap-3">
        <Btn kind="secondary" icon={Printer} testid="public-print-button" onClick={() => window.print()}>Print</Btn>
        {p.can_decide && !done && !mode ? (
          <>
            <Btn testid="public-accept-button" icon={Handshake} onClick={() => setMode("accept")}>Accept</Btn>
            <Btn kind="secondary" testid="public-changes-button" icon={MessageSquare} onClick={() => setMode("changes")}>Request changes</Btn>
          </>
        ) : null}
      </div>
      {mode ? <DecisionForm token={token} mode={mode} onCancel={() => setMode(null)} onDone={(m) => { setDone(m); setMode(null); load(); }} /> : null}
    </div>,
  );
}
