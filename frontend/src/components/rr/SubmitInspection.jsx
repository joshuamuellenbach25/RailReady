import { useRef, useState } from "react";
import { Send } from "lucide-react";
import { api, errText } from "@/lib/api";
import { Banner, Btn } from "./ui";

const OPEN = ["Missing required", "Needs review"];
// Plain names for the submission details (server labels carry units in brackets).
export const DETAIL_LABEL = {
  inspected_quantity: "Ties inspected",
  repair_quantity: "Ties to replace",
  tie_specification: "Tie specification",
  material_responsibility: "Who supplies the ties",
  work_location: "Work location and limits",
};

/**
 * Submit a draft inspection (same endpoint as the field app's "Finish inspection"). Before sending, the server's own
 * readiness is read: items still arriving and required details still open block the submit with a plain list.
 * The server still enforces role, revision and upload checks.
 */
export default function SubmitInspection({ visitId, onSubmitted }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [open, setOpen] = useState([]);
  const flight = useRef(false);

  async function submit() {
    if (flight.current) return;
    flight.current = true;
    setBusy(true);
    setErr(null);
    setOpen([]);
    try {
      const r = await api(`/visits/${visitId}/readiness`);
      const missing = r.uploads?.missing || 0;
      const still = (r.fields || []).filter((f) => OPEN.includes(f.state));
      if (missing) setErr(`${missing} item${missing === 1 ? " is" : "s are"} still arriving from the field app. Wait for them to finish, then submit.`);
      else if (still.length) {
        setErr("Complete the departure checklist in the field app before submitting. These details are still missing or need review:");
        setOpen(still);
      } else {
        await api(`/visits/${visitId}/submit`, { body: { expected_revision: r.visit_revision, device_unsynced: 0 } });
        onSubmitted?.();
      }
    } catch (e) {
      setErr(`The inspection was not submitted. ${errText(e)}`);
    } finally {
      setBusy(false);
      flight.current = false;
    }
  }

  return (
    <div data-testid="review-submit" className="space-y-2">
      <Btn testid="review-submit-button" icon={Send} loading={busy} onClick={submit}>Submit inspection</Btn>
      {err ? (
        <Banner testid="review-submit-error" tone="error" text={err}>
          {open.length ? (
            <>
              <ul data-testid="review-submit-missing" className="list-disc space-y-0.5 pl-4">
                {open.map((f) => <li key={f.field} data-testid={`review-submit-missing-${f.field}`}>{DETAIL_LABEL[f.field] || f.label}</li>)}
              </ul>
              <p>For details not covered by the checklist, choose suggested values from your voice or typed notes.</p>
            </>
          ) : null}
        </Banner>
      ) : null}
    </div>
  );
}
