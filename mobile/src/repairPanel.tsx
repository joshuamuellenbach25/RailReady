// Phase 15 steps 2-3 inside the existing inspection screen: actual work, a manual defect, and the one Finish repair tap.
// Everything saves on the phone first (repo.saveVisit) and sends with the existing queue. No AI here.
import { useEffect, useState } from "react";
import { View } from "react-native";
import { api } from "@/src/api";
import * as repo from "@/src/local/repo";
import { syncAll } from "@/src/sync";
import { Banner, Btn, Card, Input, T } from "@/src/ui";
import { storage } from "@/src/utils/storage";

const KINDS: repo.WorkItem["kind"][] = ["work", "material", "labor", "equipment"];
type RateItem = { key: string; description: string; unit: string | null };

export function RepairPanel({ uid, visit, onChange }: { uid: string; visit: repo.LocalVisit; onChange: () => void }) {
  const r = visit.repair!;
  const done = r.finish;
  const [w, setW] = useState({ kind: "work" as repo.WorkItem["kind"], description: "", quantity: "", unit: "each", rate_key: null as string | null });
  const [defect, setDefect] = useState("");
  const [date, setDate] = useState(r.completion_date || new Date().toISOString().slice(0, 10));
  const [msg, setMsg] = useState<string | null>(null);
  const [items, setItems] = useState<RateItem[]>([]);
  const [blockers, setBlockers] = useState<string[] | null>(null);
  const [docs, setDocs] = useState<{ kind: string; title: string; status: string; blockers: string[] }[] | null>(null);

  useEffect(() => {
    storage.getItem<string | null>(`operators:${uid}`, null).then((s) => {
      const op = s ? (JSON.parse(s) as { uuid: string; rate_items?: RateItem[] }[]).find((o) => o.uuid === r.operator_id) : null;
      setItems(op?.rate_items || []);
    });
  }, [uid, r.operator_id]);
  useEffect(() => {
    if (visit.repair_sync !== "Verified") return;
    api(`/repairs/${visit.uuid}`).then((d) => {
      setBlockers(d.blockers.submit.filter((b: string) => b !== "You need office access to submit invoices."));
      setDocs(d.documents_model || null);
    }).catch(() => {});
  }, [visit.uuid, visit.repair_sync]);

  async function save(next: repo.LocalRepair, note: string) {
    await repo.saveVisit(uid, { ...visit, repair: next, repair_sync: "Saved" });
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
  async function finish() {
    if (!r.work.length) return setMsg("Add the actual work before finishing.");
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) return setMsg("Completion date must look like 2026-10-25.");
    await save({ ...r, completion_date: date, finish: true, finished_at_client: new Date().toISOString() }, "Repair finished. Saved on phone.");
  }

  return (
    <Card testID="repair-panel">
      <T bold size={17}>Repair: {r.operator_name || "Not set"}</T>
      <T muted size={13} testID="repair-refs">PO {r.po || "Not set"} - {r.railroad || "Not set"} - Track {r.track || "Not set"} - MP {r.milepost || "Not set"}</T>
      {msg ? <Banner testID="repair-message" tone="info" icon="content-save-check-outline" text={msg} /> : null}
      <T bold>Actual work</T>
      {r.work.length ? r.work.map((x, i) => <T key={x.uuid} testID={`repair-work-${i}`}>{x.kind}: {x.description} - {x.quantity} {x.unit}</T>) : <T muted testID="repair-work-empty">No work recorded yet.</T>}
      {!done ? (
        <View style={{ gap: 8 }}>
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
          <Input testID="repair-date-input" label="Completion date (YYYY-MM-DD)" value={date} onChangeText={setDate} />
          <Btn testID="repair-finish-button" title="Finish repair" onPress={finish} />
        </View>
      ) : (
        <T testID="repair-finished" bold>Finished {r.completion_date} - {visit.repair_sync === "Verified" ? "Sent" : "Saved on phone"}</T>
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
