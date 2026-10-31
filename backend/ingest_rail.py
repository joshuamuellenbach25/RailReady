"""Ingest rail-only GTFS (SFMTA, BART, Caltrain) into rail_gtfs and create indexes. Idempotent; zips staged in /tmp/rail."""
import asyncio
import json
import sys

sys.path.insert(0, "/app/backend")
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
from core import db
import rail_map as RM


async def main():
    await db.rail_gtfs.create_index([("geometry", "2dsphere")])
    await db.rail_gtfs.create_index([("feed", 1), ("kind", 1)])
    await db.rail_tile_cache.create_index("key", unique=True)
    await db.rail_tile_cache.create_index("expires_at", expireAfterSeconds=0)
    await db.pins.create_index("uuid", unique=True)
    await db.pins.create_index("visit_id", unique=True, name="one_pin_per_inspection", partialFilterExpression={"visit_id": {"$type": "string"}})
    await db.pins.create_index([("workspace_id", 1), ("lat", 1), ("lon", 1)])
    await db.locations.create_index("uuid", unique=True)
    await db.locations.create_index([("workspace_id", 1), ("visit_id", 1)])
    for feed in (sys.argv[1:] or list(RM.GTFS_FEEDS)):
        try:
            print(json.dumps(await RM.ingest_gtfs(feed), default=str))
        except Exception as e:
            print(feed, "FAILED", type(e).__name__, str(e)[:200])

asyncio.run(main())
