import { Move } from "lucide-react";
import { WS } from "./ws";

const pct = (v) => (v == null ? "" : Math.round(v * 1000) / 10);
const field = "rr-focus h-9 w-full rounded-[3px] border border-[#4A5157] bg-[#111315] px-2 text-[13px] text-[#E6E8EA]";

// Anchor move (REQ-134). The new spot is picked on the original photo (or typed as %), and the server
// re-projects it through this photo's estimated depth. Only the marker moves: review state, quantities and documents stay.
export default function MoveAnchor({ item, placing, onStart, onChange, onCancel, onSave, canPlace, withReason = true }) {
  const movable = item?.placed && item.anchor?.anchor_id;
  if (!movable && !canPlace) return null;
  if (!placing || placing.item_id !== item.item_id) {
    return <button type="button" data-testid="drawer-move-marker" className={`${WS.btn} mt-1 w-full justify-center`} onClick={() => onStart(item)}><Move aria-hidden className="h-4 w-4" />{movable ? "Move marker" : "Place marker"}</button>;
  }
  const [u, v] = placing.point || [];
  const setAxis = (i, val) => {
    const n = Math.min(100, Math.max(0, Number(val))) / 100;
    const p = [...(placing.point || (item.anchor?.u != null ? [item.anchor.u, item.anchor.v] : [0.5, 0.5]))];
    p[i] = Number.isFinite(n) ? n : p[i];
    onChange({ point: p });
  };
  return (
    <form data-testid="drawer-move-form" className={`mt-1 space-y-1.5 border ${WS.line} p-2`} onSubmit={(e) => { e.preventDefault(); onSave(); }}>
      <p className="text-[13px] font-semibold">Click the new spot on the original photo, or enter it below.</p>
      <p className={`text-[12px] ${WS.sub}`}>Only the marker position changes. Review state, quantities and issued documents are not affected.</p>
      <div className="grid grid-cols-2 gap-1.5">
        <div>
          <label htmlFor="mv-u" className="block text-[12px] font-semibold text-[#A9B0B6]">From left (%)</label>
          <input id="mv-u" data-testid="drawer-move-u" type="number" min={0} max={100} step={0.1} value={pct(u)} onChange={(e) => setAxis(0, e.target.value)} className={field} />
        </div>
        <div>
          <label htmlFor="mv-v" className="block text-[12px] font-semibold text-[#A9B0B6]">From top (%)</label>
          <input id="mv-v" data-testid="drawer-move-v" type="number" min={0} max={100} step={0.1} value={pct(v)} onChange={(e) => setAxis(1, e.target.value)} className={field} />
        </div>
      </div>
      {withReason ? (
        <>
          <label htmlFor="mv-reason" className="block text-[12px] font-semibold text-[#A9B0B6]">Reason (optional)</label>
          <input id="mv-reason" data-testid="drawer-move-reason" value={placing.reason} onChange={(e) => onChange({ reason: e.target.value })} placeholder="e.g. centre on the tie end" className={field} />
        </>
      ) : null}
      <div className="flex gap-1.5">
        <button type="submit" data-testid="drawer-move-save" className={WS.btn} disabled={!placing.point || placing.saving}>{placing.saving ? "Saving..." : "Save position"}</button>
        <button type="button" data-testid="drawer-move-cancel" className={WS.btn} disabled={placing.saving} onClick={onCancel}>Cancel</button>
      </div>
    </form>
  );
}
