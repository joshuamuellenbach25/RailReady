import { useCallback, useEffect, useState } from "react";
import { Check, ShieldAlert, Scale } from "lucide-react";
import { ApiError, api, errText } from "@/lib/api";
import { Badge, Banner, Btn, Card, H2, Loading, Mono, Msg } from "./ui";

// Proposed fields with source excerpts (web port of /app/mobile/app/visit/[id]/fields.tsx).
export default function FieldsPanel({ visitId, locked, refreshKey, onChanged }) {
  const [data, setData] = useState(null);
  const [msg, setMsg] = useState(null);
  const [armed, setArmed] = useState(null);
  const load = useCallback(async () => {
    try {
      setData(await api(`/visits/${visitId}/proposals`));
    } catch (e) {
      setMsg({ tone: "error", text: errText(e) });
    }
  }, [visitId]);
  useEffect(() => { load(); }, [load, refreshKey]);

  async function accept(field, p) {
    setMsg(null);
    try {
      await api(`/visits/${visitId}/fields/${field}`, { body: { expected_revision: data.visit_revision, action: "accept_proposal", proposal_id: p.uuid, source: "review" } });
      setMsg({ tone: "success", text: `${field.replace(/_/g, " ")} set to ${p.value}` });
      setArmed(null);
      onChanged?.();
    } catch (e) {
      if (e instanceof ApiError && e.status === 409 && e.detail?.server) {
        const srv = e.detail.server.answers?.[field];
        setMsg({ tone: "warning", text: `${e.detail.message} Your entry: "${p.value}". Saved value: "${srv ? `${srv.state}${srv.value != null ? ": " + srv.value : ""}` : "unchanged"}".` });
      } else setMsg({ tone: "error", text: errText(e) });
    }
    load();
  }

  if (!data) return <Card testid="fields-panel">{msg ? <Banner tone="error" text={msg.text} testid="fields-load-error" /> : <Loading text="Loading..." />}</Card>;
  return (
    <Card testid="fields-panel" className="space-y-4">
      <div>
        <H2>Details from voice notes and typed notes</H2>
        <p className="text-[15px] text-[#59636B]">Review the details extracted from voice notes and typed notes.</p>
      </div>
      <Msg msg={msg} testid="fields-message" />
      {data.runs.filter((r) => r.status === "Failed").map((r) => (
        <Banner key={r.uuid} testid={`fields-run-failed-${r.uuid}`} tone="error" text="We couldn't pick details out of one of the notes. You can still fill them in yourself." />
      ))}
      {data.fields.map((f) => (
        <div key={f.field} data-testid={`field-card-${f.field}`} className="space-y-2 border-t-2 border-[#D9DEE2] pt-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="font-semibold">{f.label}</h3>
            <Badge testid={`field-state-${f.field}`} label={f.state} />
          </div>
          {f.answer?.state === "Provided" ? <p data-testid={`field-value-${f.field}`} className="font-bold">Value: {String(f.answer.value)}</p> : null}
          {f.answer?.reason ? <p className="text-sm text-[#59636B]">Reason: {f.answer.reason}</p> : null}
          {f.review_reason ? <Banner testid={`field-review-reason-${f.field}`} tone="warning" text={f.review_reason} /> : null}
          {f.discrepancy ? <Banner testid={`field-discrepancy-${f.field}`} tone="warning" icon={Scale} text={`Discrepancy: sources disagree (${f.distinct_values.join(" vs ")}). Choose one or answer in Departure check.`} /> : null}
          {!f.proposals.length && f.state === "Missing required" ? <p className="text-sm text-[#59636B]">Not mentioned in any note yet.</p> : null}
          {f.proposals.map((p) => (
            <div key={p.uuid} data-testid={`proposal-${p.uuid}`} className="space-y-1 border-l border-[#C5CCD2] pl-3">
              <p className="font-semibold">Suggested: {String(p.value)}</p>
              <blockquote data-testid={`proposal-excerpt-${p.uuid}`} className="text-sm italic text-[#202428]">"{p.excerpt}"</blockquote>
              {p.untrusted ? <Badge testid={`proposal-untrusted-${p.uuid}`} label="From untrusted text" icon={ShieldAlert} tone="warning" /> : null}
              <p className="text-[13px] text-[#59636B]">From a {p.source_kind === "audio" ? "voice note" : "typed note"}</p>
              <Mono label="Technical details" className="block">{p.model_id}</Mono>
              {!locked && f.answer?.proposal_id !== p.uuid ? (
                <Btn small kind={p.untrusted && armed === p.uuid ? "danger" : "secondary"} icon={Check} testid={`proposal-accept-${p.uuid}`}
                  onClick={() => (p.untrusted && armed !== p.uuid ? setArmed(p.uuid) : accept(f.field, p))}>
                  {p.untrusted ? (armed === p.uuid ? "Confirm: use untrusted value" : "Review untrusted value") : "Use this value"}
                </Btn>
              ) : f.answer?.proposal_id === p.uuid ? <Badge label="Accepted" icon={Check} tone="success" /> : null}
            </div>
          ))}
        </div>
      ))}
    </Card>
  );
}
