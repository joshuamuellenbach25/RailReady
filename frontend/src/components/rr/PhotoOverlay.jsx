import { useState } from "react";
import { ImageOff } from "lucide-react";

const clamp = (n) => Math.min(1, Math.max(0, Number(n) || 0));

/**
 * Photo with highlighted candidate regions. Regions are normalized [x, y, w, h] of the original image.
 * The wrapper shrink-wraps the *displayed* image (inline-block around a block img with max sizes), so percentage
 * boxes always map to the rendered pixels regardless of aspect ratio, letterboxing or window resize.
 */
export default function PhotoOverlay({ src, candidates = [], active, onActive, onPick, alt = "Site photo" }) {
  const [loaded, setLoaded] = useState(false);
  const [failed, setFailed] = useState(false);
  return (
    <div data-testid="photo-overlay" className="flex min-h-[220px] items-center justify-center rounded-lg bg-[#22272B] p-2">
      {failed ? (
        <p data-testid="photo-load-error" className="flex items-center gap-2 p-8 text-gray-200"><ImageOff aria-hidden className="h-5 w-5" /> Photo could not be loaded.</p>
      ) : (
        <div className="relative inline-block max-w-full align-top">
          <img src={src} alt={alt} onLoad={() => setLoaded(true)} onError={() => setFailed(true)} className="block h-auto max-h-[68vh] w-auto max-w-full select-none" draggable={false} />
          {loaded
            ? candidates.map((c, i) => {
                if (!Array.isArray(c.region)) return null;
                const [x, y, w, h] = c.region.map(clamp);
                const dismissed = c.review_state === "Dismissed";
                const on = active === c.uuid;
                const num = c.n ?? i + 1;
                // If an earlier box starts at (almost) the same corner, move this label to the top-right so both stay readable.
                const clash = candidates.slice(0, i).some((o) => Array.isArray(o.region) && Math.abs(o.region[0] - x) < 0.05 && Math.abs(o.region[1] - y) < 0.05);
                return (
                  <button type="button" key={c.uuid} data-testid={`candidate-region-${num}`} data-candidate-id={c.uuid} aria-label={`Item ${num}: ${c.label || "marked spot"}`}
                    onMouseEnter={() => onActive?.(c.uuid)} onMouseLeave={() => onActive?.(null)} onFocus={() => onActive?.(c.uuid)} onClick={() => onPick?.(c.uuid)}
                    className={`rr-focus absolute cursor-pointer transition-[background-color,border-width] duration-150 ${dismissed ? "border-[3px] border-dashed border-[#D9DEE2]" : c.review ? "border-[3px] border-dashed border-[#E0A100]" : on ? "border border-[#B32624] bg-[#B32624]/20" : "border-[3px] border-[#B32624]"}`}
                    style={{ left: `${x * 100}%`, top: `${y * 100}%`, width: `${Math.min(w, 1 - x) * 100}%`, height: `${Math.min(h, 1 - y) * 100}%` }}>
                    <span className={`absolute top-0 whitespace-nowrap ${clash ? "right-0" : "left-0"} px-1.5 font-mono text-xs font-bold ${dismissed ? "bg-gray-300 text-[#202428]" : c.review ? "bg-[#E0A100] text-[#202428]" : "bg-[#B32624] text-white"}`}>{num}</span>
                  </button>
                );
              })
            : null}
        </div>
      )}
    </div>
  );
}
