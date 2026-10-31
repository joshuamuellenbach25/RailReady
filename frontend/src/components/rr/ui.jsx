// RailReady design system (phase 5). Tokens live in index.css (--rr-*) and are mirrored here as Tailwind arbitrary values.
// Status = line icon + text; colour only for meaningful states. Diagnostics live behind a disclosure (Mono / Details).
import {
  AlertCircle, AlertOctagon, Ban, BadgeCheck, Camera, Check, CheckCircle2, ChevronRight, Circle, CircleHelp, Clock, CloudOff, CloudUpload,
  Eye, FileCheck2, Info, Loader2, Lock, MinusCircle, Pencil, Receipt, RefreshCw, Timer, Upload, UserCog, XCircle, XOctagon,
} from "lucide-react";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { useAuth } from "@/lib/auth";

export const C = {
  canvas: "bg-[#F3F4F4]", surface: "bg-white", text: "text-[#202428]", sub: "text-[#59636B]", border: "border-[#D9DEE2]",
  nav: "bg-[#22272B]", action: "bg-[#B32624]",
};

export const STATUS = {
  "Saved on this device": [FileCheck2, "neutral"], Queued: [Clock, "neutral"], Uploading: [Upload, "neutral"],
  "Uploaded unverified": [CircleHelp, "warning"], Verified: [CloudUpload, "success"], "Retry wait": [Timer, "warning"],
  Blocked: [AlertOctagon, "error"], Running: [RefreshCw, "neutral"], Done: [CheckCircle2, "success"], Failed: [XOctagon, "error"],
  "Not started": [Circle, "neutral"], Provided: [Check, "success"], "Missing required": [AlertCircle, "error"],
  "Needs review": [Eye, "warning"], "Unknown with reason": [CircleHelp, "neutral"], "Not applicable": [MinusCircle, "neutral"],
  "Needs estimator input": [UserCog, "neutral"], Draft: [Pencil, "neutral"], "Inspection in progress": [Pencil, "neutral"], Submitted: [Lock, "neutral"],
  "Received complete": [Receipt, "success"], "Receiving partial": [Receipt, "warning"], "Offline ready": [CloudOff, "success"],
  Pending: [Clock, "warning"], Confirmed: [BadgeCheck, "success"], Corrected: [Pencil, "success"], Dismissed: [XCircle, "neutral"],
  "Closer photo requested": [Camera, "warning"], Granted: [Check, "success"], Denied: [Ban, "error"], Unknown: [CircleHelp, "warning"],
  Published: [FileCheck2, "neutral"], Accepted: [BadgeCheck, "success"], Superseded: [MinusCircle, "neutral"],
  "Changes requested": [Pencil, "warning"], Issued: [FileCheck2, "neutral"], Expired: [Clock, "neutral"], Revoked: [Ban, "neutral"],
  Active: [Check, "success"], Requested: [Clock, "warning"], "Not arranged": [Circle, "warning"],
  Downloading: [Upload, "neutral"], Verifying: [RefreshCw, "neutral"], Storing: [Upload, "neutral"], Indexing: [RefreshCw, "neutral"],
  Complete: [CheckCircle2, "success"], Partial: [AlertCircle, "warning"], Unsupported: [Ban, "warning"], Abstained: [MinusCircle, "neutral"],
  UNKNOWN: [CircleHelp, "warning"], Provisional: [CircleHelp, "warning"], "Locked test": [Lock, "neutral"],
};
// Plain-language labels (phase 8). API values are unchanged; people never see internal states.
export const LABEL = {
  "Saved on this device": "Saved on the phone", Queued: "Waiting", Uploading: "Sending", "Uploaded unverified": "Sending", Verified: "Received",
  "Retry wait": "Will try again", Blocked: "Stuck, needs attention", Running: "Working on it", Done: "Done", Failed: "Didn't work",
  "Not started": "Not started", Provided: "Answered", "Missing required": "Still needed", "Needs review": "Needs review",
  "Unknown with reason": "Not known", "Needs estimator input": "Office to fill in", Draft: "In progress", Submitted: "Ready for the office",
  "Received complete": "Everything received", "Receiving partial": "Some items still arriving", "Offline ready": "Ready offline",
  Pending: "Needs review", Confirmed: "Confirmed", Corrected: "Corrected", Dismissed: "Not an issue", "Closer photo requested": "Closer photo asked for",
  Granted: "On", Denied: "Off", Unknown: "Not set", Published: "Link ready to share", Accepted: "Customer accepted", Superseded: "Replaced",
  "Changes requested": "Customer asked for changes", Issued: "Issued", Expired: "Expired", Revoked: "Link turned off",
  Requested: "Requested", "Not arranged": "Not arranged",
};

// Restrained: text + icon on a neutral chip; tone tints the icon/text only.
export const TONE = {
  success: "border-[#BFD8C6] bg-[#F1F7F2] text-[#1E5B32]",
  warning: "border-[#E6D3A8] bg-[#FBF6EA] text-[#7A4A00]",
  error: "border-[#E8C1BF] bg-[#FBEFEE] text-[#8F1D1B]",
  info: "border-[#D9DEE2] bg-white text-[#202428]",
  brand: "border-[#D9DEE2] bg-white text-[#202428]",
  neutral: "border-[#D9DEE2] bg-white text-[#3C444B]",
};

export function Badge({ label, prefix, icon, tone, testid, className = "" }) {
  const [SIcon, sTone] = STATUS[label] || [Info, "neutral"];
  const I = icon || SIcon;
  return (
    <span data-testid={testid} className={`inline-flex max-w-full items-center gap-1.5 rounded-md border px-2 py-0.5 text-[13px] font-medium leading-5 ${TONE[tone || sTone]} ${className}`}>
      <I aria-hidden className="h-3.5 w-3.5 shrink-0" />
      <span className="min-w-0 break-words">{prefix ? `${prefix}: ` : ""}{LABEL[label] || label}</span>
    </span>
  );
}

const KIND = {
  primary: "bg-[#B32624] text-white border-[#B32624] hover:bg-[#962020] hover:border-[#962020]",
  secondary: "bg-white text-[#202428] border-[#C5CCD2] hover:bg-[#F3F4F4]",
  danger: "bg-white text-[#8F1D1B] border-[#E8C1BF] hover:bg-[#FBEFEE]",
  ghost: "bg-transparent text-[#202428] border-transparent hover:bg-[#EEF0F1]",
  header: "bg-transparent text-white border-[#4A5157] hover:bg-[#2E3439]",
};

export function Btn({ children, title, onClick, icon: I, kind = "primary", disabled, loading, testid, small, type = "button", className = "", ...rest }) {
  return (
    <button type={type} data-testid={testid} onClick={onClick} disabled={disabled || loading} aria-busy={loading || undefined}
      className={`rr-focus inline-flex items-center justify-center gap-2 rounded-md border font-semibold transition-colors duration-150 disabled:cursor-not-allowed disabled:opacity-50 ${small ? "min-h-[44px] px-3 text-sm" : "min-h-[48px] px-4 text-[15px]"} ${KIND[kind]} ${className}`}
      {...rest}>
      {loading ? <Loader2 aria-hidden className="h-4 w-4 animate-spin" /> : I ? <I aria-hidden className="h-4 w-4 shrink-0" /> : null}
      <span>{children ?? title}</span>
    </button>
  );
}

export function Card({ children, testid, className = "" }) {
  return <section data-testid={testid} className={`rr-rise rounded-xl border border-[#E3E7EA] bg-white p-5 shadow-[0_1px_2px_rgba(32,36,40,0.04),0_4px_16px_rgba(32,36,40,0.04)] md:p-6 ${className}`}>{children}</section>;
}

export function H2({ children, className = "", ...r }) {
  return <h2 className={`text-lg font-semibold tracking-[-0.01em] text-[#202428] ${className}`} {...r}>{children}</h2>;
}
export function Kicker({ children }) {
  return <p className="text-[13px] font-medium text-[#59636B]">{children}</p>;
}

const BANNER_ICON = { success: CheckCircle2, warning: AlertCircle, error: AlertOctagon, info: Info, brand: Info, neutral: Info };
export function Banner({ text, tone = "info", icon, testid, children }) {
  const I = icon || BANNER_ICON[tone];
  return (
    <div data-testid={testid} role={tone === "error" ? "alert" : "status"} className={`rounded-md border p-3 ${TONE[tone]}`}>
      <div className="flex items-start gap-2">
        <I aria-hidden className="mt-0.5 h-4 w-4 shrink-0" />
        <p className="flex-1 text-[15px] font-medium">{text}</p>
      </div>
      {children ? <div className="mt-2 space-y-1 pl-6 text-sm">{children}</div> : null}
    </div>
  );
}

/** Blocker shown next to the item it concerns (REQ-225) - never only a disabled control. */
export function Blocker({ text, testid, to }) {
  return (
    <p data-testid={testid} role="note" className="mt-1 flex items-start gap-1.5 text-[13px] font-medium text-[#8F1D1B]">
      <AlertCircle aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0" />
      <span className="min-w-0 break-words">{text}{to ? <> - {to}</> : null}</span>
    </p>
  );
}

export function Field({ id, label, value, onChange, multiline, type = "text", placeholder, testid, hint, ...rest }) {
  const cls = "rr-focus w-full rounded-md border border-[#C5CCD2] bg-white px-3 text-base text-[#202428] placeholder:text-[#7A848C] disabled:cursor-not-allowed disabled:bg-[#F3F4F4]";
  return (
    <div className="space-y-1">
      <label htmlFor={id} className="block text-sm font-medium text-[#202428]">{label}</label>
      {multiline ? (
        <textarea id={id} data-testid={testid} value={value} placeholder={placeholder} onChange={(e) => onChange(e.target.value)} rows={4} className={`${cls} py-2`} {...rest} />
      ) : (
        <input id={id} data-testid={testid} type={type} value={value} placeholder={placeholder} onChange={(e) => onChange(e.target.value)} className={`${cls} min-h-[44px]`} {...rest} />
      )}
      {hint ? <p className="text-[13px] text-[#59636B]">{hint}</p> : null}
    </div>
  );
}

/** Native select (keyboard + screen-reader friendly). options: [[value, label]]. */
export function Select({ id, label, value, onChange, options, testid, hint, placeholder, className = "", ...rest }) {
  return (
    <div className={`space-y-1 ${className}`}>
      {label ? <label htmlFor={id} className="block text-sm font-medium text-[#202428]">{label}</label> : null}
      <select id={id} data-testid={testid} value={value ?? ""} onChange={(e) => onChange(e.target.value)}
        className="rr-focus min-h-[44px] w-full rounded-md border border-[#C5CCD2] bg-white px-3 text-base text-[#202428] disabled:cursor-not-allowed disabled:bg-[#F3F4F4]" {...rest}>
        {placeholder ? <option value="">{placeholder}</option> : null}
        {options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
      </select>
      {hint ? <p className="text-[13px] text-[#59636B]">{hint}</p> : null}
    </div>
  );
}

export function Checkbox({ id, label, checked, onChange, testid }) {
  return (
    <label htmlFor={id} className="inline-flex min-h-[44px] cursor-pointer items-center gap-2 text-sm text-[#202428]">
      <input id={id} data-testid={testid} type="checkbox" checked={!!checked} onChange={(e) => onChange(e.target.checked)} className="rr-focus h-5 w-5 accent-[#B32624]" />
      {label}
    </label>
  );
}

export function Loading({ text = "Loading...", testid = "loading" }) {
  return (
    <div data-testid={testid} className="flex items-center gap-3 p-8 text-[#59636B]" role="status">
      <Loader2 aria-hidden className="h-5 w-5 animate-spin" />
      <span>{text}</span>
    </div>
  );
}

export function Empty({ text, testid, children }) {
  return (
    <div data-testid={testid} className="rounded-xl border border-dashed border-[#D2D8DD] bg-white/70 p-8 text-center text-[15px] text-[#59636B]">
      <p>{text}</p>{children ? <div className="mt-3">{children}</div> : null}
    </div>
  );
}

/** Diagnostics disclosure (REQ-228): hashes, byte counts, receipt ids, model metadata. Closed by default. */
export function Details({ label = "Technical details", children, testid, className = "" }) {
  const { isAdmin } = useAuth();
  if (!isAdmin) return null; // technical content is for administrators only (phase 8)
  return (
    <details data-testid={testid} className={`group/details min-w-0 text-[13px] text-[#59636B] ${className}`}>
      <summary className="rr-focus inline-flex min-h-[32px] cursor-pointer list-none items-center gap-1 rounded font-medium text-[#3C444B] hover:text-[#202428] [&::-webkit-details-marker]:hidden">
        <ChevronRight aria-hidden className="h-3.5 w-3.5 transition-transform group-open/details:rotate-90" />{label} (admin)
      </summary>
      <div className="mt-1 break-all font-mono text-xs">{children}</div>
    </details>
  );
}
export function Mono({ children, className = "", testid, label }) {
  return <Details testid={testid} label={label} className={className}>{children}</Details>;
}

export function Modal({ open, onClose, title, description, children, testid, wide }) {
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent data-testid={testid} className={`max-h-[90vh] overflow-y-auto rounded-lg border border-[#D9DEE2] bg-white shadow-lg ${wide ? "sm:max-w-2xl" : "sm:max-w-lg"}`}>
        <DialogHeader>
          <DialogTitle className="text-xl font-semibold text-[#202428]">{title}</DialogTitle>
          <DialogDescription className={description ? "text-[#59636B]" : "sr-only"}>{description || title}</DialogDescription>
        </DialogHeader>
        <div className="space-y-3">{children}</div>
      </DialogContent>
    </Dialog>
  );
}

export function PageHead({ kicker, title, subtitle, right, testid }) {
  return (
    <header data-testid={testid} className="mb-8 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        {kicker ? <Kicker>{kicker}</Kicker> : null}
        <h1 className="mt-0.5 break-words text-[28px] font-semibold tracking-[-0.02em] text-[#202428]">{title}</h1>
        {subtitle ? <p className="mt-1.5 max-w-2xl text-[15px] text-[#59636B]">{subtitle}</p> : null}
      </div>
      {right ? <div className="flex flex-wrap items-center gap-2">{right}</div> : null}
    </header>
  );
}

export function Msg({ msg, testid }) {
  return msg ? <Banner testid={testid} tone={msg.tone} text={msg.text} /> : null;
}

export const fmt = (iso) => (iso ? new Date(iso).toLocaleString() : "-");
export const short = (h, n = 16) => (h ? `${String(h).slice(0, n)}...` : "-");
