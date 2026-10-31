import { Ban, Check, ShieldCheck, ShieldOff } from "lucide-react";
import { scopeLabel } from "@/lib/settings";
import { Badge, Mono, fmt } from "../ui";

export function DefaultBadge({ p, testid }) {
  return p.default === "allow"
    ? <Badge testid={testid} label="Photo analysis: On for all sites" icon={ShieldCheck} tone="success" />
    : <Badge testid={testid} label="Photo analysis: Off unless turned on below" icon={ShieldOff} tone="warning" />;
}

/** Read-only view of one policy version's rules. */
export default function PolicyRules({ p, nameOf, prefix = "policy" }) {
  return (
    <div className="space-y-4 text-sm">
      <div>
        <h3 className="font-medium">Off for these sites, customers or inspections ({p.restrictions.length})</h3>
        {p.restrictions.length ? (
          <ul className="mt-1 space-y-1">
            {p.restrictions.map((r, i) => (
              <li key={`${r.scope}-${r.id}`} data-testid={`${prefix}-restriction-${i}`} className="flex flex-wrap items-start gap-x-2">
                <Ban aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[#8F1D1B]" />
                <span><b className="font-medium">{scopeLabel(r.scope)}:</b> {nameOf(r.scope, r.id) || "A record you no longer have access to"}{r.reason ? ` - ${r.reason}` : ""}</span>
                <Mono label="Record details">{r.scope} {r.id}</Mono>
              </li>
            ))}
          </ul>
        ) : <p className="mt-1 text-[#59636B]">None. The setting above applies everywhere.</p>}
      </div>
      <div>
        <h3 className="font-medium">Single photos or notes set by hand ({p.evidence_exceptions.length})</h3>
        {p.evidence_exceptions.length ? (
          <ul className="mt-1 space-y-1">
            {p.evidence_exceptions.map((e, i) => (
              <li key={e.evidence_id} data-testid={`${prefix}-exception-${i}`} className="flex flex-wrap items-start gap-x-2">
                {e.allow ? <Check aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[#1E5B32]" /> : <Ban aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[#8F1D1B]" />}
                <span>{e.allow ? "On" : "Off"} for one photo or note{e.reason ? ` - ${e.reason}` : ""}</span>
                <Mono label="Evidence details">evidence {e.evidence_id}</Mono>
              </li>
            ))}
          </ul>
        ) : <p className="mt-1 text-[#59636B]">None.</p>}
      </div>
      <p className="text-[13px] text-[#59636B]">Saved {fmt(p.created_at)}{p.note && !/legacy|migration|processing|version/i.test(p.note) ? ` - "${p.note}"` : ""}</p>
      <Mono label="Version details">policy {p.uuid} - v{p.version} - by {p.created_by}{p.previous_version ? ` - replaces v${p.previous_version}` : ""}</Mono>
    </div>
  );
}
