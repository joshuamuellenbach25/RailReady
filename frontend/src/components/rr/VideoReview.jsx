import { useEffect, useRef, useState } from "react";
import { Clock, Film, RefreshCw } from "lucide-react";
import { api, errText, isAbort, withAuth } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { reviewCandidate, validRegion } from "@/lib/photoReview";
import useReview from "@/lib/useReview";
import CandidateCard from "./CandidateCard";
import ResultStatus from "./ResultStatus";
import { Banner, Btn, Msg } from "./ui";

/** m:ss.s */
export const fmtT = (s) => {
  if (typeof s !== "number" || !Number.isFinite(s)) return "-";
  const m = Math.floor(s / 60);
  const r = s - m * 60;
  return `${m}:${r < 10 ? "0" : ""}${r.toFixed(1)}`;
};

/** Authenticated playback: <video src> with ?auth= (contract section 4). The browser sends Range requests itself. */
function Player({ ev, vref, info }) {
  const [state, setState] = useState("loading");
  const [n, setN] = useState(0);
  return (
    <div className="space-y-2">
      <div className="relative overflow-hidden rounded-xl bg-[#22272B]">
        <video key={n} ref={vref} data-testid="video-player" controls preload="metadata" playsInline src={withAuth(`/evidence/${ev.uuid}/content`)}
          onLoadedMetadata={() => setState("ready")} onError={() => setState("failed")} className="aspect-video w-full bg-black object-contain" />
        {state === "loading" ? <p data-testid="video-loading" role="status" className="absolute inset-x-0 bottom-0 bg-[#22272B]/85 px-3 py-2 text-[14px] text-white">Loading video...</p> : null}
      </div>
      {state === "failed" ? (
        <Banner tone="error" testid="video-error" text="Video did not load. Try again.">
          <Btn small kind="secondary" icon={RefreshCw} testid="video-retry-button" onClick={() => { setState("loading"); setN((x) => x + 1); }}>Retry</Btn>
        </Banner>
      ) : null}
      {info?.video ? (
        <p data-testid="video-info" className="text-[13px] text-[#59636B]">
          Length {fmtT(info.video.duration_s)}{info.video.width ? `, ${info.video.width} x ${info.video.height}` : ""}
        </p>
      ) : null}
    </div>
  );
}

/** The exact analysed frame with its box drawn as percentages of that image (never over the playing video). */
function Frame({ ev, item }) {
  const f = item.raw.frame;
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [f?.id]);
  const box = item.raw.scope !== "image" && validRegion(item.raw.region) ? item.raw.region : null;
  if (!f?.id) return <p data-testid="video-frame-missing" className="text-[14px] text-[#59636B]">The analysed frame image is not stored for this older check. Use the video at {fmtT(item.raw.timestamp_s)}.</p>;
  return (
    <figure data-testid="video-frame" className="space-y-1">
      <div className="relative inline-block w-full overflow-hidden rounded-lg border border-[#D9DEE2] bg-[#22272B]">
        {failed ? <p data-testid="video-frame-error" className="p-4 text-[14px] text-white">The frame image did not load. The video and this finding are unchanged.</p> : (
          <img data-testid="video-frame-image" src={withAuth(`/evidence/${ev.uuid}/frames/${encodeURIComponent(f.id)}`)} alt={`Analysed frame at ${fmtT(f.t)}`}
            onError={() => setFailed(true)} className="block h-auto w-full" />
        )}
        {box && !failed ? (
          <span data-testid="video-frame-box" aria-hidden className="pointer-events-none absolute border-2 border-[#FF3B30] shadow-[0_0_0_1px_rgba(0,0,0,0.6)]"
            style={{ left: `${box[0] * 100}%`, top: `${box[1] * 100}%`, width: `${box[2] * 100}%`, height: `${box[3] * 100}%` }} />
        ) : null}
      </div>
      <figcaption className="text-[13px] text-[#59636B]">Analysed frame at {fmtT(f.t)}</figcaption>
    </figure>
  );
}

function FindingRow({ item, n, on, onPick, onSeek }) {
  const ts = item.raw.timestamps_s?.length ? item.raw.timestamps_s : [item.raw.timestamp_s];
  return (
    <li className={`flex flex-wrap items-center gap-2 px-4 py-2 ${on ? "bg-[#FBEDEC]" : ""}`}>
      <button type="button" data-testid={`video-finding-${n}`} data-candidate-id={item.uuid} aria-pressed={on} onClick={() => onPick(item)}
        className="rr-focus flex min-h-[44px] flex-1 items-center gap-2 text-left text-[15px]">
        <span aria-hidden className="flex h-6 min-w-6 items-center justify-center rounded-full bg-[#E6E8EA] text-[13px] font-semibold">{n}</span>
        <span className="font-mono text-[14px]">{fmtT(item.raw.timestamp_s)}</span>
        <span className="flex-1">{item.label}</span>
        <span className="text-[13px] text-[#59636B]">{item.pending ? "To check" : item.review_state}</span>
      </button>
      {ts.length > 1 ? (
        <span data-testid={`video-finding-${n}-times`} className="flex flex-wrap items-center gap-1 text-[13px] text-[#59636B]">
          <Clock aria-hidden className="h-3.5 w-3.5" />Seen at
          {ts.map((t) => <button key={t} type="button" data-testid={`video-finding-${n}-time-${t}`} onClick={() => onSeek(t)} className="rr-focus min-h-[32px] rounded border border-[#D9DEE2] bg-white px-1.5 font-mono hover:bg-[#F3F4F4]">{fmtT(t)}</button>)}
        </span>
      ) : null}
    </li>
  );
}

/** Video evidence: player, timestamped findings (seek on click), analysed frame with box, Confirm / Correct / Dismiss. */
export default function VideoReview({ ev, locked, onChanged }) {
  const { isAdmin } = useAuth();
  const { d, err, load } = useReview(ev);
  const vref = useRef(null);
  const [sel, setSel] = useState(null);
  const [msg, setMsg] = useState(null);
  const [info, setInfo] = useState(null);
  useEffect(() => {
    const c = new AbortController();
    setSel(null);
    api(`/evidence/${ev.uuid}/content-info`, { signal: c.signal }).then(setInfo).catch((e) => { if (!isAbort(e)) setInfo(null); });
    return () => c.abort();
  }, [ev.uuid]);

  const seek = (t) => {
    const v = vref.current;
    if (!v || typeof t !== "number") return;
    v.currentTime = t; // same finding again seeks again: always set, never skipped
    v.dataset.lastSeek = String(t);
  };
  const items = d?.items || [];
  const cur = items.find((i) => i.uuid === sel) || null;
  const n = (i) => items.indexOf(i) + 1;

  async function decide(item, action, extra) {
    setMsg(null);
    try {
      await reviewCandidate(item, action, extra);
      setMsg({ tone: "success", text: "Saved." });
      await load();
      onChanged?.();
      return true;
    } catch (e) {
      setMsg({ tone: "warning", text: e?.status === 409 ? "Someone answered this a moment ago. Showing the latest answer." : `Your answer was not saved. ${errText(e)}` });
      load();
      return false;
    }
  }

  return (
    <div data-testid="video-review" className="grid gap-4">
      <div className="space-y-3">
        <Player ev={ev} vref={vref} info={info} />
        <ResultStatus d={d} />
        {err ? <Banner tone="error" testid="video-review-error" text={`The results for this video did not load. The video is saved. ${err}`}><Btn small kind="secondary" icon={RefreshCw} testid="video-review-reload" onClick={load}>Try again</Btn></Banner> : null}
        {items.length ? (
          <ul data-testid="video-findings" aria-label="Findings in this video" className="divide-y divide-[#E3E7EA] rounded-xl border border-[#E3E7EA] bg-white">
            {items.map((i) => <FindingRow key={i.uuid} item={i} n={n(i)} on={i.uuid === sel} onSeek={seek} onPick={(x) => { setSel(x.uuid); seek(x.raw.timestamp_s); }} />)}
          </ul>
        ) : null}
      </div>
      <div className="space-y-3">
        <Msg msg={msg} testid="video-message" />
        {cur ? (
          <>
            <Frame ev={ev} item={cur} />
            <CandidateCard item={cur} n={n(cur)} locked={locked} active onActive={() => {}} onDecide={decide} isAdmin={isAdmin} taxonomyId={d?.taxonomyId}
              unboxedText="Applies to the whole frame. No exact spot marked." error={msg && msg.tone !== "success" ? <Banner tone={msg.tone} text={msg.text} testid="video-decision-error" /> : null} />
          </>
        ) : items.length ? (
          <p data-testid="video-pick-hint" className="flex items-center gap-2 text-[15px] text-[#59636B]"><Film aria-hidden className="h-4 w-4" />Select a finding to jump to that moment and see the analysed frame.</p>
        ) : null}
      </div>
    </div>
  );
}
