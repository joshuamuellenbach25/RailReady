import { router, useFocusEffect, useLocalSearchParams } from "expo-router";
import { useCallback, useState } from "react";
import { api, errText } from "@/src/api";
import { useAuth } from "@/src/auth";
import * as repo from "@/src/local/repo";
import { Badge, Btn, Card, fmt, H, Input, Row, Screen, T } from "@/src/ui";

export default function Site() {
  const { id, name: siteName } = useLocalSearchParams<{ id: string; name?: string }>();
  const { user } = useAuth();
  const uid = user ? user.uuid : "";
  const [bundle, setBundle] = useState<repo.Bundle | null>(null);
  const [visits, setVisits] = useState<repo.LocalVisit[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [title, setTitle] = useState("");

  const load = useCallback(async () => {
    setBundle(await repo.getBundle(uid, id));
    setVisits((await repo.listVisits(uid)).filter((v) => v.site_id === id).reverse());
  }, [uid, id]);
  // REQ-195: prepare automatically in the background on site open; no button gate (REQ-197).
  const prepare = useCallback(async () => {
    setBusy(true);
    try {
      const data = await api(`/sites/${id}/bundle`);
      setBundle(await repo.saveBundle(uid, id, data)); // "Available offline" only after local commit is read back
      setErr(null);
    } catch (e) {
      setErr(errText(e));
    } finally {
      setBusy(false);
    }
  }, [uid, id]);
  useFocusEffect(useCallback(() => { load().then(() => prepare()); }, [load, prepare]));

  async function start() {
    // Capture proceeds regardless of preparation state; an uncached site starts a provisional draft.
    const name = bundle?.data?.site?.name || String(siteName || "Site (details not yet on this device)");
    const v = await repo.createVisit(uid, id, name, title.trim() || `Inspection ${new Date().toLocaleDateString()}`);
    router.push(`/visit/${v.uuid}`);
  }

  const d = bundle?.data;
  return (
    <Screen testID="site-screen" title={d?.site?.name || String(siteName || "Site")} subtitle={d?.customer?.name}>
      <Row>
        {bundle ? (
          <Badge testID="site-offline-ready-badge" label="Available offline" icon="check" />
        ) : (
          <Badge testID="site-preparing-badge" label={busy ? "Preparing for offline..." : "Not yet available offline"} icon={busy ? "cloud-download" : "cloud-off-outline"} />
        )}
        {bundle ? <T testID="site-prepared-at" muted size={13}>Updated {fmt(bundle.prepared_at)}</T> : null}
      </Row>
      {err && !bundle ? <T testID="site-prepare-error" muted size={13}>No connection right now. You can still start an inspection - it&apos;s saved on this phone.</T> : null}
      <Card testID="site-start-card">
        <Input testID="site-visit-title-input" label="Inspection title (optional)" value={title} onChangeText={setTitle} placeholder="e.g. Spur 1 tie survey" />
        <Btn testID="site-start-visit-button" title="Start inspection" icon="clipboard-plus" onPress={start} />
      </Card>
      {d ? (
        <>
          <Card>
            <H>Site</H>
            <T>{d.site.address}</T>
            <T muted>Access: {d.site.access_notes || "-"}</T>
            <T muted>Tracks: {d.tracks.map((t: any) => t.name).join(", ")}</T>
          </Card>
          {d.site.prior_findings?.length ? (
            <Card testID="site-prior-findings">
              <H>Prior findings</H>
              {d.site.prior_findings.map((f: any) => (
                <Row key={f.id}>
                  <Badge label={f.status} icon="history" tone="warning" />
                  <T style={{ flex: 1 }}>{f.text} ({f.recorded_at})</T>
                </Row>
              ))}
            </Card>
          ) : null}
        </>
      ) : null}
      {visits.length ? <H>Inspections at this site</H> : null}
      {visits.map((v) => (
        <Card key={v.uuid} testID={`site-visit-${v.uuid}`} onPress={() => router.push(`/visit/${v.uuid}`)}>
          <T bold>{v.title}</T>
          <T muted size={13}>Resume inspection</T>
          <Row>
            <Badge label={v.status} />
            <T muted size={12}>{fmt(v.created_at)}</T>
          </Row>
        </Card>
      ))}
    </Screen>
  );
}
