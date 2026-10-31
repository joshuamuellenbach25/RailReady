// Phase 14 phone map: U.S. rail only. MapLibre GL JS in a WebView (works in Expo Go); iframe on Expo web.
// Data flows through the app: per-tile cache (memory + phone storage, keyed by filter version) so layers seen before
// still show offline; stale view generations are aborted. Long-press drops a pin -> local site + inspection (offline-first),
// then the pin links on the server after they send.
import { router } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";
import { Platform, View } from "react-native";
import { WebView } from "react-native-webview";
import NetInfo from "@react-native-community/netinfo";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { api, errText } from "@/src/api";
import { useAuth } from "@/src/auth";
import * as repo from "@/src/local/repo";
import { MAPLIBRE_CDN, MAPLIBRE_VERSION, mapHtml } from "@/src/mapHtml";
import { syncAll } from "@/src/sync";
import { useTheme } from "@/src/theme";
import { Banner, Btn, Input, Screen, Sheet, T } from "@/src/ui";
import { storage } from "@/src/utils/storage";

const FILTER = "rail-only-v1";
const LAYER_MIN: Record<string, number> = { ntad_lines: 3, caltrans: 5, ntad_mileposts: 11, ntad_crossings: 12 };
const tileKey = (k: string) => `railtile:${FILTER}:${k}`;
// storage holds strings; JSON-encode structured values
const getJ = async (k: string, d: any) => { const v = await storage.getItem<string | null>(k, null); try { return v ? JSON.parse(v) : d; } catch { return d; } };
const setJ = (k: string, v: any) => storage.setItem(k, JSON.stringify(v));
type Drop = { lat: number; lon: number; id: string } | null;

async function flushPendingPins(uid: string) {
  const key = `pending-pins:${uid}`;
  const list: any[] = await getJ(key, []);
  const left: any[] = [];
  for (const p of list) {
    try {
      await api("/map/pins", { method: "POST", body: p });
    } catch {
      left.push(p); // not synced yet / offline: keep, retried on the next map open
    }
  }
  await setJ(key, left);
  return left.length;
}

export default function MapScreen() {
  const { user } = useAuth();
  const uid = user ? user.uuid : "";
  const insets = useSafeAreaInsets();
  const { colors } = useTheme();
  const web = useRef<any>(null);
  const frame = useRef<any>(null);
  const mem = useRef(new Map<string, any>());
  const ctl = useRef<AbortController | null>(null);
  const [html, setHtml] = useState<string | null>(null);
  const [banner, setBanner] = useState<string | null>(null);
  const [drop, setDrop] = useState<Drop>(null);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [q, setQ] = useState("");
  const [results, setResults] = useState<any[]>([]);
  const [suggest, setSuggest] = useState<any>(null);

  const send = useCallback((m: any) => {
    const s = JSON.stringify(m);
    if (Platform.OS === "web") frame.current?.contentWindow?.postMessage(s, "*");
    else web.current?.postMessage(s);
  }, []);

  useEffect(() => {
    (async () => {
      let js = await storage.getItem<string | null>(`maplibre-js-${MAPLIBRE_VERSION}`, null);
      let css = await storage.getItem<string | null>(`maplibre-css-${MAPLIBRE_VERSION}`, null);
      if (Platform.OS !== "web" && (!js || !css)) {
        try { // keep a copy so the map engine loads with no connection next time
          js = await (await fetch(`${MAPLIBRE_CDN}/maplibre-gl.js`)).text();
          css = await (await fetch(`${MAPLIBRE_CDN}/maplibre-gl.css`)).text();
          await storage.setItem(`maplibre-js-${MAPLIBRE_VERSION}`, js);
          await storage.setItem(`maplibre-css-${MAPLIBRE_VERSION}`, css);
        } catch { /* offline first run: the page reports it can't load */ }
      }
      const c = { line: colors.onSurface, caltrans: colors.warning, path: colors.brandPrimary, station: colors.brandPrimary, pin: colors.brandPrimary,
        pinDone: colors.success, text: colors.onSurface, halo: colors.surface, bg: colors.surfaceSecondary };
      setHtml(mapHtml({ js: Platform.OS === "web" ? null : js, css: Platform.OS === "web" ? null : css, colors: c, center: [-122.42, 37.77], zoom: 11 }));
    })();
  }, [colors]);

  const fetchLayer = useCallback(async (key: string, path: string, gen: number, signal: AbortSignal) => {
    let fc = mem.current.get(key);
    if (!fc) {
      try {
        fc = await api(path, { signal });
        mem.current.set(key, fc);
        setJ(tileKey(key), fc).catch(() => {});
      } catch (e: any) {
        if (signal.aborted) return;
        fc = await getJ(tileKey(key), null); // offline: last saved copy of this tile
        if (!fc) {
          setBanner("Rail layer unavailable. Pins still work.");
          return;
        }
      }
    }
    if (!signal.aborted) send({ type: "layer", gen, key, fc });
  }, [send]);

  const loadPins = useCallback(async () => {
    try {
      const items = await api("/map/items");
      const pins = items.pins.map((p: any) => ({ type: "Feature", geometry: { type: "Point", coordinates: [p.lon, p.lat] },
        properties: { kind: "pin", _id: p.uuid, visit_id: p.visit_id, site_id: p.site_id, name: p.name, inspection_state: p.inspection_state } }));
      const cams = items.camera_first.map((c: any) => ({ type: "Feature", geometry: { type: "Point", coordinates: [c.lon, c.lat] },
        properties: { kind: "camera_first", _id: `cam-${c.visit_id}`, visit_id: c.visit_id } }));
      await setJ(`map-items:${uid}`, { pins, cams });
      send({ type: "layer", key: "pins/all", fc: { type: "FeatureCollection", features: pins } });
      send({ type: "layer", key: "camera/all", fc: { type: "FeatureCollection", features: cams } });
    } catch {
      const c = await getJ(`map-items:${uid}`, null);
      const local = (await repo.listLocalSites(uid)).filter((s: any) => s.lat != null).map((s: any) => ({ type: "Feature",
        geometry: { type: "Point", coordinates: [s.lon, s.lat] }, properties: { kind: "pin", _id: s.uuid, site_id: s.uuid, name: s.name, inspection_state: "Saved on phone" } }));
      send({ type: "layer", key: "pins/all", fc: { type: "FeatureCollection", features: [...(c?.pins || []), ...local] } });
    }
  }, [send, uid]);

  const onMessage = useCallback(async (raw: string) => {
    let m: any;
    try { m = JSON.parse(raw); } catch { return; }
    if (m.type === "ready") {
      const online = (await NetInfo.fetch()).isConnected !== false;
      let style: any = null;
      try { style = await api(`/map/basemap-style${online ? "" : "?offline=1"}`); } catch { /* fall through */ }
      if (!style) style = await api("/map/basemap-style?offline=1").catch(() => ({ version: 8, sources: {}, layers: [{ id: "bg", type: "background", paint: { "background-color": colors.surfaceSecondary } }] }));
      if (style?.metadata?.basemap_unavailable || !online) setBanner("Basemap unavailable. Showing rail lines and pins on a plain north-up plot.");
      send({ type: "style", style });
    } else if (m.type === "loaded") {
      loadPins();
      flushPendingPins(uid).catch(() => {});
    } else if (m.type === "view") {
      ctl.current?.abort(); // drop the previous view's requests
      const c = new AbortController();
      ctl.current = c;
      const z = m.tiles[0]?.[0] ?? 3;
      for (const [layer, min] of Object.entries(LAYER_MIN)) {
        if (z < min) continue;
        for (const t of m.tiles) fetchLayer(`${layer}/${t.join("/")}`, `/map/layers/${layer}/${t.join("/")}`, m.gen, c.signal);
      }
      if (m.zoom >= 8) {
        const [w, s, e, n] = m.bbox.map((v: number) => Math.round(v * 10) / 10);
        fetchLayer(`gtfs/${w},${s},${e},${n}`, `/map/layers/gtfs?bbox=${w - 0.1},${s - 0.1},${e + 0.1},${n + 0.1}`, m.gen, c.signal);
      }
    } else if (m.type === "longpress") {
      setDrop({ lat: m.lat, lon: m.lon, id: `pin-${Date.now()}-${Math.random().toString(36).slice(2, 8)}` });
      setName("");
      setSuggest(null);
      api(`/map/nearby?lat=${m.lat}&lon=${m.lon}`).then(setSuggest).catch(() => {});
    } else if (m.type === "open") {
      if (m.props.visit_id) router.push(`/visit/${m.props.visit_id}`);
      else if (m.props.site_id) router.push(`/site/${m.props.site_id}`);
    } else if (m.type === "fatal") {
      setBanner(m.text);
    }
  }, [colors, fetchLayer, loadPins, send, uid]);

  useEffect(() => {
    if (Platform.OS !== "web") return;
    const h = (e: MessageEvent) => { if (typeof e.data === "string") onMessage(e.data); };
    window.addEventListener("message", h);
    return () => window.removeEventListener("message", h);
  }, [onMessage]);
  useEffect(() => () => ctl.current?.abort(), []);

  async function savePin() {
    if (!drop || busy) return; // single flight; drop.id is the stable idempotency key for this pin
    setBusy(true);
    try {
      const nm = name.trim() || `Pin ${drop.lat.toFixed(5)}, ${drop.lon.toFixed(5)}`;
      const site = await repo.createSite(uid, { name: nm, address: null, description: null, lat: drop.lat, lon: drop.lon, location_accuracy_m: null });
      const v = await repo.createVisit(uid, site.uuid, nm, nm);
      const key = `pending-pins:${uid}`;
      const list: any[] = await getJ(key, []);
      await setJ(key, [...list, { uuid: drop.id, lat: drop.lat, lon: drop.lon, name: nm, site_id: site.uuid, visit_id: v.uuid }]);
      setDrop(null);
      syncAll(uid).then(() => flushPendingPins(uid)).then(loadPins).catch(() => {});
      router.push(`/visit/${v.uuid}`);
    } catch (e: any) {
      setBanner(errText(e));
    } finally {
      setBusy(false);
    }
  }

  async function doSearch() {
    if (!q.trim()) return;
    try { setResults((await api(`/map/search?q=${encodeURIComponent(q.trim())}`)).results); } catch (e: any) { setBanner(errText(e)); }
  }

  return (
    <Screen title="Rail map" testID="map-screen" scroll={false}>
      <View style={{ gap: 8, paddingBottom: 8 }}>
        <Input testID="map-search-input" label="Find" placeholder="Station, site or lat, lon" value={q} onChangeText={setQ} onSubmitEditing={doSearch} />
        {results.length ? results.slice(0, 5).map((r, i) => (
          <Btn key={i} small kind="secondary" testID={`map-search-result-${i}`} title={`${r.label}${r.kind === "rail_station" ? " (station)" : r.kind === "site" ? " (site)" : ""}`}
            onPress={() => { send({ type: "fly", lat: r.lat, lon: r.lon, zoom: 15 }); setResults([]); }} />
        )) : null}
        {banner ? <Banner testID="map-banner" tone="warning" icon="map-marker-off" text={banner} /> : null}
        <T muted size={13}>Press and hold on the map to drop a pin.</T>
      </View>
      <View testID="map-view" style={{ flex: 1, borderRadius: 12, overflow: "hidden", marginBottom: insets.bottom + 8, backgroundColor: colors.surfaceSecondary }}>
        {html ? (Platform.OS === "web"
          // Expo web preview only: react-native-webview has no web build, so the same page runs in an iframe.
          ? <iframe ref={frame} title="Rail map" srcDoc={html} style={{ border: 0, width: "100%", height: "100%" }} />
          : <WebView ref={web} originWhitelist={["*"]} source={{ html, baseUrl: "https://railready.local/" }} onMessage={(e) => onMessage(e.nativeEvent.data)}
              javaScriptEnabled domStorageEnabled style={{ flex: 1 }} />) : null}
      </View>
      <Sheet visible={!!drop} onClose={() => setDrop(null)} title="Save pin and start inspection" testID="map-pin-sheet">
        <T testID="map-pin-coords">{drop ? `${drop.lat.toFixed(6)}, ${drop.lon.toFixed(6)}` : ""}</T>
        <T muted size={13}>Approximate defect location. Railway details stay empty until you enter them.</T>
        {suggest && (suggest.railroad || suggest.nearest_milepost) ? (
          <T testID="map-pin-suggestion" size={14}>Nearby, not exact: {[suggest.railroad, suggest.subdivision, suggest.nearest_milepost ? `MP ${suggest.nearest_milepost.milepost}` : null].filter(Boolean).join(", ")}</T>
        ) : null}
        <Input testID="map-pin-name-input" label="Site name (optional)" value={name} onChangeText={setName} />
        <Btn testID="map-pin-save-button" title={busy ? "Saving..." : "Save pin and start inspection"} disabled={busy} onPress={savePin} />
        <Btn testID="map-pin-cancel-button" kind="ghost" title="Cancel" onPress={() => setDrop(null)} />
      </Sheet>
    </Screen>
  );
}
