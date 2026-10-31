import { BadgeCheck, Camera, Clock, MapPin, MapPinOff, Pencil, XCircle } from "lucide-react";

// Workspace palette: opaque neutral panels on charcoal; muted teal = selection only (never "safe/compliant/repaired").
export const WS = {
  panel: "bg-[#1B1E21]",
  line: "border-[#2E3337]",
  text: "text-[#E6E8EA]",
  sub: "text-[#A9B0B6]",
  sel: "bg-[#1F3A3A] outline outline-2 outline-[#3F8F8C]",
  btn: "rr-focus inline-flex min-h-[36px] items-center gap-1.5 rounded-[3px] border border-[#4A5157] bg-[#24282C] px-2.5 text-[13px] font-semibold text-[#E6E8EA] hover:bg-[#2E3337] disabled:cursor-not-allowed disabled:opacity-45 [@media(pointer:coarse)]:min-h-[44px]",
  on: "border-[#3F8F8C] bg-[#1F3A3A]",
};

export const REVIEW = {
  Pending: [Clock, "Pending review"],
  Confirmed: [BadgeCheck, "Confirmed"],
  Corrected: [Pencil, "Corrected"],
  Dismissed: [XCircle, "Not an issue"],
  "Needs evidence": [Camera, "Needs evidence"],
  "Closer photo requested": [Camera, "Needs evidence"],
};

export function StateChip({ state, testid }) {
  const [I, text] = REVIEW[state] || [Clock, state || "Unknown"];
  const warn = state === "Pending" || state === "Needs evidence" || state === "Closer photo requested";
  return (
    <span data-testid={testid} className={`inline-flex items-center gap-1 rounded-[3px] border px-1.5 py-px text-[12px] font-semibold ${warn ? "border-[#8A6A2E] text-[#F1D9A6]" : "border-[#4A5157] text-[#D5DADF]"}`}>
      <I aria-hidden className="h-3.5 w-3.5" />{text}
    </span>
  );
}

export function PlaceChip({ placed, testid }) {
  const I = placed ? MapPin : MapPinOff;
  return (
    <span data-testid={testid} className="inline-flex items-center gap-1 rounded-[3px] border border-[#4A5157] px-1.5 py-px text-[12px] font-semibold text-[#D5DADF]">
      <I aria-hidden className="h-3.5 w-3.5" />{placed ? "Placed" : "Unplaced"}
    </span>
  );
}
