import { useEffect, useRef, useState } from "react";
import { ImagePlus, RefreshCw } from "lucide-react";
import { api, errText, newId, sha256Hex } from "@/lib/api";
import { Badge, Banner, Btn, Card, H2, Mono } from "./ui";

// Browser photo upload into a draft visit: same flow as the mobile outbox (register -> PUT content -> server verify -> manifest -> receipt).
async function uploadOne(visitId, item, set) {
  set({ state: "Uploading" });
  const reg = await api(`/visits/${visitId}/evidence`, {
    body: { uuid: item.uuid, kind: "photo", sha256: item.sha256, size: item.size, mime: item.mime, filename: item.filename, captured_at: item.captured_at },
  });
  let state = reg.upload_state;
  if (state !== "Verified") {
    if (state !== "Uploaded unverified") {
      const form = new FormData();
      form.append("file", new Blob([item.buf], { type: item.mime }), item.filename);
      await api(`/evidence/${item.uuid}/content`, { method: "PUT", form });
      set({ state: "Uploaded unverified" });
    }
    state = (await api(`/evidence/${item.uuid}/verify`, { method: "POST" })).upload_state;
  }
  if (state === "Hash mismatch") throw new Error("That photo did not arrive complete. Nothing was saved. Try the upload again.");
  if (state !== "Verified") throw new Error("That photo did not arrive complete. Nothing was saved. Try the upload again.");
  set({ state: "Verified" });
  const m = await api(`/visits/${visitId}/manifests`, { body: { members: [{ evidence_id: item.uuid, sha256: item.sha256, size: item.size }], device_id: "web" } });
  set({ state: "Verified", manifest: m.state, receipt: m.receipt_id });
}

// Pre-send states shown by this computer (contract section 2); after "Verified" the server state takes over.
const STATE_LABEL = { Queued: "Saved on this computer", Waiting: "Waiting for connection", Uploading: "Sending photo", "Uploaded unverified": "Sending photo", Verified: "Sent", "Retry wait": "Not sent. Try again" };

export default function UploadPhoto({ visitId, onUploaded }) {
  const ref = useRef(null);
  const [items, setItems] = useState([]);
  const patch = (uuid, p) => setItems((xs) => xs.map((x) => (x.uuid === uuid ? { ...x, ...p } : x)));

  async function run(item) {
    patch(item.uuid, { error: null });
    try {
      await uploadOne(visitId, item, (p) => patch(item.uuid, p));
      onUploaded(item.uuid);
    } catch (e) {
      const offline = !navigator.onLine || e instanceof TypeError; // no answer at all: keep the file and resend when back online
      patch(item.uuid, { state: offline ? "Waiting" : "Retry wait", error: offline ? null : errText(e) }); // file kept; same UUID keeps it idempotent
    }
  }
  const latest = useRef(items);
  latest.current = items;
  useEffect(() => {
    const on = () => latest.current.filter((x) => x.state === "Waiting").forEach((x) => run(x));
    window.addEventListener("online", on);
    return () => window.removeEventListener("online", on);
  });
  async function pick(files) {
    for (const file of Array.from(files || [])) {
      const buf = await file.arrayBuffer();
      const item = { uuid: newId(), filename: file.name, mime: file.type || "image/jpeg", size: file.size, buf, captured_at: new Date(file.lastModified || Date.now()).toISOString(), state: "Queued" };
      item.sha256 = await sha256Hex(buf);
      setItems((xs) => [...xs, item]);
      await run(item);
    }
    if (ref.current) ref.current.value = "";
  }

  return (
    <Card testid="web-upload-card" className="space-y-3 border-dashed">
      <H2>Add photos</H2>
      <p className="text-[15px] text-[#59636B]">Add photos from this computer.</p>
      <label htmlFor="web-upload-input" className="rr-focus inline-flex min-h-[48px] cursor-pointer items-center gap-2 rounded-lg border border-[#B32624] bg-[#B32624] px-4 font-semibold text-white transition-colors hover:bg-[#962020]">
        <ImagePlus aria-hidden className="h-4 w-4" /> Choose photos
      </label>
      <input id="web-upload-input" ref={ref} data-testid="web-upload-input" type="file" accept="image/jpeg,image/png,image/webp" multiple className="sr-only" onChange={(e) => pick(e.target.files)} />
      {items.map((it) => (
        <div key={it.uuid} data-testid={`web-upload-item-${it.uuid}`} className="space-y-1 rounded border border-[#D9DEE2] p-2">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-bold">{it.filename}</span>
            <Badge testid={`web-upload-state-${it.uuid}`} label={STATE_LABEL[it.error ? "Retry wait" : it.state] || "Sending photo"} />
            
          </div>
          <Mono label="Technical details" className="block">id {it.uuid} - SHA-256 {it.sha256 || "..."} - {it.size} bytes{it.receipt ? ` - receipt ${it.receipt}` : ""}</Mono>
          {it.error ? (
            <>
              <Banner tone="error" text={it.error} testid={`web-upload-error-${it.uuid}`} />
              <Btn small icon={RefreshCw} testid={`web-upload-retry-${it.uuid}`} onClick={() => run(it)}>Try again</Btn>
            </>
          ) : it.state === "Waiting" ? (
            <Btn small kind="secondary" icon={RefreshCw} testid={`web-upload-retry-${it.uuid}`} onClick={() => run(it)}>Send now</Btn>
          ) : null}
        </div>
      ))}
    </Card>
  );
}
