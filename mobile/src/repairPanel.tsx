// Phase 15 steps 2-3 inside the existing inspection screen: actual work, a manual defect, and the one Finish repair tap.
// Everything saves on the phone first (repo.saveVisit) and sends with the existing queue. No AI here.
import { useEffect, useState } from "react";
import { View } from "react-native";
import { api } from "@/src/api";
import { LOC_FIELDS, locFieldError } from "@/src/geo";
import * as repo from "@/src/local/repo";
import { syncAll } from "@/src/sync";
import { Banner, Btn, Card, Input, T } from "@/src/ui";
import { storage } from "@/src/utils/storage";

const hasCoords = (l: any) => !!l && Number.isFinite(l.lat) && Number.isFinite(l.lon) && Math.abs(l.lat) <= 90 && Math.abs(l.lon) <= 180;

const KINDS: repo.WorkItem["kind"][] = ["work", "material", "labor", "equipment"];
type RateItem = { key: string; description: string; unit: string | null };

export function RepairPanel({ uid, visit, onChange }: { uid: string; visit: repo.LocalVisit; onChange: () => void }) {
  const r = visit.repair!;
  const done = r.finish;
  const [w, setW] = useState({ kind: "work" as repo.WorkItem["kind"], description: "", quantity: "", unit: "each", rate_key: null as string | null });
  const [defect, setDefect] = useState("");
  const [date, setDate] = useState(r.completion_date || new Date().toISOString().slice(0, 10));
  const [po, setPo] = useState(r.po || "");
  const [loc, setLoc] = useState<Record<string, string>>({ railroad: r.railroad || "", track: r.track || "", milepost: r.milepost || "" });
  const [req, setReq] = useState<{ fields: string[]; name: string } | null>(null);
  const [reqError, setReqError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [items, setItems] = useState<RateItem[]>([]);
  const [blockers, setBlockers] = useState<string[] | null>(null);
  const [docs, setDocs] = useState<{ kind: string; title: string; status: string; blockers: string[] }[] | null>(null);

  useEffect(() => { setPo(r.po || ""); }, [visit.uuid, r.po]);

  useEffect(() => {
    let active = true;
    const saved = visit.repair_requirements?.operator_id === r.operator_id ? visit.repair_requirements : null;
    let known = !!saved;
    setReq(saved);
    setReqError(null);
    const apply = (ops: any[]) => {
      const op = ops.find((o) => o.uuid === r.operator_id);
      if (!active || !op) return false;
      setItems(op.rate_items || []);
      if (op.location_requirements_version !== 1) return false; // older caches omit form-derived requirements
      known = true;
      setReq({ fields: op.required_location_fields || [], name: op.short_name || op.name || "The operator" });
      setReqError(null);
      return true;
    };
    (async () => {
      try {
        const s = await storage.getItem<string | null>(`operators:${uid}`, null);
        if (s && !saved) apply(JSON.parse(s));
      } catch { /* an unreadable cache is not permission to finish without requirements */ }
      try {
        const ops = await api("/operators");
        if (!active) return;
        if (!apply(ops)) {
          setReq(null);
          setReqError("Operator requirements are unavailable. Ask the office to check this operator.");
          return;
        }
        await storage.setItem(`operators:${uid}`, JSON.stringify(ops));
      } catch {
        if (active && !known) setReqError("Connect once to load this operator's requirements. Your work remains saved.");
      }
    })();
    return () => { active = false; };
  }, [uid, r.operator_id, visit.repair_requirements]);
  useEffect(() => {
    if (visit.repair_sync !== "Verified") return;
    api(`/repairs/${visit.uuid}`).then((d) => {
      setBlockers(d.blockers.submit.filter((b: string) => b !== "You need office access to submit invoices."));
      setDocs(d.documents_model || null);
    }).catch(() => {});
  }, [visit.uuid, visit.repair_sync]);

  async function save(next: repo.LocalRepair, note: string) {
    await repo.saveVisit(uid, { ...visit, repair: { ...next, po: po.trim() || null }, repair_sync: "Saved", repair_finish_blockers: undefined,
      ...(req && r.operator_id ? { repair_requirements: { ...req, operator_id: r.operator_id } } : {}) });
    setMsg(note);
    onChange();
    syncAll(uid).catch(() => {});
  }
  async function addWork() {
    if (!w.description.trim() || !(Number(w.quantity) > 0) || !w.unit.trim()) return setMsg("Enter what was done, a quantity above 0 and a unit.");
    await save({ ...r, work: [...r.work, { uuid: `wi-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`, kind: w.kind, description: w.description.trim(),
      quantity: w.quantity.trim(), unit: w.unit.trim(), rate_key: w.rate_key }] }, "Saved on phone");
    setW({ ...w, description: "", quantity: "", rate_key: null });
  }
  async function addDefect() {
    if (!defect.trim()) return;
    await repo.addObservation(uid, visit.uuid, { kind: "finding", text: defect.trim() });
    setDefect("");
    setMsg("Defect saved on phone");
    onChange();
    syncAll(uid).catch(() => {});
  }
  // Only operator-required railroad/track/milepost gate Finish; a coordinate location satisfies the location otherwise.
  const missing = LOC_FIELDS.filter(([k]) => req?.fields.includes(k)).map(([k, label]) => {
    const e = loc[k].trim() ? locFieldError(k, loc[k]) : `${label} missing. ${req!.name} requires it before Finish.`;
    return e;
  }).filter(Boolean) as string[];
  async function finish() {
    if (!req) return setMsg(reqError || "Loading operator requirements. Your work remains saved.");
    if (!po.trim() || po.trim().length > 80) return setMsg("Enter a contract or PO reference, up to 80 characters, before finishing.");
    if (!r.work.length) return setMsg("Add the actual work before finishing.");
    const parsed = new Date(`${date}T00:00:00Z`);
    const tomorrow = new Date();
    tomorrow.setUTCDate(tomorrow.getUTCDate() + 1);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date) || !Number.isFinite(parsed.getTime()) || parsed.toISOString().slice(0, 10) !== date
      || date > tomorrow.toISOString().slice(0, 10)) return setMsg("Enter a valid completion date, no later than tomorrow.");
    if (missing.length) return setMsg(missing.join(" "));
    const set = Object.fromEntries(LOC_FIELDS.filter(([k]) => loc[k].trim()).map(([k]) => [k, loc[k].trim()]));
    await save({ ...r, ...set, completion_date: date, finish: true, finished_at_client: new Date().toISOString() }, "Completion queued. Saved on phone; awaiting server confirmation.");
  }

  return (
    <Card testID="repair-panel">
      <T bold size={17}>Repair: {r.operator_name || "Not set"}</T>
      <T muted size={13} testID="repair-refs">PO {r.po || "Not set"} - {r.railroad || "Not set"} - Track {r.track || "Not set"} - MP {r.milepost || "Not set"}</T>
      {visit.links?.work_order_number ? <T size={13} testID="repair-workorder">From work order {visit.links.work_order_number}</T> : null}
      {visit.links?.location ? <T size={13} testID="repair-location">Location: {Number(visit.links.location.lat).toFixed(6)}, {Number(visit.links.location.lon).toFixed(6)} ({visit.links.location.method_label})</T> : null}
      {!done ? <T size={13} bold testID="repair-next-action">Next: record the actual work, then tap Finish repair.</T> : null}
      {msg && !visit.repair_finish_blockers?.length ? <Banner testID="repair-message" tone="info" icon="content-save-check-outline" text={msg} /> : null}
      {visit.repair_finish_blockers?.length ? <Banner testID="repair-finish-rejected" tone="warning" icon="alert-circle-outline"
        text={`Repair remains open: ${visit.repair_finish_blockers.join(" ")}`} /> : null}
      <T bold>Actual work</T>
      {r.work.length ? r.work.map((x, i) => <T key={x.uuid} testID={`repair-work-${i}`}>{x.kind}: {x.description} - {x.quantity} {x.unit}</T>) : <T muted testID="repair-work-empty">No work recorded yet.</T>}
      {!done ? (
        <View style={{ gap: 8 }}>
          <Input testID="repair-po-input" label="Contract or PO number (required)" value={po} onChangeText={setPo} />
          <Btn small testID="repair-po-save" kind="secondary" title="Save reference" disabled={!po.trim() || po.trim().length > 80 || po.trim() === (r.po || "")}
            onPress={() => save(r, "Reference saved on phone.")} />
          {items.length ? <T muted size={13}>Pick a rate item, or type the work below.</T> : null}
          {items.map((it) => <Btn key={it.key} small testID={`repair-rate-item-${it.key}`} kind={w.rate_key === it.key ? "primary" : "secondary"}
            title={`${it.description} (${it.unit || "Not set"})`} onPress={() => setW({ ...w, kind: "work", description: it.description, unit: it.unit || "", rate_key: it.key })} />)}
          <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6 }}>
            {KINDS.map((k) => <Btn key={k} small testID={`repair-kind-${k}`} kind={w.kind === k ? "primary" : "secondary"} title={k} onPress={() => setW({ ...w, kind: k })} />)}
          </View>
          <Input testID="repair-work-desc-input" label="What was done or used" value={w.description} onChangeText={(s) => setW({ ...w, description: s, rate_key: null })} />
          <Input testID="repair-work-qty-input" label="Quantity" keyboardType="decimal-pad" value={w.quantity} onChangeText={(s) => setW({ ...w, quantity: s })} />
          <Input testID="repair-work-unit-input" label="Unit" value={w.unit} onChangeText={(s) => setW({ ...w, unit: s })} />
          <Btn testID="repair-add-work-button" kind="secondary" title="Add work" onPress={addWork} />
          <Input testID="repair-defect-input" label="Defect found (manual)" value={defect} onChangeText={setDefect} multiline />
          <Btn testID="repair-add-defect-button" kind="secondary" title="Add defect" onPress={addDefect} />
          {LOC_FIELDS.filter(([k]) => req?.fields.includes(k) || (k !== "track" && !hasCoords((r as any).location))).map(([k, label]) => (
            <Input key={k} testID={`repair-${k}-input`} label={req?.fields.includes(k) ? `${label} (required by ${req!.name})` : `${label} (location: add with ${k === "railroad" ? "milepost" : "railroad"} if there is no pin)`}
              value={loc[k]} onChangeText={(s) => setLoc({ ...loc, [k]: s })} />
          ))}
          <Input testID="repair-date-input" label="Completion date (YYYY-MM-DD)" value={date} onChangeText={setDate} />
          {missing.length ? <T size={13} testID="repair-finish-blocked">{missing.join(" ")}</T> : null}
          {!req ? <T size={13} testID="repair-requirements-pending">{reqError || "Loading operator requirements..."}</T> : null}
          <Btn testID="repair-finish-button" title="Finish repair" disabled={!req || !po.trim() || po.trim().length > 80 || missing.length > 0} onPress={finish} />
        </View>
      ) : (
        <T testID="repair-finished" bold>{visit.repair_sync === "Verified" ? `Finished ${r.completion_date} - Sent` : `Completion queued for ${r.completion_date} - Saved on phone`}</T>
      )}
      {done ? (blockers === null ? <T muted size={13} testID="repair-blockers-pending">Office blockers show once the repair is sent.</T>
        : docs ? (
          <View testID="repair-documents" style={{ gap: 8 }}>
            {docs.map((x) => (
              <View key={x.kind} testID={`repair-doc-${x.kind}`} style={{ gap: 2 }}>
                <T bold>{x.title} - {x.status}</T>
                {x.blockers.length ? x.blockers.map((b, i) => <T key={b} size={13} testID={`repair-doc-${x.kind}-blocker-${i}`}>- {b}</T>)
                  : <T size={13} testID={`repair-doc-${x.kind}-ok`}>No blockers.</T>}
              </View>
            ))}
          </View>
        )
        : blockers.length ? (
          <View testID="repair-blockers" style={{ gap: 4 }}>
            <T bold>Before the invoice can be sent</T>
            {blockers.map((b, i) => <T key={b} size={13} testID={`repair-blocker-${i}`}>- {b}</T>)}
          </View>
        ) : <T testID="repair-blockers-none">No blockers.</T>) : null}
    </Card>
  );
}
