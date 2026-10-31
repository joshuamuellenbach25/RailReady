import { AlertTriangle, CheckCircle2, Clock, Download, FileWarning, History, ImageOff, Layers, Loader2, Lock, MonitorX, TimerOff } from "lucide-react";
import { WS } from "./ws";

// REQ-182: every scene state has its own text + icon (never colour alone).
export const STATES = {
  "no-photo": [ImageOff, "No photo"],
  queued: [Clock, "Getting the 3D view ready..."],
  processing: [Loader2, "Building the 3D view..."],
  downloading: [Download, "Loading the 3D view..."],
  rendering: [Loader2, "Loading the 3D view..."],
  ready: [CheckCircle2, "Ready"],
  "depth-uninformative": [Layers, "A 3D view doesn't help for this photo"],
  denied: [Lock, "You don't have access to this photo"],
  expired: [TimerOff, "This photo link expired. Refresh the page."],
  unsupported: [FileWarning, "This photo can't be shown in 3D. Open the photo instead."],
  graphics: [MonitorX, "3D isn't available on this device"],
  failed: [AlertTriangle, "The 3D view didn't work for this photo"],
  model: [AlertTriangle, "3D view isn't available right now"],
  loading: [Loader2, "Loading the 3D view..."],
  preparing: [Loader2, "Preparing 3D view..."],
  blocked: [Lock, "3D view is turned off for this inspection"],
  stalled: [Clock, "The 3D view is taking a long time"],
  previous: [History, "Showing the previous view while it updates"],
  "previous-failed": [AlertTriangle, "Showing the previous view. The update did not finish."],
};
const SPIN = ["processing", "rendering", "loading", "preparing"];

export function StateIcon({ k, className = "h-4 w-4" }) {
  const [I] = STATES[k] || STATES.loading;
  return <I aria-hidden className={`${className} ${SPIN.includes(k) ? "animate-spin" : ""}`} />;
}

export function StatePanel({ k, title, detail, children, overlay, reason }) {
  return (
    <div data-testid={`scene-state-${k}`} data-state={k} data-reason={reason || undefined} role="status"
      className={overlay ? "absolute inset-x-0 bottom-0 z-30 bg-[#111315]/95 px-3 py-2" : "absolute inset-0 z-30 flex items-center justify-center bg-[#0D0F10] p-4"}>
      <div className={overlay ? "" : `max-w-md space-y-2 border ${WS.line} ${WS.panel} p-4`}>
        <p className="flex items-center gap-2 text-[15px] font-bold"><StateIcon k={k} />{title || STATES[k]?.[1]}</p>
        {detail ? <p className={`text-[13px] ${WS.sub}`}>{detail}</p> : null}
        {children ? <div className="flex flex-wrap gap-2 pt-1">{children}</div> : null}
      </div>
    </div>
  );
}
