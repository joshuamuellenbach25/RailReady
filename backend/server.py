import asyncio
import logging
import os

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from core import client, ensure_indexes
import jobs
import routes_ai
import routes_demo
import routes_estimate
import routes_field
import routes_office
import routes_public
import routes_scene
import routes_photo_scene
import routes_diag
import routes_phase5
import routes_plain
import routes_kotri
import routes_phase7
import routes_calibration
import routes_map
import routes_repair
import routes_contract
import calibration
import seed
import storage

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
log = logging.getLogger("server")

app = FastAPI(title="RailReady API", version="phase-5", openapi_url="/api/openapi.json", docs_url="/api/docs", redoc_url=None)
app.include_router(routes_field.router)
app.include_router(routes_ai.router)
app.include_router(routes_estimate.router)
app.include_router(routes_office.router)
app.include_router(routes_public.router)
app.include_router(routes_demo.router)
app.include_router(routes_scene.router)
app.include_router(routes_photo_scene.router)
app.include_router(routes_diag.router)
app.include_router(routes_phase5.router)
app.include_router(routes_calibration.router)
app.include_router(routes_map.router)
app.include_router(routes_repair.router)
import routes_paperwork  # noqa: E402  Phase 17
app.include_router(routes_paperwork.router)
app.include_router(routes_contract.router)
app.include_router(routes_plain.router)
app.include_router(routes_kotri.router)
app.include_router(routes_phase7.router)


@app.get("/api/health", tags=["meta"])
async def health():
    return {"ok": True}


app.add_middleware(CORSMiddleware, allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
                   allow_credentials=False, allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
async def startup():
    await ensure_indexes()
    await routes_repair.ensure_indexes()
    await routes_paperwork.ensure_indexes()
    await routes_contract.ensure_indexes()
    await seed.seed()
    try:
        storage.init_storage()
        log.info("Object storage initialized")
    except Exception as e:
        log.error("Storage init failed: %s", e)
    await jobs.recover_dead_leases()
    import scenes
    asyncio.get_running_loop().run_in_executor(None, scenes.prepare_model)  # startup prep: provision/verify + one session
    jobs.start_workers()
    for coll, keys in (("dataset_files", [("release_id", 1), ("path", 1)]), ("dataset_annotations", [("release_id", 1), ("split", 1), ("ann_id", 1)])):
        await client[os.environ["DB_NAME"]][coll].create_index(keys, unique=True)
    await client[os.environ["DB_NAME"]].dataset_images.create_index("uuid", unique=True)
    await client[os.environ["DB_NAME"]].dataset_annotations.create_index("image_key")
    calibration.start_worker()
    import photo_pipeline
    await photo_pipeline.seed_taxonomy()
    await photo_pipeline.recover_interrupted()
    import routes_public
    log.info("acceptance recovery: %s", await routes_public.recover_acceptances())


@app.on_event("shutdown")
async def shutdown():
    await jobs.release_own_leases()
    client.close()
