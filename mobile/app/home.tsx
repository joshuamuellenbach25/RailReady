import { router, useFocusEffect, useLocalSearchParams } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";
import { AppState } from "react-native";
import { api, API, errText } from "@/src/api";
import { useAuth } from "@/src/auth";
import * as repo from "@/src/local/repo";
import { getSyncError, subscribe, syncAll } from "@/src/sync";
import { safeReload } from "@/src/reload";
import { Banner, Btn, Card, Fab, fmt, H, Input, Row, Screen, Sheet, T } from "@/src/ui";
import { volumeSupported } from "@/src/volumeCapture";
import { backgroundStatus, bgSupported } from "@/src/background";
import { storage } from "@/src/utils/storage";

export function useSignOut() {
  const { user, signOut } = useAuth();
  const uid = user ? user.uuid : "";
  const [warn, setWarn] = useState<number | null>(null);
  async function start() {
    if (!user) return;
    const n = user.role === "foreman" ? await repo.unsyncedCount(user.uuid) : 0;
    if (n > 0) setWarn(n);
    else await finish();
  }
  async function finish() {
    setWarn(null);
    await signOut();
    router.replace("/login");
  }
  const sheet = (
    <Sheet visible={warn !== null} onClose={() => setWarn(null)} title="Some items aren't backed up yet" testID="signout-warning-sheet">
      <T>{`${warn} item(s) are only on this phone so far.`}</T>
      <T>They stay safely on this phone, locked to your account. They&apos;ll be backed up next time you sign in with a connection.</T>
      <Btn testID="signout-sync-first-button" title="Try again now" icon="refresh" onPress={async () => { await syncAll(uid, true).catch(() => {}); const n = await repo.unsyncedCount(uid); setWarn(n ? n : null); }} />
      <Btn testID="signout-confirm-button" kind="danger" title="Sign out anyway" icon="logout" onPress={finish} />
    </Sheet>
  );
  return { start, sheet };
}

// Phase 16: repairs started in the office from a work order (Start repair) appear on the foreman's phone once.
// They arrive already sent (Verified); the existing repair panel then records the work and the Finish tap.
async function importAssignedRepairs(uid: string) {
  const list: any[] = await api("/repairs-assigned");
  if (list.length) await storage.setItem(`operators:${uid}`, JSON.stringify(await api("/operators"))); // rate items for the repair panel
  let n = 0;
  for (const a of list) {
    const local = await repo.getLocalVisit(uid, a.visit.uuid);
    const r = a.repair;
    const loc = r.location;
    const links = { work_order_id: r.work_order_id, work_order_number: a.work_order?.number || null, repair_id: r.uuid,
      location: loc ? { lat: loc.lat, lon: loc.lon, method_label: loc.method_label, railroad: loc.railroad, subdivision: loc.subdivision, milepost: loc.milepost } : null };
    if (local) {
      if (!local.links?.work_order_id) await repo.saveVisit(uid, { ...local, links });
      continue;
    }
    await repo.saveVisit(uid, {
      uuid: a.visit.uuid, site_id: a.visit.site_id, site_name: a.site_name || "", title: a.visit.title, processing_permission: a.visit.processing_permission || "Policy",
      server_revision: a.visit.revision, status: a.visit.status, created_at: a.visit.created_at, sync: { state: "Verified", attempts: 0 }, links,
      repair: { operator_id: r.operator_id, operator_name: r.operator_name, po: r.po, railroad: r.railroad, track: r.track, milepost: r.milepost,
        work: r.work || [], completion_date: r.completion_date, finish: !!r.completion, finished_at_client: r.completion?.confirmed_at_client || null },
      repair_sync: "Verified",
    });
    n++;
  }
  return n;
}

export default function Home() {
  const { user, workspace } = useAuth();
  const [sites, setSites] = useState<any[] | null>(null);
  const [bundles, setBundles] = useState<Record<string, repo.Bundle>>({});
  const [visits, setVisits] = useState<repo.LocalVisit[]>([]);
  const [unsynced, setUnsynced] = useState(0);
  const [syncError, setSyncError] = useState<string | null>(null);
  const [offline, setOffline] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [menu, setMenu] = useState(false);
  const [volOk, setVolOk] = useState(false); // runtime-detected; false in Expo Go / web / PWA (REQ-1315)
  const [volHelp, setVolHelp] = useState(false);
  useEffect(() => {
    volumeSupported().then(setVolOk);
  }, []);
  const [newSite, setNewSite] = useState(false);
  const { newsite } = useLocalSearchParams<{ newsite?: string }>();
  useEffect(() => { if (newsite === "1") { setNewSite(true); router.setParams({ newsite: undefined }); } }, [newsite]); // map "New site" option
  const [ns, setNs] = useState({ name: "", address: "", description: "" });
  const [nsErr, setNsErr] = useState<string | null>(null);
  const nsBusy = useRef(false);
  async function saveNewSite() {
    if (nsBusy.current) return; // single-flight: a double tap saves one site
    if (!ns.name.trim()) return setNsErr("Enter a site name.");
    nsBusy.current = true;
    try {
      const s = await repo.createSite(uid, { name: ns.name.trim(), address: ns.address.trim() || null, description: ns.description.trim() || null });
      setNewSite(false);
      setNs({ name: "", address: "", description: "" });
      setNsErr(null);
      syncAll(uid).catch(() => {});
      router.push({ pathname: "/site/[id]", params: { id: s.uuid, name: s.name } });
    } catch (e) {
      setNsErr(errText(e));
    } finally {
      nsBusy.current = false;
    }
  }
  const so = useSignOut();
  const uid = user ? user.uuid : "";

  useEffect(() => {
    const refresh = () => {
      setSyncError(getSyncError(uid));
      repo.unsyncedCount(uid).then(setUnsynced).catch(() => {});
    };
    refresh();
    return subscribe(refresh);
  }, [uid]);

  const load = useCallback(async () => {
    if (!uid) return;
    const bs = await repo.listBundles(uid);
    setBundles(Object.fromEntries(bs.map((b) => [b.site_id, b])));
    setVisits((await repo.listVisits(uid)).reverse());
    setUnsynced(await repo.unsyncedCount(uid));
    let list: any[];
    try {
      list = await api("/sites");
      const local = (await repo.listLocalSites(uid)).filter((l) => !list.some((x: any) => x.uuid === l.uuid));
      setSites([...list, ...local.map((l) => ({ ...l, customer_name: null, local_only: true }))]);
      setOffline(null);
    } catch (e) {
      setOffline(errText(e));
      setSites(bs.map((b) => ({ ...b.data.site, customer_name: b.data.customer?.name, local_only: !!b.data.local_only })));
      return;
    }
    // REQ-195: background prep of assigned sites + sync of saved captures; never blocks capture.
    syncAll(uid).then(async () => setUnsynced(await repo.unsyncedCount(uid))).catch(() => {});
    if (user && user.role === "foreman") {
      await importAssignedRepairs(uid).catch(() => 0);
      setVisits((await repo.listVisits(uid)).reverse());
    }
    for (const s of list) {
      try {
        await repo.saveBundle(uid, s.uuid, await api(`/sites/${s.uuid}/bundle`));
      } catch {
        // stays "Not yet available offline"
      }
    }
    const nb = await repo.listBundles(uid);
    setBundles(Object.fromEntries(nb.map((b) => [b.site_id, b])));
  }, [uid, user]);
  useFocusEffect(useCallback(() => { load(); }, [load]));
  useEffect(() => {
    const sub = AppState.addEventListener("change", (st) => st === "active" && load()); // retry on foreground
    return () => sub.remove();
  }, [load]);

  const status = unsynced ? `${unsynced} item${unsynced === 1 ? "" : "s"} not backed up yet` : null; // shown only when it matters
  return (
    <Screen testID="home-screen" back={false} title="My work" subtitle={`${user ? user.name : ""} - ${workspace?.name || ""}`}
      right={<Btn small kind="header" title="Account" icon="account-circle-outline" testID="account-menu-button" onPress={() => setMenu(true)} />}
      refreshing={refreshing} onRefresh={async () => { setRefreshing(true); await load(); setRefreshing(false); }}
      fab={<Fab testID="home-new-site-fab" label="New inspection on the rail map" onPress={() => router.push("/map")} />}>
      {user && user.role === "foreman" ? <Btn testID="home-open-repair-button" kind="secondary" icon="wrench" title="Open repair" onPress={() => router.push("/repair/new")} /> : null}
      {status ? (
        <Row style={{ flexWrap: "nowrap" }}>
          <T muted size={13} testID="home-unsynced-count" style={{ flex: 1 }}>{status}{offline ? " - they'll back up when you have a connection" : ""}.{bgSupported ? "" : " Open RailReady to finish sending your saved captures."}</T>
          <Btn small kind="ghost" testID="home-sync-retry-button" title="Try again" icon="refresh"
            onPress={() => syncAll(uid, true).then(async () => setUnsynced(await repo.unsyncedCount(uid))).catch(() => {})} />
        </Row>
      ) : null}
      {syncError ? (
        <Banner testID="home-location-sync-error" tone="warning" icon="map-marker-alert-outline" text={syncError}>
          <Btn small kind="ghost" testID="home-location-sync-retry" title="Try again" icon="refresh" onPress={() => syncAll(uid, true).catch(() => {})} />
        </Banner>
      ) : null}
      {visits.length ? <H>In progress</H> : null}
      {visits.map((v) => (
        <Card key={v.uuid} testID={`home-visit-${v.uuid}`} onPress={() => router.push(`/visit/${v.uuid}`)}>
          <T bold size={16}>{v.title}</T>
          <T muted size={13}>{v.site_name} - started {fmt(v.created_at)} - {v.status}</T>
          <T size={14}>Resume inspection</T>
        </Card>
      ))}
      <H>Assigned sites</H>
      {sites === null ? <T muted>Loading sites...</T> : null}
      {sites?.length === 0 ? <T muted>No sites assigned.</T> : null}
      {sites?.map((s) => (
        <Card key={s.uuid} testID={`site-card-${s.uuid}`} onPress={() => router.push({ pathname: "/site/[id]", params: { id: s.uuid, name: s.name } })}>
          <T bold size={16}>{s.name}</T>
          {[s.customer_name, s.address].filter(Boolean).length ? <T muted size={13}>{[s.customer_name, s.address].filter(Boolean).join(" - ")}</T> : null}
          <T muted size={13} testID={bundles[s.uuid] ? `site-offline-ready-${s.uuid}` : undefined}>{bundles[s.uuid] ? "Ready to use without signal" : "Getting ready..."}</T>
        </Card>
      ))}
      <Sheet visible={newSite} onClose={() => setNewSite(false)} title="New site" testID="new-site-sheet">
        <Input testID="new-site-name-input" label="Site name" value={ns.name} onChangeText={(v) => setNs({ ...ns, name: v })} placeholder="For example: North yard spur" />
        <Input testID="new-site-address-input" label="Location or address (optional)" value={ns.address} onChangeText={(v) => setNs({ ...ns, address: v })} />
        <Input testID="new-site-description-input" label="Short description (optional)" value={ns.description} onChangeText={(v) => setNs({ ...ns, description: v })} multiline />
        {nsErr ? <Banner testID="new-site-error" tone="error" icon="alert-circle-outline" text={nsErr} /> : null}
        <Btn testID="new-site-save-button" title="Save site" icon="content-save-outline" onPress={saveNewSite} />
        <T muted size={13}>Saved on this phone first. It is sent when you have a connection.</T>
      </Sheet>
      <Sheet visible={menu} onClose={() => setMenu(false)} title="Account" testID="account-menu-sheet">
        {user && user.role === "admin" ? <Btn testID="account-sync-details-button" kind="secondary" title="Diagnostics (admin)" icon="stethoscope" onPress={() => { setMenu(false); router.push("/outbox"); }} /> : null}
        {user && user.role === "admin" ? <T muted size={12} testID="account-admin-background">Admin details: background sending {backgroundStatus().upload}; scheduled runs {backgroundStatus().task}</T> : null}
        {user && user.role === "admin" ? <T muted size={12} testID="account-admin-backend-url">Admin details: this app talks to {API}</T> : null}
        <Btn testID="home-camera-check-button" kind="secondary" title="Camera check" icon="camera" onPress={() => { setMenu(false); router.push("/camera-smoke"); }} />
        {volOk ? <Btn testID="help-volume-button-photos" kind="secondary" title="Help: Volume button photos" icon="volume-high" onPress={() => { setMenu(false); setVolHelp(true); }} /> : null}
        <Btn testID="account-reload-app-button" kind="secondary" title="Reload app" icon="cog-refresh-outline" onPress={() => { setMenu(false); safeReload(); }} />
        <Btn testID="signout-button" kind="danger" title="Sign out" icon="logout" onPress={() => { setMenu(false); so.start(); }} />
      </Sheet>
      {volOk ? (
        <Sheet visible={volHelp} onClose={() => setVolHelp(false)} title="Take photos with your volume buttons" testID="volume-help-sheet">
          <T size={18}>Keep your thumb on either volume button and press it to take a photo. The shutter still works.</T>
          <Btn testID="volume-help-got-it" title="Got it" style={{ minHeight: 56 }} onPress={() => setVolHelp(false)} />
        </Sheet>
      ) : null}
      {so.sheet}
    </Screen>
  );
}
