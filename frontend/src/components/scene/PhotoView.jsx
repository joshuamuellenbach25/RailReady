import { useRef, useState } from "react";
import { validRegion } from "@/lib/photoReview";
import useAspectFit from "./useAspectFit";

const clamp01 = (v) => Math.min(1, Math.max(0, Number(v) || 0));
const Dot = ({ p, testid, cls }) => (
  <span data-testid={testid} aria-hidden className={`pointer-events-none absolute h-4 w-4 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 ${cls}`} style={{ left: `${p[0] * 100}%`, top: `${p[1] * 100}%` }} />
);

/**
 * Original photo in a centred letterbox viewport (same fit as the 3D canvas). Region boxes use normalized [x,y,w,h];
 * anchor points sit at left + u-viewW. In placing mode a click maps back to [u, v] relative to the panel rect;
 * clicks in the letterbox bars are rejected.
 */
export default function PhotoView({ src, fallbackSrc, ow, oh, items, selectedId, showMarkers, onSelect, placing, onPlace }) {
  const panelRef = useRef(null);
  const [nat, setNat] = useState(null);
  const [failed, setFailed] = useState(false);
  const [useFallback, setUseFallback] = useState(false); // signed URL expired/refused -> authenticated media route once
  const w0 = ow || nat?.[0];
  const h0 = oh || nat?.[1];
  const fit = useAspectFit(panelRef, w0, h0);
  const mismatch = nat && w0 && Math.abs(nat[0] / nat[1] - w0 / h0) > 0.02;

  function place(e) {
    const r = panelRef.current.getBoundingClientRect();
    const u = (e.clientX - r.left - fit.left) / fit.width;
    const v = (e.clientY - r.top - fit.top) / fit.height;
    if (u < 0 || u > 1 || v < 0 || v > 1) return; // letterbox
    const q = (n) => Math.round(n * 100000) / 100000;
    onPlace([q(u), q(v)]);
  }

  const sel = placing ? items.find((i) => i.item_id === placing.item_id) : null;
  return (
    <div ref={panelRef} data-testid="scene-original-photo" className="absolute inset-0 min-h-0 min-w-0 overflow-hidden bg-[#0D0F10]" onClick={placing && fit ? place : undefined}>
      {failed ? <p className="p-4 text-[14px] text-[#E6E8EA]">Original photo could not be loaded.</p> : null}
      {!failed ? (
        <div data-testid="scene-photo-viewport" className={`absolute ${placing ? "cursor-crosshair outline outline-2 outline-dashed outline-[#F1D9A6]" : ""}`}
          style={fit ? { left: fit.left, top: fit.top, width: fit.width, height: fit.height } : { inset: 0 }} data-view-w={fit?.width} data-view-h={fit?.height}>
          <img src={useFallback ? fallbackSrc : src} alt="Original site photo" draggable={false} onError={() => (!useFallback && fallbackSrc && fallbackSrc !== src ? setUseFallback(true) : setFailed(true))}
            onLoad={(e) => setNat([e.currentTarget.naturalWidth, e.currentTarget.naturalHeight])}
            className={`block h-full w-full select-none ${fit ? "object-fill" : "object-contain"}`} />
          {fit && showMarkers && !placing
            ? items.map((i) => {
                if (!validRegion(i.region)) return null; // image-level result: listed, no box
                const [x, y, w, h] = i.region.map(clamp01);
                const on = i.item_id === selectedId;
                return (
                  <button key={i.item_id} type="button" data-testid={`scene-box-${i.item_id}`} aria-label={`Region ${i.n}: ${i.label}`} aria-pressed={on} onClick={() => onSelect(i.item_id)}
                    className={`rr-focus absolute border-2 ${on ? "z-10 border-[#3F8F8C] bg-[#3F8F8C]/20 outline outline-2 outline-white" : i.review_state === "Dismissed" ? "border-dashed border-[#C9CED3]" : "border-[#E6E8EA]"}`}
                    style={{ left: `${x * 100}%`, top: `${y * 100}%`, width: `${Math.min(w, 1 - x) * 100}%`, height: `${Math.min(h, 1 - y) * 100}%` }}>
                    <span className={`absolute left-0 top-0 px-1 text-[12px] font-bold ${on ? "bg-[#3F8F8C] text-white" : "bg-[#E6E8EA] text-[#111315]"}`}>{i.n}</span>
                  </button>
                );
              })
            : null}
          {fit && showMarkers && !placing
            ? items.filter((i) => i.placed && i.anchor?.u != null).map((i) => (
                <span key={i.item_id} data-testid={`scene-photo-pin-${i.item_id}`} aria-hidden data-x={(i.anchor.u * fit.width).toFixed(2)} data-y={(i.anchor.v * fit.height).toFixed(2)}
                  className={`pointer-events-none absolute h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-[#111315] ${i.item_id === selectedId ? "z-10 bg-[#3F8F8C]" : "bg-[#E6E8EA]"}`}
                  style={{ left: `${i.anchor.u * 100}%`, top: `${i.anchor.v * 100}%` }} />
              ))
            : null}
          {fit && placing ? (
            <>
              {sel?.anchor?.u != null ? <Dot p={[sel.anchor.u, sel.anchor.v]} testid="scene-place-current" cls="border-[#E6E8EA] bg-[#111315]/60" /> : null}
              {placing.point ? <Dot p={placing.point} testid="scene-place-new" cls="border-[#111315] bg-[#F1D9A6]" /> : null}
              <p data-testid="scene-place-layer" className="pointer-events-none absolute bottom-0 left-0 bg-[#111315] px-2 py-1 text-[12px] font-semibold text-[#F1D9A6]">Placing marker. Click the new spot.</p>
            </>
          ) : null}
        </div>
      ) : null}
      {mismatch ? <p data-testid="scene-orientation-warning" className="absolute bottom-2 left-2 bg-[#111315] px-2 py-1 text-[12px] text-[#F1D9A6]">The displayed photo shape differs from the recorded size. Boxes may be offset.</p> : null}
    </div>
  );
}
