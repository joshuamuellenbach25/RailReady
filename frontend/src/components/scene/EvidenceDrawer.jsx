import { useState } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, Camera, Check, ExternalLink, Pencil, X } from "lucide-react";
import { cropUrl } from "@/lib/scene";
import { CATS, catLabel } from "@/components/rr/CandidateCard";
import { useAuth } from "@/lib/auth";
import { PlaceChip, StateChip, WS } from "./ws";
import MoveAnchor from "./MoveAnchor";

const Row = ({ label, children, testid }) => (
  <div className={`border-b ${WS.line} py-2`}>
    <dt className="text-[12px] font-semibold uppercase tracking-wide text-[#A9B0B6]">{label}</dt>
    <dd data-testid={testid} className="mt-0.5 break-words text-[14px] text-[#E6E8EA]">{children ?? <span className="text-[#A9B0B6]">Not recorded</span>}</dd>
  </div>
);
const fmt = (s) => (s ? new Date(s).toLocaleString() : null);
// Fields may be plain text or structured objects (e.g. human_review = {decision, actor, actor_role, at, note}).
function txt(v) {
  if (v == null || v === "") return null;
  if (typeof v !== "object") return String(v);
  if (v.decision || v.actor) return `${v.decision || "Reviewed"} by ${v.actor || "-"}${v.actor_role ? ` (${v.actor_role})` : ""}${v.at ? ` at ${fmt(v.at)}` : ""}${v.note ? ` - "${v.note}"` : ""}`;
  return Object.entries(v).filter(([, x]) => x != null && x !== "").map(([k, x]) => `${k.replace(/_/g, " ")}: ${typeof x === "object" ? JSON.stringify(x) : x}`).join(" - ");
}

function Decide({ item, canDecide, onDecide }) {
  const [corr, setCorr] = useState(null);
  if (!canDecide) return null;
  return (
    <div className="space-y-2 py-2">
      <div className="grid grid-cols-2 gap-1.5">
        <button type="button" data-testid="drawer-confirm" className={WS.btn} onClick={() => onDecide(item, "confirm")}><Check aria-hidden className="h-4 w-4" />Yes</button>
        <button type="button" data-testid="drawer-correct" className={WS.btn} onClick={() => setCorr({ category: item.category || CATS[0], note: "" })}><Pencil aria-hidden className="h-4 w-4" />Not quite</button>
        <button type="button" data-testid="drawer-dismiss" className={WS.btn} onClick={() => onDecide(item, "dismiss")}><X aria-hidden className="h-4 w-4" />No</button>
        <button type="button" data-testid="drawer-closer" className={WS.btn} onClick={() => onDecide(item, "request_closer_photo")}><Camera aria-hidden className="h-4 w-4" />Closer photo</button>
      </div>
      {corr ? (
        <form data-testid="drawer-correct-form" className="space-y-1.5" onSubmit={async (e) => { e.preventDefault(); if (await onDecide(item, "correct", { corrected_category: corr.category, note: corr.note || undefined })) setCorr(null); }}>
          <label htmlFor="drw-cat" className="block text-[12px] font-semibold text-[#A9B0B6]">Category</label>
          <select id="drw-cat" data-testid="drawer-correct-category" value={corr.category} onChange={(e) => setCorr({ ...corr, category: e.target.value })} className="rr-focus h-9 w-full rounded-[3px] border border-[#4A5157] bg-[#111315] px-2 text-[13px] text-[#E6E8EA]">
            {CATS.map((c) => <option key={c} value={c}>{catLabel(c)}</option>)}
          </select>
          <label htmlFor="drw-note" className="block text-[12px] font-semibold text-[#A9B0B6]">What you see</label>
          <textarea id="drw-note" data-testid="drawer-correct-note" rows={2} value={corr.note} onChange={(e) => setCorr({ ...corr, note: e.target.value })} className="rr-focus w-full rounded-[3px] border border-[#4A5157] bg-[#111315] p-2 text-[13px] text-[#E6E8EA]" />
          <div className="flex gap-1.5">
            <button type="submit" data-testid="drawer-correct-save" className={WS.btn}>Save correction</button>
            <button type="button" data-testid="drawer-correct-cancel" className={WS.btn} onClick={() => setCorr(null)}>Cancel</button>
          </div>
        </form>
      ) : null}
    </div>
  );
}

// Right evidence drawer. Every evidence aspect is its own field (REQ-149); nothing is merged into a single "status".
export default function EvidenceDrawer({ item, visitId, originalHref, canDecide, onDecide, msg, onClose, move }) {
  const { isAdmin } = useAuth();
  if (!item) return <aside data-testid="scene-drawer" className={`${WS.panel} p-3 text-[14px] ${WS.sub}`}>Select a finding in the inventory, a marker or a region box to see its evidence.</aside>;
  const a = item.anchor;
  const pv = item.provenance || {};
  const link = "rr-focus inline-flex min-h-[36px] [@media(pointer:coarse)]:min-h-[44px] items-center gap-1 text-[13px] font-semibold text-[#9FD3CF] underline-offset-2 hover:underline";
  return (
    <aside data-testid="scene-drawer" aria-label="Evidence" className={`${WS.panel} min-h-0 overflow-y-auto px-3 pb-3`}>
      <div className={`sticky top-0 z-[1] flex items-start justify-between gap-2 border-b ${WS.line} ${WS.panel} py-2`}>
        <div className="min-w-0">
          <h2 data-testid="drawer-name" className="break-words text-[15px] font-bold leading-tight text-[#E6E8EA]">{item.n}. {item.label}</h2>
          <p data-testid="drawer-id" className="font-mono text-[12px] text-[#A9B0B6]">{item.short_id} - {item.item_id}</p>
        </div>
        {onClose ? <button type="button" data-testid="drawer-close" aria-label="Close evidence" className={WS.btn} onClick={onClose}><X aria-hidden className="h-4 w-4" /></button> : null}
      </div>
      <div className="flex flex-wrap gap-1 pt-2">
        <StateChip state={item.review_state} testid="drawer-review-state" />
        <PlaceChip placed={item.placed} testid="drawer-place-state" />
      </div>
      {msg ? <p data-testid="drawer-message" role="status" className={`mt-2 rounded-[3px] border px-2 py-1 text-[13px] ${msg.tone === "error" || msg.tone === "warning" ? "border-[#B35A55] text-[#F3C4C0]" : "border-[#4A5157] text-[#E6E8EA]"}`}>{msg.text}</p> : null}
      <Decide item={item} canDecide={canDecide && item.review_state === "Pending"} onDecide={onDecide} />
      {move ? <MoveAnchor item={item} {...move} /> : null}
      {Array.isArray(item.region) ? <img data-testid="drawer-crop" src={cropUrl(item.item_id)} alt={`Crop of region ${item.n}`} className="mt-1 max-h-40 w-full border border-[#2E3337] bg-black object-contain" /> : null}
      <a href={originalHref} target="_blank" rel="noopener noreferrer" data-testid="drawer-original-link" className={link}>Open original photo <ExternalLink aria-hidden className="h-3.5 w-3.5" /></a>
      <dl className="mt-1">
        <Row label="Visible evidence" testid="drawer-visible-evidence">{txt(item.visible_reason)}</Row>
        <Row label="Source time" testid="drawer-source-time">{fmt(item.source_time)}</Row>
        {isAdmin ? <Row label="Technical details" testid="drawer-provenance">{pv.model_id ? `${pv.model_id} - ${pv.prompt_version || "-"} - ${pv.run_id || "-"}` : "-"}</Row> : null}
        {isAdmin ? <Row label="Identity source" testid="drawer-identity-source">{txt(item.identity_source)}</Row> : null}
        <Row label="Visible condition" testid="drawer-visible-condition">{txt(item.visible_condition)}</Row>
        <Row label="Human review" testid="drawer-human-review">{txt(item.human_review) || item.review_state}</Row>
        <Row label="Location basis" testid="drawer-location-basis">
          {item.placed && a ? `${a.location_basis} - ${a.placement}${a.uncertainty != null ? ` - uncertainty ${typeof a.uncertainty === "object" ? JSON.stringify(a.uncertainty) : a.uncertainty}` : ""} - v${a.version} by ${a.actor || "-"} ${fmt(a.at) || ""}` : `Unplaced - ${item.unplacedReason}`}
        </Row>
      </dl>
      <div className="flex flex-col pt-2">
        <Link to={`/office/visits/${visitId}?e=${item.evidence_id}`} data-testid="drawer-finding-link" className={link}>Open in inspection <ArrowRight aria-hidden className="h-3.5 w-3.5" /></Link>
        {item.engagement_id || item.scope_item_id ? <Link to={`/office/visits/${visitId}/estimate`} data-testid="drawer-estimate-link" className={link}>Open estimate <ArrowRight aria-hidden className="h-3.5 w-3.5" /></Link> : <span className={`text-[12px] ${WS.sub}`}>Not linked to an estimate line yet.</span>}
      </div>
    </aside>
  );
}
