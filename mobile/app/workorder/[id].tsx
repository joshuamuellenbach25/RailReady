import { useFocusEffect, useLocalSearchParams } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import { Linking, View } from "react-native";
import { api, errText, paperworkUrl } from "@/src/api";
import { Badge, Banner, Btn, Card, fmt, H, Input, Loading, Row, Screen, T } from "@/src/ui";

const NEXT: Record<string, string> = { "Not arranged": "Requested", Requested: "Confirmed" };

export default function WorkOrder() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const [w, setW] = useState<any>(null);
  const [date, setDate] = useState("");
  const [msg, setMsg] = useState<{ tone: any; text: string } | null>(null);
  const [saving, setSaving] = useState(false);
  const load = useCallback(async () => {
    try {
      const r = await api(`/work-orders/${id}`);
      setW(r);
      setDate(r.scheduled_date || "");
    } catch (e) {
      setMsg({ tone: "error", text: errText(e) });
    }
  }, [id]);
  useFocusEffect(useCallback(() => { load(); }, [load]));
  const [ops, setOps] = useState<{ uuid: string; name: string }[]>([]);
  const [op, setOp] = useState<string | null>(null);
  const [po, setPo] = useState("");
  useEffect(() => { api("/operators").then(setOps).catch(() => {}); }, []);
  async function startRepair() {
    if (saving || !op || !po.trim() || po.trim().length > 80) return;
    setSaving(true); // single flight; the server returns the existing repair on a repeat (unique work_order_id)
    try {
      const r = await api(`/work-orders/${id}/start-repair`, { method: "POST", body: { operator_id: op, po: po.trim() } });
      setMsg({ tone: "success", text: r.created ? "Repair started. It is on the foreman's phone." : "Repair already started." });
    } catch (e) {
      setMsg({ tone: "error", text: errText(e) });
    }
    await load();
    setSaving(false);
  }
  async function patch(body: any) {
    if (saving) return;
    setSaving(true); // REQ-162: one planning save in flight at a time
    try {
      await api(`/work-orders/${id}`, { method: "PATCH", body: { expected_revision: w.revision, ...body } });
      setMsg({ tone: "success", text: "Saved" });
    } catch (e) {
      setMsg({ tone: "error", text: errText(e) });
    }
    await load();
    setSaving(false);
  }
  if (!w) return <Screen title="Work order">{msg ? <Banner tone="error" text={msg.text} /> : <Loading />}</Screen>;
  const fs = w.frozen_scope;
  return (
    <Screen testID="workorder-screen" title={`Work order ${w.number}`} subtitle={`Planning - from accepted version ${fs.version_no}`}>
      {msg ? <Banner testID="workorder-message" tone={msg.tone} icon="information" text={msg.text} /> : null}
      <Card testID="workorder-next">
        <T bold testID="workorder-next-action">Next: {w.next_action}</T>
        <T size={14} testID="workorder-location">{w.location ? `Location: ${Number(w.location.lat).toFixed(6)}, ${Number(w.location.lon).toFixed(6)} (${w.location.method_label})${[w.location.railroad, w.location.subdivision, w.location.milepost ? `MP ${w.location.milepost}` : null].filter(Boolean).length ? ` - ${[w.location.railroad, w.location.subdivision, w.location.milepost ? `MP ${w.location.milepost}` : null].filter(Boolean).join(", ")}` : ""}` : "Location: Not set"}</T>
        {w.repair ? <T testID="workorder-repair-status">Repair {w.repair.status} ({w.repair.uuid}). The foreman records the work on their phone.</T> : null}
        {w.repair ? (
          <View testID="workorder-paperwork" style={{ gap: 8, marginTop: 8 }}>
            <T bold>Paperwork PDFs</T>
            {(["work_order", "invoice", "packet"] as const).map((doc) => (
              <View key={doc} style={{ flexDirection: "row", gap: 8, alignItems: "center" }}>
                <T size={14} style={{ flex: 1 }}>{doc === "work_order" ? "Work order form" : doc === "invoice" ? "Invoice" : "Complete packet"}</T>
                <Btn small testID={`workorder-preview-${doc}`} title="Preview" icon="eye-outline"
                  onPress={() => Linking.openURL(paperworkUrl(w.repair.visit_id || `wo-repair-${id}`, doc, false)).catch((e) => setMsg({ tone: "error", text: errText(e) }))} />
                <Btn small testID={`workorder-download-${doc}`} title="Download" icon="download"
                  onPress={() => Linking.openURL(paperworkUrl(w.repair.visit_id || `wo-repair-${id}`, doc, true)).catch((e) => setMsg({ tone: "error", text: errText(e) }))} />
              </View>
            ))}
          </View>
        ) : null}
        {w.start_repair_eligible ? (
          <View style={{ gap: 8 }}>
            <T bold>Start repair: pick the operator</T>
            <Row>{ops.map((o) => <Btn key={o.uuid} small testID={`workorder-operator-${o.uuid}`} kind={op === o.uuid ? "primary" : "secondary"} title={o.name} onPress={() => setOp(o.uuid)} />)}</Row>
            <Input testID="workorder-po-input" label="Contract or PO number (required)" value={po} onChangeText={setPo} />
            <Btn testID="workorder-start-repair-button" icon="wrench" title={saving ? "Starting..." : "Start repair"} disabled={saving || !op || !po.trim() || po.trim().length > 80} onPress={startRepair} />
          </View>
        ) : null}
      </Card>
      <Card testID="workorder-frozen-scope">
        <H>Accepted scope (frozen)</H>
        {fs.findings.map((f: string) => <T key={f}>- {f}</T>)}
        {fs.not_inspected.map((n: any) => <T key={n.area} muted>Not inspected: {n.area} - {n.reason}</T>)}
        {fs.ties_supplied_by_customer ? <Badge label="Ties supplied by customer" icon="truck" /> : null}
        {fs.lines.map((l: any) => <T key={l.description} muted>{l.description}: {l.quantity} {l.unit} - ${l.line_total}</T>)}
        <T bold>Total ${fs.totals.total} USD</T>
      </Card>
      <Card testID="workorder-planning">
        <H>Planning (editable)</H>
        <T bold>Crew</T>
        <Row>{w.crews.map((c: any) => <Btn key={c.uuid} small disabled={saving} testID={`workorder-crew-${c.uuid}`} kind={w.crew_id === c.uuid ? "primary" : "secondary"} title={c.name} onPress={() => patch({ crew_id: c.uuid })} />)}</Row>
        <Input testID="workorder-date-input" label="Planned date (YYYY-MM-DD)" value={date} onChangeText={setDate} />
        <Btn small kind="secondary" testID="workorder-date-save" title={saving ? "Saving..." : "Save date"} icon="calendar" disabled={saving} onPress={() => patch({ scheduled_date: date })} />
        <Row>
          <T bold>Access:</T>
          <Badge testID="workorder-access-status" label={w.access_status} icon="key" tone={w.access_status === "Confirmed" ? "success" : "warning"} />
        </Row>
        {NEXT[w.access_status] ? <Btn small disabled={saving} testID="workorder-access-next" title={`Mark access ${NEXT[w.access_status]}`} icon="arrow-right" onPress={() => patch({ access_status: NEXT[w.access_status] })} /> : null}
        {w.access_history.map((h: any, i: number) => <T key={i} muted size={12}>{h.from} = {h.to} by {h.by_name} at {fmt(h.at)}</T>)}
        <T muted size={12}>This is a planning record only. Access must be arranged by a person; it does not authorize work.</T>
      </Card>
    </Screen>
  );
}
