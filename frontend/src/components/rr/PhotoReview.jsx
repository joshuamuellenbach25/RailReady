import { useState } from "react";
import { RefreshCw, ScanSearch } from "lucide-react";
import { errText, mediaUrl } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { analyzePhoto, reviewCandidate } from "@/lib/photoReview";
import useReview from "@/lib/useReview";
import PhotoOverlay from "./PhotoOverlay";
import CandidateCard from "./CandidateCard";
import ResultStatus from "./ResultStatus";
import { Banner, Btn, Msg } from "./ui";

/** Photo + result together, then one open question at a time (Confirm / Correct / Dismiss). All findings, uncertain included. */
export default function PhotoReview({ ev, locked, onChanged }) {
  const { isAdmin } = useAuth();
  const [starting, setStarting] = useState(false);
  const { d, err, load } = useReview(ev, { forcePoll: starting });
  const [msg, setMsg] = useState(null);
  const [active, setActive] = useState(null);
  const [current, setCurrent] = useState(null);

  async function start(again) {
    setStarting(true);
    setMsg(null);
    try {
      await analyzePhoto(ev.uuid, again);
      await load();
    } catch (e) {
      setMsg({ tone: "error", text: `The photo check did not start. The photo is saved. ${errText(e)}` });
    }
    setStarting(false);
  }
  async function decide(item, action, extra) {
    setMsg(null);
    try {
      await reviewCandidate(item, action, extra);
      setMsg({ tone: "success", text: "Saved." });
      setCurrent(null);
      await load();
      onChanged?.();
      return true;
    } catch (e) {
      setMsg({ tone: "warning", text: e?.status === 409 ? "Someone answered this a moment ago. Showing the latest answer." : `Your answer was not saved. ${errText(e)}` });
      load();
      return false;
    }
  }

  const items = d?.items || [];
  const cur = items.find((i) => i.uuid === current) || items.find((i) => i.pending) || null;
  const n = (i) => items.indexOf(i) + 1;
  const errBanner = msg && msg.tone !== "success" ? <Banner tone={msg.tone} text={msg.text} testid="evidence-modal-error" /> : null;

  return (
    <div data-testid="photo-review" className="space-y-4">
      <PhotoOverlay src={mediaUrl(ev.uuid)} alt={ev.caption || "Site photo"} active={active || cur?.uuid} onActive={setActive} onPick={setCurrent}
        candidates={items.filter((i) => i.boxed).map((i) => ({ uuid: i.uuid, n: n(i), region: i.region, review_state: i.review_state, review: i.admission === "review", label: i.label }))} />
      <ResultStatus d={d} checkingText={starting ? "Checking photo" : null} />
      {err ? <Banner tone="error" testid="photo-review-error" text={`The result for this photo did not load. The photo is saved. ${err}`}><Btn small kind="secondary" icon={RefreshCw} testid="photo-review-reload" onClick={load}>Try again</Btn></Banner> : null}
      <Msg msg={msg} testid="evidence-message" />
      {d && !d.state && !d.runs.length && !starting && !locked ? (
        <Btn icon={ScanSearch} testid="photo-check-button" onClick={() => start(false)}>Check this photo</Btn>
      ) : null}
      {d?.state === "failed" && !starting && !locked ? <Btn kind="secondary" icon={RefreshCw} testid="photo-check-again-button" onClick={() => start(true)}>Try again</Btn> : null}
      {cur ? <CandidateCard item={cur} n={n(cur)} locked={locked} active onActive={setActive} onDecide={decide} error={errBanner} isAdmin={isAdmin} taxonomyId={d?.taxonomyId} /> : null}
      {items.length > 1 || (items.length && !cur) ? (
        <ul data-testid="photo-items" className="divide-y divide-[#E3E7EA] rounded-xl border border-[#E3E7EA] bg-white">
          {items.filter((i) => i !== cur).map((i) => (
            <li key={i.uuid}>
              <button type="button" data-testid={`photo-item-${n(i)}`} data-candidate-id={i.uuid} onClick={() => setCurrent(i.uuid)} onMouseEnter={() => setActive(i.uuid)}
                className="rr-focus flex min-h-[44px] w-full items-center gap-2 px-4 py-2 text-left text-[15px] hover:bg-[#F6F7F7]">
                <span aria-hidden className="flex h-6 min-w-6 items-center justify-center rounded-full bg-[#E6E8EA] text-[13px] font-semibold">{n(i)}</span>
                <span className="flex-1">{i.label}{i.boxed ? "" : " (whole photo)"}</span>
                {i.kind === "rail" ? <span className="text-[12px] text-[#59636B]">Rail surface</span> : null}
                <span className="text-[13px] text-[#59636B]">{i.pending ? "To check" : i.review_state}</span>
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
