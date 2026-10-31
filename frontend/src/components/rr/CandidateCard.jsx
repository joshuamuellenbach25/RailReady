import { useEffect, useState } from "react";
import { Camera, Check, Pencil, Save, X } from "lucide-react";
import { Badge, Btn, Field, Modal, Mono, fmt } from "./ui";
import { LEGACY_CATS, LEGACY_LABEL, RAIL_CATS, RAIL_LABEL, components } from "@/lib/photoReview";

const ROLE = { foreman: "the foreman", estimator: "the office", admin: "an admin" };
export const CATS = LEGACY_CATS;
export const catLabel = (k) => LEGACY_LABEL[k] || k;

function CorrectSheet({ item, taxonomyId, onClose, onSave, error }) {
  const p7 = item.kind === "p7";
  const cats = item.kind === "rail" ? RAIL_CATS.map((k) => ({ code: k, name: RAIL_LABEL[k].replace(/^Possible /, "") }))
    : LEGACY_CATS.map((k) => ({ code: k, name: LEGACY_LABEL[k].replace(/^Possible /, "") }));
  const [list, setList] = useState(p7 ? [] : cats);
  const [pick, setPick] = useState(p7 ? item.raw.human_identity?.code || "" : (cats.some((c) => c.code === item.raw.category) ? item.raw.category : cats[0].code));
  const [note, setNote] = useState("");
  useEffect(() => { if (p7) components(taxonomyId).then(setList); }, [p7, taxonomyId]);
  return (
    <Modal open onClose={onClose} title="What do you see?" testid="candidate-correct-sheet">
      <label htmlFor="corr-pick" className="mb-1 block text-sm font-medium">Closest match</label>
      <select id="corr-pick" data-testid="correct-component-select" value={pick} onChange={(e) => setPick(e.target.value)}
        className="rr-focus mb-3 min-h-[44px] w-full rounded-lg border border-[#D2D8DD] bg-white px-3 text-[15px]">
        {p7 ? <option value="">Choose a part</option> : null}
        {list.map((l) => <option key={l.code} value={l.code}>{l.name}</option>)}
      </select>
      <Field id="corr-note" testid="correct-note-input" label="In your words (optional)" multiline value={note} onChange={setNote} placeholder="For example: only the plate is cracked, the tie looks fine" />
      {error}
      <Btn testid="correct-save-button" icon={Save} disabled={!pick} onClick={() => onSave(p7 ? { code: pick, note } : { category: pick, note })}>Save</Btn>
    </Modal>
  );
}

/** One question: photo result in plain words, then Confirm / Correct / Dismiss. Scores only in admin Details. */
export default function CandidateCard({ item, n, locked, active, onActive, onDecide, error, isAdmin, taxonomyId, unboxedText = "No spot marked. Look at the whole photo." }) {
  const [correct, setCorrect] = useState(false);
  const p7 = item.source === "p7";
  return (
    <article data-testid={`candidate-card-${n}`} data-candidate-id={item.uuid} onMouseEnter={() => onActive(item.uuid)} onFocus={() => onActive(item.uuid)}
      className={`rr-rise space-y-3 rounded-xl border bg-white p-5 transition-[border-color,box-shadow] duration-200 ${active ? "border-[#B32624] shadow-[0_4px_16px_rgba(179,38,36,0.10)]" : "border-[#E3E7EA]"}`}>
      <h3 className="flex items-start gap-2.5 text-[16px] font-semibold leading-snug">
        <span aria-hidden className="mt-0.5 flex h-6 min-w-6 items-center justify-center rounded-full bg-[#B32624] px-1 text-[13px] text-white">{n}</span>
        <span data-testid={`candidate-question-${n}`}>{item.label}{item.pending ? ". Does this look right?" : ""}</span>
      </h3>
      {!item.pending ? <Badge testid={`candidate-state-${n}`} label={item.review_state} /> : null}
      {item.admission === "review" ? <p className="text-[14px] text-[#7A4A00]">Not sure about this one. Check it against the photo.</p> : null}
      {item.reason ? <p className="text-[15px] text-[#3C444B]"><span className="font-medium text-[#202428]">What stood out: </span><span data-raw="1">{item.reason}</span></p> : null}
      {!item.boxed ? <p data-testid={`candidate-unlocalized-note-${n}`} className="text-[14px] text-[#59636B]">{unboxedText}</p> : null}
      {item.decisions.length ? (
        <ul className="space-y-0.5 text-[13px] text-[#59636B]">
          {item.decisions.map((d) => <li key={d.uuid}>Answered by {ROLE[d.actor_role] || "a team member"}, {fmt(d.at)}{d.note ? `: "${d.note}"` : ""}</li>)}
        </ul>
      ) : null}
      {!locked && item.pending ? (
        <div className="space-y-2">
          <div className="grid grid-cols-3 gap-2">
            <Btn small icon={Check} testid={`candidate-confirm-${n}`} onClick={() => onDecide(item, "confirm")}>Confirm</Btn>
            <Btn small kind="secondary" icon={Pencil} testid={`candidate-correct-${n}`} onClick={() => setCorrect(true)}>Correct</Btn>
            <Btn small kind="secondary" icon={X} testid={`candidate-dismiss-${n}`} onClick={() => onDecide(item, "dismiss")}>Dismiss</Btn>
          </div>
          <Btn small kind="ghost" icon={Camera} testid={`candidate-closer-${n}`} onClick={() => onDecide(item, "request_closer_photo")}>Ask for a closer photo</Btn>
        </div>
      ) : null}
      {isAdmin && p7 ? (
        <Mono label="Details" className="block">
          {JSON.stringify({ identity: item.raw.identity, concerns: item.raw.concerns, detector: item.raw.detector, box_state: item.raw.box_state, model: item.raw.model_id, prompt: item.raw.prompt_version })}
        </Mono>
      ) : null}
      {correct ? <CorrectSheet item={item} taxonomyId={taxonomyId} error={error} onClose={() => setCorrect(false)} onSave={async (x) => { if (await onDecide(item, "correct", x)) setCorrect(false); }} /> : null}
    </article>
  );
}
