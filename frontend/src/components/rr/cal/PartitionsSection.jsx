import { useCallback, useEffect, useState } from "react";
import { Layers } from "lucide-react";
import { api, errText } from "@/lib/api";
import { ACTIVE, num, usePoll } from "@/lib/calibration";
import { Badge, Banner, Blocker, Btn, Card, Field, H2, Mono, fmt } from "../ui";
import { Mark } from "./Metrics";

function Partition({ id, onLoaded }) {
  const [p, setP] = useState(null);
  const [err, setErr] = useState(null);
  const load = useCallback(() => api(`/calibration/partitions/${id}`).then((x) => { setP(x); onLoaded(x); return `${x.status}`; }).catch((e) => setErr(errText(e))), [id, onLoaded]);
  useEffect(() => { load(); }, [load]);
  usePoll(load, !!p && ACTIVE.includes(p.status));
  if (err) return <Banner tone="error" text={err} />;
  if (!p) return null;
  const c = p.counts || {};
  const g = p.grouping || {};
  return (
    <li data-testid={`cal-partition-${p.version}`} className="space-y-2 rounded-md border border-[#D9DEE2] p-3 text-sm">
      <div className="flex flex-wrap items-center gap-2"><span className="font-medium">Partition v{p.version}</span><Badge label={p.status} />{g.kind ? <Badge label="Provisional" prefix="Grouping" /> : null}<span className="text-[13px] text-[#59636B]">{fmt(p.created_at)}</span></div>
      {p.status === "Complete" ? (
        <>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-1 sm:grid-cols-3">
            {[["Fit (train)", c.fit], ["Calibration (train)", c.calibration], ["Locked test (val)", c.test_locked], ["Quarantined images", c.quarantined], ["Groups", c.groups], ["Quarantined groups", c.quarantined_groups]].map(([l, v]) => (
              <div key={l}><dt className="text-[13px] text-[#59636B]">{l}</dt><dd className="font-mono">{num(v)}</dd></div>
            ))}
          </dl>
          <p data-testid={`cal-partition-leak-${p.version}`} className="flex flex-wrap items-center gap-2">Val images in fit or calibration: <span className="font-mono">{num(p.val_in_fit_or_calibration)}</span><Mark ok={p.val_in_fit_or_calibration === 0} yes="None, test stays locked" no="Leak, do not use" /></p>
          {g.kind ? <p className="text-[13px] text-[#59636B]">Grouping ({g.kind}): {g.perceptual_hash}; near-duplicates at hamming {"<="} {g.near_duplicate_hamming_max}; {g.sequence_rule}; {g.test_overlap_rule}.</p> : null}
        </>
      ) : null}
      <p className="text-[13px] text-[#59636B]">{p.test_policy} - Augmentation: {p.augmentation_policy}</p>
      <Mono label="Partition details">{p.uuid} - seed {p.config?.seed} - calibration fraction {p.config?.calibration_fraction} - membership sha256 {p.membership_sha256 || "-"}</Mono>
    </li>
  );
}

export default function PartitionsSection({ r, onPartitions }) {
  const [seed, setSeed] = useState("");
  const [frac, setFrac] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const [extra, setExtra] = useState([]);
  const ids = [...new Set([...(r.partitions || []).map((x) => (typeof x === "string" ? x : x.uuid)), ...extra])];
  const [loaded, setLoaded] = useState({});
  const onLoaded = useCallback((p) => setLoaded((m) => (m[p.uuid]?.status === p.status ? m : { ...m, [p.uuid]: p })), []);
  useEffect(() => { onPartitions(Object.values(loaded)); }, [loaded, onPartitions]);
  const complete = r.status === "Complete";
  async function create() {
    setBusy(true);
    setMsg(null);
    try {
      const body = { release_id: r.uuid, ...(seed ? { seed: Number(seed) } : {}), ...(frac ? { calibration_fraction: Number(frac) } : {}) };
      const x = await api("/calibration/partitions", { body });
      setExtra((e) => [...e, x.partition.uuid]);
      setMsg({ tone: "success", text: `Partition v${x.partition.version} queued.` });
    } catch (e) { setMsg({ tone: "error", text: errText(e) }); } finally { setBusy(false); }
  }
  return (
    <Card testid="cal-partitions" className="space-y-3">
      <H2>Partitions</H2>
      <p className="text-[13px] text-[#59636B]">Fit and calibration come from the source train split only; val is the locked final test. Partitions are immutable.</p>
      <div className="flex flex-wrap items-end gap-3">
        <Field id="cal-seed" testid="cal-partition-seed" label="Seed (optional)" type="number" value={seed} onChange={setSeed} />
        <Field id="cal-frac" testid="cal-partition-fraction" label="Calibration fraction (optional)" type="number" step="0.05" value={frac} onChange={setFrac} placeholder="0.25" />
        <Btn icon={Layers} testid="cal-partition-create" loading={busy} disabled={!complete} onClick={create}>Create partition</Btn>
      </div>
      {!complete ? <Blocker testid="cal-partition-blocker" text={`Needs a Complete release (currently ${r.status}).`} /> : null}
      {msg ? <Banner tone={msg.tone} text={msg.text} testid="cal-partition-message" /> : null}
      {ids.length ? <ul className="space-y-2">{ids.map((id) => <Partition key={id} id={id} onLoaded={onLoaded} />)}</ul> : <p data-testid="cal-partitions-empty" className="text-sm text-[#59636B]">No partitions yet.</p>}
    </Card>
  );
}
