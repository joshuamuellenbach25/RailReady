import { useEffect, useState } from "react";
import { ShieldCheck, ShieldOff } from "lucide-react";
import { api } from "@/lib/api";
import { BLOCKED_MSG, basisLabel } from "@/lib/settings";
import { Badge, Banner, Mono } from "./ui";

/** Effective processing policy for an inspection, as resolved by the server (REQ-206/210). */
export default function PolicyStatus({ visitId, refreshKey }) {
  const [p, setP] = useState(null);
  useEffect(() => { api(`/visits/${visitId}/processing-policy`).then(setP).catch(() => setP(null)); }, [visitId, refreshKey]);
  if (!p) return null;
  if (p.allowed) {
    return (
      <div data-testid="review-policy-status" className="flex flex-wrap items-center gap-2">
        <Badge testid="review-policy-badge" label="Photo analysis is on" icon={ShieldCheck} tone="success" />
        <Mono label="Technical details">policy v{p.policy_version} - {p.basis}</Mono>
      </div>
    );
  }
  // `allowed: false` is the server's effective policy for this inspection (not a provider failure); its fixed message is shown in our wording.
  return (
    <Banner testid="review-policy-status" tone="warning" icon={ShieldOff} text={BLOCKED_MSG}>
      <p data-testid="review-policy-basis">{basisLabel(p.basis)}{p.detail ? ` - ${p.detail}` : ""}. You can still review everything yourself.</p>
      <Mono label="Technical details">policy v{p.policy_version} - {p.basis}</Mono>
    </Banner>
  );
}
