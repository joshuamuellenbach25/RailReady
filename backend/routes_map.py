"""Phase 14 rail map API (absorbs Phase 11 location records). All routes /api/map/* and /api/locations*.
Pins create a site + inspection exactly once (client uuid). Location records keep the selected spot separate from the camera
position, store provenance, and use revision checks for conflicts. Nothing here auto-fills railway fields."""
import math
import re
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from pymongo.errors import DuplicateKeyError

import rail_map as RM
from core import audit, clean, current_user, db, get_scoped, get_visit, iso, require_role
from routes_field import SiteIn, VisitIn, create_site, create_visit

router = APIRouter(prefix="/api")
LAYER_FAIL = {"code": "layer_unavailable", "message": "Rail layer unavailable. Pins still work."}
OUT_OF_RANGE = "Location is out of range."


def _bbox(s: str) -> tuple:
    try:
        w, so, e, n = (float(x) for x in s.split(","))
    except Exception:
        raise HTTPException(422, {"code": "bad_bbox", "message": "bbox must be west,south,east,north"})
    if not (-180 <= w < e <= 180 and -90 <= so < n <= 90):
        raise HTTPException(422, {"code": "bad_bbox", "message": OUT_OF_RANGE})
    return (w, so, e, n)


@router.get("/map/sources", tags=["map"])
async def sources(user=Depends(current_user)):
    feeds = {d["feed"]: {k: v for k, v in d.items() if k != "_id"} async for d in db.rail_sources.find({})}
    return {"filter_version": RM.FILTER_VERSION, "rail_route_types": RM.RAIL_ROUTE_TYPES, "service_path_label": RM.SERVICE_PATH_LABEL,
            "gtfs": {k: {**v, "ingest": feeds.get(k)} for k, v in RM.GTFS_FEEDS.items()},
            "arcgis": {k: {"name": v["name"], "url": v["url"], "min_zoom": v["min_zoom"], "geometry": v["geom"]} for k, v in RM.ARCGIS_LAYERS.items()},
            "osm": {"enabled": False, "reason": "Overpass not reachable from this server on 2026-10-25; optional source (REQ-1423)"},
            "basemap": RM.BASEMAP, "tile_zoom_max": RM.MAX_TILE_Z}


@router.get("/map/basemap-style", tags=["map"])
async def basemap_style(offline: bool = False, user=Depends(current_user)):
    if offline:
        return RM.offline_style()
    try:
        return await RM.basemap_style()
    except Exception:
        return {**RM.offline_style(), "metadata": {"basemap_unavailable": True}}  # rail + pins still render on a plain plot


@router.get("/map/layers/gtfs", tags=["map"])
async def gtfs_layer(bbox: str, user=Depends(current_user)):
    return await RM.gtfs_features(_bbox(bbox))


@router.get("/map/layers/{layer}/{z}/{x}/{y}", tags=["map"])
async def arcgis_layer(layer: str, z: int, x: int, y: int, user=Depends(current_user)):
    if layer not in RM.ARCGIS_LAYERS or not (0 <= z <= 22) or not (0 <= x < 2 ** z) or not (0 <= y < 2 ** z):
        raise HTTPException(404, "Not found")
    try:
        return await RM.tile(layer, z, x, y)
    except Exception:
        raise HTTPException(502, LAYER_FAIL)


COORD = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*[, ]\s*(-?\d+(?:\.\d+)?)\s*$")


@router.get("/map/search", tags=["map"])
async def search(q: str = Query(min_length=1, max_length=120), user=Depends(current_user)):
    """Coordinates, rail stations (only stops served by rail trips are stored) and this workspace's sites."""
    out = []
    m = COORD.match(q)
    if m:
        lat, lon = float(m.group(1)), float(m.group(2))
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise HTTPException(422, {"code": "out_of_range", "message": OUT_OF_RANGE})
        out.append({"kind": "coordinates", "label": f"{lat:.6f}, {lon:.6f}", "lat": lat, "lon": lon})
    rx = {"$regex": re.escape(q.strip()), "$options": "i"}
    async for s in db.rail_gtfs.find({"kind": {"$in": ["station", "stop"]}, "parent_id": None, "name": rx}).limit(10):
        lon, lat = s["geometry"]["coordinates"]
        out.append({"kind": "rail_station", "label": s["name"], "lat": lat, "lon": lon, "id": s["id"], "source": s["source"]})
    async for s in db.sites.find({"workspace_id": user["workspace_id"], "name": rx, "lat": {"$ne": None}}).limit(10):
        out.append({"kind": "site", "label": s["name"], "lat": s["lat"], "lon": s["lon"], "id": s["uuid"]})
    return {"results": out}


@router.get("/map/nearby", tags=["map"])
async def nearby(lat: float = Query(ge=-90, le=90), lon: float = Query(ge=-180, le=180), user=Depends(current_user)):
    try:
        return await RM.nearby(lat, lon)
    except Exception:
        raise HTTPException(502, LAYER_FAIL)


class MilepostQuery(BaseModel):
    railroad: str = Field(min_length=1, max_length=20)
    subdivision: str = Field(min_length=1, max_length=120)
    milepost: str = Field(min_length=1, max_length=20)  # as entered; kept verbatim when unresolved (REQ-1606)


@router.get("/map/milepost-options", tags=["map"])
async def milepost_options(feature_id: str = Query(pattern=r"^(ntad_lines|ntad_mileposts):\d+$"), user=Depends(current_user)):
    try:
        return await RM.map_milepost_options(feature_id)
    except ValueError as e:
        return {"options": [], "message": str(e)}
    except Exception:
        raise HTTPException(502, {"code": "reference_unavailable", "message": "Milepost references unavailable. Use a saved selection or a manual pin."})


@router.post("/map/milepost", tags=["map"])
async def milepost(body: MilepostQuery, user=Depends(current_user)):
    try:
        n = float(body.milepost.strip())
    except ValueError:
        n = None
    if n is None or not math.isfinite(n) or n < 0 or n > 10000:
        return {"resolved": False, "text": body.milepost, "message": "Milepost must be a number. Place the pin on the map."}
    try:
        r = await RM.resolve_milepost(body.railroad, body.subdivision, n)
    except Exception:
        r = {"resolved": False, "message": "Milepost reference is unavailable right now. Place the pin on the map."}
    return {**r, "text": body.milepost, "railroad": body.railroad.strip(), "subdivision_entered": body.subdivision.strip()}


# ---------------- pins ----------------
class PinRail(BaseModel):
    railroad: Optional[str] = Field(None, max_length=120)
    subdivision: Optional[str] = Field(None, max_length=120)
    milepost_text: Optional[str] = Field(None, max_length=40)  # as entered


METHOD_LABEL = {"gps": "My location (GPS)", "pin": "Map pin", "coordinates": "Entered coordinates", "milepost": "From milepost reference",
                "milepost_pin": "Milepost entered; pin confirmed by worker"}


class PinIn(BaseModel):
    uuid: str = Field(min_length=8, max_length=64)
    lat: float
    lon: float
    name: Optional[str] = Field(None, max_length=120)
    note: Optional[str] = Field(None, max_length=500)
    camera_lat: Optional[float] = None  # where the phone was, kept separate from the selected spot
    camera_lon: Optional[float] = None
    camera_accuracy_m: Optional[float] = Field(None, ge=0)
    site_id: Optional[str] = None  # link mode: the phone created the site + inspection locally (offline-first) and synced them
    visit_id: Optional[str] = None
    method: Literal["gps", "pin", "coordinates", "milepost", "milepost_pin"] = "pin"
    railway: Optional[PinRail] = None
    milepost_ref: Optional[dict] = None  # the /map/milepost result when method == "milepost"
    fixed_at: Optional[str] = Field(None, max_length=40)  # GPS fix time reported by the phone (method == "gps")

    @field_validator("lat", "lon", "camera_lat", "camera_lon")
    @classmethod
    def finite(cls, v, info):
        if v is None:
            return v
        lim = 90 if "lat" in info.field_name else 180
        if not math.isfinite(v) or abs(v) > lim:
            raise ValueError(OUT_OF_RANGE)
        return v


async def _pin_view(p: dict) -> dict:
    ev = await db.evidence.count_documents({"visit_id": p["visit_id"]})
    v = await db.visits.find_one({"uuid": p["visit_id"]}, {"status": 1, "title": 1})
    out = clean(p)
    out.update({"evidence_count": ev, "visit_status": (v or {}).get("status"),
                "inspection_state": "Not inspected" if not ev else ("Submitted" if (v or {}).get("status") == "Submitted" else "In progress")})
    return out


@router.post("/map/pins", tags=["map"])
async def create_pin(body: PinIn, user=Depends(require_role("foreman"))):
    """Drop a pin -> site + inspection, exactly once per client uuid (double tap, retry, offline replay)."""
    old = await db.pins.find_one({"uuid": body.uuid})
    if old:
        if old["workspace_id"] != user["workspace_id"]:
            raise HTTPException(404, "Not found")
        return await _pin_view(old)
    name = (body.name or "").strip() or f"Pin {body.lat:.5f}, {body.lon:.5f}"
    ref = None
    if body.method == "milepost":  # only a server-verified reference point may be labeled as one
        rw0 = body.railway or PinRail()
        if not (rw0.railroad and rw0.subdivision and rw0.milepost_text):
            raise HTTPException(422, {"code": "milepost_incomplete", "message": "Enter railroad, subdivision and milepost."})
        selected = body.milepost_ref or {}
        if selected.get("selection") == "map_feature":
            if not selected.get("id") or not selected.get("line_id"):
                raise HTTPException(422, {"code": "milepost_incomplete", "message": "Select the reference milepost and its line again."})
            try:
                options = await RM.map_milepost_options(selected["id"], selected["line_id"])
            except ValueError as e:
                raise HTTPException(422, {"code": "milepost_unresolved", "message": str(e)})
            except Exception:
                raise HTTPException(503, {"code": "reference_unavailable", "message": "Saved location is waiting for reference verification. Retry when connected."})
            chk = next((o for o in options["options"] if o["id"] == selected["id"] and o["line_id"] == selected["line_id"]), {})
            try:
                same_milepost = float(chk.get("milepost")) == float(rw0.milepost_text)
            except (TypeError, ValueError):
                same_milepost = False
            if chk and (str(chk["railroad"]).casefold() != rw0.railroad.strip().casefold() or
                        str(chk["subdivision"]).casefold() != rw0.subdivision.strip().casefold() or
                        not same_milepost):
                raise HTTPException(422, {"code": "milepost_mismatch", "message": "Selected milepost metadata does not match its source record."})
        else:
            chk = await milepost(MilepostQuery(railroad=rw0.railroad, subdivision=rw0.subdivision, milepost=rw0.milepost_text), user)
        if not chk.get("resolved") or abs(chk["lat"] - body.lat) > 1e-6 or abs(chk["lon"] - body.lon) > 1e-6:
            raise HTTPException(422, {"code": "milepost_unresolved", "message": "Milepost not found in the reference data. Confirm a pin on the map."})
        ref = {k: chk.get(k) for k in ("source", "id", "version", "line_id", "line_version", "subdivision", "milepost", "label", "association", "selection")}
    if body.site_id and body.visit_id:
        site = await db.sites.find_one({"uuid": body.site_id, "workspace_id": user["workspace_id"]})
        visit = await db.visits.find_one({"uuid": body.visit_id, "workspace_id": user["workspace_id"], "site_id": body.site_id})
        if not site or not visit:
            raise HTTPException(409, {"code": "not_synced", "message": "Waiting for the inspection to send. The pin will link after that."})
        linked = await db.pins.find_one({"visit_id": visit["uuid"]})
        if linked:  # one pin per inspection: a replay under another client id returns the existing pin + location
            return await _pin_view(linked)
    else:
        site = await create_site(SiteIn(uuid=f"pin-site-{body.uuid}", name=name, lat=body.lat, lon=body.lon,
                                        description=(body.note or "").strip() or None), user)
        visit = await create_visit(VisitIn(uuid=f"pin-visit-{body.uuid}", site_id=site["uuid"], title=name), user)
    rw = body.railway or PinRail()
    railway = {"railroad": rw.railroad, "subdivision": rw.subdivision, "milepost": {"text": rw.milepost_text} if rw.milepost_text else None}
    loc = {"uuid": f"pin-loc-{body.uuid}", "workspace_id": user["workspace_id"], "visit_id": visit["uuid"], "evidence_id": None,
           "role": "approximate_defect", "source": {"gps": "device", "milepost": "operator_dataset"}.get(body.method, "manual"),
           "lat": body.lat, "lon": body.lon, "accuracy_m": body.camera_accuracy_m if body.method == "gps" else None,
           "fixed_at": body.fixed_at if body.method == "gps" else None,
           "method": body.method, "method_label": METHOD_LABEL[body.method], "milepost_ref": ref,
           "label": "Approximate defect location", "railway": railway, "revision": 1, "history": [], "created_by": user["uuid"], "created_at": iso()}
    await db.locations.update_one({"uuid": loc["uuid"]}, {"$setOnInsert": loc}, upsert=True)
    if body.camera_lat is not None and body.camera_lon is not None:
        cam = {**loc, "uuid": f"pin-cam-{body.uuid}", "role": "camera_position", "source": "device", "lat": body.camera_lat, "lon": body.camera_lon,
               "accuracy_m": body.camera_accuracy_m, "label": "Camera position"}
        await db.locations.update_one({"uuid": cam["uuid"]}, {"$setOnInsert": cam}, upsert=True)
    pin = {"uuid": body.uuid, "workspace_id": user["workspace_id"], "site_id": site["uuid"], "visit_id": visit["uuid"], "location_id": loc["uuid"],
           "lat": body.lat, "lon": body.lon, "name": name, "dataset_versions": {k: v.get("feed_version") async for k, v in _feeds()},
           "filter_version": RM.FILTER_VERSION, "created_by": user["uuid"], "created_at": iso()}
    try:
        await db.pins.update_one({"uuid": body.uuid}, {"$setOnInsert": pin}, upsert=True)
    except DuplicateKeyError:  # concurrent link under another client id: one pin per inspection (unique index)
        return await _pin_view(await db.pins.find_one({"visit_id": visit["uuid"]}))
    await audit(user, user["workspace_id"], "pin.created", "pin", body.uuid, {"site_id": site["uuid"], "visit_id": visit["uuid"]})
    return await _pin_view(await db.pins.find_one({"uuid": body.uuid}))


async def _feeds():
    async for d in db.rail_sources.find({}):
        yield d["feed"], {"feed_version": d.get("version")}


@router.get("/map/pins", tags=["map"])
async def list_pins(bbox: Optional[str] = None, user=Depends(current_user)):
    q = {"workspace_id": user["workspace_id"]}
    if bbox:
        w, s, e, n = _bbox(bbox)
        q.update({"lat": {"$gte": s, "$lte": n}, "lon": {"$gte": w, "$lte": e}})
    return [await _pin_view(p) for p in await db.pins.find(q).sort("created_at", -1).to_list(2000)]


@router.get("/map/items", tags=["map"])
async def map_items(user=Depends(current_user)):
    """Pins plus camera-first inspections that have a located capture (role camera_position)."""
    pins = await list_pins(None, user)
    pinned = {p["visit_id"] for p in pins}
    cams = []
    async for loc in db.locations.find({"workspace_id": user["workspace_id"], "role": "camera_position", "visit_id": {"$nin": list(pinned)}}):
        cams.append({"kind": "camera_first", "visit_id": loc["visit_id"], "evidence_id": loc.get("evidence_id"), "lat": loc["lat"], "lon": loc["lon"],
                     "label": "Camera position"})
    return {"pins": pins, "camera_first": cams}


# ---------------- Phase 11 location records ----------------
class Milepost(BaseModel):
    prefix: Optional[str] = Field(None, max_length=10)
    number: Optional[float] = None
    text: Optional[str] = Field(None, max_length=40)  # as written, never reformatted


class Offset(BaseModel):
    distance: float = Field(ge=0)
    unit: Literal["ft", "m", "mi"]
    direction: Optional[str] = Field(None, max_length=40)


class Railway(BaseModel):
    railroad: Optional[str] = Field(None, max_length=120)
    subdivision: Optional[str] = Field(None, max_length=120)
    branch: Optional[str] = Field(None, max_length=120)
    track: Optional[str] = Field(None, max_length=40)
    milepost: Optional[Milepost] = None
    offset: Optional[Offset] = None
    nearby_asset: Optional[str] = Field(None, max_length=200)
    landmark_notes: Optional[str] = Field(None, max_length=500)


class LocationIn(BaseModel):
    uuid: str = Field(min_length=8, max_length=64)
    visit_id: str
    evidence_id: Optional[str] = None
    role: Literal["camera_position", "approximate_defect", "confirmed_onsite"]
    source: Literal["device", "media_metadata", "manual", "operator_dataset"]
    lat: Optional[float] = None
    lon: Optional[float] = None
    accuracy_m: Optional[float] = Field(None, ge=0)
    fix_time: Optional[str] = None
    railway: Railway = Railway()

    @field_validator("lat", "lon")
    @classmethod
    def finite(cls, v, info):
        if v is None:
            return v  # null is allowed: "Not recorded"
        if not math.isfinite(v) or abs(v) > (90 if info.field_name == "lat" else 180):
            raise ValueError(OUT_OF_RANGE)
        return v  # 0 is a valid coordinate


class LocationUpdate(BaseModel):
    expected_revision: int
    lat: Optional[float] = None
    lon: Optional[float] = None
    accuracy_m: Optional[float] = Field(None, ge=0)
    source: Optional[Literal["device", "media_metadata", "manual", "operator_dataset"]] = None
    railway: Optional[Railway] = None

    _finite = field_validator("lat", "lon")(LocationIn.finite.__func__)


@router.post("/locations", tags=["locations"])
async def create_location(body: LocationIn, user=Depends(require_role("foreman", "admin", "estimator"))):
    await get_visit(user, body.visit_id)
    if (body.lat is None) != (body.lon is None):
        raise HTTPException(422, {"code": "incomplete", "message": "Enter both latitude and longitude, or neither."})
    old = await db.locations.find_one({"uuid": body.uuid})
    if old:
        if old["workspace_id"] != user["workspace_id"]:
            raise HTTPException(404, "Not found")
        return clean(old)
    doc = {**body.model_dump(), "workspace_id": user["workspace_id"], "revision": 1, "history": [],
           "label": {"camera_position": "Camera position", "approximate_defect": "Approximate defect location", "confirmed_onsite": "Confirmed on site"}[body.role],
           "created_by": user["uuid"], "created_at": iso(), "updated_at": iso()}
    await db.locations.update_one({"uuid": body.uuid}, {"$setOnInsert": doc}, upsert=True)
    return clean(await db.locations.find_one({"uuid": body.uuid}))


@router.put("/locations/{location_id}", tags=["locations"])
async def update_location(location_id: str, body: LocationUpdate, user=Depends(require_role("foreman", "admin", "estimator"))):
    cur, _ = await get_scoped("locations", user, location_id)
    upd = {k: v for k, v in body.model_dump(exclude_unset=True).items() if k != "expected_revision"}
    prev = {k: cur.get(k) for k in upd}
    r = await db.locations.update_one({"uuid": location_id, "revision": body.expected_revision}, {
        "$set": {**upd, "updated_at": iso(), "updated_by": user["uuid"]}, "$inc": {"revision": 1},
        "$push": {"history": {"at": iso(), "by": user["uuid"], "from_revision": body.expected_revision, "previous": prev}}})
    if not r.modified_count:
        latest = await db.locations.find_one({"uuid": location_id})
        raise HTTPException(409, {"code": "conflict", "message": "Changed elsewhere. Choose which to keep.", "latest": clean(latest)})
    return clean(await db.locations.find_one({"uuid": location_id}))


@router.get("/visits/{visit_id}/locations", tags=["locations"])
async def visit_locations(visit_id: str, user=Depends(current_user)):
    await get_visit(user, visit_id)
    return [clean(x) for x in await db.locations.find({"visit_id": visit_id, "workspace_id": user["workspace_id"]}).to_list(500)]
