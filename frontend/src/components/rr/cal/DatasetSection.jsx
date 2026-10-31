import { useState } from "react";
import { Download, FileArchive, Scale } from "lucide-react";
import { api, errText } from "@/lib/api";
import { ACTIVE, mb, num } from "@/lib/calibration";
import { Badge, Banner, Blocker, Btn, Card, H2, Mono, fmt } from "../ui";
import { Mark } from "./Metrics";

const ROWS = [
  ["images", "Images", "images"], ["train_images", "Train images", "train_images"], ["val_images", "Val images (locked test)", "val_images"],
  ["annotations", "Raw annotations", "annotations"], ["train_annotations", "Train annotations", "train_annotations"], ["val_annotations", "Val annotations", "val_annotations"],
  ["whole_image_annotations", "Whole-image ('image' category)", "whole_image_annotations"], ["physical_annotations", "Component annotations (incl. virtual baseplates)", "physical_annotations_incl_virtual_baseplates"],
];

function Progress({ r }) {
  const p = r.progress || {};
  const dl = r.source?.size ? Math.min(1, (p.downloaded_bytes || 0) / r.source.size) : 0;
  const fv = p.files_total ? (p.files_verified || 0) / p.files_total : 0;
  const bar = (v) => <div className="h-2 w-full overflow-hidden rounded bg-[#E4E8EB]"><div className="h-full bg-[#22272B] transition-all" style={{ width: `${v * 100}%` }} /></div>;
  return (
    <div data-testid="cal-progress" className="space-y-2 text-sm">
      <div><p>Download {mb(p.downloaded_bytes)} of {mb(r.source?.size)}</p>{bar(dl)}</div>
      <div><p>Files verified in private storage {num(p.files_verified)} of {num(p.files_total)}{p.store_pass ? ` - storage pass ${p.store_pass}` : ""}</p>{bar(fv)}</div>
      <p className="flex flex-wrap gap-3"><Mark ok={!!p.archive_verified} yes="Archive hash verified" no="Archive not verified yet" testid="cal-archive-verified" /></p>
    </div>
  );
}

function Counts({ r }) {
  const c = r.counts || {};
  const e = r.expected || {};
  return (
    <table data-testid="cal-counts" className="w-full text-sm">
      <thead><tr className="border-b border-[#D9DEE2] text-left text-[13px] text-[#3C444B]"><th className="py-1.5">Count</th><th>Contract</th><th>Imported</th><th /></tr></thead>
      <tbody>
        {ROWS.map(([k, label, ck]) => (
          <tr key={k} className="border-b border-[#EEF0F1]"><td className="py-1.5">{label}</td><td className="font-mono">{num(e[k])}</td><td className="font-mono">{num(c[ck])}</td><td><Mark ok={c[ck] === e[k]} testid={`cal-count-${k}`} /></td></tr>
        ))}
        <tr className="border-b border-[#EEF0F1]"><td className="py-1.5">Images decoded as 512x512 and re-verified</td><td className="font-mono">{num(e.images)}</td><td className="font-mono">{num(c.images_verified_512)}</td><td><Mark ok={c.images_verified_512 === e.images} testid="cal-count-verified512" /></td></tr>
        <tr><td className="py-1.5">Annotation JSON files hash-verified</td><td className="font-mono">2</td><td className="font-mono">{num(c.json_verified)}</td><td><Mark ok={c.json_verified === 2} testid="cal-count-json" /></td></tr>
      </tbody>
    </table>
  );
}

function Upload({ onDone }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  async function send(file) {
    if (!file) return;
    setBusy(true);
    setErr(null);
    const form = new FormData();
    form.append("file", file);
    try { onDone(await api("/calibration/datasets/import", { method: "POST", form })); } catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  }
  return (
    <div data-testid="cal-upload" className="space-y-2 rounded-md border border-dashed border-[#C5CCD2] p-3">
      <label htmlFor="cal-zip" className="block text-sm font-medium">Upload the exact source ZIP instead</label>
      <p className="text-[13px] text-[#59636B]">Same verification: the archive must match the contract size and SHA-256 or it is rejected.</p>
      <input id="cal-zip" data-testid="cal-upload-input" type="file" accept=".zip,application/zip" disabled={busy} onChange={(e) => send(e.target.files?.[0])} className="rr-focus block text-sm" />
      {busy ? <p className="text-sm">Uploading...</p> : null}
      {err ? <Banner tone="error" testid="cal-upload-error" text={err} /> : null}
    </div>
  );
}

export default function DatasetSection({ releases, r, onSelect, onImported }) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const running = r && ACTIVE.includes(r.status);
  async function start() {
    setBusy(true);
    setMsg(null);
    try {
      const x = await api("/calibration/datasets/import", { body: { source: "kaggle_fixed" } });
      setMsg({ tone: "success", text: x.already_complete ? "This release is already Complete. Nothing to import." : x.resumed ? "Import resumed from the last verified file." : "Import started." });
      onImported(x);
    } catch (e) { setMsg({ tone: "error", text: errText(e) }); } finally { setBusy(false); }
  }
  const showUpload = r && (r.upload_option || ["Blocked", "Failed", "Partial"].includes(r.status));
  return (
    <Card testid="cal-dataset" className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <H2 id="cal-dataset-h">Dataset</H2>
        {r ? <Badge testid="cal-release-status" label={r.status} /> : null}
        <div className="ml-auto flex flex-wrap items-center gap-2">
          {releases.length > 1 ? (
            <select aria-label="Release" data-testid="cal-release-select" value={r?.uuid} onChange={(e) => onSelect(e.target.value)} className="rr-focus min-h-[44px] rounded-md border border-[#C5CCD2] bg-white px-2 text-sm">
              {releases.map((x) => <option key={x.uuid} value={x.uuid}>{x.name} v{x.version} - {x.status}</option>)}
            </select>
          ) : null}
          <Btn small icon={Download} testid="cal-import-button" loading={busy} disabled={running} onClick={start}>{r ? "Resume / re-check import" : "Import dataset"}</Btn>
        </div>
      </div>
      {running ? <Blocker testid="cal-import-running" text="Import in progress. The status updates automatically." /> : null}
      {msg ? <Banner tone={msg.tone} text={msg.text} testid="cal-import-message" /> : null}
      {!r ? <p className="text-sm text-[#59636B]">No release imported yet. Import downloads the fixed Kaggle source (elvin1233/rail-components v1) and verifies every file.</p> : (
        <div className="grid gap-5 lg:grid-cols-2">
          <div className="space-y-4">
            <p className="text-sm"><b className="font-medium">{r.name}</b> - version {r.version} - started {fmt(r.created_at)} - updated {fmt(r.updated_at)}</p>
            <Progress r={r} />
            {r.blocker ? <Banner tone="warning" testid="cal-blocker" text={r.blocker} /> : null}
            {r.failed_files?.length ? (
              <details data-testid="cal-failed-files" className="text-sm">
                <summary className="rr-focus inline-flex min-h-[32px] cursor-pointer items-center rounded font-medium text-[#8F1D1B]">Files not yet verified ({r.failed_files.length}{r.failed_files.length >= 50 ? "+" : ""})</summary>
                <ul className="mt-1 max-h-48 space-y-0.5 overflow-auto break-all font-mono text-xs text-[#59636B]">{r.failed_files.map((f) => <li key={f}>{f}</li>)}</ul>
              </details>
            ) : null}
            {r.rejected_members?.length ? <Banner tone="error" testid="cal-rejected" text={`Archive members rejected: ${r.rejected_members.slice(0, 5).join(", ")}`} /> : null}
            {showUpload ? <Upload onDone={onImported} /> : null}
            {r.receipt ? (
              <div data-testid="cal-receipt" className="text-sm"><Badge label="Received complete" /> <span className="text-[#59636B]">{num(r.receipt.files)} files - {fmt(r.receipt.completed_at)}</span>
                <Mono label="Receipt details">archive {r.receipt.archive_sha256} - manifest {r.receipt.manifest_sha256}</Mono></div>
            ) : <p data-testid="cal-no-receipt" className="text-[13px] text-[#59636B]">No receipt yet. A receipt is issued only when every file is verified.</p>}
            <Mono label="Source details">{r.source?.dataset} - {r.source?.size} bytes - sha256 {r.source?.sha256}</Mono>
          </div>
          <div className="space-y-4">
            <Counts r={r} />
            <Attribution r={r} />
          </div>
        </div>
      )}
    </Card>
  );
}

function Attribution({ r }) {
  const a = r.attribution || {};
  return (
    <div data-testid="cal-attribution" className="space-y-1 rounded-md border border-[#D9DEE2] bg-[#F8F9F9] p-3 text-sm">
      <p className="flex items-center gap-2 font-medium"><Scale aria-hidden className="h-4 w-4" />Attribution and license</p>
      <p>{a.authors}. {a.citation}. DOI <span data-testid="cal-doi" className="font-mono text-[13px]">{a.doi}</span></p>
      <p>Source: {a.source} - Region: {a.region}{a.region_source ? ` (${a.region_source})` : ""}</p>
      <p data-testid="cal-license" className="font-medium">{r.license?.id || "CC BY-NC-SA 4.0"} - private research/calibration use</p>
      {r.license?.use ? <p className="text-[13px] text-[#59636B]">{r.license.use}</p> : null}
      <p className="flex items-center gap-1 text-[13px] text-[#59636B]"><FileArchive aria-hidden className="h-3.5 w-3.5" />Images stay in private workspace storage; they are never shown to customers.</p>
    </div>
  );
}
