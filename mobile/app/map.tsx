// Phase 14 phone map: U.S. rail only. MapLibre GL JS in a WebView (works in Expo Go); iframe on Expo web.
// Data flows through the app: per-tile cache (memory + phone storage, keyed by filter version) so layers seen before
// still show offline; stale view generations are aborted. Long-press drops a pin -> local site + inspection (offline-first),
// then the pin links on the server after they send.
import { router } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";
import { Linking, Platform, ScrollView, View } from "react-native";
import { WebView } from "react-native-webview";
import NetInfo from "@react-native-community/netinfo";
import * as Location from "expo-location";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { api, errText } from "@/src/api";
import { useAuth } from "@/src/auth";
import { METHOD_LABEL, parseLatLon } from "@/src/geo";
import * as repo from "@/src/local/repo";
import { MAPLIBRE_CDN, MAPLIBRE_VERSION, mapHtml } from "@/src/mapHtml";
import { syncAll } from "@/src/sync";
import { useTheme } from "@/src/theme";
import { Banner, Btn, Input, Row, Screen, Sheet, T } from "@/src/ui";
import { storage } from "@/src/utils/storage";

const FILTER = "rail-only-v1";
const LAYER_MIN: Record<string, number> = { ntad_lines: 3, caltrans: 5, ntad_mileposts: 11, ntad_crossings: 12 };
const tileKey = (k: string) => `railtile:${FILTER}:${k}`;
// storage holds strings; JSON-encode structured values
const getJ = async (k: string, d: any) => { const v = await storage.getItem<string | null>(k, null); try { return v ? JSON.parse(v) : d; } catch { return d; } };
const setJ = (k: string, v: any) => storage.setItem(k, JSON.stringify(v));
type Method = "gps" | "pin" | "coordinates" | "milepost" | "milepost_pin";
type Drop = { lat: number; lon: number; id: string; method: Method; accuracy?: number | null; fixed_at?: string | null; railway?: any; milepost_ref?: any } | null;
const US: [number, number] = [-98.58, 39.83]; // REQ-1601: national view
const SF = { lat: 37.7749, lon: -122.4194 };
const newId = () => `pin-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;

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
  const [mode, setMode] = useState<null | "coords" | "milepost">(null);
  const [cl, setCl] = useState({ lat: "", lon: "" });
  const [mp, setMp] = useState({ railroad: "", subdivision: "", milepost: "" });
  const [mpPending, setMpPending] = useState<any>(null); // unresolved milepost: text kept, a pin must be placed + confirmed
  const [confirmed, setConfirmed] = useState(false);
  const [entryErr, setEntryErr] = useState<string | null>(null);
  const [gps, setGps] = useState<null | "explain" | "denied" | "settings">(null);
  const saving = useRef(false);
  const selectionRequest = useRef(0);
  const [railPick, setRailPick] = useState<{ features: any[]; options: any[]; message: string; loading: boolean; cached?: boolean } | null>(null);

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
      setHtml(mapHtml({ js: Platform.OS === "web" ? null : js, css: Platform.OS === "web" ? null : css, colors: c, center: US, zoom: 3 }));
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

  const mpRef = useRef<any>(null);
  useEffect(() => { mpRef.current = mpPending; }, [mpPending]);
  // One draft pin at a time, kept apart from saved pins (REQ-1436). An unresolved milepost keeps its text on the pin.
  const placeDraft = useCallback((lat: number, lon: number, method: Method, extra: Partial<NonNullable<Drop>> = {}) => {
    const pend = mpRef.current;
    const m: Method = method === "pin" && pend ? "milepost_pin" : method;
    setDrop((d) => ({ lat, lon, id: d?.id || newId(), method: m, railway: m === "milepost_pin" ? pend : extra.railway, ...extra }));
    setConfirmed(false);
    setSuggest(null);
    send({ type: "draft", lat, lon });
    api(`/map/nearby?lat=${lat}&lon=${lon}`).then(setSuggest).catch(() => {});
  }, [send]);

  const loadMilepostOptions = useCallback(async (feature: any) => {
    const request = ++selectionRequest.current;
    setRailPick({ features: [], options: [], message: `Loading mileposts for ${feature.label}...`, loading: true });
    const key = `milepost-options:v1:${feature.id}`;
    let result: any, cached = false;
    try {
      result = await api(`/map/milepost-options?feature_id=${encodeURIComponent(feature.id)}`);
      await setJ(key, result);
    } catch {
      result = await getJ(key, null);
      cached = !!result;
    }
    if (request !== selectionRequest.current) return;
    setRailPick({ features: [], options: result?.options || [], loading: false, cached,
      message: result?.message || "Reference data is unavailable. Reconnect to select this milepost, or close and place a manual pin." });
  }, []);

  function selectMilepostReference(ref: any) {
    selectionRequest.current++;
    setRailPick(null);
    setMpPending(null);
    mpRef.current = null;
    setMode(null);
    setEntryErr(null);
    placeDraft(ref.lat, ref.lon, "milepost", { railway: { railroad: ref.railroad, subdivision: ref.subdivision, milepost: String(ref.milepost) }, milepost_ref: ref });
    send({ type: "fly", lat: ref.lat, lon: ref.lon, zoom: 14 });
  }

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
      syncAll(uid).catch(() => {}); // pending locations are part of the normal queue (src/sync.ts)
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
    } else if (m.type === "rail_pick") {
      const features = (m.features || []).filter((f: any) => /^(ntad_lines|ntad_mileposts):\d+$/.test(f.id));
      if (features.length === 1) loadMilepostOptions(features[0]);
      else if (features.length) setRailPick({ features, options: [], message: "Multiple rail features overlap. Choose the line or milepost you mean.", loading: false });
    } else if (m.type === "rail_unreferenced") {
      placeDraft(m.lat, m.lon, "pin");
      setBanner("This source has no linked reference mileposts. Confirm this manual pin or enter a known milepost; none has been inferred.");
    } else if (m.type === "longpress" || m.type === "tap") {
      placeDraft(m.lat, m.lon, "pin");
    } else if (m.type === "open") {
      if (m.props.visit_id) router.push(`/visit/${m.props.visit_id}`);
      else if (m.props.site_id) router.push(`/site/${m.props.site_id}`);
    } else if (m.type === "fatal") {
      setBanner(m.text);
    }
  }, [colors, fetchLayer, loadPins, send, uid, placeDraft, loadMilepostOptions]);

  useEffect(() => {
    if (Platform.OS !== "web") return;
    const h = (e: MessageEvent) => { if (typeof e.data === "string") onMessage(e.data); };
    window.addEventListener("message", h);
    return () => window.removeEventListener("message", h);
  }, [onMessage]);
  useEffect(() => () => ctl.current?.abort(), []);

  // REQ-1608: "Use this location" creates the site + inspection once per draft id (double tap, back + tap again, retry).
  async function savePin() {
    if (!drop || saving.current) return;
    if (drop.method === "milepost_pin" && !confirmed) return setEntryErr("Confirm the pin position first. The milepost was not found in the reference data.");
    saving.current = true;
    setBusy(true);
    try {
      const nm = name.trim() || `Pin ${drop.lat.toFixed(5)}, ${drop.lon.toFixed(5)}`;
      const rw = drop.railway || null;
      // one local transaction: site + inspection + pending pin/location (stable ids); a repeat tap returns the same inspection
      const { visitId } = await repo.createPinVisit(uid, { pinId: drop.id, name: nm, lat: drop.lat, lon: drop.lon, accuracy: drop.accuracy ?? null,
        method: drop.method, fixed_at: drop.fixed_at ?? null, method_label: METHOD_LABEL[drop.method],
        milepost_ref: drop.milepost_ref || null,
        railway: rw ? { railroad: rw.railroad || null, subdivision: rw.subdivision || null, milepost_text: rw.milepost || null } : null });
      setDrop(null);
      setMpPending(null);
      send({ type: "draft", lat: null, lon: null });
      syncAll(uid).then(loadPins).catch(() => {});
      router.push(`/visit/${visitId}`);
    } catch (e: any) {
      setBanner(errText(e));
    } finally {
      saving.current = false;
      setBusy(false);
    }
  }

  async function doSearch() {
    if (!q.trim()) return;
    try { setResults((await api(`/map/search?q=${encodeURIComponent(q.trim())}`)).results); } catch (e: any) { setBanner(errText(e)); }
  }

  function useCoords() {
    const r = parseLatLon(cl.lat, cl.lon);
    if ("error" in r) return setEntryErr(r.error); // REQ-1604: nothing is saved
    setEntryErr(null);
    placeDraft(r.lat, r.lon, "coordinates");
    send({ type: "fly", lat: r.lat, lon: r.lon, zoom: 14 });
    setMode(null);
  }

  async function findMilepost() {
    if (!mp.railroad.trim() || !mp.subdivision.trim() || !mp.milepost.trim()) return setEntryErr("Enter railroad, subdivision and milepost.");
    setEntryErr(null);
    const entered = { railroad: mp.railroad.trim(), subdivision: mp.subdivision.trim(), milepost: mp.milepost.trim() };
    let r: any = null;
    try { r = await api("/map/milepost", { method: "POST", body: entered }); } catch (e: any) { r = { resolved: false, message: errText(e) }; }
    if (r.resolved) {
      setMpPending(null);
      mpRef.current = null;
      placeDraft(r.lat, r.lon, "milepost", { railway: entered, milepost_ref: r });
      send({ type: "fly", lat: r.lat, lon: r.lon, zoom: 14 });
      setMode(null);
    } else { // REQ-1606: keep the entered text; the worker must place and confirm a pin
      setMpPending(entered);
      mpRef.current = entered;
      setDrop(null);
      send({ type: "draft", lat: null, lon: null });
      setEntryErr(`${r.message || "Milepost not found."} Tap the map to place the pin, then confirm it.`);
    }
  }

  // REQ-1607: GPS is optional. Denied keeps pin, coordinate and milepost entry working.
  async function myLocation(ask = false) {
    try {
      let p = await Location.getForegroundPermissionsAsync();
      if (p.status !== "granted") {
        if (!p.canAskAgain) return setGps("settings");
        if (!ask) return setGps(p.status === "denied" ? "denied" : "explain");
        p = await Location.requestForegroundPermissionsAsync();
        if (p.status !== "granted") return setGps(p.canAskAgain ? "denied" : "settings");
      }
      setGps(null);
      const pos = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.High });
      placeDraft(pos.coords.latitude, pos.coords.longitude, "gps", { accuracy: pos.coords.accuracy ?? null, fixed_at: pos.timestamp ? new Date(pos.timestamp).toISOString() : null });
      send({ type: "fly", lat: pos.coords.latitude, lon: pos.coords.longitude, zoom: 15 });
    } catch (e: any) {
      setGps(null);
      setBanner(`Location not available: ${e?.message || "unknown"}. Tap the map or enter coordinates instead.`);
    }
  }

  const pending = mpPending ? `Milepost ${mpPending.milepost} (${mpPending.railroad}, ${mpPending.subdivision}) kept as entered. Tap the map to place the pin.` : null;
  return (
    <Screen title="Rail map" testID="map-screen" scroll={false}>
      <View style={{ gap: 8, paddingBottom: 8 }}>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8, paddingRight: 8 }} style={{ flexGrow: 0 }}>
          <Btn small kind="secondary" testID="map-sf-button" icon="city-variant-outline" title="San Francisco" onPress={() => send({ type: "fly", lat: SF.lat, lon: SF.lon, zoom: 12 })} />
          <Btn small kind="secondary" testID="map-us-button" icon="earth" title="U.S." onPress={() => send({ type: "fly", lat: US[1], lon: US[0], zoom: 3 })} />
          <Btn small kind="secondary" testID="map-gps-button" icon="crosshairs-gps" title="My location" onPress={() => myLocation(false)} />
          <Btn small kind={mode === "coords" ? "primary" : "secondary"} testID="map-coords-toggle" icon="numeric" title="Lat/Lon" onPress={() => { setEntryErr(null); setMode(mode === "coords" ? null : "coords"); }} />
          <Btn small kind={mode === "milepost" ? "primary" : "secondary"} testID="map-milepost-toggle" icon="sign-direction" title="Milepost" onPress={() => { setEntryErr(null); setMode(mode === "milepost" ? null : "milepost"); }} />
          <Btn small kind="ghost" testID="map-new-site-button" icon="plus-box-outline" title="New site" onPress={() => router.push("/home?newsite=1")} />
        </ScrollView>
        {mode === "coords" ? (
          <View testID="map-coords-form" style={{ gap: 6 }}>
            <Row style={{ flexWrap: "nowrap" }}>
              <View style={{ flex: 1 }}><Input testID="map-lat-input" label="Latitude" placeholder="37.7749" keyboardType="numbers-and-punctuation" value={cl.lat} onChangeText={(t) => setCl({ ...cl, lat: t })} /></View>
              <View style={{ flex: 1 }}><Input testID="map-lon-input" label="Longitude" placeholder="-122.4194" keyboardType="numbers-and-punctuation" value={cl.lon} onChangeText={(t) => setCl({ ...cl, lon: t })} /></View>
            </Row>
            <Btn small testID="map-coords-go" title="Place pin here" icon="map-marker-plus" onPress={useCoords} />
          </View>
        ) : null}
        {mode === "milepost" ? (
          <View testID="map-milepost-form" style={{ gap: 6 }}>
            <Row style={{ flexWrap: "nowrap" }}>
              <View style={{ flex: 1 }}><Input testID="map-mp-railroad-input" label="Railroad (code)" placeholder="UP" value={mp.railroad} onChangeText={(t) => setMp({ ...mp, railroad: t })} /></View>
              <View style={{ flex: 1 }}><Input testID="map-mp-number-input" label="Milepost" placeholder="17" keyboardType="numbers-and-punctuation" value={mp.milepost} onChangeText={(t) => setMp({ ...mp, milepost: t })} /></View>
            </Row>
            <Input testID="map-mp-subdivision-input" label="Line or subdivision" placeholder="Peninsula" value={mp.subdivision} onChangeText={(t) => setMp({ ...mp, subdivision: t })} />
            <Btn small testID="map-mp-find" title="Find milepost" icon="magnify" onPress={findMilepost} />
          </View>
        ) : null}
        {!mode ? <Input testID="map-search-input" label="Find" placeholder="Station, site or lat, lon" value={q} onChangeText={setQ} onSubmitEditing={doSearch} /> : null}
        {results.length ? results.slice(0, 5).map((r, i) => (
          <Btn key={i} small kind="secondary" testID={`map-search-result-${i}`} title={`${r.label}${r.kind === "rail_station" ? " (station)" : r.kind === "site" ? " (site)" : ""}`}
            onPress={() => { send({ type: "fly", lat: r.lat, lon: r.lon, zoom: 15 }); setResults([]); }} />
        )) : null}
        {entryErr ? <Banner testID="map-entry-error" tone="error" icon="alert-circle-outline" text={entryErr} /> : null}
        {pending && !entryErr ? <Banner testID="map-milepost-pending" tone="warning" icon="map-marker-question" text={pending} /> : null}
        {banner ? <Banner testID="map-banner" tone="warning" icon="map-marker-off" text={banner} /> : null}
        {!drop ? <T muted size={13} testID="map-hint">Tap a rail line to choose its reference milepost. Zoom in to tap a milepost marker, or tap empty map space for a pin.</T> : null}
      </View>
      <View testID="map-view" style={{ flex: 1, minHeight: 220, borderRadius: 12, overflow: "hidden", marginBottom: drop ? 8 : insets.bottom + 8, backgroundColor: colors.surfaceSecondary }}>
        {html ? (Platform.OS === "web"
          // Expo web preview only: react-native-webview has no web build, so the same page runs in an iframe.
          ? <iframe ref={frame} title="Rail map" srcDoc={html} style={{ border: 0, width: "100%", height: "100%" }} />
          : <WebView ref={web} originWhitelist={["*"]} source={{ html, baseUrl: "https://railready.local/" }} onMessage={(e) => onMessage(e.nativeEvent.data)}
              javaScriptEnabled domStorageEnabled style={{ flex: 1 }} />) : null}
      </View>
      {drop ? (
        <View testID="map-draft-panel" style={{ gap: 6, paddingBottom: insets.bottom + 8 }}>
          <T bold testID="map-pin-coords">{`${drop.lat.toFixed(6)}, ${drop.lon.toFixed(6)}`}</T>
          <T size={13} testID="map-pin-method">{METHOD_LABEL[drop.method]}{drop.method === "gps" && drop.accuracy ? ` (about ${Math.round(drop.accuracy)} m)` : ""}{drop.railway ? ` - ${[drop.railway.railroad, drop.railway.subdivision, drop.railway.milepost ? `MP ${drop.railway.milepost}` : null].filter(Boolean).join(", ")}` : ""}</T>
          {drop.milepost_ref ? <T muted size={12} testID="map-selected-reference">{`${drop.milepost_ref.source} / ${drop.milepost_ref.id} / ${drop.milepost_ref.line_id}`}</T> : null}
          {suggest && (suggest.railroad || suggest.nearest_milepost) ? (
            <T testID="map-pin-suggestion" muted size={13}>Nearby, not exact: {[suggest.railroad, suggest.subdivision, suggest.nearest_milepost ? `MP ${suggest.nearest_milepost.milepost}` : null].filter(Boolean).join(", ")}</T>
          ) : null}
          {drop.method === "milepost_pin" ? (
            <Btn small kind={confirmed ? "primary" : "secondary"} testID="map-pin-confirm-button" icon={confirmed ? "check-circle" : "map-marker-check"}
              title={confirmed ? "Pin position confirmed" : "Confirm this pin position"} onPress={() => { setConfirmed(true); setEntryErr(null); }} />
          ) : null}
          <Input testID="map-pin-name-input" label="Site name (optional)" value={name} onChangeText={setName} />
          <Row style={{ flexWrap: "nowrap" }}>
            <View style={{ flex: 1 }}><Btn testID="map-use-location-button" title={busy ? "Saving..." : "Use this location"} icon="map-marker-check" disabled={busy} onPress={savePin} /></View>
            <Btn testID="map-pin-cancel-button" kind="ghost" title="Clear" onPress={() => { setDrop(null); send({ type: "draft", lat: null, lon: null }); }} />
          </Row>
        </View>
      ) : null}
      <Sheet visible={!!railPick} onClose={() => { selectionRequest.current++; setRailPick(null); }} title="Choose a reference milepost" testID="map-milepost-selection">
        <T>{railPick?.message}</T>
        {railPick?.cached ? <T muted>Saved reference data. The source record will be verified when this location syncs.</T> : null}
        <ScrollView style={{ maxHeight: 300 }}>
          {railPick?.features.map((f) => <Btn key={f.id} small kind="secondary" title={`${f.label} (${f.id})`} onPress={() => loadMilepostOptions(f)} />)}
          {railPick?.options.map((r) => <Btn key={`${r.id}:${r.line_id}`} small kind="secondary" testID={`map-select-${r.id}-${r.line_id}`}
            title={`Use MP ${r.milepost} / ${r.railroad} / ${r.subdivision} (${r.line_id})`} onPress={() => selectMilepostReference(r)} />)}
        </ScrollView>
        {!railPick?.loading ? <T muted>Confirm the line before selecting. Coordinates come from the reference milepost; no position is interpolated.</T> : null}
        <Btn kind="ghost" title="Close" onPress={() => { selectionRequest.current++; setRailPick(null); }} />
      </Sheet>
      <Sheet visible={!!gps} onClose={() => setGps(null)} title="Use your location" testID="map-gps-sheet">
        <T>RailReady uses your location only to place the inspection pin where you are standing.</T>
        {gps === "denied" || gps === "settings" ? <Banner testID="map-gps-denied" tone="warning" icon="crosshairs-off" text="Location permission is off. You can still tap the map, enter coordinates or enter a milepost." /> : null}
        {gps === "settings"
          ? <Btn testID="map-gps-settings-button" title="Open Settings" icon="cog" onPress={() => { setGps(null); Linking.openSettings(); }} />
          : <Btn testID="map-gps-continue-button" title={gps === "denied" ? "Try again" : "Continue"} icon="check" onPress={() => myLocation(true)} />}
        <Btn testID="map-gps-cancel-button" kind="ghost" title="Not now" onPress={() => setGps(null)} />
      </Sheet>
    </Screen>
  );
}
