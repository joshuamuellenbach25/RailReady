# Phase 4b: reference processor interface -> RailReady implementation

Processor module: `backend/photo_scene_processor.py`, built from a reference implementation. It contains only pure functions: no database, no auth, no storage.

| Reference interface | RailReady implementation |
|---|---|
| decode/validate (JPEG/PNG/WEBP, single frame, <=20 MiB, <=32 MP, min side >=32, no transparency, MAX_IMAGE_PIXELS=32e6, LOAD_TRUNCATED_IMAGES=False, DecompressionBombWarning->error) | `P.decode(data)` -> (oriented RGB, {format, exif_orientation 1–8, raw_w/h, oriented_w/h}); raises `UnsupportedImage` (code `unsupported`) |
| exif_transpose once | inside `P.decode` |
| model input 518 / ×14 / BICUBIC / ImageNet / NCHW | `P.model_input(oriented)` |
| ONNX session (CPUExecutionProvider, intra_op=min(4,cpu)), 2D finite output | `P.DepthSession(path).infer(x)`. One session per process (`scenes.PROC_SESSION`), loaded at startup by `scenes.prepare_model()`. Depth job concurrency is 1 |
| display thumbnail 384 LANCZOS, depth BICUBIC, p2/p98, span<1e-6 -> DepthUninformative, z=3/(0.5+d), HFOV 55, back-projection, f_dc/opacity/scale/rot, 14-prop PLY + comment | `P.build(data, session)` -> {manifest, artifacts{splat, display_z, depth_png, oriented_photo}, z, focal, width, height} |
| display_z.npy (allow_pickle=False), depth.png uint16, oriented.png | `artifacts.display_z`, `artifacts.depth_png`, `artifacts.oriented_photo` |
| manifest schema_version 1, processor_revision "photo-scene-v1", artifact sha256s | `manifest` (marked `provisional_schema: true` until the REQ-164 field list is available); stored as `manifest.json` and on the scene doc. `scene_hash` = sha256 of the canonical manifest JSON |
| anchor_from_point / anchor_from_box (box validation, floor(u·W)/floor(v·H) sampling) | `P.anchor_from_point(z, f, u, v)`, `P.anchor_from_box(z, f, box)`; inverse is `P.project(xyz, f, W, H)` |
| placement_method / location_basis | `"bbox_center_estimated_depth"` (manual moves: `"manual_point_estimated_depth"`) / `"single_photo_estimated_depth"` |
| provision_model (.part in target dir, <=512 MiB, hash verify, os.replace, cleanup) | `P.provision_model(target_path, sha, url, max_bytes, urlopen)`. `RAILREADY_DEPTH_MODEL_PATH` points at the verified file in models |
| processing key | `P.processing_key(source_sha)` = source sha \| photo-scene-v1 \| model sha \| settings hash. A changed key creates a new scene revision lazily when the scene is opened |
| EXIF raw->oriented regions (8 orientations, envelope), crop/letterbox undo | `P.raw_to_oriented_box`, `P.crop_box_to_full`, `P.region_to_oriented(region, frame, orientation)`. Candidates store `region_frame={"kind":"oriented_full"}` because analysis already runs on oriented images, so regions are never transformed twice |

## Routes (Phase 4 routes remain as aliases)
| Reference | Route | Notes |
|---|---|---|
| create scene | `POST /api/evidence/{evidence_id}/photo-scene` | 200 `{status:"ready", scene_id, job_id, revision}` or 202 job view. On a failed scene this retries from the stored bytes |
| job status | `GET /api/photo-scene-jobs/{job_id}` | `{job_id, evidence_id, status, scene_id, error, started_at, completed_at}` |
| scene | `GET /api/photo-scenes/{scene_id}` | `scene_id` = revision-specific scene uuid. Returns `{scene_id, evidence_id, visit_id, revision, scene_hash, status, error, processor_revision, is_current, latest_scene_id, manifest, assets, label, created_at, ready_at}` |
| assets | `assets.{splat, oriented_photo, original}` = `{kind:"signed_url", url, content_type, byte_length, sha256, expires_at}`; `assets.{depth_grid, manifest}` = `{kind:"authenticated_route", ...}` | `GET /api/photo-scenes/{scene_id}/assets/{splat\|oriented_photo\|original\|depth_grid\|depth_png\|manifest}?st=`. st is <=10 min, bound to scene + artifact kind, and revalidated per request. Re-fetching the scene gives a new URL for the same artifact sha |
| list revisions | `GET /api/evidence/{evidence_id}/photo-scenes` | extension |
| anchors | `GET /api/photo-scenes/{scene_id}/anchors` -> `{scene_id, revision, anchors:[{finding_id, kind, anchor_id, version, u, v, xyz, placement_method, placement, location_basis, uncertainty, stale, stale_reason, source_region, actor, at}], unplaced:[{finding_id, kind, reason}]}` | |
| place anchor | `PUT /api/photo-scenes/{scene_id}/anchors/{finding_id}` `{u, v, expected_version, reason?}` | The server computes xyz from that revision's grid. `expected_version: 0` creates the first anchor. Errors: 409 `stale_version`, 409 `scene_not_ready`, 422 `invalid_point` |
| saved view | `GET/PUT /api/photo-scenes/{scene_id}/view` `{camera:{position,target,fov_deg}, selected_finding_id}` | Saved per user per scene revision |

Statuses: `queued | processing | ready | depth_uninformative | failed`. Error codes: `unsupported`, `blocked` (status stays queued), `model_unavailable`, `storage_unavailable`, `depth_failed`, `source_mismatch`, `depth_uninformative`, `not_verified`, `not_found`, `link_expired`, `invalid_link`. All errors are `{code, message, retryable}` with no paths or stack traces.

Phase-4 alias vocabulary is unchanged: `Queued/Processing/Ready/Failed/Unsupported/Blocked` on `/api/evidence/{id}/scene`, `/api/visits/{id}/scenes`, `/api/scenes/{scene_id}/asset`, `/api/anchors/{anchor_id}`.

Anchors: a partial unique index on (evidence_id, scene_revision, item_id, current=true), plus version history. A duplicate delivery is ignored (first write wins). Manual placements survive auto refresh. A region change creates a new version of an auto anchor; on a manual anchor it only sets `stale`. Anchors are never moved between photos or revisions.

Fault injection (`POST /api/dev/fault`, stage `depth`, `mode`): `error` | `storage` | `uninformative` | `checksum`.
