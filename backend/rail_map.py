"""Phase 14 rail-only map data adapters (backend).

Sources (metadata and samples read before writing each adapter):
- GTFS (SFMTA, BART, Caltrain): ONLY route_type 0/1/2 admitted (REQ-1407). Extended types (100-1702) are rejected: no
  provider-verified mapping is configured (REQ-1408). Geometry: rail routes -> trips -> shape_id -> shapes.txt ordered
  by shape_pt_sequence (REQ-1409). Stops only via rail trips' stop_times plus parent stations (REQ-1410). Ids scoped
  feed:version:id (REQ-1411). Rail trips without a shape are hidden (unresolvable pattern, REQ-1413).
- NTAD North American Rail Network Lines / Rail Mileposts / Railroad Grade Crossings (ArcGIS FeatureServer/0, WGS84,
  maxRecordCount 2000, pagination supported): bbox query, inSR=4326, outSR=4326, paginated past 2000 (REQ-1415).
- Caltrans California Rail Network (FeatureServer/0, stored in 3857, requested with outSR=4326) (REQ-1421).
- OSM via Overpass: OPTIONAL (REQ-1423). Overpass was unreachable from this server on 2026-10-25, so it is disabled.
Nothing here classifies by name, color, agency or proximity (REQ-1404).
"""
import asyncio
import copy
import csv
import hashlib
import io
import json
import math
import os
import re
import zipfile
from datetime import datetime, timedelta, timezone

import httpx

from core import db, iso

FILTER_VERSION = "rail-only-v1"
RAIL_ROUTE_TYPES = {"0": "Light rail or streetcar", "1": "Subway or metro", "2": "Rail"}
SERVICE_PATH_LABEL = "Service path, not surveyed track"
UA = {"User-Agent": "RailReady/1.0 (rail inspection app; private use)"}
CACHE_DIR = "/tmp/rail"

GTFS_FEEDS = {
    "sfmta": {"name": "SFMTA GTFS", "url": "https://data.sf.gov/download/dni7-qpv3/application/x-zip-compressed",
              "catalog": "https://catalog.data.gov/dataset/sfmta-general-transit-feed-specification-gtfs-production"},
    "bart": {"name": "BART GTFS", "url": "https://www.bart.gov/dev/schedules/google_transit.zip",
             "catalog": "https://www.bart.gov/schedules/developers/gtfs"},
    "caltrain": {"name": "Caltrain GTFS", "url": "https://data.trilliumtransit.com/gtfs/caltrain-ca-us/caltrain-ca-us.zip",
                 "catalog": "https://www.caltrain.com/developer-resources"},
}

NTAD = "https://services.arcgis.com/xOi1kZaI0eWDREZv/ArcGIS/rest/services"
ARCGIS_LAYERS = {
    "ntad_lines": {"name": "NTAD North American Rail Network Lines", "url": f"{NTAD}/NTAD_North_American_Rail_Network_Lines/FeatureServer/0",
                   "geom": "line", "id_field": "FRAARCID", "min_zoom": 3},
    "ntad_mileposts": {"name": "NTAD Rail Mileposts", "url": f"{NTAD}/NTAD_Rail_Mileposts/FeatureServer/0",
                       "geom": "point", "id_field": "OBJECTID", "min_zoom": 11},
    "ntad_crossings": {"name": "NTAD Railroad Grade Crossings", "url": f"{NTAD}/NTAD_Railroad_Grade_Crossings/FeatureServer/0",
                       "geom": "point", "id_field": "CrossingID", "min_zoom": 12},
    "caltrans": {"name": "Caltrans California Rail Network",
                 "url": "https://caltrans-gis.dot.ca.gov/arcgis/rest/services/CHrailroad/California_Rail_Network/FeatureServer/0",
                 "geom": "line", "id_field": "OBJECTID", "min_zoom": 5},
}
PAGE = 2000
MAX_PAGES = 40
TILE_TTL = timedelta(days=7)
MAX_TILE_Z = 12

BASEMAP = {"name": "OpenFreeMap Liberty", "style_url": "https://tiles.openfreemap.org/styles/liberty",
           "terms": "https://openfreemap.org/tos/", "key_required": False,
           "attribution": "OpenFreeMap, OpenMapTiles, data from OpenStreetMap contributors",
           "offline_limits": "Per download: at most 3,000 tiles or 50 MB, at most 4 parallel requests, unique User-Agent"}
BUS_CLASSES = ["bus", "bus_stop", "bus_station", "busway", "bus_guideway", "trolleybus"]


# ---------------- GTFS ----------------
def _rows(z: zipfile.ZipFile, name: str):
    if name not in z.namelist():
        return []
    return list(csv.DictReader(io.TextIOWrapper(z.open(name), "utf-8-sig")))


def extract_gtfs_rail(feed: str, data: bytes, retrieved_at: str) -> dict:
    """Pure function: GTFS zip bytes -> rail-only paths and stops. No name/color/agency heuristics."""
    z = zipfile.ZipFile(io.BytesIO(data))
    info = _rows(z, "feed_info.txt")
    version = (info[0].get("feed_version") if info else None) or hashlib.sha256(data).hexdigest()[:12]
    version = re.sub(r"[^A-Za-z0-9._-]+", "_", version.strip()).strip("_")  # ids stay URL/colon safe
    scope = f"{feed}:{version}"
    routes = _rows(z, "routes.txt")
    rejected = {}
    rail_routes = {}
    for r in routes:
        t = (r.get("route_type") or "").strip()
        if t in RAIL_ROUTE_TYPES:
            rail_routes[r["route_id"]] = r
        else:
            rejected[t] = rejected.get(t, 0) + 1  # bus (3), cable tram (5), extended types: all rejected
    trips = [t for t in _rows(z, "trips.txt") if t["route_id"] in rail_routes]
    hidden = [t["trip_id"] for t in trips if not t.get("shape_id")]
    trips = [t for t in trips if t.get("shape_id")]
    shape_ids = {t["shape_id"] for t in trips}
    pts: dict[str, list] = {}
    for p in _rows(z, "shapes.txt"):
        if p["shape_id"] in shape_ids:
            pts.setdefault(p["shape_id"], []).append((int(float(p["shape_pt_sequence"])), float(p["shape_pt_lon"]), float(p["shape_pt_lat"])))
    shape_route: dict[str, set] = {}
    for t in trips:
        shape_route.setdefault(t["shape_id"], set()).add(t["route_id"])
    paths = []
    for sid, plist in pts.items():
        plist.sort()
        coords = [[round(x, 6), round(y, 6)] for _, x, y in plist]
        for rid in sorted(shape_route.get(sid, ())):
            r = rail_routes[rid]
            paths.append({"kind": "path", "id": f"{scope}:route:{rid}:shape:{sid}", "feed": feed, "feed_version": version,
                          "route_id": rid, "shape_id": sid, "route_type": int(r["route_type"]),
                          "mode": RAIL_ROUTE_TYPES[r["route_type"]], "short_name": r.get("route_short_name") or None,
                          "long_name": r.get("route_long_name") or None, "label": SERVICE_PATH_LABEL,
                          "geometry": {"type": "LineString", "coordinates": coords}})
    trip_ids = {t["trip_id"] for t in trips}
    stop_ids = {s["stop_id"] for s in _rows(z, "stop_times.txt") if s["trip_id"] in trip_ids}
    all_stops = {s["stop_id"]: s for s in _rows(z, "stops.txt")}
    parents = {all_stops[s].get("parent_station") for s in stop_ids if s in all_stops and all_stops[s].get("parent_station")}
    stops = []
    for sid in sorted(stop_ids | {p for p in parents if p in all_stops}):
        s = all_stops.get(sid)
        if not s or not s.get("stop_lat"):
            continue
        children = sorted(c for c in stop_ids if all_stops.get(c, {}).get("parent_station") == sid)
        stops.append({"kind": "station" if sid in parents else "stop", "id": f"{scope}:stop:{sid}", "feed": feed,
                      "feed_version": version, "stop_id": sid, "name": s.get("stop_name"),
                      "parent_id": f"{scope}:stop:{s['parent_station']}" if s.get("parent_station") else None,
                      "platform_ids": [f"{scope}:stop:{c}" for c in children],
                      "geometry": {"type": "Point", "coordinates": [round(float(s["stop_lon"]), 6), round(float(s["stop_lat"]), 6)]}})
    for d in paths + stops:
        d.update({"source": GTFS_FEEDS.get(feed, {}).get("name", feed), "retrieved_at": retrieved_at, "filter_version": FILTER_VERSION})
    return {"feed": feed, "version": version, "paths": paths, "stops": stops, "rejected_route_types": rejected,
            "hidden_trips_without_shape": len(hidden), "rail_routes": sorted(rail_routes)}


async def ingest_gtfs(feed: str) -> dict:
    os.makedirs(CACHE_DIR, exist_ok=True)
    async with httpx.AsyncClient(timeout=120, follow_redirects=True, headers=UA) as c:
        r = await c.get(GTFS_FEEDS[feed]["url"])
        r.raise_for_status()
    data = r.content
    with open(f"{CACHE_DIR}/{feed}.zip", "wb") as f:  # staged under /tmp, never /app
        f.write(data)
    out = extract_gtfs_rail(feed, data, iso())
    docs = out["paths"] + out["stops"]
    await db.rail_gtfs.delete_many({"feed": feed})
    if docs:
        await db.rail_gtfs.insert_many([dict(d) for d in docs])
    summary = {k: v for k, v in out.items() if k not in ("paths", "stops")}
    summary.update({"paths": len(out["paths"]), "stops": len(out["stops"]), "at": iso(), "filter_version": FILTER_VERSION})
    await db.rail_sources.update_one({"feed": feed}, {"$set": summary}, upsert=True)
    return summary


def _feature(d: dict) -> dict:
    props = {k: v for k, v in d.items() if k not in ("geometry", "_id")}
    props.update({"_source": d["source"], "_id": d["id"], "_version": d["feed_version"], "_retrieved_at": d["retrieved_at"]})
    return {"type": "Feature", "id": d["id"], "geometry": d["geometry"], "properties": props}


async def gtfs_features(bbox: tuple) -> dict:
    w, s, e, n = bbox
    poly = {"type": "Polygon", "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]]}
    docs = await db.rail_gtfs.find({"filter_version": FILTER_VERSION, "geometry": {"$geoIntersects": {"$geometry": poly}}}).to_list(20000)
    return {"type": "FeatureCollection", "features": [_feature(d) for d in docs], "filter_version": FILTER_VERSION}


# ---------------- ArcGIS (NTAD, Caltrans) ----------------
def tile_bbox(z: int, x: int, y: int) -> tuple:
    def lon(xx):
        return xx / 2 ** z * 360 - 180

    def lat(yy):
        return math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * yy / 2 ** z))))
    return (lon(x), lat(y + 1), lon(x + 1), lat(y))


def generalization(layer: str, z: int) -> tuple[str, float | None]:
    """National zooms use generalized geometry and coarser subsets; detail loads on zoom-in (REQ-1417)."""
    tol = 360 / (256 * 2 ** z) if z < MAX_TILE_Z else None  # ~1 px at this zoom, in degrees
    if layer == "ntad_lines":
        if z < 6:
            return "STRACNET IN ('C','S')", tol
        if z < 9:
            return "NET='M'", tol
    return "1=1", tol


def _decorate(layer: str, f: dict, version: str, retrieved: str) -> dict:
    meta = ARCGIS_LAYERS[layer]
    p = f.get("properties") or {}
    fid = p.get(meta["id_field"], f.get("id"))
    p.update({"_source": meta["name"], "_id": f"{layer}:{fid}", "_version": version, "_retrieved_at": retrieved})
    if layer == "ntad_lines" and p.get("TRACKS") is not None:
        p["_tracks_label"] = f"Tracks: {p['TRACKS']} (count)"  # TRACKS is a count, never a track number (REQ-1420)
    if layer == "caltrans":
        b, e_ = p.get("BEGIN_MP"), p.get("END_MP")
        p["_milepost_range"] = f"MP {b} to {e_}" if b is not None and e_ is not None else "Not recorded"  # range only (REQ-1422)
        if p.get("NUM_TRACK") not in (None, " "):
            p["_tracks_label"] = f"Tracks: {str(p['NUM_TRACK']).strip()} (count)"
    f["properties"] = p
    f["id"] = p["_id"]
    return f


_versions: dict[str, str] = {}


async def layer_version(c: httpx.AsyncClient, layer: str) -> str:
    if layer not in _versions:
        r = await c.get(ARCGIS_LAYERS[layer]["url"], params={"f": "json"})
        ms = (r.json().get("editingInfo") or {}).get("dataLastEditDate")
        _versions[layer] = datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat() if ms else f"retrieved {iso()}"
    return _versions[layer]


async def fetch_arcgis(layer: str, bbox: tuple, z: int, client: httpx.AsyncClient | None = None) -> dict:
    meta = ARCGIS_LAYERS[layer]
    where, tol = generalization(layer, z)
    own = client is None
    c = client or httpx.AsyncClient(timeout=60, headers=UA)
    try:
        version = await layer_version(c, layer)
        feats, offset, pages, truncated = [], 0, 0, False
        while True:
            params = {"where": where, "geometry": ",".join(f"{v:.6f}" for v in bbox), "geometryType": "esriGeometryEnvelope",
                      "inSR": 4326, "outSR": 4326, "spatialRel": "esriSpatialRelIntersects", "outFields": "*",
                      "resultOffset": offset, "resultRecordCount": PAGE, "geometryPrecision": 6, "f": "geojson"}
            if tol and meta["geom"] == "line":
                params["maxAllowableOffset"] = f"{tol:.6f}"
            r = await c.get(meta["url"] + "/query", params=params)
            r.raise_for_status()
            d = r.json()
            if "error" in d:
                raise RuntimeError(str(d["error"])[:200])
            page = d.get("features", [])
            feats += page
            pages += 1
            more = d.get("exceededTransferLimit") or (d.get("properties") or {}).get("exceededTransferLimit")
            if not more or not page:
                break
            if pages >= MAX_PAGES:
                truncated = True
                break
            offset += len(page)
        retrieved = iso()
        return {"type": "FeatureCollection", "features": [_decorate(layer, f, version, retrieved) for f in feats],
                "pages": pages, "truncated": truncated, "where": where, "tolerance_deg": tol, "filter_version": FILTER_VERSION}
    finally:
        if own:
            await c.aclose()


_inflight: dict[str, asyncio.Future] = {}


async def tile(layer: str, z: int, x: int, y: int) -> dict:
    """Server-side cached tile (Mongo, 7 days) with single-flight so concurrent identical requests share one fetch."""
    z = min(z, MAX_TILE_Z)
    if z < ARCGIS_LAYERS[layer]["min_zoom"]:
        return {"type": "FeatureCollection", "features": [], "below_min_zoom": True, "min_zoom": ARCGIS_LAYERS[layer]["min_zoom"]}
    key = f"{layer}/{z}/{x}/{y}/{FILTER_VERSION}"
    hit = await db.rail_tile_cache.find_one({"key": key})
    if hit and hit["expires_at"] > datetime.now(timezone.utc).replace(tzinfo=None):
        return {**hit["data"], "cache": "hit"}
    if key in _inflight:
        return await asyncio.shield(_inflight[key])
    fut = asyncio.get_running_loop().create_future()
    _inflight[key] = fut
    try:
        data = await fetch_arcgis(layer, tile_bbox(z, x, y), z)
        await db.rail_tile_cache.update_one({"key": key}, {"$set": {"key": key, "data": data, "expires_at": datetime.now(timezone.utc).replace(tzinfo=None) + TILE_TTL}}, upsert=True)
        fut.set_result({**data, "cache": "miss"})
        return {**data, "cache": "miss"}
    except Exception as e:
        fut.set_exception(e)
        fut.exception()  # mark retrieved
        raise
    finally:
        _inflight.pop(key, None)


async def nearby(lat: float, lon: float) -> dict:
    """Suggestion only, never moves the pin and never picks a track (REQ-1440, REQ-1145)."""
    out = {"label": "Nearby, not exact", "railroad": None, "subdivision": None, "branch": None, "nearest_milepost": None, "sources": []}
    async with httpx.AsyncClient(timeout=30, headers=UA) as c:
        common = {"geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint", "inSR": 4326, "outSR": 4326,
                  "spatialRel": "esriSpatialRelIntersects", "units": "esriSRUnit_Meter", "f": "json", "returnGeometry": "false"}
        r = await c.get(ARCGIS_LAYERS["ntad_lines"]["url"] + "/query", params={**common, "distance": 300, "outFields": "FRAARCID,RROWNER1,SUBDIV,BRANCH,TRACKS"})
        lines = [f["attributes"] for f in r.json().get("features", [])]
        if lines:
            a = lines[0]
            out.update({"railroad": a.get("RROWNER1"), "subdivision": a.get("SUBDIV"), "branch": a.get("BRANCH"),
                        "line_id": f"ntad_lines:{a.get('FRAARCID')}"})
            out["sources"].append({"source": ARCGIS_LAYERS["ntad_lines"]["name"], "version": await layer_version(c, "ntad_lines")})
        r = await c.get(ARCGIS_LAYERS["ntad_mileposts"]["url"] + "/query", params={**common, "distance": 3000, "outFields": "OBJECTID,SUBDIV,MILEPOST,LAT,LON"})
        mps = [f["attributes"] for f in r.json().get("features", [])]
    if mps:
        def dist(m):
            return haversine_m(lat, lon, m["LAT"], m["LON"])
        m = min(mps, key=dist)
        out["nearest_milepost"] = {"milepost": m["MILEPOST"], "subdivision": m["SUBDIV"], "distance_m": round(dist(m)),
                                   "id": f"ntad_mileposts:{m['OBJECTID']}", "label": "Nearby, not exact"}
        out["sources"].append({"source": ARCGIS_LAYERS["ntad_mileposts"]["name"]})
    return out


TRACK_RIGHTS = ["RROWNER1", "RROWNER2", "RROWNER3"] + [f"TRKRGHTS{i}" for i in range(1, 10)]


def _line_distance_m(lat: float, lon: float, geometry: dict) -> float:
    """Distance to the actual source geometry, never a guessed milepost coordinate."""
    paths = geometry.get("paths", [])
    scale = math.cos(math.radians(lat))
    best = float("inf")
    for path in paths:
        for a, b in zip(path, path[1:]):
            ax, ay = (a[0] - lon) * scale * 111320, (a[1] - lat) * 111320
            bx, by = (b[0] - lon) * scale * 111320, (b[1] - lat) * 111320
            dx, dy = bx - ax, by - ay
            t = max(0, min(1, -(ax * dx + ay * dy) / (dx * dx + dy * dy))) if dx or dy else 0
            best = min(best, math.hypot(ax + t * dx, ay + t * dy))
    return best


def _milepost_option(point: dict, line: dict) -> dict | None:
    p, a = point.get("attributes", {}), line.get("attributes", {})
    sub = str(p.get("SUBDIV") or "").strip()
    if not sub or sub.casefold() != str(a.get("SUBDIV") or "").strip().casefold():
        return None
    lat, lon, mp = p.get("LAT"), p.get("LON"), p.get("MILEPOST")
    if any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in (lat, lon, mp)):
        return None
    if abs(lat) > 90 or abs(lon) > 180 or _line_distance_m(lat, lon, line.get("geometry", {})) > 35:
        return None
    railroad = next((str(a[k]).strip() for k in TRACK_RIGHTS if a.get(k) and str(a[k]).strip()), None)
    if not railroad or p.get("OBJECTID") is None or a.get("FRAARCID") is None:
        return None
    return {"resolved": True, "id": f"ntad_mileposts:{p['OBJECTID']}", "line_id": f"ntad_lines:{a['FRAARCID']}",
            "lat": lat, "lon": lon, "milepost": mp, "railroad": railroad, "subdivision": sub,
            "source": ARCGIS_LAYERS["ntad_mileposts"]["name"], "label": "Selected reference milepost", "selection": "map_feature",
            "association": "Same subdivision and source line geometry; line confirmed by worker"}


async def map_milepost_options(feature_id: str, line_id: str | None = None) -> dict:
    """Options for a clicked source feature. No global-nearest lookup or interpolation."""
    match = re.fullmatch(r"(ntad_lines|ntad_mileposts):(\d+)", feature_id)
    if not match or (line_id is not None and not re.fullmatch(r"ntad_lines:\d+", line_id)):
        raise ValueError("Choose a supported rail line or reference milepost.")
    layer, fid = match.groups()
    async with httpx.AsyncClient(timeout=30, headers=UA) as c:
        async def query(name, **params):
            r = await c.get(ARCGIS_LAYERS[name]["url"] + "/query", params={"f": "json", "outFields": "*",
                "outSR": 4326, "returnGeometry": "true", "resultRecordCount": 2000, **params})
            r.raise_for_status()
            data = r.json()
            if data.get("error") or data.get("exceededTransferLimit"):
                raise ValueError("Reference selection is incomplete. Zoom in or select a milepost directly.")
            return data.get("features", [])
        selected = await query(layer, where=f"{ARCGIS_LAYERS[layer]['id_field']}={fid}")
        if len(selected) != 1:
            return {"options": [], "message": "Reference feature not found. Select another point or place a manual pin."}
        if layer == "ntad_mileposts":
            points = selected
            p = points[0]["attributes"]
            lines = await query("ntad_lines", where=f"FRAARCID={line_id.split(':')[1]}" if line_id else "1=1",
                geometry=f"{p['LON']},{p['LAT']}", geometryType="esriGeometryPoint", inSR=4326,
                distance=35, units="esriSRUnit_Meter", spatialRel="esriSpatialRelIntersects")
        else:
            lines = selected
            a = lines[0]["attributes"]
            sub = str(a.get("SUBDIV") or "").strip().upper().replace("'", "''")
            if not sub:
                return {"options": [], "message": "This line has no reference subdivision. Select a manual pin."}
            points = await query("ntad_mileposts", where=f"UPPER(SUBDIV)='{sub}'",
                geometry=json.dumps({**lines[0]["geometry"], "spatialReference": {"wkid": 4326}}),
                geometryType="esriGeometryPolyline", inSR=4326, distance=35, units="esriSRUnit_Meter",
                spatialRel="esriSpatialRelIntersects")
        version = await layer_version(c, "ntad_mileposts")
        line_version = await layer_version(c, "ntad_lines")
    options = [o for p in points for line in lines if (o := _milepost_option(p, line))]
    for o in options:
        o.update({"version": version, "line_version": line_version})
    options.sort(key=lambda o: (o["milepost"], o["line_id"]))
    return {"options": options, "message": "Choose the reference milepost and confirm its line." if options else
            "No applicable reference mileposts on this line. Keep a manual pin; no milepost has been inferred."}


async def resolve_milepost(railroad: str, subdivision: str, milepost: float) -> dict:
    """REQ-1605: a point only when NTAD Rail Mileposts has this exact milepost on this subdivision AND an NTAD rail line within
    300 m names the railroad (owner or trackage rights). Otherwise unresolved; nothing is interpolated (REQ-1422)."""
    rr, sub = railroad.strip().upper(), subdivision.strip().upper().replace("'", "''")
    async with httpx.AsyncClient(timeout=30, headers=UA) as c:
        r = await c.get(ARCGIS_LAYERS["ntad_mileposts"]["url"] + "/query", params={
            "where": f"UPPER(SUBDIV)='{sub}' AND MILEPOST={milepost}", "outFields": "OBJECTID,SUBDIV,MILEPOST,STATEAB,LAT,LON",
            "returnGeometry": "false", "f": "json", "resultRecordCount": 50})
        r.raise_for_status()
        mps = [f["attributes"] for f in r.json().get("features", [])]
        matches = []
        for m in mps:
            q = await c.get(ARCGIS_LAYERS["ntad_lines"]["url"] + "/query", params={
                "geometry": f"{m['LON']},{m['LAT']}", "geometryType": "esriGeometryPoint", "inSR": 4326, "distance": 300, "units": "esriSRUnit_Meter",
                "spatialRel": "esriSpatialRelIntersects", "outFields": ",".join(["FRAARCID"] + TRACK_RIGHTS), "returnGeometry": "false", "f": "json"})
            lines = [f["attributes"] for f in q.json().get("features", [])]
            hit = next((a for a in lines if rr in {str(a.get(k) or "").strip().upper() for k in TRACK_RIGHTS}), None)
            if hit:
                matches.append((m, hit))
        version = await layer_version(c, "ntad_mileposts")
    if len(matches) != 1:
        return {"resolved": False, "candidates": len(matches),
                "message": "Milepost not found in the reference data for this railroad and subdivision." if not matches
                else "More than one reference point matches. Place the pin on the map."}
    m, line = matches[0]
    return {"resolved": True, "lat": m["LAT"], "lon": m["LON"], "label": "From milepost reference",
            "source": ARCGIS_LAYERS["ntad_mileposts"]["name"], "id": f"ntad_mileposts:{m['OBJECTID']}", "version": version,
            "line_id": f"ntad_lines:{line.get('FRAARCID')}", "subdivision": m["SUBDIV"], "milepost": m["MILEPOST"], "state": m.get("STATEAB")}


def haversine_m(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371008.8 * math.asin(math.sqrt(a))


# ---------------- basemap ----------------
_style_cache: dict = {}


def strip_bus(style: dict) -> dict:
    """Remove bus routes and bus-stop symbols from the basemap (streets stay) (REQ-1405)."""
    s = copy.deepcopy(style)
    no_bus = ["!", ["any", ["match", ["coalesce", ["get", "class"], ""], BUS_CLASSES, True, False],
                    ["match", ["coalesce", ["get", "subclass"], ""], BUS_CLASSES, True, False]]]
    layers = []
    for l in s["layers"]:
        if l.get("source-layer") == "poi" and l["id"] == "poi_transit":
            l["filter"] = ["match", ["get", "class"], ["airport", "rail"], True, False]  # was airport, bus, rail
        if l.get("source-layer") in ("poi", "transportation", "transportation_name"):
            l["filter"] = ["all", l["filter"], no_bus] if "filter" in l else no_bus
        layers.append(l)
    s["layers"] = layers
    s.setdefault("metadata", {})["railready"] = {"bus_stripped": True, "filter_version": FILTER_VERSION, "terms": BASEMAP["terms"]}
    return s


async def basemap_style() -> dict:
    if "style" not in _style_cache:
        async with httpx.AsyncClient(timeout=30, headers=UA) as c:
            r = await c.get(BASEMAP["style_url"])
            r.raise_for_status()
        _style_cache["style"] = strip_bus(r.json())
    return _style_cache["style"]


def offline_style() -> dict:
    """North-up plot fallback: no basemap tiles, just a plain background (REQ-1448, REQ-1173)."""
    return {"version": 8, "name": "North-up plot (offline)", "sources": {}, "layers": [{"id": "bg", "type": "background", "paint": {"background-color": "#F4F4F2"}}]}
