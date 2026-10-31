import { Redirect, router, useFocusEffect } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/src/auth";
import * as repo from "@/src/local/repo";
import { getSyncError, isSyncing, subscribe, syncAll } from "@/src/sync";
import { Badge, Banner, Btn, Card, Empty, fmt, Row, Screen, T } from "@/src/ui";

const KIND: Record<string, string> = { "visit record": "Inspection", photo: "Photo", audio: "Voice note", note: "Note", measurement: "Measurement", location: "Location", "not inspected": "Not checked", urgent: "Urgent" };
type Item = { id: string; kind: string; visit: string; title: string; sync: repo.SyncInfo; at: string };

export default function Outbox() {
  const { user } = useAuth();
  const uid = user ? user.uuid : "";
  const [items, setItems] = useState<Item[]>([]);
  const [visits, setVisits] = useState<repo.LocalVisit[]>([]);
  const [syncing, setSyncing] = useState(false);
  const [syncError, setSyncError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const vs = await repo.listVisits(uid);
    const names = Object.fromEntries(vs.map((v) => [v.uuid, v.title]));
    const ev = await repo.listEvidence(uid);
    const ob = await repo.listObs(uid);
    const pins = await repo.listPins(uid);
    setVisits(vs);
    setItems([
      ...vs.map((v) => ({ id: v.uuid, kind: "visit record", visit: v.title, title: v.pending_permission ? `Permission change -> ${v.pending_permission}` : "Visit details", sync: v.pending_permission ? { ...v.sync, state: "Queued" as const } : v.sync, at: v.created_at })),
      ...ob.map((o) => ({ id: o.uuid, kind: o.kind.replace("_", " "), visit: names[o.visit_id], title: o.label || o.area || o.text || "", sync: o.sync, at: o.captured_at })),
      ...ev.map((e) => ({ id: e.uuid, kind: e.kind, visit: names[e.visit_id], title: e.kind === "note" ? e.text!.slice(0, 60) : e.filename, sync: e.sync, at: e.captured_at })),
      ...pins.map((p) => ({ id: p.id, kind: "location", visit: names[p.visit_id] || p.payload.name, title: p.payload.name, sync: p.sync, at: p.created_at })),
    ]);
    setSyncing(isSyncing());
    setSyncError(getSyncError(uid));
  }, [uid]);
  useFocusEffect(useCallback(() => { load(); }, [load]));
  useEffect(() => subscribe(load), [load]);
  useEffect(() => {
    const t = setInterval(() => { if (uid) syncAll(uid, false); }, 30_000); // automatic retry honoring backoff
    return () => clearInterval(t);
  }, [uid]);

  const pending = items.filter((i) => i.sync.state !== "Verified").length;
  const admin = !!user && user.role === "admin";
  if (!admin) return <Redirect href="/home" />; // diagnostics are admin-only (REQ-263); foremen only see the gentle home line // technical details (receipts, errors) are admin-only (REQ-258)
  return (
    <Screen testID="outbox-screen" title="Backup status" subtitle={syncError ? "Some saved locations need attention" : pending ? `${pending} item${pending === 1 ? "" : "s"} not backed up yet` : "Everything is backed up"}
      footer={<Btn testID="outbox-sync-now-button" title={syncing ? "Backing up..." : "Back up now"} icon="cloud-upload-outline" loading={syncing} onPress={() => syncAll(uid, true)} />}>
      <T muted size={13}>Everything you capture is kept safe on this phone and backed up automatically when you have a connection.</T>
      {syncError ? <Banner testID="outbox-location-sync-error" tone="warning" icon="map-marker-alert-outline" text={syncError} /> : null}
      {visits.filter((v) => v.manifest && admin).map((v) => (
        <Card key={v.uuid} testID={`outbox-transfer-${v.uuid}`}>
          <T bold>{v.title}</T>
          <Row>
            <Badge testID={`outbox-transfer-state-${v.uuid}`} label={v.manifest!.state} />
            {v.manifest!.missing ? <Badge label={`${v.manifest!.missing} missing`} tone="error" icon="alert-circle-outline" /> : null}
          </Row>
          {v.manifest!.receipt_id ? <T testID={`outbox-receipt-${v.uuid}`} muted size={12}>Receipt {v.manifest!.receipt_id}</T> : null}
        </Card>
      ))}
      {!items.length ? <Empty testID="outbox-empty" icon="tray" text="Nothing captured yet." /> : null}
      {items.map((i) => (
        <Card key={i.id} testID={`outbox-item-${i.id}`}>
          <Row style={{ flexWrap: "nowrap" }}>
            <T bold style={{ flex: 1 }}>{KIND[i.kind] || "Item"}</T>
            <Badge testID={`outbox-item-state-${i.id}`} label={i.sync.state} />
          </Row>
          {i.title && i.kind !== "visit record" ? <T numberOfLines={2} size={14}>{i.kind === "photo" || i.kind === "audio" ? "" : i.title}</T> : null}
          <T muted size={12}>{i.visit} - {fmt(i.at)}</T>
          {admin && i.sync.error ? <T testID={`outbox-item-error-${i.id}`} muted size={12}>Last error: {i.sync.error}{i.sync.next_at ? ` - next retry ${fmt(i.sync.next_at)}` : ""}</T> : null}
          {i.sync.state === "Blocked" || i.sync.state === "Retry wait" ? <Btn small kind="secondary" testID={`outbox-retry-${i.id}`} title="Try again" icon="refresh" onPress={() => syncAll(uid, true)} /> : null}
        </Card>
      ))}
      <Btn kind="ghost" testID="outbox-home-button" title="Back to My work" icon="home-outline" onPress={() => router.replace("/home")} />
    </Screen>
  );
}
