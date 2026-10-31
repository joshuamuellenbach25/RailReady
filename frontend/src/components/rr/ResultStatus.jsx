import { AlertTriangle, CheckCircle2, ClipboardCheck, Loader2, Ban } from "lucide-react";

const ICON = { checking: Loader2, needs_review: ClipboardCheck, partial: AlertTriangle, complete: CheckCircle2, failed: AlertTriangle, unavailable: Ban };
const TONE = { failed: "text-[#8F1D1B]", unavailable: "text-[#7A4A00]", partial: "text-[#7A4A00]", needs_review: "text-[#7A4A00]", complete: "text-[#1E6B3A]", checking: "text-[#202428]" };

/** The server's state for one photo or video, rendered exactly as sent (result_label, result_empty_copy). */
export default function ResultStatus({ d, checkingText }) {
  if (!d) return null;
  const k = checkingText ? "checking" : d.state;
  const label = checkingText || d.label;
  if (!label) return null; // never checked: no state to show
  const Icon = ICON[k] || ClipboardCheck;
  return (
    <div data-testid="result-status" data-state={k || "none"} role="status" className="space-y-1">
      <p className={`flex items-center gap-2 text-[15px] font-semibold ${TONE[k] || "text-[#202428]"}`}>
        <Icon aria-hidden className={`h-4 w-4 shrink-0 ${k === "checking" ? "animate-spin" : ""}`} />
        <span data-testid="result-label">{label}</span>
      </p>
      {d.empty && !checkingText ? <p data-testid="result-empty-copy" className="text-[15px] text-[#202428]">{d.empty}</p> : null}
    </div>
  );
}
