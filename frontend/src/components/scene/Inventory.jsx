import { useMemo, useState } from "react";
import { Search } from "lucide-react";
import { PlaceChip, StateChip, WS } from "./ws";

// Left inventory: label + short id + review state + placed/unplaced. Search/filters only appear when there is real data.
export default function Inventory({ items, selectedId, onSelect }) {
  const [q, setQ] = useState("");
  const [f, setF] = useState("all");
  const states = useMemo(() => [...new Set(items.map((i) => i.review_state))], [items]);
  const anyUnplaced = items.some((i) => !i.placed);
  const shown = items.filter((i) => {
    if (f === "unplaced" && i.placed) return false;
    if (f !== "all" && f !== "unplaced" && i.review_state !== f) return false;
    const s = q.trim().toLowerCase();
    return !s || `${i.label} ${i.short_id} ${i.category || ""}`.toLowerCase().includes(s);
  });
  return (
    <nav aria-label="Findings on this photo" data-testid="scene-inventory" className={`flex min-h-0 flex-col ${WS.panel}`}>
      <div className={`border-b ${WS.line} px-2.5 py-2`}>
        <h2 className="text-[13px] font-bold uppercase tracking-wide text-[#C9CED3]">Inventory ({items.length})</h2>
        {items.length ? (
          <div className="mt-2 space-y-1.5">
            <label htmlFor="inv-search" className="sr-only">Search findings</label>
            <div className="relative">
              <Search aria-hidden className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[#A9B0B6]" />
              <input id="inv-search" data-testid="scene-inventory-search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search"
                className="rr-focus h-9 w-full rounded-[3px] border border-[#4A5157] bg-[#111315] pl-7 [@media(pointer:coarse)]:h-11 pr-2 text-[13px] text-[#E6E8EA] placeholder:text-[#8A9299]" />
            </div>
            <label htmlFor="inv-filter" className="sr-only">Filter by state</label>
            <select id="inv-filter" data-testid="scene-inventory-filter" value={f} onChange={(e) => setF(e.target.value)}
              className="rr-focus h-9 w-full rounded-[3px] border border-[#4A5157] bg-[#111315] px-2 text-[13px] [@media(pointer:coarse)]:h-11 text-[#E6E8EA]">
              <option value="all">All states</option>
              {states.map((s) => <option key={s} value={s}>{s}</option>)}
              {anyUnplaced ? <option value="unplaced">Unplaced</option> : null}
            </select>
          </div>
        ) : null}
      </div>
      <ul className="min-h-0 flex-1 overflow-y-auto">
        {!items.length ? <li className={`px-2.5 py-3 text-[13px] ${WS.sub}`}>No findings listed here. The check result for this photo is on the inspection page.</li> : null}
        {shown.map((i) => {
          const sel = i.item_id === selectedId;
          return (
            <li key={i.item_id} className={`border-b ${WS.line}`}>
              <button type="button" data-testid={`scene-row-${i.item_id}`} aria-current={sel ? "true" : undefined} onClick={() => onSelect(i.item_id, true)}
                className={`rr-focus block min-h-[44px] w-full px-2.5 py-2 text-left hover:bg-[#24282C] ${sel ? WS.sel : ""}`}>
                <span className="flex items-start gap-2">
                  <span aria-hidden className="mt-px inline-flex h-5 min-w-5 items-center justify-center rounded-[3px] bg-[#E6E8EA] px-1 text-[12px] font-bold text-[#111315]">{i.n}</span>
                  <span className="min-w-0">
                    <span className="block break-words text-[14px] font-semibold leading-tight text-[#E6E8EA]">{String(i.label ?? "")}</span>
                    <span className="block font-mono text-[12px] text-[#A9B0B6]">{i.short_id}</span>
                  </span>
                </span>
                <span className="mt-1.5 flex flex-wrap gap-1">
                  <StateChip state={i.review_state} testid={`scene-row-state-${i.item_id}`} />
                  <PlaceChip placed={i.placed} testid={`scene-row-place-${i.item_id}`} />
                </span>
              </button>
            </li>
          );
        })}
        {items.length && !shown.length ? <li className={`px-2.5 py-3 text-[13px] ${WS.sub}`}>No matches.</li> : null}
      </ul>
    </nav>
  );
}
