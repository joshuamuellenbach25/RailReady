import { useCallback, useEffect, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, ImageOff } from "lucide-react";
import { API, api, errText, getToken } from "@/lib/api";
import { num } from "@/lib/calibration";
import { Badge, Banner, Btn, Card, Checkbox, H2, Loading, Modal, Mono, Select } from "../ui";

/** Dataset media needs the Bearer header -> fetch as a Blob URL (revoked on unmount). */
function useBlob(path, enabled) {
  const [url, setUrl] = useState(null);
  const [err, setErr] = useState(null);
  useEffect(() => {
    if (!enabled) return undefined;
    let u = null;
    let off = false;
    fetch(`${API}${path.replace(/^\/api/, "")}`, { headers: { Authorization: `Bearer ${getToken()}` } })
      .then((r) => (r.ok ? r.blob() : Promise.reject(new Error(`Image unavailable (${r.status})`))))
      .then((b) => { if (!off) { u = URL.createObjectURL(b); setUrl(u); } })
      .catch((e) => !off && setErr(e.message));
    return () => { off = true; if (u) URL.revokeObjectURL(u); };
  }, [path, enabled]);
  return [url, err];
}

function Thumb({ img, onOpen }) {
  const ok = img.verified && img.decoded;
  const [url] = useBlob(img.media_url, ok);
  return (
    <button type="button" data-testid={`cal-img-${img.file_name}-${img.split}`} onClick={() => onOpen(img)} className="rr-focus group relative aspect-square overflow-hidden rounded-md border border-[#D9DEE2] bg-[#22272B] text-left">
      {url ? <img src={url} alt={`${img.split} ${img.file_name}`} className="h-full w-full object-cover transition-opacity group-hover:opacity-90" /> : (
        <span className="flex h-full flex-col items-center justify-center gap-1 p-2 text-center text-[12px] text-[#C9CED3]"><ImageOff aria-hidden className="h-5 w-5" />{ok ? "Loading..." : "Not in private storage yet"}</span>
      )}
      <span className="absolute inset-x-0 bottom-0 flex flex-wrap items-center gap-1 bg-[#22272B]/85 px-1.5 py-1 text-[11px] text-white">
        {img.split}/{img.file_name} - {img.annotation_count} boxes{img.test_locked ? " - Locked test" : ""}
      </span>
    </button>
  );
}

function Detail({ rid, img, onClose }) {
  const [d, setD] = useState(null);
  const [err, setErr] = useState(null);
  const [boxes, setBoxes] = useState(true);
  const [url, imgErr] = useBlob(img.media_url, img.verified && img.decoded);
  useEffect(() => { api(`/calibration/datasets/${rid}/images/${encodeURIComponent(img.uuid)}`).then(setD).catch((e) => setErr(errText(e))); }, [rid, img.uuid]);
  const W = d?.width || img.width || 512;
  const H = d?.height || img.height || 512;
  return (
    <Modal open onClose={onClose} wide testid="cal-image-detail" title={`${img.split}/${img.file_name}`} description="Source annotations are dataset labels. Boxes are drawn in the original pixel space.">
      <div className="flex flex-wrap items-center gap-2">
        {img.test_locked ? <Badge testid="cal-detail-locked" label="Locked test" /> : <Badge label={img.split === "train" ? "Train" : img.split} tone="neutral" />}
        <Checkbox id="cal-boxes" testid="cal-boxes-toggle" label="Show annotation boxes" checked={boxes} onChange={setBoxes} />
      </div>
      <div className="relative w-full overflow-hidden rounded-md bg-[#22272B]" style={{ aspectRatio: `${W} / ${H}` }}>
        {url ? <img src={url} alt={`Dataset image ${img.file_name}`} className="absolute inset-0 h-full w-full" /> : <p className="p-4 text-sm text-[#C9CED3]">{imgErr || (img.verified ? "Loading..." : "Image is not in private storage yet. Annotations are shown below.")}</p>}
        {boxes && d ? d.annotations.filter((a) => a.bbox && a.physical !== false).map((a) => (
          <span key={a.ann_id} data-testid={`cal-box-${a.ann_id}`} title={`${a.category_name} - ${a.attributes?.Condition || ""}`}
            className={`pointer-events-none absolute border-2 ${a.attributes?.Condition === "Bad" ? "border-[#E5484D]" : "border-[#4CC38A]"} ${a.virtual_baseplate ? "border-dashed" : ""}`}
            style={{ left: `${(a.bbox[0] / W) * 100}%`, top: `${(a.bbox[1] / H) * 100}%`, width: `${(a.bbox[2] / W) * 100}%`, height: `${(a.bbox[3] / H) * 100}%` }} />
        )) : null}
      </div>
      <p className="text-[12px] text-[#59636B]">Solid green = Good, solid red = Bad, dashed = virtual baseplate.</p>
      {err ? <Banner tone="error" text={err} /> : null}
      {d ? (
        <ul data-testid="cal-annotations" className="max-h-56 divide-y divide-[#EEF0F1] overflow-auto text-sm">
          {d.annotations.map((a) => (
            <li key={a.ann_id} className="flex flex-wrap gap-x-3 py-1">
              <span className="font-medium">{a.category_name}</span>
              <span>{a.attributes?.Condition || "-"}</span>
              {a.attributes?.Type ? <span className="text-[#59636B]">Type {a.attributes.Type}</span> : null}
              {a.attributes?.occluded ? <span className="text-[#59636B]">occluded</span> : null}
              {a.virtual_baseplate ? <span className="text-[#7A4A00]">virtual baseplate</span> : null}
              {a.physical === false ? <span className="text-[#59636B]">whole-image label</span> : null}
            </li>
          ))}
        </ul>
      ) : <Loading />}
      <Mono label="Image details">{img.uuid} - coco {img.coco_id} - sha256 {img.sha256 || "-"} - {W}x{H}</Mono>
    </Modal>
  );
}

export default function ImageBrowser({ r }) {
  const [f, setF] = useState({ split: "", category_id: "", condition: "" });
  const [page, setPage] = useState(1);
  const [d, setD] = useState(null);
  const [err, setErr] = useState(null);
  const [open, setOpen] = useState(null);
  const [busy, setBusy] = useState(false);
  const seq = useRef(0);
  const load = useCallback(() => {
    const q = new URLSearchParams({ page, page_size: 24 });
    Object.entries(f).forEach(([k, v]) => v && q.set(k, v));
    const n = ++seq.current; // ignore out-of-order responses from earlier filter states
    setBusy(true);
    api(`/calibration/datasets/${r.uuid}/images?${q}`).then((x) => { if (n === seq.current) { setD(x); setErr(null); } }).catch((e) => n === seq.current && setErr(errText(e)))
      .finally(() => n === seq.current && setBusy(false));
  }, [r.uuid, f, page]);
  useEffect(() => { load(); }, [load]);
  const set = (k) => (v) => { setF((p) => ({ ...p, [k]: v })); setPage(1); };
  const pages = d ? Math.max(1, Math.ceil(d.total / d.page_size)) : 1;
  return (
    <Card testid="cal-images" className="space-y-3">
      <H2>Image browser</H2>
      <div className="grid gap-3 sm:grid-cols-3">
        <Select id="cal-f-split" testid="cal-filter-split" label="Split" value={f.split} onChange={set("split")} options={[["", "All"], ["train", "Train"], ["val", "Val (locked test)"]]} />
        <Select id="cal-f-cat" testid="cal-filter-category" label="Category" value={f.category_id} onChange={set("category_id")} options={[["", "All"], ...(r.stats?.categories || []).map((c) => [String(c.category_id), c.name])]} />
        <Select id="cal-f-cond" testid="cal-filter-condition" label="Condition" value={f.condition} onChange={set("condition")} options={[["", "Any"], ["Good", "Good"], ["Bad", "Bad"]]} />
      </div>
      {err ? <Banner tone="error" testid="cal-images-error" text={err} /> : null}
      {!d ? <Loading /> : (
        <>
          <p data-testid="cal-images-total" aria-live="polite" className="text-sm text-[#59636B]">{busy ? "Updating. Showing previous results. " : ""}{num(d.total)} images - page {d.page} of {pages}</p>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-6 xl:grid-cols-8">{d.images.map((i) => <Thumb key={i.uuid} img={i} onOpen={setOpen} />)}</div>
          <div className="flex items-center gap-2">
            <Btn small kind="secondary" icon={ChevronLeft} testid="cal-images-prev" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</Btn>
            <Btn small kind="secondary" icon={ChevronRight} testid="cal-images-next" disabled={page >= pages} onClick={() => setPage(page + 1)}>Next</Btn>
          </div>
        </>
      )}
      {open ? <Detail rid={r.uuid} img={open} onClose={() => setOpen(null)} /> : null}
    </Card>
  );
}
